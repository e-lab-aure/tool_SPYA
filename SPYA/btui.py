#!/usr/bin/env python3
"""
SPYA — Système Phone Your Audio

Proxy Bluetooth transparent pour bridge et capture audio HFP/A2DP.
Interface TUI SSH pour la gestion des connexions Bluetooth et l'enregistrement
des flux audio (micro + haut-parleur) via PipeWire/WirePlumber.

Prérequis système : pipewire, wireplumber, bluez, sox, hcitools, pactl
Configuration      : /etc/spya.conf ou ~/.config/spya/spya.conf
"""

import configparser
import datetime
import logging
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional


# ─── Chargement de la configuration ──────────────────────────────────────────

_CONFIG_PATHS = [
    Path('/etc/spya.conf'),
    Path.home() / '.config' / 'spya' / 'spya.conf',
]

_CONFIG_DEFAULTS = {
    'adapter_headset_hci':  'hci0',
    'adapter_headset_mac':  '',
    'adapter_terminal_hci': 'hci1',
    'adapter_terminal_mac': '',
    'headset_mac':          '',
    'rec_dir':              str(Path.home() / 'recordings'),
    'log_file':             str(Path.home() / 'SPYA' / 'spya.log'),
    'tui_width':            '54',
}


def _load_config() -> configparser.SectionProxy:
    """
    Charge la configuration depuis /etc/spya.conf ou ~/.config/spya/spya.conf.
    Applique les valeurs par défaut si aucun fichier n'est trouvé.

    Returns:
        Section de configuration [spya] avec valeurs fusionnées.
    """
    parser = configparser.ConfigParser(defaults=_CONFIG_DEFAULTS)
    parser.add_section('spya')
    for path in _CONFIG_PATHS:
        if path.exists():
            parser.read(str(path))
            break
    return parser['spya']


_CFG = _load_config()

REC_DIR         = _CFG['rec_dir']
LOG_FILE        = _CFG['log_file']
TUI_WIDTH       = int(_CFG['tui_width'])
HCI_HEADSET     = _CFG['adapter_headset_hci']
HCI_TERMINAL    = _CFG['adapter_terminal_hci']
ADAPTER_MAC_MAP = {
    HCI_HEADSET:  _CFG['adapter_headset_mac'],
    HCI_TERMINAL: _CFG['adapter_terminal_mac'],
}
HCI_LABELS = {
    HCI_HEADSET:  'Casque',
    HCI_TERMINAL: 'Terminal',
}


# ─── Logging ──────────────────────────────────────────────────────────────────

def _setup_logger() -> logging.Logger:
    """
    Configure le logger applicatif vers fichier uniquement.
    La sortie console est évitée pour ne pas corrompre l'affichage TUI.

    Returns:
        Logger configuré 'spya'.
    """
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('spya')
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            '[%(levelname)s] %(asctime)s — %(funcName)s — %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(handler)
    return logger


log = _setup_logger()


# ─── Codes ANSI ───────────────────────────────────────────────────────────────

RESET  = '\033[0m'
BOLD   = '\033[1m'
DIM    = '\033[2m'
GREEN  = '\033[92m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
RED    = '\033[91m'


# ─── Validation ───────────────────────────────────────────────────────────────

_MAC_PATTERN = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')


def is_valid_mac(mac: str) -> bool:
    """
    Valide le format d'une adresse MAC Bluetooth.

    Args:
        mac: Chaîne à valider.

    Returns:
        True si le format XX:XX:XX:XX:XX:XX est respecté.
    """
    return bool(_MAC_PATTERN.match(mac))


# ─── État global de l'enregistrement ─────────────────────────────────────────

# [proc_mic | None, proc_spk, path_mic_tmp, path_spk_tmp, path_output]
# Réinitialisé à [] quand aucun enregistrement n'est actif.
_rec_state: list = []


# ─── Exécution de commandes système ──────────────────────────────────────────

