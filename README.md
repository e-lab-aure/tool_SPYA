# SPYA — Bridge Bluetooth Transparent Windows ↔ Jabra via Raspberry Pi

> **S**ystème **P**hone **Y**our **A**udio — Bridge HFP/A2DP full-duplex entre Windows 11 et un casque Jabra, via un Raspberry Pi comme relais Bluetooth.

---

## Vue d'ensemble

Ce projet transforme un **Raspberry Pi 1 Model B** en pont Bluetooth transparent, permettant à Windows 11 d'utiliser un casque Jabra HomeWork avec :

- **Musique (A2DP)** : flux audio HD 44.1kHz stéréo Windows → Jabra
- **Appels Teams/Zoom (HFP)** : micro full-duplex mSBC 16kHz, bascule automatique
- **Enregistrement audio** : capture simultanée micro + haut-parleur pendant les appels
- **Interface TUI** : gestion complète depuis SSH (connexion, appairage, enregistrement)

---

## Architecture du système

```
┌─────────────────────────────────────────────────────────────┐
│                    Windows 11 (AXOLOTL)                     │
│              Teams / Zoom / Musique                         │
│         Périphérique audio : "RPI-PC"                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ Bluetooth classique (BT 2.x/3.x)
                       │ A2DP Source + HFP Audio Gateway
                       │
              ┌────────▼────────┐
              │  hci1 (dongle 2) │  ← Windows
              │  A0:AD:9F:73:C5:49│
              │                  │
              │  Raspberry Pi 1B │
              │  PipeWire 1.2.7  │
              │  WirePlumber     │
              │  BlueZ 5.66      │
              │                  │
              │  hci0 (dongle 1) │  → Jabra
              │  A0:AD:9F:73:B7:76│
              └────────┬────────┘
                       │ Bluetooth classique
                       │ A2DP Sink + HFP Headset (mSBC 16kHz)
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  Jabra HomeWork                              │
│              MAC : 6C:FB:ED:67:F5:43                        │
└─────────────────────────────────────────────────────────────┘
```

### Flux audio détaillé

```
Mode MUSIQUE (A2DP)
═══════════════════
Windows Spotify/YouTube
    │ A2DP Source (hci1)
    ▼
[PipeWire — routing automatique]
    │ A2DP Sink (hci0)
    ▼
Jabra HomeWork (stéréo 44.1kHz)


Mode APPEL Teams/Zoom (HFP mSBC)
══════════════════════════════════

Windows Teams (micro)              Windows Teams (haut-parleur)
    ▲                                         │
    │ HFP AG uplink (hci1)       HFP AG downlink (hci1)
    │                                         │
[PipeWire]                              [PipeWire]
    │                                         │
    │ HFP HF uplink (hci0)       HFP HF downlink (hci0)
    │                                         ▼
Jabra micro ──────────────────── Jabra haut-parleur
              (mSBC 16kHz)
```

### Bascule automatique A2DP ↔ HFP

```
Teams démarre un appel
        │
        ▼
Windows signale HFP Audio Gateway
        │
        ▼
WirePlumber détecte le changement de profil
        │
        ▼
Jabra bascule A2DP Sink → HFP Headset-Head-Unit
(WirePlumber rule 52-jabra-hfp.lua force HFP)
        │
        ▼
SCO link établi — audio bidirectionnel actif
        │
    Appel terminé
        │
        ▼
Jabra repasse en A2DP Sink automatiquement
```

---

## Matériel

| Composant | Détail |
|-----------|--------|
| Raspberry Pi 1 Model B | BCM2835, ARMv6 700MHz, 512MB RAM |
| OS | Raspberry Pi OS Bookworm (12) |
| Dongle BT hci0 | A0:AD:9F:73:B7:76 → Jabra |
| Dongle BT hci1 | A0:AD:9F:73:C5:49 → Windows |
| Casque | Jabra HomeWork (BT classique, MAC 6C:FB:ED:67:F5:43) |
| PC | Windows 11 AXOLOTL (MAC C0:A5:E8:6A:57:1F) |

> **Pourquoi deux dongles ?** Un seul adaptateur BT ne peut pas être simultanément `HFP HF` (côté casque) **et** `HFP AG` (côté PC). Deux dongles permettent de jouer les deux rôles en parallèle.

---

## Stack logicielle

