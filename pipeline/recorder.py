"""
recorder.py
───────────
Manages custom gesture recording sessions.

Static gesture:
  - Hold pose for 2 seconds, captures a landmark snapshot every 400ms → 5 samples.

Dynamic gesture:
  - Record motion within 1 second, captures a sequence of frames → stores as one sample.
  - User repeats 5–7 times; each run is one sample entry.

The Recorder is driven by the main pipeline loop — call update() every frame.
It emits RecordingEvents that the WebSocket server can forward to the UI.

Usage:
    recorder = Recorder(config, dtw_matcher)
    recorder.start_session("custom_peace_down", label="Peace Down", gesture_type="static")

    # in main loop:
    event = recorder.update(frame_result)
    if event:
        ws_server.broadcast_raw(event.to_dict())
"""

import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Optional

import numpy as np

from pipeline.config_manager import ConfigManager
from pipeline.mediapipe_detection import FrameResult
from pipeline.dtw_matcher import DTWMatcher

logger = logging.getLogger(__name__)


#Rcording Session State Machine 

class RecordingState(Enum):
    IDLE        = auto()
    COUNTDOWN   = auto()   # 3-2-1 before capture starts
    CAPTURING   = auto()   # actively collecting frames
    BETWEEN     = auto()   # rest period between samples (show "Ready? Again...")
    COMPLETE    = auto()   # all samples collected, saving


@dataclass
class RecordingEvent:
    """Sent over WebSocket to update the UI during a recording session."""
    event:          str           # "state_change" | "sample_saved" | "complete" | "cancelled"
    state:          str           # RecordingState name
    gesture_id:     str
    samples_done:   int
    samples_total:  int
    countdown:      Optional[int] = None    # 3, 2, 1 or None
    message:        str = ""

    def to_dict(self) -> dict:
        return {"type": "RECORDING_EVENT", **asdict(self)}


# Recorder 

