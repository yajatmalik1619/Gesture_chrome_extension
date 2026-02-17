"""
config_manager.py
─────────────────
Single source of truth for gestures_config.json.

Responsibilities:
  - Load and validate the config on startup
  - Watch the file for live changes (the UI writes to it, pipeline picks it up)
  - Provide typed accessors for every section the pipeline needs
  - Write back user changes (bindings, settings, custom gestures)

Usage:
    cfg = ConfigManager("gestures_config.json")
    cfg.start_watching()           # background thread, reloads on file change
    action = cfg.get_binding("FIST")          # → "window_minimize"
    cfg.set_binding("FIST", "tab_close")      # persists to disk
"""

import json
import threading
import time
import logging
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, config_path: str = "gestures_config.json"):
        self._path = Path(config_path)
        self._lock = threading.RLock()
        self._config: dict = {}
        self._last_mtime: float = 0.0
        self._watch_thread: Optional[threading.Thread] = None
        self._watching = False
        self._on_reload_callbacks: list[Callable] = []

        self._load()

    # ── Load / Save ────────────────────────────────────────────────────────────

    def _load(self):
        """Read and parse the JSON file. Thread-safe."""
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            with self._lock:
                self._config = data
                self._last_mtime = self._path.stat().st_mtime
            logger.info(f"Config loaded from {self._path}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load config: {e}")
            raise

    def save(self):
        """Write current in-memory config back to disk."""
        with self._lock:
            data = self._config.copy()
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        logger.info("Config saved.")

    # ── File Watcher ───────────────────────────────────────────────────────────

    def start_watching(self, poll_interval: float = 1.0):
        """Spawn a daemon thread that polls for file changes every `poll_interval` seconds."""
        if self._watching:
            return
        self._watching = True
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            args=(poll_interval,),
            daemon=True,
            name="ConfigWatcher"
        )
        self._watch_thread.start()
        logger.info("Config file watcher started.")

    def stop_watching(self):
        self._watching = False

    def _watch_loop(self, interval: float):
        while self._watching:
            try:
                mtime = self._path.stat().st_mtime
                if mtime != self._last_mtime:
                    logger.info("Config file changed — reloading.")
                    self._load()
                    for cb in self._on_reload_callbacks:
                        try:
                            cb(self._config)
                        except Exception as e:
                            logger.warning(f"Reload callback error: {e}")
            except Exception as e:
                logger.warning(f"Config watcher error: {e}")
            time.sleep(interval)

    def on_reload(self, callback: Callable[[dict], None]):
        """Register a callback that fires whenever the config is reloaded."""
        self._on_reload_callbacks.append(callback)

    # ── Generic Accessors ──────────────────────────────────────────────────────

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Nested key access. e.g. cfg.get("settings", "scroll_speed") → 3
        """
        with self._lock:
            node = self._config
            for k in keys:
                if not isinstance(node, dict) or k not in node:
                    return default
                node = node[k]
            return node

    def set(self, *keys_and_value, persist: bool = True):
        """
        Nested key setter. Last positional arg is the value.
        e.g. cfg.set("settings", "scroll_speed", 5)
        """
        *keys, value = keys_and_value
        with self._lock:
            node = self._config
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = value
        if persist:
            self.save()

    # ── Settings ───────────────────────────────────────────────────────────────

    @property
    def settings(self) -> dict:
        return self.get("settings", default={})

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.get("settings", key, default=default)

    def set_setting(self, key: str, value: Any):
        self.set("settings", key, value)

    # ── Actions ────────────────────────────────────────────────────────────────

    @property
    def actions(self) -> dict:
        return self.get("actions", default={})

    def get_action(self, action_id: str) -> Optional[dict]:
        return self.get("actions", action_id)

    def is_repeatable(self, action_id: str) -> bool:
        return self.get("actions", action_id, "repeatable", default=False)

    def action_has_modifier(self, action_id: str) -> bool:
        return self.get("actions", action_id, "modifier") == "finger_count"

    def action_has_two_hand(self, action_id: str) -> bool:
        return bool(self.get("actions", action_id, "two_hand", "enabled", default=False))

    # ── Gestures ───────────────────────────────────────────────────────────────

    @property
    def gestures(self) -> dict:
        return self.get("gestures", default={})

    def get_gesture(self, gesture_id: str) -> Optional[dict]:
        return self.get("gestures", gesture_id)

    def is_gesture_enabled(self, gesture_id: str) -> bool:
        # Check built-in first, then custom
        enabled = self.get("gestures", gesture_id, "enabled")
        if enabled is None:
            enabled = self.get("custom_gestures", gesture_id, "enabled")
        return bool(enabled)

    def set_gesture_enabled(self, gesture_id: str, enabled: bool):
        """Enable / disable a gesture. Checks both built-in and custom."""
        if self.get("gestures", gesture_id) is not None:
            self.set("gestures", gesture_id, "enabled", enabled)
        elif self.get("custom_gestures", gesture_id) is not None:
            self.set("custom_gestures", gesture_id, "enabled", enabled)
        else:
            logger.warning(f"Gesture not found: {gesture_id}")

    # ── Bindings ───────────────────────────────────────────────────────────────

    @property
    def bindings(self) -> dict:
        return self.get("bindings", default={})

    def get_binding(self, gesture_id: str) -> Optional[str]:
        """Return the action_id bound to a gesture, or None if unbound/disabled."""
        if not self.is_gesture_enabled(gesture_id):
            return None
        action = self.get("bindings", gesture_id)
        return action if action != "none" else None

    def set_binding(self, gesture_id: str, action_id: str):
        """Reassign a gesture to a different action."""
        self.set("bindings", gesture_id, action_id)
        logger.info(f"Binding updated: {gesture_id} → {action_id}")

    # ── Custom Gestures ────────────────────────────────────────────────────────

    @property
    def custom_gestures(self) -> dict:
        raw = self.get("custom_gestures", default={})
        # Filter out metadata keys starting with _
        return {k: v for k, v in raw.items() if not k.startswith("_")}

    def get_custom_gesture(self, gesture_id: str) -> Optional[dict]:
        return self.get("custom_gestures", gesture_id)

    def save_custom_gesture(self, gesture_id: str, gesture_data: dict):
        """Persist a newly recorded custom gesture."""
        self.set("custom_gestures", gesture_id, gesture_data)
        # Auto-create a binding entry as 'none' if not already set
        if gesture_id not in self.bindings:
            self.set("bindings", gesture_id, "none", persist=False)
        self.save()
        logger.info(f"Custom gesture saved: {gesture_id}")

    def delete_custom_gesture(self, gesture_id: str):
        """Remove a custom gesture and its binding."""
        with self._lock:
            self._config.get("custom_gestures", {}).pop(gesture_id, None)
            self._config.get("bindings", {}).pop(gesture_id, None)
        self.save()
        logger.info(f"Custom gesture deleted: {gesture_id}")

    def add_sample_to_custom_gesture(self, gesture_id: str, sample: dict):
        """Append a new recording sample to an existing custom gesture."""
        with self._lock:
            cg = self._config.get("custom_gestures", {})
            if gesture_id not in cg:
                logger.warning(f"Custom gesture not found: {gesture_id}")
                return
            cg[gesture_id].setdefault("samples", []).append(sample)
        self.save()

    # ── Two-Hand Multiplier Config ─────────────────────────────────────────────

    @property
    def multiplier_config(self) -> dict:
        return self.get_setting("two_hand_multiplier", default={
            "enabled": True,
            "activation": "hold",
            "hold_duration_seconds": 0.5,
            "max_fingers": 5,
            "max_product": 25
        })

    # ── Cursor Layer Config ────────────────────────────────────────────────────

    @property
    def cursor_config(self) -> dict:
        return self.get("cursor_layer", default={})

    # ── WebSocket Config ───────────────────────────────────────────────────────

    @property
    def ws_host(self) -> str:
        return self.get_setting("websocket_host", default="localhost")

    @property
    def ws_port(self) -> int:
        return self.get_setting("websocket_port", default=8765)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def all_gesture_ids(self) -> list[str]:
        """All enabled gesture IDs from both built-in and custom."""
        ids = [
            gid for gid, g in self.gestures.items()
            if g.get("enabled", True)
        ]
        ids += [
            gid for gid, g in self.custom_gestures.items()
            if g.get("enabled", True)
        ]
        return ids

    def __repr__(self):
        return f"<ConfigManager path={self._path} gestures={len(self.gestures)} bindings={len(self.bindings)}>"