```
┌─────────────────────────────────────┐
│         btui.py (TUI Python)        │  ← Interface utilisateur SSH
├─────────────────────────────────────┤
│   PipeWire 1.2.7 + WirePlumber      │  ← Routage audio + profils BT
│         0.4.13                      │
├─────────────────────────────────────┤
│           BlueZ 5.66                │  ← Stack Bluetooth Linux
├─────────────────────────────────────┤
│   2× Dongles USB Bluetooth          │  ← Hardware
└─────────────────────────────────────┘
```

- **PipeWire** : remplace PulseAudio, gère nativement HFP/A2DP sans oFono
- **WirePlumber** : policy engine de PipeWire — applique les règles de profil BT automatiquement
- **BlueZ 5.66** : backend HFP natif (`hfphsp-backend = native`), supporte mSBC sans oFono
- **sox 14.4.2** : mixage audio WAV léger (indispensable sur ARMv6, ffmpeg trop lourd)

---

## Fichiers du projet

```
SPYA/
├── btui.py              ← TUI principale (SSH) — gestion BT + enregistrement
├── bt_connect_watch.sh  ← Daemon de surveillance profil HFP Jabra
└── capture.sh           ← Capture HFP alternative legacy (parec)

/etc/bluetooth/
└── main.conf            ← Config BlueZ (Name=RPI-PC, Class, AlwaysPairable)

~/.config/wireplumber/bluetooth.lua.d/
├── 51-custom-bt.lua     ← Active mSBC, headset-roles
└── 52-jabra-hfp.lua     ← Force Jabra en headset-head-unit

~/recordings/
└── rec_YYYYMMDD_HHMMSS.wav  ← Enregistrements audio
```

---

## Configuration BlueZ `/etc/bluetooth/main.conf`

```ini
[General]
IOCapability = NoInputNoOutput
Name = RPI-PC
Class = 0x200404
DiscoverableTimeout = 0
AlwaysPairable = true

[Policy]
ReconnectAttempts = 0
AutoEnable = true
```

- `Name = RPI-PC` : nom visible depuis Windows lors de la recherche BT
- `Class = 0x200404` : classe "Audio/Video — Wearable Headset" — Windows identifie le RPi comme périphérique audio
- `AlwaysPairable = true` : pas besoin de lancer manuellement le mode pairing
- `IOCapability = NoInputNoOutput` : simplifie l'appairage (pas de PIN)

---

## Configuration WirePlumber

### `51-custom-bt.lua` — Activation mSBC et rôles HFP/HSP

```lua
bluez_monitor.properties = {
  ["bluez5.enable-msbc"]       = true,
  ["bluez5.enable-hw-volume"]  = true,
  ["bluez5.hfphsp-backend"]    = "native",
  ["bluez5.headset-roles"]     = "[ hsp_hs hsp_ag hfp_hf hfp_ag ]",
}
```

- `enable-msbc` : active le codec mSBC (16kHz wide-band) au lieu du CVSD (8kHz narrow-band)
- `hfphsp-backend = native` : BlueZ gère HFP directement, sans oFono
- `headset-roles` : le RPi joue **tous les rôles** — il peut être casque (HF) avec Jabra et gateway (AG) avec Windows simultanément

### `52-jabra-hfp.lua` — Forçage profil HFP Jabra

```lua
rule = {
  matches = {
    { { "device.name", "matches", "bluez_card.6C_FB_ED_67_F5_43" } },
  },
  apply_properties = {
    ["device.profile"] = "headset-head-unit",
  },
}
table.insert(bluez_monitor.rules, rule)
```

Force le Jabra en profil `headset-head-unit` (HFP mSBC) à chaque connexion. Sans cette règle, WirePlumber peut laisser le casque en A2DP même lors d'un appel, ce qui bloque le micro.

---

## Interface TUI — `btui.py`

### Menus disponibles

```
╔══════════════════════════════════════════════╗
║  BT BRIDGE MANAGER   PipeWire 1.2.7          ║
╠══════════════════════════════════════════════╣
║  DONGLES                                     ║
║  hci0 A0:AD:9F:73:B7:76  Casque  UP          ║
║   ● Jabra HomeWork       [conn]              ║
║  hci1 A0:AD:9F:73:C5:49  PC      UP          ║
║   ● AXOLOTL              [conn]              ║
╠══════════════════════════════════════════════╣
║  [1] Connecter un peripherique               ║
║  [2] Visible PC         (hci1)               ║
║  [3] Appairer casque    (hci0)               ║
║  [4] Scanner nouveaux appareils              ║
║  [5] Deconnecter un peripherique             ║
║  [6] Demarrer enregistrement                 ║
║  [l] Lister enregistrements                  ║
║  [r] Actualiser   [q] Quitter                ║
╚══════════════════════════════════════════════╝
```