class Recorder:
    # Timing constants
    COUNTDOWN_SECONDS       = 3
    STATIC_CAPTURE_SECONDS  = 2.0
    STATIC_SAMPLE_INTERVAL  = 0.4    # capture every 400ms → 5 samples in 2s
    DYNAMIC_CAPTURE_SECONDS = 1.0
    BETWEEN_REST_SECONDS    = 2.0
    TARGET_SAMPLES          = 6      # 5–7; we use 6

    def __init__(self, config: ConfigManager, dtw: DTWMatcher):
        self.cfg = config
        self.dtw = dtw
        self._state         = RecordingState.IDLE
        self._gesture_id    = ""
        self._label         = ""
        self._gesture_type  = "static"  # "static" | "dynamic"
        self._preferred_hand = "Right"
        self._samples:      list[dict] = []
        self._frame_buffer: list[np.ndarray] = []   # for dynamic recording
        self._state_start   = 0.0
        self._last_capture  = 0.0
        self._countdown_val = self.COUNTDOWN_SECONDS

    # Session Control 

    def start_session(
        self,
        gesture_id: str,
        label: str,
        gesture_type: str = "static",
        preferred_hand: str = "Right"
    ):
        """
        Begin a new recording session.
        gesture_type: "static" or "dynamic"
        """
        if self._state != RecordingState.IDLE:
            logger.warning("Recording already in progress — cancelling previous session.")
            self.cancel()

        self._gesture_id     = gesture_id
        self._label          = label
        self._gesture_type   = gesture_type
        self._preferred_hand = preferred_hand
        self._samples        = []
        self._frame_buffer   = []
        self._transition(RecordingState.COUNTDOWN)
        logger.info(f"Recording session started: {gesture_id} ({gesture_type})")

    def cancel(self):
        old_id = self._gesture_id
        self._transition(RecordingState.IDLE)
        logger.info(f"Recording cancelled: {old_id}")
        return RecordingEvent(
            event="cancelled", state="IDLE",
            gesture_id=old_id,
            samples_done=len(self._samples),
            samples_total=self.TARGET_SAMPLES,
            message="Recording cancelled."
        )

    @property
    def is_active(self) -> bool:
        return self._state != RecordingState.IDLE

    #  Frame Update 
    def update(self, frame_result: FrameResult) -> Optional[RecordingEvent]:
        """
        Call every frame. Returns a RecordingEvent if something noteworthy
        happened (state change, sample saved, complete), else None.
        """
        if self._state == RecordingState.IDLE:
            return None

        hand = frame_result.hands.get(self._preferred_hand) or \
               next(iter(frame_result.hands.values()), None)

        now = time.time()

        #  COUNTDOWN
        if self._state == RecordingState.COUNTDOWN:
            elapsed  = now - self._state_start
            remaining = self.COUNTDOWN_SECONDS - int(elapsed)
            if remaining <= 0:
                self._transition(RecordingState.CAPTURING)
                return RecordingEvent(
                    event="state_change", state="CAPTURING",
                    gesture_id=self._gesture_id,
                    samples_done=len(self._samples),
                    samples_total=self.TARGET_SAMPLES,
                    countdown=None,
                    message="Go! Perform the gesture now."
                )
            if remaining != self._countdown_val:
                self._countdown_val = remaining
                return RecordingEvent(
                    event="state_change", state="COUNTDOWN",
                    gesture_id=self._gesture_id,
                    samples_done=len(self._samples),
                    samples_total=self.TARGET_SAMPLES,
                    countdown=remaining,
                    message=f"Get ready… {remaining}"
                )
            return None

        #  CAPTURING 
        if self._state == RecordingState.CAPTURING:
            if hand is None:
                return None   # wait for hand to appear

            elapsed = now - self._state_start

            if self._gesture_type == "static":
                event = self._capture_static(hand.landmarks, elapsed, now)
            else:
                event = self._capture_dynamic(hand.landmarks, elapsed)

            return event

        #  BETWEEN
        if self._state == RecordingState.BETWEEN:
            elapsed = now - self._state_start
            if elapsed >= self.BETWEEN_REST_SECONDS:
                self._countdown_val = self.COUNTDOWN_SECONDS
                self._transition(RecordingState.COUNTDOWN)
                return RecordingEvent(
                    event="state_change", state="COUNTDOWN",
                    gesture_id=self._gesture_id,
                    samples_done=len(self._samples),
                    samples_total=self.TARGET_SAMPLES,
                    countdown=self.COUNTDOWN_SECONDS,
                    message=f"Sample {len(self._samples)}/{self.TARGET_SAMPLES} saved. Get ready again…"
                )
            return None

        return None

    #  Static Capture

    def _capture_static(
        self, landmarks: np.ndarray, elapsed: float, now: float
    ) -> Optional[RecordingEvent]:
        """
        During the 2s capture window, snap a sample every STATIC_SAMPLE_INTERVAL.
        One full run = 1 sample (the median frame of the window, for robustness).
        """
        self._frame_buffer.append(landmarks.copy())

        if elapsed >= self.STATIC_CAPTURE_SECONDS:
            # Take the median frame (most representative)
            stacked = np.stack(self._frame_buffer, axis=0)
            median_frame = np.median(stacked, axis=0)
            sample = {
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "landmarks": self.dtw.prepare_static_sample(median_frame)
            }
            return self._save_sample(sample)

        return None

    #  Dynamic Capture

    def _capture_dynamic(
        self, landmarks: np.ndarray, elapsed: float
    ) -> Optional[RecordingEvent]:
        """
        Record every frame for 1 second, then store the whole sequence as one sample.
        """
        self._frame_buffer.append(landmarks.copy())

        if elapsed >= self.DYNAMIC_CAPTURE_SECONDS:
            sample = {
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "landmarks": self.dtw.prepare_dynamic_sample(self._frame_buffer)
            }
            return self._save_sample(sample)

        return None

    # Sample Saving 

    def _save_sample(self, sample: dict) -> RecordingEvent:
        self._samples.append(sample)
        self._frame_buffer = []
        logger.info(
            f"Sample {len(self._samples)}/{self.TARGET_SAMPLES} saved for {self._gesture_id}"
        )

        if len(self._samples) >= self.TARGET_SAMPLES:
            return self._finalise()

        self._transition(RecordingState.BETWEEN)
        return RecordingEvent(
            event="sample_saved", state="BETWEEN",
            gesture_id=self._gesture_id,
            samples_done=len(self._samples),
            samples_total=self.TARGET_SAMPLES,
            message=f"Sample {len(self._samples)}/{self.TARGET_SAMPLES} saved. Rest briefly…"
        )

    def _finalise(self) -> RecordingEvent:
        """All samples collected — persist the gesture."""
        import datetime
        gesture_data = {
            "label":       self._label,
            "type":        self._gesture_type,
            "hand":        self._preferred_hand.lower(),
            "created_at":  datetime.datetime.utcnow().isoformat() + "Z",
            "deletable":   True,
            "enabled":     True,
            "recording": {
                "duration_seconds": (
                    self.STATIC_CAPTURE_SECONDS
                    if self._gesture_type == "static"
                    else self.DYNAMIC_CAPTURE_SECONDS
                ),
                "num_samples": len(self._samples),
                "capture_fps": 30
            },
            "dtw_threshold": 0.15,
            "samples": self._samples
        }
        self.cfg.save_custom_gesture(self._gesture_id, gesture_data)
        gid = self._gesture_id
        self._transition(RecordingState.COMPLETE)
        self._transition(RecordingState.IDLE)

        logger.info(f"Custom gesture saved: {gid} ({len(self._samples)} samples)")
        return RecordingEvent(
            event="complete", state="COMPLETE",
            gesture_id=gid,
            samples_done=len(self._samples),
            samples_total=self.TARGET_SAMPLES,
            message=f"Gesture '{self._label}' saved successfully!"
        )

    #  State Machine 

    def _transition(self, new_state: RecordingState):
        logger.debug(f"Recording: {self._state.name} → {new_state.name}")
        self._state       = new_state
        self._state_start = time.time()
        self._frame_buffer = []