def run_cmd(cmd: str, timeout: int = 10) -> str:
    """
    Exécute une commande shell et retourne sa sortie standard.
    Logue les erreurs et timeouts sans lever d'exception vers l'appelant.

    Args:
        cmd:     Commande shell à exécuter.
        timeout: Délai maximum en secondes (défaut 10s).

    Returns:
        Sortie standard de la commande, ou chaîne vide en cas d'erreur.
    """
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            log.debug(
                f"Code retour {result.returncode} pour: {cmd!r} — "
                f"{result.stderr.strip()}"
            )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        log.warning(f"Timeout ({timeout}s) dépassé sur: {cmd!r}")
        return ''
    except OSError as exc:
        log.error(f"Erreur OS sur commande {cmd!r}: {exc}")
        return ''


# ─── Bluetooth — état des adaptateurs ────────────────────────────────────────

def get_adapters() -> dict:
    """
    Lit l'état des adaptateurs Bluetooth locaux via hciconfig.

    Returns:
        Dict { 'hciX': {'addr': str, 'up': bool} }
    """
    output       = run_cmd('hciconfig')
    adapters     = {}
    current_hci  = None

    for line in output.splitlines():
        if line.startswith('hci'):
            current_hci = line.split(':')[0]
            adapters[current_hci] = {'addr': '', 'up': False}
        elif current_hci and 'BD Address:' in line:
            adapters[current_hci]['addr'] = line.split('BD Address:')[1].split()[0]
        elif current_hci and 'UP' in line:
            adapters[current_hci]['up'] = True

    return adapters


def get_device_adapter_map() -> tuple:
    """
    Construit deux mappings MAC → adaptateur HCI :
    - Appareils appairés  : lecture de /var/lib/bluetooth/{adapter_mac}/
    - Connexions actives  : sortie de 'hcitool -i hciX con' (lignes ACL)

    BlueZ 5.66+ ne retourne plus /org/bluez/hci dans bluetoothctl info,
    ce double mécanisme compense cette régression.

    Returns:
        (paired_map, connected_map) — deux dicts { mac: hci_name }
    """
    paired_map    = {}
    connected_map = {}

    for hci, adapter_mac in ADAPTER_MAC_MAP.items():
        if not adapter_mac:
            continue
        bt_path = Path(f'/var/lib/bluetooth/{adapter_mac}')
        try:
            for entry in bt_path.iterdir():
                mac = entry.name
                if is_valid_mac(mac) and mac not in paired_map:
                    paired_map[mac] = hci
        except OSError as exc:
            log.warning(f"Impossible de lire {bt_path}: {exc}")

    for hci in ADAPTER_MAC_MAP:
        output = run_cmd(f'hcitool -i {hci} con')
        for line in output.splitlines():
            if 'ACL' in line:
                parts = line.split()
                if len(parts) >= 3 and is_valid_mac(parts[2]):
                    connected_map[parts[2]] = hci

    return paired_map, connected_map


def get_devices() -> dict:
    """
    Retourne l'état complet de tous les appareils BT connus (appairés ou connectés).

    Returns:
        Dict { mac: {'name': str, 'connected': bool, 'paired': bool, 'adapter': str} }
    """
    paired_map, connected_map = get_device_adapter_map()
    output  = run_cmd('bluetoothctl devices')
    devices = {}

    for line in output.splitlines():
        parts = line.split(' ', 2)
        if len(parts) < 3 or not is_valid_mac(parts[1]):
            continue
        mac, name = parts[1], parts[2]
        info = run_cmd(f'bluetoothctl info {mac}')
        devices[mac] = {
            'name':      name,
            'connected': mac in connected_map,
            'paired':    'Paired: yes' in info,
            'adapter':   connected_map.get(mac, paired_map.get(mac, 'unknown')),
        }

    return devices


def _parse_device_list(output: str) -> list:
    """
    Parse la sortie de 'bluetoothctl devices' en liste de tuples (mac, name).
    Filtre les lignes avec MAC invalide.

    Args:
        output: Sortie brute de bluetoothctl devices.

    Returns:
        Liste de tuples [(mac, name), ...]
    """
    devices = []
    for line in output.splitlines():
        parts = line.split(' ', 2)
        if len(parts) >= 3 and is_valid_mac(parts[1]):
            devices.append((parts[1], parts[2]))
    return devices


