-- WirePlumber — Force le Jabra HomeWork en profil HFP (headset-head-unit) en permanence
-- Place: ~/.config/wireplumber/bluetooth.lua.d/52-jabra-hfp.lua

rule = {
  matches = {
    {
      { "device.name", "matches", "bluez_card.6C_FB_ED_67_F5_43" },
    },
  },
  apply_properties = {
    ["device.profile"] = "headset-head-unit",
  },
}

table.insert(bluez_monitor.rules, rule)
