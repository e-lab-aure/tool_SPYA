#!/bin/bash
JABRA="bluez_card.6C_FB_ED_67_F5_43"
echo "[watch] Surveillance Jabra HFP..."
prev=""
while true; do
    STATUS=$(pactl list cards short 2>/dev/null | grep "$JABRA")
    if [ -n "$STATUS" ]; then
        PROF=$(pactl list cards 2>/dev/null | grep -A5 "Name: $JABRA" | grep "Active Profile" | awk "{print \$3}")
        if [ "$PROF" != "headset-head-unit" ] && [ "$PROF" != "$prev" ]; then
            echo "[watch] Jabra profil=$PROF -> HFP..."
            sleep 0.5
            pactl set-card-profile "$JABRA" headset-head-unit 2>/dev/null
        fi
        prev="$PROF"
    else
        prev=""
    fi
    sleep 2
done