# ─── Bluetooth — actions ──────────────────────────────────────────────────────

def bt_connect(mac: str, name: str) -> str:
    """
    Connecte un périphérique Bluetooth par son adresse MAC.

    Args:
        mac:  Adresse MAC validée du périphérique.
        name: Nom affiché du périphérique (pour les messages et logs).

    Returns:
        Message de résultat pour affichage TUI.
    """
    log.info(f"Connexion BT: {name} ({mac})")
    result = run_cmd(f'bluetoothctl connect {mac}', timeout=20)

    if 'success' in result.lower():
        log.info(f"Connexion réussie: {name} ({mac})")
        return f'Connecté : {name}'

    log.warning(f"Echec connexion: {name} ({mac}) — réponse: {result!r}")
    return f'Echec connexion : {name}'


def bt_disconnect(mac: str, name: str) -> str:
    """
    Déconnecte un périphérique Bluetooth par son adresse MAC.

    Args:
        mac:  Adresse MAC validée du périphérique.
        name: Nom affiché du périphérique.

    Returns:
        Message de résultat pour affichage TUI.
    """
    log.info(f"Déconnexion BT: {name} ({mac})")
    result = run_cmd(f'bluetoothctl disconnect {mac}', timeout=10)

    if 'success' in result.lower():
        log.info(f"Déconnexion réussie: {name} ({mac})")
        return f'Déconnecté : {name}'

    log.warning(f"Echec déconnexion: {name} ({mac})")
    return f'Echec déconnexion : {name}'


# ─── Audio — sources PipeWire ─────────────────────────────────────────────────

def get_bt_audio_sources() -> tuple:
    """
    Détecte les sources audio Bluetooth actives dans PipeWire.

    Returns:
        (source_micro, source_moniteur) — noms PipeWire des sources actives.
        L'une ou l'autre peut être None si absente (ex: A2DP = pas de micro).
    """
    output         = run_cmd('pactl list sources short')
    mic_source     = None
    monitor_source = None

    for line in output.splitlines():
        if 'bluez' not in line:
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        source_name = tokens[1]
        if 'monitor' in line:
            monitor_source = source_name
        else:
            mic_source = source_name

    return mic_source, monitor_source


def get_source_format(source_name: str) -> tuple:
    """
    Lit le format audio (fréquence, canaux) d'une source PipeWire.

    Args:
        source_name: Nom de la source (ex: bluez_input.6C_FB_ED_67_F5_43.0)

    Returns:
        (sample_rate_hz, channels) — ex: (16000, 1) HFP, (48000, 2) A2DP.
        Retourne (48000, 2) par défaut si la source est introuvable.
    """
    output = run_cmd('pactl list sources short')

    for line in output.splitlines():
        if source_name not in line:
            continue
        tokens = line.split()
        try:
            channels    = int(next(t[:-2] for t in tokens if t.endswith('ch')))
            sample_rate = int(next(t[:-2] for t in tokens if t.endswith('Hz')))
            return sample_rate, channels
        except (StopIteration, ValueError) as exc:
            log.warning(f"Impossible de parser le format de {source_name!r}: {exc}")

    log.warning(f"Source {source_name!r} introuvable dans pactl — format par défaut appliqué")
    return 48000, 2


# ─── Enregistrement ───────────────────────────────────────────────────────────

