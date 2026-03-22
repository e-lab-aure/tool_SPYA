# SPYA — Bluetooth Audio Proxy : Capture Hardware de Flux Audio

> **S**ystème **P**hone **Y**our **A**udio — Proxy Bluetooth transparent entre n'importe quel terminal (PC, smartphone, tablette) et n'importe quel casque/écouteur, avec capture hardware des flux audio entrant et sortant.

---

## ⚠️ Avertissement légal

> **L'enregistrement de conversations à l'insu de l'une des parties est illégal dans de nombreux pays.**
>
> L'utilisation de cet outil pour enregistrer des communications sans le consentement explicite de **toutes les parties impliquées** peut constituer une infraction pénale.
>
> - **France** : L'article 226-1 du Code pénal punit l'interception de communications privées de **1 an d'emprisonnement et 45 000 € d'amende**. La loi du 10 juillet 1991 encadre strictement les écoutes.
> - **Union Européenne** : Le RGPD (art. 5 et 6) impose une base légale pour tout traitement de données personnelles, dont les enregistrements vocaux.
> - **États-Unis** : La loi fédérale (Federal Wiretap Act, 18 U.S.C. § 2511) et les lois étatiques (dont certaines exigent le consentement de **toutes** les parties — "all-party consent states") encadrent les enregistrements.
> - **Canada, UK, Australie** : Législations similaires, sanctions variables.
>
> **Cas d'usage légaux** : usage strictement personnel, enregistrement de ses propres appels, documentation avec accord explicite de tous les participants, contextes professionnels réglementés (compliance, journalisme, recherche), tests techniques en environnement contrôlé.
>
> **L'auteur de ce projet décline toute responsabilité quant à l'utilisation de cet outil en dehors du cadre légal applicable dans votre juridiction.**

---

## Concept : le proxy Bluetooth comme point de capture universel

Les plateformes de visioconférence, téléphonie VoIP et communications unifiées (Teams, Zoom, Google Meet, téléphonie mobile, softphones...) intègrent des mécanismes qui limitent ou interdisent l'enregistrement audio depuis la couche applicative :

- **Désactivation de l'API d'enregistrement** pour les comptes non-administrateurs
- **Chiffrement end-to-end** qui rend impossible la capture au niveau réseau
- **Restrictions MDM/GPO** bloquant les logiciels d'enregistrement sur les terminaux professionnels
- **Détection des outils de capture** audio virtuels (VB-Cable, Voicemeeter, etc.)
- **Politique d'entreprise** interdisant l'installation de tout logiciel tiers

**SPYA contourne l'ensemble de ces restrictions par conception**, non pas en attaquant le logiciel ou le réseau, mais en opérant à une couche que ces systèmes ne peuvent pas contrôler : **le signal audio analogique/numérique entre le terminal et le périphérique audio**, au niveau hardware Bluetooth.

```
Applications (Teams, Zoom, téléphonie mobile...)
         │  ← restreintes, chiffrées, surveillées
         │
    [Terminal]  ←── zone de contrôle des plateformes
         │
         │  Signal BT ← SPYA s'insère ICI
         ▼
   [Proxy Linux]  ←── hors de portée des plateformes
         │
         ▼
  [Casque / Écouteurs]
```

Du point de vue du terminal (PC, smartphone), le proxy est un périphérique audio Bluetooth ordinaire. Il n'existe aucun moyen pour une application de distinguer un périphérique BT réel d'un proxy SPYA — le signal sort du terminal, passe par le proxy, et c'est là qu'il est capturé, **avant toute restriction applicative**.

---

## Ce que capture SPYA

