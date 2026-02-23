"""
gesture_detector_fixed.py
"""

import math
import time
import logging
from collections import deque, Counter
from dataclasses import dataclass, field
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np

from pipeline.config_manager import ConfigManager

logger = logging.getLogger(__name__)


# Data Classes 

@dataclass
class HandResult:
    """Processed result for a single hand in one frame."""
    label: str                          # "Left" or "Right"
    landmarks: np.ndarray               # shape (21, 3) normalised 0–1
    static_gesture: Optional[str]       # e.g. "FIST", "PALM", "PEACE" or None
    dynamic_gesture: Optional[str]      # e.g. "SWIPE_LEFT", "WAVE" or None
    palm_facing: bool                   # True = palm faces camera
    confidence: float                   # MediaPipe handedness score
    finger_count: int                   # 0–5 extended fingers (thumb included)
    pinch_distance: float               # normalised dist between thumb tip & index tip
    velocity: float                     # normalised wrist speed (px/frame, smoothed)
    is_stationary: bool                 # True when velocity < STATIONARY_THRESHOLD


@dataclass
class FrameResult:
    """Complete output for one processed frame."""
    hands: dict[str, HandResult] = field(default_factory=dict)  # keyed by "Left"/"Right"
    combo_gesture: Optional[str] = None   # two-hand combo name or None
    timestamp: float = field(default_factory=time.time)


# ── Constants ─────────────────────────────────────────────────────────────

STATIONARY_VELOCITY_THRESHOLD = 0.008   # normalised units/frame
PINCH_THRESHOLD_DEFAULT = 0.05          # normalised distance


# ── Gesture Detector ──────────────────────────────────────────────────────