def _fix_wav_header(filepath: str) -> None:
    """
    Corrige les champs de taille du header WAV après arrêt brutal de pw-record.

    pw-record tué via SIGTERM ne met pas à jour RIFF chunk size ni data chunk size
    dans le header WAV (les deux restent à 0). sox lit ces valeurs, voit 0 samples,
    et produit un fichier de sortie vide. Ce correctif recalcule les tailles
    réelles à partir de la taille du fichier sur disque.

    Structure WAV simplifiée :
      octets  0- 3 : 'RIFF'
      octets  4- 7 : taille totale - 8   (little-endian uint32)
      octets  8-11 : 'WAVE'
      octets 12-15 : 'fmt '
      ...
      octets 36-39 : 'data'
      octets 40-43 : taille des données  (little-endian uint32)

    Args:
        filepath: Chemin absolu vers le fichier WAV à corriger.
    """
    file_size = os.path.getsize(filepath)
    if file_size < 44:
        log.warning(
            f"Fichier WAV trop petit pour correction: {filepath} ({file_size} octets)"
        )
        return

    with open(filepath, 'r+b') as wav_file:
        wav_file.seek(4)
        wav_file.write(struct.pack('<I', file_size - 8))
        wav_file.seek(40)
        wav_file.write(struct.pack('<I', file_size - 44))

    log.debug(f"Header WAV corrigé: {filepath} ({file_size} octets)")


def _finalize_recording(mic_tmp: str, spk_tmp: str, output_path: str) -> None:
    """
    Finalise l'enregistrement : correction des headers WAV, mixage, nettoyage.
    Exécutée dans un thread daemon pour ne pas bloquer l'interface TUI.

    Étapes :
      1. Attente 1s que pw-record termine ses écritures bufférisées.
      2. Correction des headers WAV corrompus par SIGTERM (_fix_wav_header).
      3. Mixage micro + haut-parleur via 'sox -m' (si micro disponible).
         Timeout genereux (300s) car le RPi 1 ARMv6 est lent (~40s pour 5min).
      4. Copie simple du haut-parleur si micro absent (mode A2DP pur).
      5. Suppression des fichiers temporaires /tmp/spya_*.wav.

    Args:
        mic_tmp:     Chemin WAV temporaire micro.
        spk_tmp:     Chemin WAV temporaire haut-parleur.
        output_path: Chemin WAV final de sortie.
    """
    time.sleep(1)

    # Correction des headers corrompus avant tout traitement
    for tmp_file in (mic_tmp, spk_tmp):
        if os.path.exists(tmp_file):
            _fix_wav_header(tmp_file)

    mic_size = os.path.getsize(mic_tmp) if os.path.exists(mic_tmp) else 0

    if mic_size > 44:
        # Mixage micro + haut-parleur (sox -m = mix, pas concaténation)
        log.info(f"Mixage sox: {mic_tmp} + {spk_tmp} → {output_path}")
        run_cmd(f'sox -m {mic_tmp} {spk_tmp} {output_path}', timeout=300)

        if not os.path.exists(output_path) or os.path.getsize(output_path) <= 44:
            log.error(f"Sox a produit un fichier vide ou échoué: {output_path}")
        else:
            log.info(
                f"Enregistrement finalisé: {output_path} "
                f"({os.path.getsize(output_path)} octets)"
            )
    else:
        # Pas de micro actif (mode A2DP pur) — copie directe du haut-parleur
        log.info(f"Pas de micro actif — copie haut-parleur vers {output_path}")
        shutil.copy2(spk_tmp, output_path)
        log.info(f"Enregistrement finalisé: {output_path}")

    # Nettoyage des fichiers temporaires
    for tmp_file in (mic_tmp, spk_tmp):
        try:
            os.remove(tmp_file)
            log.debug(f"Fichier temporaire supprimé: {tmp_file}")
        except OSError as exc:
            log.warning(f"Impossible de supprimer {tmp_file}: {exc}")