```
┌─────────────────────────────────────────────────────────────────┐
│                         Terminal                                │
│   (PC, laptop, smartphone, tablette — tout système BT)         │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ Teams/Zoom   │    │ Téléphonie   │    │ Musique      │      │
│  │ (visio)      │    │ (mobile/VoIP)│    │ (streaming)  │      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
│         └──────────────────┴──────────────────┘              │
│                             │  Audio BT (A2DP / HFP)           │
└─────────────────────────────┼───────────────────────────────────┘
                              │
                   ┌──────────▼──────────┐
                   │   PROXY SPYA        │◄── SSH / Interface TUI
                   │   (Linux + BT)      │
                   │                     │
                   │  ┌───────────────┐  │
                   │  │  PipeWire     │  │
                   │  │  (routing)    │  │
                   │  └───────┬───────┘  │
                   │          │ pw-record│
                   │  ┌───────▼───────┐  │
                   │  │  recordings/  │  │◄── Fichiers WAV capturés
                   │  │  *.wav        │  │    (micro + haut-parleur)
                   │  └───────────────┘  │
                   └──────────┬──────────┘
                              │  Audio BT
                   ┌──────────▼──────────┐
                   │  Casque / Écouteurs │
                   │  (tout périphérique │
                   │   BT classique)     │
                   └─────────────────────┘
```

**Ce qui est capturé, sans exception :**
- Flux sortant (haut-parleur) : tout ce que l'utilisateur entend — voix des interlocuteurs, sons système, musique
- Flux entrant (micro) : tout ce que l'utilisateur dit, capturé au niveau BT avant transmission

Aucune application sur le terminal ne peut détecter cette capture. Elle se passe entièrement dans le proxy, sur un système Linux indépendant.

---

## Pourquoi c'est structurellement indétectable

Les systèmes de contrôle des enregistrements opèrent tous à la couche logicielle du terminal :

| Mécanisme de contrôle | Niveau | Contourné par SPYA |
|---|---|---|
| Désactivation de l'API d'enregistrement | Application | ✓ — SPYA n'utilise pas ces APIs |
| Restriction GPO/MDM sur logiciels | OS Terminal | ✓ — SPYA est sur un système séparé |
| Chiffrement end-to-end réseau | Transport | ✓ — capture après déchiffrement côté audio |
| Détection de périphériques audio virtuels | Driver/OS | ✓ — SPYA est un vrai périphérique BT matériel |
| Indicateurs d'enregistrement dans l'app | Application | ✓ — totalement transparent |
| Audit logs de l'entreprise | Application/Réseau | ✓ — aucune trace côté terminal |

Le signal audio, une fois sorti du terminal vers le périphérique Bluetooth, **appartient au domaine physique**. Il n'existe aucune couche protocolaire dans Bluetooth Classic (A2DP/HFP) qui permettrait à l'émetteur de savoir ce que le récepteur fait du signal.

---

## Architecture matérielle

```
          ┌──────────────────────────────────────┐
          │          Terminal source              │
          │  (PC / smartphone / tablette / etc.) │
          └──────────────────┬───────────────────┘
                             │
                   Bluetooth A2DP / HFP
                   (profils audio classiques)
                             │
          ┌──────────────────▼───────────────────┐
          │              PROXY SPYA               │
          │                                       │
          │  Adaptateur BT #1 ←→ Terminal         │
          │  Adaptateur BT #2 ←→ Casque           │
          │                                       │
          │  ┌─────────────────────────────────┐  │
          │  │  Stack Linux audio              │  │
          │  │  PipeWire + WirePlumber + BlueZ │  │
          │  └──────────────┬──────────────────┘  │
          │                 │                     │
          │         pw-record (capture)           │
          │                 │                     │
          │         ~/recordings/*.wav            │
          └──────────────────┬───────────────────┘
                             │
                   Bluetooth A2DP / HFP
                             │
          ┌──────────────────▼───────────────────┐
          │       Casque / Écouteurs BT           │
          │  (tout périphérique audio classique) │
          └──────────────────────────────────────┘
```

