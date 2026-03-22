-- WirePlumber — Active mSBC, hw-volume, et tous les rôles HFP/HSP
-- Place: ~/.config/wireplumber/bluetooth.lua.d/51-custom-bt.lua

bluez_monitor.properties = {
  ["bluez5.enable-msbc"]       = true,
  ["bluez5.enable-hw-volume"]  = true,
  ["bluez5.hfphsp-backend"]    = "native",
  ["bluez5.headset-roles"]     = "[ hsp_hs hsp_ag hfp_hf hfp_ag ]",
}
