-- 52-headset-hfp.lua — Force le casque cible en profil HFP à chaque connexion
--
-- Remplacer XX_XX_XX_XX_XX_XX par l'adresse MAC du casque (: remplacés par _)
-- Exemple : casque MAC 6C:FB:ED:67:F5:43 → bluez_card.6C_FB_ED_67_F5_43
--
-- Emplacement : ~/.config/wireplumber/bluetooth.lua.d/52-headset-hfp.lua
-- Appliquer   : systemctl --user restart wireplumber

rule = {
  matches = {
    {
      { "device.name", "matches", "bluez_card.XX_XX_XX_XX_XX_XX" },
    },
  },
  apply_properties = {
    -- headset-head-unit : HFP mSBC 16kHz — micro + haut-parleur full-duplex
    -- headset-head-unit-cvsd : HFP CVSD 8kHz (fallback si mSBC non supporté)
    ["device.profile"] = "headset-head-unit",
  },
}

table.insert(bluez_monitor.rules, rule)