**Deux adaptateurs Bluetooth sont nécessaires** car les profils HFP exigent de jouer des rôles opposés simultanément :
- Adaptateur côté terminal : `HFP Audio Gateway` + `A2DP Source` (imite un casque pour le terminal)
- Adaptateur côté casque : `HFP Headset` + `A2DP Sink` (imite un terminal pour le casque)

Un seul adaptateur ne peut pas être les deux à la fois.

---

## Compatibilité matérielle

**Carte programmable** : N'importe quelle carte fonctionnant sous Linux avec support USB.

| Plateforme | Compatibilité | Notes |
|---|---|---|
| Raspberry Pi (toutes versions) | ✓ | Testé sur RPi 1B ARMv6 |
| Raspberry Pi Zero W/2W | ✓ | BT intégré utilisable pour un côté |
| Orange Pi / Banana Pi | ✓ | Toute distribution Debian/Ubuntu |
| BeagleBone | ✓ | |
| Odroid | ✓ | |
| PC x86 (laptop/mini-PC) | ✓ | Le plus performant |
| Tout Linux avec 2 ports USB | ✓ | |

**Adaptateurs Bluetooth** : N'importe quel dongle USB BT supportant les profils A2DP et HFP sous BlueZ (classe 1 ou 2, BT 2.x / 3.x / 4.x).

**Terminal source** : Tout périphérique capable de se connecter en Bluetooth audio — PC, Mac, smartphone Android/iOS, tablette, téléphone fixe BT, etc.

**Périphérique audio** : Tout casque ou écouteurs Bluetooth classique (BT Classic, pas LE Audio).

---

## Stack logicielle

```
┌──────────────────────────────────────────┐
│        btui.py  (TUI Python SSH)         │  ← Interface de contrôle
├──────────────────────────────────────────┤
│   PipeWire + WirePlumber                 │  ← Routage audio + profils BT
├──────────────────────────────────────────┤
│             BlueZ 5.x                    │  ← Stack Bluetooth Linux
├──────────────────────────────────────────┤
│        2× Dongles USB Bluetooth          │  ← Hardware
└──────────────────────────────────────────┘
```