def start_recording() -> tuple:
    """
    Démarre la capture audio des flux BT actifs via deux processus pw-record
    lancés en parallèle : micro (HFP) et haut-parleur (monitor PipeWire).

    Returns:
        (True, timestamp_str) si démarré avec succès.
        (False, message_erreur) si aucune source BT n'est disponible.
    """
    global _rec_state

    os.makedirs(REC_DIR, exist_ok=True)
    mic_source, monitor_source = get_bt_audio_sources()

    if not monitor_source:
        log.warning("Tentative d'enregistrement sans source audio BT active")
        return False, 'Aucune source audio Bluetooth trouvée.'

    timestamp   = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    mic_tmp     = f'/tmp/spya_mic_{timestamp}.wav'
    spk_tmp     = f'/tmp/spya_spk_{timestamp}.wav'
    output_path = f'{REC_DIR}/rec_{timestamp}.wav'

    # Capture micro — disponible uniquement en mode HFP (absent en A2DP pur)
    if mic_source:
        rate, channels = get_source_format(mic_source)
        proc_mic = subprocess.Popen(
            f'pw-record --target={mic_source} --rate={rate} --channels={channels} {mic_tmp}',
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        log.info(f"Capture micro: {mic_source} ({rate}Hz {channels}ch) → {mic_tmp}")
    else:
        # Fichier placeholder vide pour _finalize_recording
        Path(mic_tmp).touch()
        proc_mic = None
        log.info("Pas de source micro (mode A2DP) — placeholder créé")

    # Capture haut-parleur via la source monitor PipeWire
    rate, channels = get_source_format(monitor_source)
    proc_spk = subprocess.Popen(
        f'pw-record --target={monitor_source} --rate={rate} --channels={channels} {spk_tmp}',
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    log.info(f"Capture haut-parleur: {monitor_source} ({rate}Hz {channels}ch) → {spk_tmp}")

    _rec_state = [proc_mic, proc_spk, mic_tmp, spk_tmp, output_path]
    log.info(f"Enregistrement démarré — sortie: {output_path}")
    return True, timestamp


def stop_recording() -> str:
    """
    Arrête l'enregistrement en cours et lance la finalisation en arrière-plan.
    Retourne immédiatement pour ne pas bloquer l'interface TUI.

    Returns:
        Message de statut pour affichage TUI.
    """
    global _rec_state

    if not _rec_state:
        return 'Aucun enregistrement actif.'

    proc_mic, proc_spk, mic_tmp, spk_tmp, output_path = _rec_state
    _rec_state = []

    for proc in (proc_mic, proc_spk):
        if proc is None:
            continue
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            log.warning(f"pw-record PID {proc.pid} ne répond pas à SIGTERM — SIGKILL")
            proc.kill()
        except OSError as exc:
            log.error(f"Erreur à l'arrêt de pw-record: {exc}")

    log.info(f"Enregistrement arrêté — finalisation en arrière-plan: {output_path}")

    threading.Thread(
        target=_finalize_recording,
        args=(mic_tmp, spk_tmp, output_path),
        daemon=True,
        name='spya-finalize'
    ).start()

    return f'Arrêt enreg. — finalisation : {os.path.basename(output_path)}'


def list_recordings() -> str:
    """
    Liste les 10 derniers enregistrements dans le répertoire de capture.

    Returns:
        Noms de fichiers séparés par des sauts de ligne, ou message si vide.
    """
    os.makedirs(REC_DIR, exist_ok=True)
    files = sorted(os.listdir(REC_DIR))
    if not files:
        return 'Aucun enregistrement.'
    return '\n'.join(files[-10:])


# ─── Interface TUI ────────────────────────────────────────────────────────────

def _strip_ansi(text: str) -> str:
    """
    Supprime les codes ANSI d'une chaîne pour calculer sa longueur visible réelle.
    Nécessaire car len() compte les caractères de contrôle invisibles.

    Args:
        text: Chaîne pouvant contenir des codes ANSI.

    Returns:
        Chaîne sans codes ANSI.
    """
    for code in (RESET, BOLD, DIM, GREEN, YELLOW, CYAN, RED):
        text = text.replace(code, '')
    return text


def tui_line(content: str = '') -> str:
    """
    Encadre une ligne de contenu dans les bordures verticales de la TUI.
    Gère le décalage longueur réelle / longueur affichée dû aux codes ANSI.

    Args:
        content: Contenu à encadrer (peut contenir des codes ANSI).

    Returns:
        Ligne formatée avec bordures et padding.
    """
    inner_width    = TUI_WIDTH - 2
    visible_length = len(_strip_ansi(content))
    padding        = max(0, inner_width - visible_length)
    return f'{CYAN}║{RESET}{content}{" " * padding}{CYAN}║{RESET}'


def tui_sep() -> str:
    """Ligne de séparation horizontale de la TUI (╠═...═╣)."""
    return f'{CYAN}╠{"═" * TUI_WIDTH}╣{RESET}'


def tui_top() -> str:
    """Bordure supérieure de la TUI (╔═...═╗)."""
    return f'{CYAN}╔{"═" * TUI_WIDTH}╗{RESET}'


def tui_bot() -> str:
    """Bordure inférieure de la TUI (╚═...═╝)."""
    return f'{CYAN}╚{"═" * TUI_WIDTH}╝{RESET}'


def draw_ui(
    devices:   dict,
    adapters:  dict,
    recording: bool,
    rec_start: Optional[float],
    message:   str
) -> None:
    """
    Efface l'écran et redessine l'interface TUI complète.

    Args:
        devices:   État des périphériques BT (get_devices()).
        adapters:  État des adaptateurs HCI (get_adapters()).
        recording: True si un enregistrement est en cours.
        rec_start: Timestamp début enregistrement (time.time()), ou None.
        message:   Message de statut à afficher (résultat de la dernière action).
    """
    os.system('clear')
    print(tui_top())
    print(tui_line(f'  {BOLD}BT BRIDGE MANAGER{RESET}   {DIM}PipeWire / BlueZ{RESET}'))
    print(tui_sep())
    print(tui_line(f' {BOLD}{YELLOW}ADAPTATEURS{RESET}'))

    for hci in sorted(adapters):
        adapter_info = adapters[hci]
        label  = HCI_LABELS.get(hci, '?')
        status = f'{GREEN}UP{RESET}' if adapter_info.get('up') else f'{RED}DOWN{RESET}'
        print(tui_line(f'  {BOLD}{hci}{RESET} {adapter_info.get("addr", "")}  {label}  {status}'))

        hci_devices = [d for d in devices.values() if d['adapter'] == hci]
        if hci_devices:
            for device in hci_devices:
                dot   = f'{GREEN}●{RESET}' if device['connected'] else f'{RED}○{RESET}'
                flags = '[conn]' if device['connected'] else '[pair]' if device['paired'] else ''
                print(tui_line(f'   {dot} {device["name"][:24]:<24} {flags}'))
        else:
            print(tui_line(f'   {DIM}(aucun){RESET}'))

    print(tui_sep())

    if recording and rec_start:
        elapsed     = int(time.time() - rec_start)
        mins, secs  = divmod(elapsed, 60)
        print(tui_line(f' {RED}{BOLD}⏺  REC  {mins:02d}:{secs:02d}{RESET}'))
        print(tui_sep())

    print(tui_line(f' {BOLD}[1]{RESET} Connecter un périphérique'))
    print(tui_line(f' {BOLD}[2]{RESET} Rendre visible au terminal  ({HCI_TERMINAL})'))
    print(tui_line(f' {BOLD}[3]{RESET} Appairer casque             ({HCI_HEADSET})'))
    print(tui_line(f' {BOLD}[4]{RESET} Scanner nouveaux appareils'))
    print(tui_line(f' {BOLD}[5]{RESET} Déconnecter un périphérique'))

    if recording:
        print(tui_line(f' {RED}{BOLD}[6] STOP enregistrement{RESET}'))
    else:
        print(tui_line(f' {BOLD}[6]{RESET} Démarrer enregistrement'))

    print(tui_line(f' {BOLD}[l]{RESET} Lister enregistrements'))
    print(tui_line(f' {BOLD}[r]{RESET} Actualiser   {BOLD}[q]{RESET} Quitter'))

    if message:
        print(tui_sep())
        for chunk in [message[i:i + TUI_WIDTH - 4] for i in range(0, len(message), TUI_WIDTH - 4)]:
            print(tui_line(f' {YELLOW}{chunk}{RESET}'))

    print(tui_bot())
    print()


# ─── Actions du menu ──────────────────────────────────────────────────────────

def action_connect() -> str:
    """
    Affiche la liste des périphériques BT connus et connecte le choix de l'utilisateur.

    Returns:
        Message de résultat pour affichage TUI.
    """
    devices = _parse_device_list(run_cmd('bluetoothctl devices'))
    if not devices:
        return 'Aucun périphérique connu.'

    print(tui_top())
    for idx, (mac, name) in enumerate(devices):
        print(tui_line(f' {BOLD}[{idx + 1}]{RESET} {name} {DIM}{mac}{RESET}'))
    print(tui_line(f' {BOLD}[0]{RESET} Annuler'))
    print(tui_bot())

    choice = input(' Choix : ').strip()
    if not choice.isdigit() or int(choice) == 0:
        return ''

    idx = int(choice) - 1
    if idx >= len(devices):
        return 'Choix invalide.'

    mac, name = devices[idx]
    print(f' Connexion {name}...')
    return bt_connect(mac, name)


def action_disconnect() -> str:
    """
    Affiche les périphériques connectés et déconnecte le choix de l'utilisateur.

    Returns:
        Message de résultat pour affichage TUI.
    """
    all_devices       = _parse_device_list(run_cmd('bluetoothctl devices'))
    connected_devices = [
        (mac, name)
        for mac, name in all_devices
        if 'Connected: yes' in run_cmd(f'bluetoothctl info {mac}')
    ]

    if not connected_devices:
        return 'Aucun périphérique connecté.'

    print(tui_top())
    for idx, (mac, name) in enumerate(connected_devices):
        print(tui_line(f' {BOLD}[{idx + 1}]{RESET} {name} {DIM}{mac}{RESET}'))
    print(tui_line(f' {BOLD}[0]{RESET} Annuler'))
    print(tui_bot())

    choice = input(' Choix : ').strip()
    if not choice.isdigit() or int(choice) == 0:
        return ''

    idx = int(choice) - 1
    if idx >= len(connected_devices):
        return 'Choix invalide.'

    mac, name = connected_devices[idx]
    return bt_disconnect(mac, name)


def action_make_visible() -> str:
    """
    Rend l'adaptateur terminal visible (piscan) pour l'appairage depuis un terminal externe.
    La visibilité dure 60 secondes, délai géré par BlueZ.

    Returns:
        Message d'instruction pour l'utilisateur.
    """
    run_cmd(f'hciconfig {HCI_TERMINAL} piscan')
    log.info(f"Adaptateur {HCI_TERMINAL} mis en mode piscan")
    return f'{HCI_TERMINAL} visible 60s — cherchez le proxy depuis votre terminal'


def action_pair_headset() -> str:
    """
    Lance un scan BT sur l'adaptateur casque pour appairer un nouveau périphérique.
    Filtre les appareils déjà appairés sur HCI_HEADSET pour n'afficher que les nouveaux.

    Returns:
        Message de résultat pour affichage TUI.
    """
    headset_adapter_mac = ADAPTER_MAC_MAP.get(HCI_HEADSET, '')
    print(f' Mettez le casque en mode pairing, scan 15s...')

    try:
        proc = subprocess.Popen(
            ['bluetoothctl'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True
        )
        proc.stdin.write(f'select {headset_adapter_mac}\nagent on\nscan on\n')
        proc.stdin.flush()
        time.sleep(15)
        proc.stdin.write('scan off\nquit\n')
        proc.stdin.flush()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        log.warning("Timeout attente bluetoothctl lors du scan casque")
        proc.kill()
    except OSError as exc:
        log.error(f"Erreur lancement bluetoothctl pour scan: {exc}")
        return 'Erreur de scan Bluetooth.'

    # Appareils déjà appairés sur HCI_HEADSET — exclus de la liste proposée
    paired_map, _ = get_device_adapter_map()
    already_on_headset = {mac for mac, hci in paired_map.items() if hci == HCI_HEADSET}

    all_devices  = _parse_device_list(run_cmd('bluetoothctl devices'))
    new_devices  = [(mac, name) for mac, name in all_devices if mac not in already_on_headset]
    display_list = new_devices if new_devices else all_devices

    if not display_list:
        return 'Aucun appareil trouvé.'

    print(tui_top())
    for idx, (mac, name) in enumerate(display_list):
        print(tui_line(f' {BOLD}[{idx + 1}]{RESET} {name} {DIM}{mac}{RESET}'))
    print(tui_line(f' {BOLD}[0]{RESET} Annuler'))
    print(tui_bot())

    choice = input(' Choix (0=annuler) : ').strip()
    if not choice.isdigit() or int(choice) == 0:
        return ''

    idx = int(choice) - 1
    if idx >= len(display_list):
        return 'Choix invalide.'

    mac, name = display_list[idx]
    log.info(f"Appairage casque: {name} ({mac})")
    run_cmd(f'bluetoothctl pair {mac}', timeout=20)
    run_cmd(f'bluetoothctl trust {mac}', timeout=10)
    result = run_cmd(f'bluetoothctl connect {mac}', timeout=20)

    if 'success' in result.lower():
        log.info(f"Appairage réussi: {name} ({mac})")
        return f'Appairé et connecté : {name}'

    log.warning(f"Appairage tenté mais connexion incertaine: {name} ({mac})")
    return f'Appairage tenté : {name}'


def action_scan() -> str:
    """
    Lance un scan Bluetooth de 10 secondes et retourne les appareils découverts.

    Returns:
        Liste des appareils trouvés (8 max), ou message si vide.
    """
    print(' Scan 10s...')
    log.info("Scan BT démarré")
    output = run_cmd('bluetoothctl -- scan on & sleep 10; bluetoothctl devices', timeout=20)
    found  = [f'{name} ({mac})' for mac, name in _parse_device_list(output)]
    log.info(f"Scan terminé: {len(found)} appareil(s) trouvé(s)")
    return '\n'.join(found[:8]) if found else 'Aucun appareil trouvé.'


# ─── Boucle principale ────────────────────────────────────────────────────────

def _flush_stdin() -> None:
    """
    Vide le buffer stdin avant chaque lecture utilisateur.
    Évite les actions répétées dues aux touches maintenues ou retours rapides.
    Sans ce flush, une touche maintenue déclenche plusieurs actions successives.
    """
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (ImportError, OSError):
        pass  # Non disponible hors Linux


def main() -> None:
    """
    Point d'entrée. Initialise le contexte et lance la boucle d'interaction TUI.
    Gère SIGINT proprement (arrêt enregistrement si actif avant sortie).
    """
    log.info("SPYA démarré")

    message:   str            = ''
    recording: bool           = False
    rec_start: Optional[float] = None

    signal.signal(signal.SIGINT, lambda sig, frame: sys.exit(0))

    while True:
        draw_ui(get_devices(), get_adapters(), recording, rec_start, message)
        message = ''
        _flush_stdin()
        choice = input(' > ').strip().lower()

        if choice == 'q':
            if recording:
                stop_recording()
            log.info("SPYA arrêté")
            os.system('clear')
            sys.exit(0)

        elif choice == '1':
            message = action_connect()

        elif choice == '2':
            message = action_make_visible()

        elif choice == '3':
            message = action_pair_headset()

        elif choice == '4':
            message = action_scan()

        elif choice == '5':
            message = action_disconnect()

        elif choice == '6':
            if recording:
                message   = stop_recording()
                recording = False
                rec_start = None
            else:
                success, result = start_recording()
                if success:
                    recording = True
                    rec_start = time.time()
                else:
                    message = result

        elif choice == 'l':
            os.system('clear')
            print(tui_top())
            for line in list_recordings().splitlines():
                print(tui_line(f' {line}'))
            print(tui_bot())
            input(' [Entrée]...')

        # 'r' et tout autre choix : simple rafraîchissement de l'affichage


if __name__ == '__main__':
    main()