class GestureDetector:
    """
    Wraps MediaPipe Hands and produces FrameResult objects.

    Preserves all detection logic from the original mediapipe_detection.py
    (angle-based finger extension, palm-facing cross product, dynamic swipe
    straightness, wave oscillation) and adds finger counting, velocity
    tracking, and pinch distance.
    """

    # MediaPipe landmark indices
    WRIST = 0
    THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
    INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
    MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
    RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
    PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

    def __init__(self, config: ConfigManager):
        self.cfg = config
        self._init_mediapipe()

        s = config.settings
        buf  = s.get("gesture_buffer_size", 5)
        dbuf = s.get("dynamic_buffer_size", 5)
        hist = s.get("position_history_size", 25)

        # Per-hand buffers
        self._static_buf:   dict[str, deque] = {
            "Left":  deque(maxlen=buf),
            "Right": deque(maxlen=buf)
        }
        self._dynamic_buf:  dict[str, deque] = {
            "Left":  deque(maxlen=dbuf),
            "Right": deque(maxlen=dbuf)
        }
        self._pos_history:  dict[str, deque] = {
            "Left":  deque(maxlen=hist),
            "Right": deque(maxlen=hist)
        }
        self._wrist_history: dict[str, deque] = {
            "Left":  deque(maxlen=6),
            "Right": deque(maxlen=6)
        }

        # Two-hand combo patterns (from config)
        self._combo_patterns = self._build_combo_patterns()

        # Register reload callback
        config.on_reload(lambda _: self._refresh_on_reload())

    def _init_mediapipe(self):
        s = self.cfg.settings
        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=s.get("max_num_hands", 2),
            min_detection_confidence=s.get("detection_confidence", 0.80),
            min_tracking_confidence=s.get("tracking_confidence", 0.70),
            model_complexity=s.get("model_complexity", 1)
        )
        self._mp_draw = mp.solutions.drawing_utils
        logger.info("MediaPipe Hands initialised.")

    def _refresh_on_reload(self):
        """Called when config file changes while pipeline is running."""
        self._combo_patterns = self._build_combo_patterns()
        logger.info("Detector refreshed from config.")

    def _build_combo_patterns(self):
        """
        FIXED: Properly access gestures as a property, not a method.
        Build dictionary of combo patterns from config.
        """
        combo_patterns = {}
        
        # Access gestures property correctly
        gestures = self.cfg.gestures
        
        if not isinstance(gestures, dict):
            logger.warning("cfg.gestures is not a dict, skipping combo patterns")
            return combo_patterns
        
        for gesture_id, g in gestures.items():
            # Ensure g is a dictionary before accessing
            if not isinstance(g, dict):
                continue
            
            if g.get("type") == "combo" and "combo_rule" in g:
                combo_rule = g.get("combo_rule")
                if isinstance(combo_rule, list) and len(combo_rule) == 2:
                    combo_patterns[gesture_id] = tuple(combo_rule)
                    logger.debug(f"Loaded combo pattern: {gesture_id} = {combo_rule}")
        
        return combo_patterns

    # ── Public API ────────────────────────────────────────────────────────

    def process_frame(self, frame: np.ndarray) -> tuple[np.ndarray, FrameResult]:
        """
        Main entry point. Takes a raw BGR frame, returns (annotated_frame, FrameResult).
        """
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._hands.process(rgb)

        frame_result = FrameResult()

        if results.multi_hand_landmarks and results.multi_handedness:
            for hand_lms, handedness in zip(
                results.multi_hand_landmarks, results.multi_handedness
            ):
                label      = handedness.classification[0].label   # "Left" / "Right"
                confidence = handedness.classification[0].score

                # Draw skeleton
                color = (0, 255, 0) if label == "Left" else (255, 0, 0)
                self._mp_draw.draw_landmarks(
                    frame, hand_lms, self._mp_hands.HAND_CONNECTIONS,
                    self._mp_draw.DrawingSpec(color=color, thickness=2, circle_radius=2),
                    self._mp_draw.DrawingSpec(color=color, thickness=2)
                )

                landmarks = np.array([[lm.x, lm.y, lm.z] for lm in hand_lms.landmark])
                hand_result = self._process_hand(landmarks, label, confidence)
                frame_result.hands[label] = hand_result

            # Check two-hand combos
            frame_result.combo_gesture = self._detect_combo(frame_result.hands)

        else:
            # No hands – clear all buffers
            for side in ("Left", "Right"):
                self._static_buf[side].clear()
                self._dynamic_buf[side].clear()
                self._pos_history[side].clear()
                self._wrist_history[side].clear()

        self._draw_ui(frame, frame_result)
        return frame, frame_result

    def close(self):
        self._hands.close()

    # ── Per-Hand Processing ───────────────────────────────────────────────

    def _process_hand(
        self,
        landmarks: np.ndarray,
        label: str,
        confidence: float
    ) -> HandResult:

        palm_facing   = self._is_palm_facing(landmarks, label)
        static_raw    = self._detect_static(landmarks, palm_facing, label)
        finger_count  = self._count_extended_fingers(landmarks)
        pinch_dist    = self._pinch_distance(landmarks)
        velocity, is_stationary = self._compute_velocity(landmarks, label)

        # Static smoothing (majority vote from deque)
        static_gesture = self._smooth_gesture(static_raw, self._static_buf[label])

        # Dynamic – always track position history and detect motion.
        # Static gesture does not suppress dynamic detection; swipes happen
        # regardless of hand pose (e.g. swiping with a fist is valid).
        dynamic_gesture = None
        tip = (landmarks[self.MIDDLE_TIP][0], landmarks[self.MIDDLE_TIP][1])
        self._pos_history[label].append(tip)
        raw_dyn = self._detect_dynamic(self._pos_history[label])
        if raw_dyn:
            self._dynamic_buf[label].append(raw_dyn)
            # Require only 2 consistent frames (was 4) to fire dynamic gesture
            if len(self._dynamic_buf[label]) >= 2:
                dynamic_gesture = Counter(self._dynamic_buf[label]).most_common(1)[0][0]
        else:
            # Only clear dynamic buffer if no motion detected
            if not raw_dyn and len(self._pos_history[label]) >= 20:
                self._dynamic_buf[label].clear()

        return HandResult(
            label=label,
            landmarks=landmarks,
            static_gesture=static_gesture if static_gesture not in ("UNKNOWN", None) else None,
            dynamic_gesture=dynamic_gesture,
            palm_facing=palm_facing,
            confidence=confidence,
            finger_count=finger_count,
            pinch_distance=pinch_dist,
            velocity=velocity,
            is_stationary=is_stationary,
        )

    # ── Finger Extension (angle-based) ────────────────────────────────────

    def _is_finger_extended(self, landmarks: np.ndarray, finger: str) -> bool:
        if finger == "thumb":
            angle = self._angle(landmarks[self.THUMB_MCP], landmarks[self.THUMB_IP], landmarks[self.THUMB_TIP])
            return angle > 160
        mapping = {
            "index":  (self.INDEX_TIP,  self.INDEX_DIP,  self.INDEX_PIP,  self.INDEX_MCP),
            "middle": (self.MIDDLE_TIP, self.MIDDLE_DIP, self.MIDDLE_PIP, self.MIDDLE_MCP),
            "ring":   (self.RING_TIP,   self.RING_DIP,   self.RING_PIP,   self.RING_MCP),
            "pinky":  (self.PINKY_TIP,  self.PINKY_DIP,  self.PINKY_PIP,  self.PINKY_MCP),
        }
        tip, dip, pip, mcp = mapping[finger]
        return (
            self._angle(landmarks[mcp], landmarks[pip], landmarks[dip]) > 140 and
            self._angle(landmarks[pip], landmarks[dip], landmarks[tip]) > 140
        )

    def _count_extended_fingers(self, landmarks: np.ndarray) -> int:
        """Return 0–5 count of extended fingers, thumb included."""
        fingers = ["thumb", "index", "middle", "ring", "pinky"]
        return sum(self._is_finger_extended(landmarks, f) for f in fingers)

    # ── Palm Facing ───────────────────────────────────────────────────────

    def _is_palm_facing(self, landmarks: np.ndarray, handedness: str) -> bool:
        wrist     = np.array(landmarks[self.WRIST])
        index_mcp = np.array(landmarks[self.INDEX_MCP])
        pinky_mcp = np.array(landmarks[self.PINKY_MCP])
        normal    = np.cross(index_mcp - wrist, pinky_mcp - wrist)
        facing    = normal[2] > 0
        if handedness == "Left":
            facing = not facing
        return facing

    # ── Static Gesture Detection ──────────────────────────────────────────

    def _detect_static(self, lm: np.ndarray, palm_facing: bool, handedness: str) -> str:
        t = self._is_finger_extended(lm, "thumb")
        i = self._is_finger_extended(lm, "index")
        m = self._is_finger_extended(lm, "middle")
        r = self._is_finger_extended(lm, "ring")
        p = self._is_finger_extended(lm, "pinky")
        n = sum([t, i, m, r, p])

        if n == 0:
            return "FIST"
        if t and n == 1:
            return "THUMBS_UP"
        
        # INDEX_ONLY: Only index finger extended (no middle finger)
        if i and not m and not r and not p and not t:
            return "INDEX_ONLY"
        
        # PEACE: Both index and middle fingers extended
        if i and m and not r and not p:
            sep = self._dist(lm[self.INDEX_TIP], lm[self.MIDDLE_TIP])
            if 0.05 < sep < 0.15:
                return "PEACE"
        
        if self._dist(lm[self.THUMB_TIP], lm[self.INDEX_TIP]) < 0.04:
            if m and r and p:
                return "OK"
        if n == 5:
            return "PALM"
        if i:
            direction = np.array(lm[self.INDEX_TIP]) - np.array(lm[self.WRIST])
            dx, dy = direction[0], direction[1]
            angle  = math.degrees(math.atan2(-dy, dx)) % 360
            if not palm_facing:
                angle = (angle + 180) % 360
            half = 22.5
            if angle >= 360 - half or angle < half:
                return "RIGHT"
            elif half <= angle < 90 + half:
                return "UP"
            elif 90 + half <= angle < 180 + half:
                return "LEFT"
            elif 180 + half <= angle < 270 + half:
                return "DOWN"
        
        # Finally, try matching against custom recorded gestures
        return self._detect_custom(lm)

    def _detect_custom(self, landmarks: np.ndarray) -> str:
        """Match landmarks against custom recorded samples."""
        custom_gestures = self._cfg.get("custom_gestures", default={})
        if not custom_gestures:
            return "UNKNOWN"
            
        best_match = "UNKNOWN"
        min_dist = float('inf')
        threshold = 0.5 # Normalized distance threshold
        
        # Normalize current landmarks (translate wrist to origin)
        wrist = landmarks[0]
        norm_lm = landmarks - wrist
        
        for gid, data in custom_gestures.items():
            if not data.get("enabled", True):
                continue
            samples = data.get("samples", [])
            for sample in samples:
                s_lms = np.array(sample.get("landmarks", []))
                if s_lms.shape != norm_lm.shape:
                    continue
                # Normalize sample
                s_wrist = s_lms[0]
                s_norm = s_lms - s_wrist
                
                # Compute total Euclidean distance across all landmarks
                dist = np.linalg.norm(norm_lm - s_norm)
                if dist < min_dist:
                    min_dist = dist
                    best_match = gid
                    
        if min_dist < threshold:
            return best_match
        return "UNKNOWN"

    # ── Dynamic Gesture Detection ─────────────────────────────────────────

    def _detect_dynamic(self, pos_history: deque) -> Optional[str]:
        if len(pos_history) < 15:
            return None
        positions = list(pos_history)
        dx = positions[-1][0] - positions[0][0]
        dy = positions[-1][1] - positions[0][1]
        total = math.sqrt(dx**2 + dy**2)
        path  = sum(
            math.sqrt((positions[i][0]-positions[i-1][0])**2 +
                      (positions[i][1]-positions[i-1][1])**2)
            for i in range(1, len(positions))
        )
        straightness = total / (path + 1e-6)

        if total > 0.12 and straightness > 0.65:
            angle = math.degrees(math.atan2(dy, dx))
            if -45 <= angle < 45:   return "SWIPE_RIGHT"
            if 45 <= angle < 135:   return "SWIPE_DOWN"
            if abs(angle) >= 135:   return "SWIPE_LEFT"
            if -135 <= angle < -45: return "SWIPE_UP"

        # Wave detection
        if len(positions) >= 18:
            xs = [p[0] for p in positions]
            changes = sum(
                1 for i in range(1, len(xs) - 1)
                if (xs[i] > xs[i-1] and xs[i] > xs[i+1]) or
                   (xs[i] < xs[i-1] and xs[i] < xs[i+1])
            )
            if changes >= 4 and np.var(xs) > 0.004:
                return "WAVE"
        return None

    # ── Two-Hand Combo Detection ──────────────────────────────────────────

    def _detect_combo(self, hands: dict[str, HandResult]) -> Optional[str]:
        if "Left" not in hands or "Right" not in hands:
            return None
        lg = hands["Left"].static_gesture
        rg = hands["Right"].static_gesture
        if not lg or not rg:
            return None
        for combo_id, (l_pat, r_pat) in self._combo_patterns.items():
            if lg == l_pat and rg == r_pat:
                return combo_id
        return None

    # ── Velocity / Stationarity ───────────────────────────────────────────

    def _compute_velocity(
        self, landmarks: np.ndarray, label: str
    ) -> tuple[float, bool]:
        wrist_pos = (landmarks[self.WRIST][0], landmarks[self.WRIST][1])
        hist = self._wrist_history[label]
        hist.append(wrist_pos)
        if len(hist) < 2:
            return 0.0, True
        velocity = math.sqrt(
            (hist[-1][0] - hist[-2][0])**2 +
            (hist[-1][1] - hist[-2][1])**2
        )
        is_stationary = velocity < STATIONARY_VELOCITY_THRESHOLD
        return velocity, is_stationary

    # ── Pinch Distance ────────────────────────────────────────────────────

    def _pinch_distance(self, landmarks: np.ndarray) -> float:
        return self._dist(landmarks[self.THUMB_TIP], landmarks[self.INDEX_TIP])

    # ── Smoothing ─────────────────────────────────────────────────────────

    @staticmethod
    def _smooth_gesture(gesture: Optional[str], buf: deque) -> Optional[str]:
        if gesture is None or gesture == "UNKNOWN":
            return None
        buf.append(gesture)
        if len(buf) >= 3:
            return Counter(buf).most_common(1)[0][0]
        return gesture

    # ── Math Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _dist(a, b) -> float:
        return math.sqrt(sum((x - y)**2 for x, y in zip(a, b)))

    @staticmethod
    def _angle(p1, p2, p3) -> float:
        v1 = np.array(p1) - np.array(p2)
        v2 = np.array(p3) - np.array(p2)
        cos_a = np.clip(
            np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6),
            -1.0, 1.0
        )
        return math.degrees(math.acos(cos_a))

    # ── Debug UI ──────────────────────────────────────────────────────────

    def _draw_ui(self, frame: np.ndarray, result: FrameResult):
        h, w, _ = frame.shape

        for side, x_start, color in [("Left", 5, (0, 255, 0)), ("Right", w - 355, (255, 0, 0))]:
            cv2.rectangle(frame, (x_start, 5), (x_start + 345, 175), (0, 0, 0), -1)
            cv2.rectangle(frame, (x_start, 5), (x_start + 345, 175), color, 2)
            cv2.putText(frame, f"{side.upper()} HAND", (x_start + 10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            if side in result.hands:
                hr = result.hands[side]
                lines = [
                    f"Static:  {hr.static_gesture or 'None'}",
                    f"Dynamic: {hr.dynamic_gesture or 'None'}",
                    f"Fingers: {hr.finger_count}",
                    f"Pinch:   {hr.pinch_distance:.3f}",
                    f"Vel:     {hr.velocity:.4f} {'[STILL]' if hr.is_stationary else ''}",
                    f"Conf:    {hr.confidence:.2f}",
                ]
                for j, line in enumerate(lines):
                    cv2.putText(frame, line, (x_start + 10, 50 + j * 22),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            else:
                cv2.putText(frame, "No detection", (x_start + 10, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)

        if result.combo_gesture:
            text = f"COMBO: {result.combo_gesture}"
            tw = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0][0]
            cv2.rectangle(frame, (w//2 - tw//2 - 10, h - 50), (w//2 + tw//2 + 10, h - 10), (0,0,0), -1)
            cv2.putText(frame, text, (w//2 - tw//2, h - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)