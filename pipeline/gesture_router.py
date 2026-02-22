"""
gesture_router.py
The brain of the pipeline â€” translates raw FrameResult detections into
structured ActionEvent objects ready for WebSocket emission.

Responsibilities:
  1. Route built-in gesture IDs â†’ action IDs via bindings config.
  2. Run DTW matcher on each frame for custom gesture candidates.
  3. Implement the two-hand multiplier mechanic:
       - Track which hand has been stationary for â‰¥ hold_duration_seconds
       - On swipe detection, compute magnitude = multiplier_fingers swipe_fingers
       - Cap at max_product (25)
  4. Handle repeatable vs one-shot action emission.
  5. Emit ActionEvents with all metadata (gesture_id, action_id, magnitude, hand, timestamp).

ActionEvent is a simple dataclass that the WebSocketServer serialises to JSON.
"""

import logging
import time
from dataclasses import dataclass, asdict, field
from typing import Optional

from pipeline.config_manager import ConfigManager
from pipeline.gesture_detector_fixed import FrameResult, HandResult
from pipeline.dtw_matcher import DTWMatcher

logger = logging.getLogger(__name__)


# â”€â”€ ActionEvent â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class ActionEvent:
    """
    A fully resolved action ready to send over WebSocket.
    The extension receives this as JSON.
    """
    action_id:   str                    # e.g. "tab_switch_left", "scroll_down"
    gesture_id:  str                    # e.g. "SWIPE_LEFT", "custom_wave"
    hand:        str                    # "Left", "Right", "Both"
    magnitude:   int         = 1        # for tab switching: N tabs to jump
    repeatable:  bool        = False    # extension uses this to decide fire-once vs loop
    timestamp:   float       = field(default_factory=time.time)
    meta:        dict        = field(default_factory=dict)  # extra data (pinch coords, etc.)

    def to_dict(self) -> dict:
        return asdict(self)


# â”€â”€ Multiplier State â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class MultiplierTracker:
    """
    Tracks the two-hand multiplier mechanic.

    Logic:
      - When a hand is detected as stationary, start a timer.
      - After hold_duration_seconds of continuous stationarity, lock the
        multiplier (finger count at that moment).
      - Clear multiplier when that hand moves again or disappears.
    """

    def __init__(self, hold_duration: float = 0.5, max_fingers: int = 5):
        self.hold_duration  = hold_duration
        self.max_fingers    = max_fingers
        self._hold_start:   dict[str, Optional[float]] = {"Left": None, "Right": None}
        self._multiplier:   dict[str, Optional[int]]   = {"Left": None, "Right": None}

    def update(self, label: str, is_stationary: bool, finger_count: int) -> Optional[int]:
        """
        Call every frame for each detected hand.
        Returns the locked multiplier for this hand if active, else None.
        """
        if is_stationary:
            if self._hold_start[label] is None:
                self._hold_start[label] = time.time()

            elapsed = time.time() - self._hold_start[label]
            if elapsed >= self.hold_duration and self._multiplier[label] is None:
                self._multiplier[label] = min(finger_count, self.max_fingers)
                logger.info(
                    f"Multiplier locked: {label} hand â†’ {self._multiplier[label]} fingers"
                )
        else:
            # Hand moved â€” clear multiplier and timer
            if self._multiplier[label] is not None:
                logger.info(f"Multiplier released: {label} hand")
            self._hold_start[label]  = None
            self._multiplier[label]  = None

        return self._multiplier[label]

    def get_multiplier_for_other_hand(self, swiping_hand: str) -> int:
        """Return the locked multiplier from the non-swiping hand, defaulting to 1."""
        other = "Right" if swiping_hand == "Left" else "Left"
        return self._multiplier.get(other) or 1

    def clear(self):
        for side in ("Left", "Right"):
            self._hold_start[side] = None
            self._multiplier[side] = None


