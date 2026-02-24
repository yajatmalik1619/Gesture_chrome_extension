"""
task_mapper.py
─────────────
GestureTaskMapper — the single owner of gesture→task binding logic.

Responsibilities:
  - Map a detected gesture_id to a task_id (action_id)
  - Persist binding changes to config
  - Restore factory defaults
  - Expose the gesture catalog (what can be detected)
  - Expose the task catalog (what can be executed)

Nothing else in the pipeline should call cfg.get_binding() directly.
All routing decisions go through this class.
"""

import logging
from typing import Optional
from pipeline.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class GestureTaskMapper:
    """
    Maps gesture IDs → task IDs.

    This is the exclusive owner of binding logic. GestureRouter asks:
        task_id = mapper.get_task(gesture_id)

    The extension UI asks for updates via WebSocket, which hit:
        mapper.update(gesture_id, task_id)   # persists to disk
        mapper.reset_defaults()              # restore factory defaults
    """

    # The 7 active defaults — installed on first run and restored by "Reset"
    # All other built-in gestures are available but unmapped by default.
    DEFAULT_BINDINGS: dict[str, str] = {
        # ── Active by default ────────────────────────────────────────────────
        "SWIPE_DOWN":        "window_minimize",   # swipe down  → minimize window
        "SWIPE_UP":          "window_maximize",   # swipe up    → maximize window
        "SWIPE_LEFT":        "tab_switch_left",   # swipe left  → previous tab
        "SWIPE_RIGHT":       "tab_switch_right",  # swipe right → next tab
        "INDEX_ONLY":        "tab_new",           # index finger → new tab
        "FIST":              "tab_close",         # fist         → close tab
        "THUMBS_UP":         "fullscreen_toggle", # thumbs up    → fullscreen

        # ── Combos: recognized but no default task ───────────────────────────
        "TWO_FISTS":         "none",
        "DOUBLE_THUMBS_UP":  "none",
        "HIGH_FIVE":         "none",

        # ── Individually disabled (no task, won't fire) ──────────────────────
        "PALM":              "none",
        "PEACE":             "none",
        "OK":                "none",
        "POINTING_UP":       "none",
        "POINTING_DOWN":     "none",
        "WAVE":              "none",
    }

    def __init__(self, cfg: ConfigManager):
        self._cfg = cfg
        logger.info("GestureTaskMapper initialised.")

    # ── Core Mapping ────────────────────────────────────────────────────────────

    def get_task(self, gesture_id: str) -> Optional[str]:
        """
        Return the task_id bound to a gesture, or None if unmapped.

        The BINDING is the sole source of truth — we do NOT gate on
        the gesture's `enabled` flag.  A gesture that is `enabled: false`
        in the gestures section but has an explicit non-none binding should
        still fire that task (the user deliberately assigned it).

        Binding = "none" (or missing) -> nothing fires.
        GestureRouter calls this once per detected gesture per frame.
        """
        # HARDCODED: INDEX_ONLY MUST be area_screenshot_drag (unmappable)
        if gesture_id == "INDEX_ONLY":
            return "area_screenshot_drag"

        raw = self._cfg.get("bindings", gesture_id)
        if raw is None or raw == "none" or str(raw).startswith("_"):
            return None
        return raw

    # ── Mutation ────────────────────────────────────────────────────────────────

    def update(self, gesture_id: str, task_id: str) -> None:
        """
        Reassign a gesture to a different task and persist to disk immediately.
        Called by WebSocket UPDATE_BINDING handler.

        Side-effect: if a real (non-none) task is assigned to a gesture that
        had enabled=false, we auto-enable it so the `enabled` flag stays
        consistent with the binding.
        """
        # HARDCODED: INDEX_ONLY MUST be area_screenshot_drag (unmappable)
        if gesture_id == "INDEX_ONLY":
            return

        self._cfg.set_binding(gesture_id, task_id)

        # Auto-enable gesture when a real task is assigned to it
        if task_id and task_id != "none":
            if self._cfg.get("gestures", gesture_id, "enabled") is False:
                self._cfg.set_gesture_enabled(gesture_id, True)
            elif self._cfg.get("custom_gestures", gesture_id, "enabled") is False:
                self._cfg.set_gesture_enabled(gesture_id, True)

        logger.info(f"Mapping updated: {gesture_id} -> {task_id}")

    def reset_defaults(self) -> None:
        """
        Restore factory-default bindings for all built-in gestures.
        Custom gesture bindings are left unchanged.
        Called by WebSocket RESET_BINDINGS handler.
        """
        with self._cfg._lock:
            existing: dict = self._cfg._config.setdefault("bindings", {})
            for gid, tid in self.DEFAULT_BINDINGS.items():
                existing[gid] = tid
        self._cfg.save()
        logger.info("All built-in bindings reset to factory defaults.")

    # ── Catalogs ────────────────────────────────────────────────────────────────

    def all_mappings(self) -> dict[str, str]:
        """Return all current gesture→task pairs (skips comment keys)."""
        return {
            k: v for k, v in self._cfg.bindings.items()
            if not k.startswith("_") and isinstance(v, str)
        }

    def gesture_catalog(self) -> dict:
        """
        Full list of recognisable gestures (built-in + custom).
        Each entry: { label, type, hand, enabled, description }
        """
        gestures = {
            k: v for k, v in self._cfg.gestures.items()
            if not k.startswith("_")
        }
        custom = {
            k: v for k, v in self._cfg.custom_gestures.items()
            if not k.startswith("_")
        }
        return {**gestures, **custom}

    def task_catalog(self) -> dict:
        """
        Full list of executable tasks (actions).
        Each entry: { label, type, shortcut, ... }
        """
        return {
            k: v for k, v in self._cfg.actions.items()
            if not k.startswith("_")
        }

    def task_exists(self, task_id: str) -> bool:
        """Return True if task_id is a known action."""
        return task_id == "none" or task_id in self._cfg.actions