### Architecture interne `btui.py`

```
btui.py
│
├── get_dev_map()        Détection adaptateurs → appareils
│   ├── /var/lib/bluetooth/{adapter_mac}/  (appareils appairés)
│   └── hcitool -i hciX con               (connexions actives)
│
├── get_devices()        État complet des appareils BT
│   └── bluetoothctl info {mac}
│
├── get_bt_sources()     Sources PipeWire actives
│   └── pactl list sources short
│
├── get_src_fmt(src)     Format audio d'une source (rate, channels)
│   └── pactl list sources short (parsing Hz/ch)
│
├── start_recording()    Lance 2 pw-record en parallèle
│   ├── pw-record --target=bluez_input.*   (micro HFP)
│   └── pw-record --target=bluez_output.*.monitor (haut-parleur)
│
└── stop_recording()     Arrête l'enregistrement
    ├── terminate() sur les 2 processus pw-record
    ├── fix_wav()   Répare les headers WAV (RIFF chunk sizes)
    └── sox -m      Mix micro + haut-parleur → fichier final
        (thread daemon — non bloquant pour l'UI)
```

---

## Pipeline d'enregistrement

```
Appel Teams en cours
│
├─ pw-record ──► /tmp/mic_TIMESTAMP.wav  (bluez_input.* 16kHz mono)
│
└─ pw-record ──► /tmp/spk_TIMESTAMP.wav  (bluez_output.*.monitor 16kHz mono)

Appui [6] STOP
│
├─ SIGTERM sur les 2 processus pw-record
│
├─ fix_wav()  ← Corrige les headers WAV (data size = 0 après SIGTERM)
│   ├─ RIFF chunk size = filesize - 8
│   └─ data chunk size = filesize - 44
│
├─ sox -m mic.wav spk.wav rec_TIMESTAMP.wav  (thread background)
│
└─ ~/recordings/rec_YYYYMMDD_HHMMSS.wav  ✓
```

---

## Problèmes rencontrés et solutions

### 1. Détection des adaptateurs Bluetooth

**Problème** : BlueZ 5.66 a supprimé le chemin `/org/bluez/hci` de la sortie de `bluetoothctl info`, rendant la détection adaptateur→appareil impossible avec l'ancienne méthode de parsing.

**Solution** : Double mécanisme dans `get_dev_map()` :
```python
# Appareils appairés → adapter via le système de fichiers
for e in os.listdir(f"/var/lib/bluetooth/{adapter_mac}"):
    if len(e)==17 and e.count(":")==5:
        paired_map[e] = hci

# Connexions actives → adapter via hcitool
for l in run(f"hcitool -i {hci} con").splitlines():
    if "ACL" in l:
        connected_map[mac] = hci
```

`/var/lib/bluetooth/{adapter_mac}/` liste les MACs des appareils appairés sur chaque dongle, sans nécessiter de droits root.

---

### 2. Headers WAV corrompus après arrêt de pw-record

**Problème** : `pw-record` tué avec `SIGTERM` ne met pas à jour les champs de taille dans le header WAV (`RIFF chunk size` et `data chunk size` restent à 0). `sox` lit le header, voit 0 samples, et produit un fichier vide.

```
Avant fix : riff=8 data=0  actual=5.6MB  → sox produit 44 bytes
Après fix : riff=correct data=correct    → sox produit le bon fichier
```

**Solution** : Correction du header avant mixage :
```python
def fix_wav(fn):
    s = os.path.getsize(fn)
    if s < 44: return
    with open(fn, "r+b") as f:
        f.seek(4);  f.write(struct.pack("<I", s - 8))   # RIFF size
        f.seek(40); f.write(struct.pack("<I", s - 44))  # data size
```

---

### 3. Mixage audio trop lent sur ARMv6

**Problème** : `ffmpeg -filter_complex amix` ne termine pas dans un délai raisonnable sur le RPi 1 ARMv6 (timeout à 120s même pour des fichiers de 2 secondes). Le filtre `amix` resamplé et sa gestion mémoire sont incompatibles avec l'architecture ARMv6.

