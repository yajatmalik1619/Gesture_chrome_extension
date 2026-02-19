# reset_gesture.py
from pipeline.config_manager import ConfigManager

cfg = ConfigManager("gestures_config_v2.json")

# Delete specific custom gesture(s) and their bindings
cfg.delete_custom_gesture("user_new_window")
cfg.delete_custom_gesture("user_new_incognito_window")

print("Done! Gestures cleared.")