"""
dtw_matcher.py
──────────────
Dynamic Time Warping matcher for user-recorded custom gestures.

How it works:
  - Each custom gesture stores 5–7 recorded samples.
  - At inference time, the live landmark sequence (or single frame for static)
    is compared against every sample of every enabled custom gesture using DTW.
  - The custom gesture with the lowest mean DTW distance across its samples
    wins, provided it is below the gesture's configured dtw_threshold.
  - For static gestures: compare single 21×3 landmark frames (flattened to 63-d vectors).
  - For dynamic gestures: compare sequences of frames, each frame flattened.

Dependencies:
  - numpy only (no external DTW library required; we implement a standard
    O(n×m) DTW with Euclidean distance on landmark vectors)

Usage:
    matcher = DTWMatcher(config)
    gesture_id = matcher.match_static(live_landmarks)   # np.ndarray (21,3)
    gesture_id = matcher.match_dynamic(live_sequence)   # list of np.ndarray (21,3)
"""

import logging
import os
from pathlib import Path
import sys
from pathlib import Path
from typing import Optional

import numpy as np

from pipeline.config_manager import ConfigManager
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

class DTWMatcher:
    """
    Matches live landmark data against stored custom gesture samples using DTW.
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
            if gesture.get("type") != gesture_type:
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
                    if gesture_type == "static":
                        stored_vec = self._flatten(np.array(stored_lm))
                        score = self._euclidean(live_data, stored_vec)
                    else:
                        stored_seq = [self._flatten(np.array(f)) for f in stored_lm]
                        score = self._dtw(live_data, stored_seq)
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