**Solution** : Remplacement par `sox -m` (SoX 14.4.2) :
- Mixage de 5 minutes en ~40s sur ARMv6 (acceptable en background)
- Traitement en arrière-plan dans un thread daemon pour ne pas bloquer l'UI
- Fallback `shutil.copy2` si le micro n'était pas actif (mode A2DP pur)

```python
# Thread daemon — l'UI reste réactive pendant la finalisation
threading.Thread(target=_finalize, args=(mf, sf, out), daemon=True).start()
```

---

### 4. Entrée clavier bloquée / actions répétées

**Problème** : L'appui maintenu sur une touche ou un retour rapide dans le menu déclenchait plusieurs fois la même action (ex : démarrage de N enregistrements simultanés).

**Solution** : Vidage du buffer stdin avant chaque `input()` :
```python
try:
    import termios, sys
    termios.tcflush(sys.stdin, termios.TCIFLUSH)
except:
    pass
ch = input(' > ').strip().lower()
```

---

### 5. profil HFP non activé automatiquement

**Problème** : Après connexion, WirePlumber laissait parfois le Jabra en profil A2DP, rendant le micro indisponible pour Teams.

**Solution en deux couches** :
- **WirePlumber rule** (`52-jabra-hfp.lua`) : force `headset-head-unit` à la connexion
- **Daemon `bt_connect_watch.sh`** : vérifie toutes les 2s et corrige si le profil dévie

---

## Surveillance du profil HFP — `bt_connect_watch.sh`

```bash
JABRA="bluez_card.6C_FB_ED_67_F5_43"
while true; do
    STATUS=$(pactl list cards short 2>/dev/null | grep "$JABRA")
    if [ -n "$STATUS" ]; then
        PROF=$(pactl list cards 2>/dev/null | grep -A5 "Name: $JABRA" \
               | grep "Active Profile" | awk '{print $3}')
        if [ "$PROF" != "headset-head-unit" ]; then
            pactl set-card-profile "$JABRA" headset-head-unit 2>/dev/null
        fi
    fi
    sleep 2
done
```

Lance au démarrage via `systemd --user` ou en arrière-plan depuis `btui.py`.

---

## Installation

### 1. Dépendances

```bash
sudo apt update
sudo apt install -y pipewire pipewire-audio wireplumber sox bluetooth bluez
```

### 2. Configuration BlueZ

```bash
sudo cp config/main.conf /etc/bluetooth/main.conf
sudo systemctl restart bluetooth
```

### 3. Configuration WirePlumber

```bash
mkdir -p ~/.config/wireplumber/bluetooth.lua.d/
cp config/51-custom-bt.lua ~/.config/wireplumber/bluetooth.lua.d/
cp config/52-jabra-hfp.lua ~/.config/wireplumber/bluetooth.lua.d/
systemctl --user restart wireplumber
```

### 4. Lancement de l'UI

```bash
cd ~/SPYA
./btui.py
```

### 5. Connexion rapide Jabra

```bash
bluetoothctl connect 6C:FB:ED:67:F5:43
```

### 6. Côté Windows

Dans Teams/Zoom : sélectionner **RPI-PC** comme périphérique audio (haut-parleur **et** micro).

---

## Utilisation quotidienne

```
1. SSH sur le RPi
2. cd ~/SPYA && ./btui.py
3. Si Jabra déconnecté → [1] Connecter → choisir Jabra
4. Lancer Teams → sélectionner "RPI-PC" → appel full-duplex
5. [6] pour enregistrer / [6] pour arrêter
6. [l] pour lister les enregistrements dans ~/recordings/
```

---

## Démarrage automatique

PipeWire et WirePlumber démarrent automatiquement via `systemd --user` au boot.

Pour `bt_connect_watch.sh` en service :

```bash
# ~/.config/systemd/user/bt-watch.service
[Unit]
Description=Jabra HFP profile watcher

[Service]
ExecStart=/home/prelude/SPYA/bt_connect_watch.sh
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now bt-watch
```

---

## Versions

| Composant | Version |
|-----------|---------|
| Raspberry Pi OS | Bookworm (12) |
| Kernel | 6.1.21+ ARMv6 |
| PipeWire | 1.2.7 |
| WirePlumber | 0.4.13 |
| BlueZ | 5.66 |
| Python | 3.11.2 |
| SoX | 14.4.2 |
