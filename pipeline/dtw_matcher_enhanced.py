"""
dtw_matcher_enhanced.py
───────────────────────
Enhanced DTW matcher that works with both:
1. Manually recorded gestures (from capture_user_gestures.py)
2. Landmark-based gestures (from gesture_landmark_recorder.py)

Replaces the original dtw_matcher.py with support for recorded gestures.
"""

import logging
from typing import Optional

import numpy as np

from pipeline.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class DTWMatcher:
    """
    Matches live landmark data against stored custom gesture samples using DTW.
    Now supports both formats:
    - Original format (from recorder.py in pipeline)
    - Recorded format (from gesture_landmark_recorder.py)
    """

    def __init__(self, config: ConfigManager):
        self.cfg = config
        config.on_reload(lambda _: logger.info("DTWMatcher: config reloaded."))

    # ── Public API ─────────────────────────────────────────────────────────────

    def match_static(self, live_landmarks: np.ndarray) -> Optional[str]:
        """
        Compare a single live frame (21×3) against all static custom gestures.
        Returns the gesture_id of the best match, or None.
        """
        live_vec = self._flatten(live_landmarks)
        return self._match_against_customs(live_vec, gesture_type="static")

    def match_dynamic(self, live_sequence: list[np.ndarray]) -> Optional[str]:
        """
        Compare a live motion sequence (list of 21×3 frames) against all
        dynamic custom gestures.
        Returns the gesture_id of the best match, or None.
        """
        if len(live_sequence) < 3:
            return None
        live_seq = [self._flatten(f) for f in live_sequence]
        return self._match_against_customs(live_seq, gesture_type="dynamic")

    # ── Core Matching ──────────────────────────────────────────────────────────

    def _match_against_customs(
        self,
        live_data,               # np.ndarray (static) or list[np.ndarray] (dynamic)
        gesture_type: str        # "static" or "dynamic"
    ) -> Optional[str]:

        best_id    = None
        best_score = float("inf")

        for gid, gesture in self.cfg.custom_gestures.items():
            if not gesture.get("enabled", True):
                continue
            
            # Check type - handle both "static"/"dynamic" and "custom_static"/"custom_dynamic"
            gtype = gesture.get("type", "")
            if not self._type_matches(gtype, gesture_type):
                continue

            samples = gesture.get("samples", [])
            if not samples:
                continue

            threshold = gesture.get("dtw_threshold", 0.15)
            scores = []

            for sample in samples:
                stored_lm = sample.get("landmarks")
                if stored_lm is None:
                    continue
                
                try:
                    score = self._compute_score(live_data, stored_lm, gesture_type)
                    if score is not None:
                        scores.append(score)
                except Exception as e:
                    logger.warning(f"DTW error for {gid}: {e}")
                    continue

            if not scores:
                continue

            mean_score = np.mean(scores)
            logger.debug(f"DTW {gid}: mean={mean_score:.4f} threshold={threshold}")

            if mean_score < threshold and mean_score < best_score:
                best_score = mean_score
                best_id    = gid

        return best_id
    
    def _type_matches(self, gesture_type: str, target_type: str) -> bool:
        """Check if gesture type matches target (handles custom_ prefix)."""
        if gesture_type == target_type:
            return True
        if gesture_type == f"custom_{target_type}":
            return True
        return False
    
    def _compute_score(self, live_data, stored_lm, gesture_type: str) -> Optional[float]:
        """Compute matching score between live and stored landmarks."""
        
        if gesture_type == "static":
            # Handle both formats
            if isinstance(stored_lm, list) and len(stored_lm) > 0:
                # Check if it's a single hand or frame data structure
                if isinstance(stored_lm[0], dict):
                    # Format: {"hands": [{"landmarks": [...]}]}
                    if "hands" in stored_lm[0] and len(stored_lm[0]["hands"]) > 0:
                        stored_vec = self._flatten(np.array(stored_lm[0]["hands"][0]["landmarks"]))
                    else:
                        return None
                else:
                    # Format: [[x,y,z], [x,y,z], ...] (21 landmarks)
                    stored_vec = self._flatten(np.array(stored_lm))
                
                return self._euclidean(live_data, stored_vec)
        
        else:  # dynamic
            # Handle sequence format
            if isinstance(stored_lm, list) and len(stored_lm) > 0:
                stored_seq = []
                
                for frame in stored_lm:
                    if isinstance(frame, dict):
                        # Format: {"hands": [{"landmarks": [...]}]}
                        if "hands" in frame and len(frame["hands"]) > 0:
                            frame_lm = frame["hands"][0]["landmarks"]
                            stored_seq.append(self._flatten(np.array(frame_lm)))
                    elif isinstance(frame, list):
                        # Format: [[x,y,z], ...] (21 landmarks)
                        stored_seq.append(self._flatten(np.array(frame)))
                
                if stored_seq:
                    return self._dtw(live_data, stored_seq)
        
        return None

    # ── DTW Implementation ─────────────────────────────────────────────────────

    @staticmethod
    def _dtw(seq_a: list[np.ndarray], seq_b: list[np.ndarray]) -> float:
        """
        Standard O(n×m) DTW between two sequences of equal-dimension vectors.
        Returns the normalised DTW distance (divided by n+m to be scale-invariant).
        """
        n, m = len(seq_a), len(seq_b)
        # Cost matrix
        cost = np.full((n, m), float("inf"))
        cost[0, 0] = np.linalg.norm(seq_a[0] - seq_b[0])

        for i in range(1, n):
            cost[i, 0] = cost[i-1, 0] + np.linalg.norm(seq_a[i] - seq_b[0])
        for j in range(1, m):
            cost[0, j] = cost[0, j-1] + np.linalg.norm(seq_a[0] - seq_b[j])

        for i in range(1, n):
            for j in range(1, m):
                local = np.linalg.norm(seq_a[i] - seq_b[j])
                cost[i, j] = local + min(cost[i-1, j], cost[i, j-1], cost[i-1, j-1])

        return float(cost[n-1, m-1]) / (n + m)

    @staticmethod
    def _euclidean(a: np.ndarray, b: np.ndarray) -> float:
        """Simple Euclidean distance for static single-frame comparison."""
        return float(np.linalg.norm(a - b))

    @staticmethod
    def _flatten(landmarks) -> np.ndarray:
        """Flatten (21, 3) → (63,) and L2-normalise for scale invariance."""
        vec = np.array(landmarks).flatten().astype(np.float32)
        norm = np.linalg.norm(vec)
        return vec / (norm + 1e-6)

    # ── Sample Recording Helpers ───────────────────────────────────────────────

    @staticmethod
    def prepare_static_sample(landmarks: np.ndarray) -> list:
        """
        Convert a single (21, 3) landmark frame into the JSON-serialisable
        format stored in custom_gestures[id].samples[n].landmarks.
        """
        return landmarks.tolist()

    @staticmethod
    def prepare_dynamic_sample(frame_sequence: list[np.ndarray]) -> list:
        """
        Convert a list of (21, 3) frames into the JSON-serialisable
        format stored in custom_gestures[id].samples[n].landmarks.
        """
        return [frame.tolist() for frame in frame_sequence]