- **PipeWire** : serveur audio moderne, gère nativement HFP/A2DP sans middleware supplémentaire
- **WirePlumber** : policy engine — bascule automatiquement entre profils A2DP (musique) et HFP (appel)
- **BlueZ** : implémentation Linux de la stack Bluetooth, backend HFP natif (pas d'oFono requis)
- **sox** : mixage audio WAV léger, adapté aux architectures embarquées faible puissance

---

## Flux audio et modes de capture

### Mode musique — A2DP

```
Terminal (streaming)
    │  A2DP Source
    ▼
[PipeWire — proxy]──────► /tmp/spk_TIMESTAMP.wav  (capture)
    │  A2DP Sink
    ▼
Casque (48kHz stéréo)
```

### Mode appel — HFP mSBC full-duplex

```
Terminal (micro sortant)          Terminal (haut-parleur entrant)
    ▲                                          │
    │  HFP AG uplink                 HFP AG downlink
    │                                          │
[PipeWire — proxy]                       [PipeWire — proxy]
    │  ▲                                       │  ▼
    │  └── /tmp/mic_TIMESTAMP.wav (capture)    └──► /tmp/spk_TIMESTAMP.wav (capture)
    │  HFP HF uplink                 HFP HF downlink
    │                                          │
Casque (micro 16kHz)              Casque (haut-parleur 16kHz)
```

Les deux flux sont capturés simultanément, puis mixés en un seul fichier WAV stéréo final.

### Bascule automatique A2DP ↔ HFP

```
Terminal démarre un appel
        │
        ▼
Signal HFP Audio Gateway envoyé au proxy
        │
        ▼
WirePlumber bascule le casque : A2DP Sink → HFP Headset-Head-Unit
        │
        ▼
Lien SCO établi — audio bidirectionnel 16kHz actif
        │
        ▼
Capture micro + haut-parleur simultanée
        │
    Appel terminé
        │
        ▼
Retour automatique en A2DP
```

---

## Interface TUI — `btui.py`

Contrôle complet via SSH, sans interface graphique :

```
╔══════════════════════════════════════════════════════╗
║  BT BRIDGE MANAGER   PipeWire 1.2.7                  ║
╠══════════════════════════════════════════════════════╣
║  DONGLES                                             ║
║  hci0 A0:AD:9F:73:B7:76  Casque  UP                  ║
║   ● Mon Casque BT            [conn]                  ║
║  hci1 A0:AD:9F:73:C5:49  Terminal  UP                ║
║   ● Mon PC / Smartphone      [conn]                  ║
╠══════════════════════════════════════════════════════╣
║  ⏺  REC  03:42                                       ║
╠══════════════════════════════════════════════════════╣
║  [1] Connecter un peripherique                       ║
║  [2] Visible terminal       (hci1)                   ║
║  [3] Appairer casque        (hci0)                   ║
║  [4] Scanner nouveaux appareils                      ║
║  [5] Deconnecter un peripherique                     ║
║  [6] STOP enregistrement                             ║
║  [l] Lister enregistrements                          ║
║  [r] Actualiser   [q] Quitter                        ║
╚══════════════════════════════════════════════════════╝
```

### Architecture interne

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
│   ├── pw-record --target=bluez_input.*          (micro HFP)
│   └── pw-record --target=bluez_output.*.monitor (haut-parleur)
│
└── stop_recording()     Arrête l'enregistrement
    ├── terminate() sur les 2 processus pw-record
    ├── fix_wav()   Répare les headers WAV corrompus
    └── sox -m      Mix micro + haut-parleur → fichier final
        (thread daemon — UI non bloquée)
```

---

## Pipeline d'enregistrement

```
Appel / session audio en cours
│
├─ pw-record ──► /tmp/mic_TIMESTAMP.wav  (bluez_input.*  — 16kHz mono HFP)
│
└─ pw-record ──► /tmp/spk_TIMESTAMP.wav  (bluez_output.*.monitor — 16kHz mono HFP
                                          ou 48kHz stéréo en A2DP)
Appui [6] STOP
│
├─ SIGTERM sur les 2 processus pw-record
│
├─ fix_wav()  ← Corrige les headers WAV (data_size = 0 après SIGTERM)
│   ├─ RIFF chunk size = filesize - 8
│   └─ data chunk size = filesize - 44
│
├─ sox -m mic.wav spk.wav rec_TIMESTAMP.wav  (thread background)
│
└─ ~/recordings/rec_YYYYMMDD_HHMMSS.wav  ✓
```

---

## Problèmes rencontrés et solutions

### 1. Détection des adaptateurs Bluetooth (BlueZ 5.66)

**Problème** : BlueZ 5.66 a supprimé le chemin `/org/bluez/hci` de la sortie de `bluetoothctl info`, rendant la détection adaptateur→appareil impossible par parsing.

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

`/var/lib/bluetooth/{adapter_mac}/` liste les MACs appairés sur chaque dongle, sans droits root.

---

### 2. Headers WAV corrompus après arrêt de pw-record

**Problème** : `pw-record` tué avec SIGTERM ne met pas à jour les champs de taille dans le header WAV. `sox` voit `data_size = 0` et produit un fichier vide.

```
Avant fix : riff=8 data=0  actual=5.6MB  → sox produit 44 bytes (vide)
Après fix : riff=correct data=correct    → sox produit le bon fichier
```

**Solution** — correction du header avant mixage :
```python
def fix_wav(fn):
    s = os.path.getsize(fn)
    if s < 44: return
    with open(fn, "r+b") as f:
        f.seek(4);  f.write(struct.pack("<I", s - 8))   # RIFF size
        f.seek(40); f.write(struct.pack("<I", s - 44))  # data size
```

---

### 3. Mixage audio incompatible avec les architectures ARMv6 faible puissance

**Problème** : `ffmpeg -filter_complex amix` timeout systématiquement sur ARMv6 700MHz — même pour des fichiers de 2 secondes. Le filtre est trop gourmand pour cette architecture.

**Solution** : `sox -m` (SoX 14.4.2), outil de traitement audio conçu pour l'embarqué :
- Mixage de 5 minutes en ~40s sur ARMv6 (traitement en arrière-plan)
- Non bloquant pour l'UI grâce au thread daemon
- Fallback `shutil.copy2` si le micro était absent (mode A2DP pur)

```python
threading.Thread(target=_finalize, args=(mf, sf, out), daemon=True).start()
```

---

### 4. Buffer clavier — actions répétées

**Problème** : Retour rapide dans le menu ou touche maintenue déclenchait plusieurs actions simultanées (N enregistrements lancés).

**Solution** : Vidage du buffer stdin avant chaque prompt :
```python
try:
    import termios, sys
    termios.tcflush(sys.stdin, termios.TCIFLUSH)
except:
    pass
ch = input(' > ').strip().lower()
```

---

### 5. Profil HFP non activé automatiquement à la connexion

**Problème** : WirePlumber pouvait laisser le casque en profil A2DP après connexion, rendant le micro indisponible.

**Solution en deux couches** :
- **WirePlumber rule** (`52-headset-hfp.lua`) : force `headset-head-unit` dès la connexion
- **Daemon `bt_connect_watch.sh`** : surveille toutes les 2s et corrige le profil si nécessaire

---

## Installation

### Prérequis matériels
- 1 carte Linux avec ≥2 ports USB libres
- 2 dongles Bluetooth USB (profils A2DP + HFP)

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

Adapter `Name=` dans `main.conf` au nom souhaité pour le proxy (visible depuis le terminal lors de l'appairage BT).

### 3. Configuration WirePlumber

```bash
mkdir -p ~/.config/wireplumber/bluetooth.lua.d/
cp config/51-custom-bt.lua ~/.config/wireplumber/bluetooth.lua.d/
# Adapter 52-headset-hfp.lua avec le MAC du casque cible
cp config/52-jabra-hfp.lua ~/.config/wireplumber/bluetooth.lua.d/
systemctl --user restart wireplumber
```

### 4. Adapter les MACs dans `btui.py`

```python
# Ligne ~33 — MACs des adaptateurs BT du proxy
AM = {
    "hci0": "XX:XX:XX:XX:XX:XX",  # dongle côté casque
    "hci1": "XX:XX:XX:XX:XX:XX",  # dongle côté terminal
}
```

Obtenir les MACs : `hciconfig -a`

### 5. Lancement

```bash
cd ~/SPYA
./btui.py
```

### 6. Côté terminal (PC / smartphone)

Appairer le proxy comme périphérique audio Bluetooth (il apparaît sous le `Name` configuré dans `main.conf`). Le sélectionner comme périphérique audio par défaut dans l'application cible.

---

## Démarrage automatique

PipeWire et WirePlumber démarrent via `systemd --user` au boot.

Service de surveillance profil (`config/bt-watch.service`) :

```bash
cp config/bt-watch.service ~/.config/systemd/user/
systemctl --user enable --now bt-watch
```

---

## Versions (configuration de référence)

| Composant | Version |
|-----------|---------|
| Linux (Raspberry Pi OS Bookworm) | Kernel 6.1.21+ ARMv6 |
| PipeWire | 1.2.7 |
| WirePlumber | 0.4.13 |
| BlueZ | 5.66 |
| Python | 3.11.2 |
| SoX | 14.4.2 |

> La configuration de référence utilise un Raspberry Pi 1 Model B (ARMv6 700MHz, 512MB RAM) — la plateforme Linux embarquée la plus contrainte possible. Le projet fonctionne sur toute carte plus récente avec de meilleures performances.
