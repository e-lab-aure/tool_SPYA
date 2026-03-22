#!/bin/bash
#
# bt_connect_watch.sh — Surveillance du profil audio du casque Bluetooth
#
# Vérifie toutes les 2 secondes que le casque est bien en profil HFP
# (headset-head-unit). Corrige automatiquement si le profil dévie.
#
# Configuration lue depuis /etc/spya.conf ou ~/.config/spya/spya.conf.
# Le champ 'headset_mac' doit être renseigné.
#
# Usage : lancer via systemd --user (voir config/bt-watch.service)
#         ou manuellement en arrière-plan : ./bt_connect_watch.sh &

set -uo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────

TARGET_PROFILE="headset-head-unit"
CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/spya/spya.conf"
FALLBACK_CONFIG="/etc/spya.conf"


# ─── Fonctions utilitaires ────────────────────────────────────────────────────

log() {
    # Affiche un message horodaté sur stdout (capturé par journald si lancé via systemd)
    # Usage : log "LEVEL" "message"
    local level="$1"
    local msg="$2"
    echo "[${level}] $(date '+%Y-%m-%d %H:%M:%S') — ${msg}"
}

load_headset_card() {
    # Lit le MAC du casque dans le fichier de configuration et le convertit
    # au format PipeWire/BlueZ : XX:XX:XX:XX:XX:XX → bluez_card.XX_XX_XX_XX_XX_XX
    local conf_file=""

    if [ -f "$CONFIG_FILE" ]; then
        conf_file="$CONFIG_FILE"
    elif [ -f "$FALLBACK_CONFIG" ]; then
        conf_file="$FALLBACK_CONFIG"
    fi

    if [ -z "$conf_file" ]; then
        return 1
    fi

    local mac
    mac=$(grep -i 'headset_mac' "$conf_file" \
          | head -1 \
          | awk -F'=' '{print $2}' \
          | tr -d ' \t\r')

    if [ -z "$mac" ]; then
        return 1
    fi

    # Conversion : 6C:FB:ED:67:F5:43 → bluez_card.6C_FB_ED_67_F5_43
    echo "bluez_card.$(echo "$mac" | tr ':' '_')"
}


# ─── Initialisation ───────────────────────────────────────────────────────────

HEADSET_CARD=$(load_headset_card) || {
    log "CRITICAL" "headset_mac non configuré dans spya.conf — arrêt"
    exit 1
}

log "INFO" "Démarrage — casque: ${HEADSET_CARD}, profil cible: ${TARGET_PROFILE}"

previous_profile=""


# ─── Boucle de surveillance ───────────────────────────────────────────────────

while true; do

    # Vérifie si la carte audio BT est présente dans PipeWire
    card_status=$(pactl list cards short 2>/dev/null | grep "$HEADSET_CARD" || true)

    if [ -n "$card_status" ]; then

        # Lit le profil actif de la carte
        current_profile=$(
            pactl list cards 2>/dev/null \
            | grep -A5 "Name: ${HEADSET_CARD}" \
            | grep 'Active Profile' \
            | awk '{print $3}' \
            || true
        )

        # Corrige le profil uniquement si différent de la cible ET nouveau
        # (la vérification du changement évite de spammer pactl inutilement)
        if [ "$current_profile" != "$TARGET_PROFILE" ] \
        && [ "$current_profile" != "$previous_profile" ]; then

            log "WARNING" "Profil incorrect: '${current_profile}' → correction vers '${TARGET_PROFILE}'"
            sleep 0.5

            if pactl set-card-profile "$HEADSET_CARD" "$TARGET_PROFILE" 2>/dev/null; then
                log "INFO" "Profil corrigé avec succès"
            else
                log "ERROR" "Echec de la correction du profil"
            fi
        fi

        previous_profile="$current_profile"

    else
        # Carte absente (casque déconnecté) — réinitialise le profil mémorisé
        if [ -n "$previous_profile" ]; then
            log "INFO" "Casque déconnecté"
        fi
        previous_profile=""
    fi

    sleep 2
done