# â”€â”€ Gesture Router â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class GestureRouter:
    """
    Converts FrameResult â†’ list[ActionEvent].

    Called once per frame from the main pipeline loop.
    """

    # Swipe gesture IDs that support the finger-count modifier
    TAB_SWIPE_GESTURES = {"SWIPE_LEFT", "SWIPE_RIGHT"}

    # After a gesture fires its primary (one-shot) action, also emit a
    # continuous secondary action every frame while the gesture is held.
    # PEACE activates cursor (one-shot) and then continuously moves it.
    CONTINUOUS_SECONDARY = {
        "PEACE": "cursor_move",
    }

    def __init__(self, config: ConfigManager, dtw: DTWMatcher):
        self.cfg  = config
        self.dtw  = dtw

        mc = config.multiplier_config
        self._multiplier = MultiplierTracker(
            hold_duration=mc.get("hold_duration_seconds", 0.5),
            max_fingers=mc.get("max_fingers", 5),
        )
        self._max_product    = mc.get("max_product", 25)
        self._multiplier_on  = mc.get("enabled", True)

        # Track last-fired gesture per hand to implement one-shot / repeatable
        self._last_gesture:    dict[str, Optional[str]] = {"Left": None, "Right": None, "Both": None}
        self._last_action:     dict[str, Optional[str]] = {"Left": None, "Right": None, "Both": None}

        # Bug 2 Fix: Rolling landmark frame buffer for DTW dynamic gesture matching.
        # Stores recent landmark frames per hand so custom dynamic gestures can be
        # matched against full motion sequences (not just a single frame placeholder).
        from collections import deque as _deque
        self._landmark_buf: dict[str, "_deque"] = {
            "Left":  _deque(maxlen=30),
            "Right": _deque(maxlen=30),
        }

        config.on_reload(lambda _: self._refresh())

    def _refresh(self):
        mc = self.cfg.multiplier_config
        self._multiplier = MultiplierTracker(
            hold_duration=mc.get("hold_duration_seconds", 0.5),
            max_fingers=mc.get("max_fingers", 5),
        )
        self._max_product   = mc.get("max_product", 25)
        self._multiplier_on = mc.get("enabled", True)
        logger.info("GestureRouter refreshed.")

    # â”€â”€ Main Entry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def route(self, frame_result: FrameResult) -> list[ActionEvent]:
        """
        Process one FrameResult and return zero or more ActionEvents.
        """
        events: list[ActionEvent] = []

        # â”€â”€ Update multiplier tracker for all detected hands â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Bug 2 Fix: Push current landmarks into rolling buffer for DTW dynamic matching
        for label, hr in frame_result.hands.items():
            self._landmark_buf[label].append(hr.landmarks)

        for label, hr in frame_result.hands.items():
            if self._multiplier_on:
                self._multiplier.update(label, hr.is_stationary, hr.finger_count)

        # â”€â”€ Two-hand combo takes priority â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if frame_result.combo_gesture:
            event = self._resolve_combo(frame_result)
            if event:
                events.append(event)
            # When a combo fires, skip individual hand processing this frame
            return events

        # â”€â”€ Per-hand gestures â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        for label, hr in frame_result.hands.items():
            event = self._resolve_hand(hr, frame_result)
            if event:
                events.append(event)
                # Bug 1 Fix: Inject continuous secondary action (e.g. cursor_move
                # while PEACE is held).  The primary action (cursor_activate) is
                # one-shot; we always want cursor_move streamed for the index finger.
                secondary_action = self.CONTINUOUS_SECONDARY.get(event.gesture_id)
                if secondary_action and secondary_action != event.action_id:
                    secondary_meta = {
                        "pinch_distance": hr.pinch_distance,
                        "landmarks":      hr.landmarks.tolist(),
                    }
                    events.append(ActionEvent(
                        action_id=secondary_action,
                        gesture_id=event.gesture_id,
                        hand=hr.label,
                        magnitude=1,
                        repeatable=True,   # always fire every frame
                        meta=secondary_meta,
                    ))

        # â”€â”€ No hands â€” clear multiplier â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if not frame_result.hands:
            self._multiplier.clear()
            self._last_gesture = {"Left": None, "Right": None, "Both": None}
            self._last_action  = {"Left": None, "Right": None, "Both": None}

        return events

    # â”€â”€ Combo Resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _resolve_combo(self, frame_result: FrameResult) -> Optional[ActionEvent]:
        gid = frame_result.combo_gesture
        action_id = self.cfg.get_binding(gid)
        if not action_id:
            return None

        # One-shot: only fire on gesture onset
        if self._last_gesture["Both"] == gid:
            repeatable = self.cfg.is_repeatable(action_id)
            if not repeatable:
                return None

        self._last_gesture["Both"] = gid
        self._last_action["Both"]  = action_id

        return ActionEvent(
            action_id=action_id,
            gesture_id=gid,
            hand="Both",
            magnitude=1,
            repeatable=self.cfg.is_repeatable(action_id),
        )

    # â”€â”€ Single-Hand Resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _resolve_hand(self, hr: HandResult, frame: FrameResult) -> Optional[ActionEvent]:
        # Determine the active gesture for this hand (dynamic > static priority)
        gesture_id = hr.dynamic_gesture or hr.static_gesture
        if not gesture_id:
            self._last_gesture[hr.label] = None
            self._last_action[hr.label]  = None
            return None

        # Try built-in binding first
        action_id = self.cfg.get_binding(gesture_id)

        # Bug 2 Fix: ALWAYS run DTW custom gesture matching every frame.
        # Custom gestures may look identical to built-in gestures from the
        # detector's perspective, so we check if the live landmarks/sequence
        # better match a custom gesture and give custom gestures priority when
        # they match within their threshold.
        if hr.dynamic_gesture:
            custom_match = self.dtw.match_dynamic(self._get_dynamic_sequence(hr))
        else:
            custom_match = self.dtw.match_static(hr.landmarks)

        if custom_match:
            # Custom gesture takes priority over built-in binding
            gesture_id = custom_match
            action_id  = self.cfg.get_binding(custom_match)

        if not action_id:
            return None

        repeatable = self.cfg.is_repeatable(action_id)

        # One-shot guard: skip if gesture hasn't changed and action isn't repeatable
        if self._last_gesture[hr.label] == gesture_id and not repeatable:
            return None

        self._last_gesture[hr.label] = gesture_id
        self._last_action[hr.label]  = action_id

        # â”€â”€ Compute magnitude for tab-switching gestures â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        magnitude = 1
        if gesture_id in self.TAB_SWIPE_GESTURES and self.cfg.action_has_modifier(action_id):
            swipe_fingers      = max(1, hr.finger_count)
            multiplier_fingers = self._multiplier.get_multiplier_for_other_hand(hr.label)
            magnitude = min(swipe_fingers * multiplier_fingers, self._max_product)
            logger.info(
                f"Tab swipe: {hr.label} hand, {swipe_fingers}f Ã— {multiplier_fingers}x = {magnitude} tabs"
            )

        # â”€â”€ Extra metadata for cursor layer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        meta = {}
        # Always include landmark data for cursor gestures and gestures that
        # drive continuous secondary actions (e.g. PEACE drives cursor_move)
        if action_id.startswith("cursor") or gesture_id in self.CONTINUOUS_SECONDARY:
            meta["pinch_distance"] = hr.pinch_distance
            meta["landmarks"]      = hr.landmarks.tolist()

        return ActionEvent(
            action_id=action_id,
            gesture_id=gesture_id,
            hand=hr.label,
            magnitude=magnitude,
            repeatable=repeatable,
            meta=meta,
        )

    # â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _get_dynamic_sequence(self, hr: HandResult) -> list:
        """
        Return the recent landmark sequence for dynamic custom gesture DTW matching.
        Uses the router's rolling landmark buffer (populated every frame in route()).
        Falls back to a single frame if the buffer is nearly empty.
        """
        buf = self._landmark_buf.get(hr.label, [])
        if len(buf) >= 3:
            return list(buf)
        return [hr.landmarks]
