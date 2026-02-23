#!/usr/bin/env python3
"""
use_recorded_gestures.py
────────────────────────
Loads recorded gestures and integrates them with mediapipe_detection.py

Usage:
    python use_recorded_gestures.py gesture_dataset.json
"""

import json
import numpy as np
from pathlib import Path

class RecordedGestureLibrary:
    """Loads and provides access to recorded gesture landmarks."""
    
    def __init__(self, dataset_path="gesture_dataset.json"):
        self.dataset_path = Path(dataset_path)
        self.gestures = []
        self.static_gestures = {}
        self.dynamic_gestures = {}
        self.combo_gestures = {}
        
        if self.dataset_path.exists():
            self._load_dataset()
        else:
            print(f"⚠ Dataset not found: {dataset_path}")
    
    def _load_dataset(self):
        """Load gesture dataset from JSON."""
        with open(self.dataset_path, 'r') as f:
            data = json.load(f)
        
        self.gestures = data.get("gestures", [])
        
        # Organize by type
        for gesture in self.gestures:
            name = gesture["name"]
            gtype = gesture["type"]
            
            if gtype == "static":
                self.static_gestures[name] = gesture
            elif gtype == "dynamic":
                self.dynamic_gestures[name] = gesture
            elif gtype == "combo":
                self.combo_gestures[name] = gesture
        
        print(f"✓ Loaded {len(self.gestures)} gestures:")
        print(f"   Static: {len(self.static_gestures)}")
        print(f"   Dynamic: {len(self.dynamic_gestures)}")
        print(f"   Combo: {len(self.combo_gestures)}")
    
    def get_static_template(self, gesture_name):
        """Get landmark template for a static gesture."""
        return self.static_gestures.get(gesture_name)
    
    def get_dynamic_template(self, gesture_name):
        """Get landmark sequence for a dynamic gesture."""
        return self.dynamic_gestures.get(gesture_name)
    
    def get_combo_template(self, gesture_name):
        """Get two-hand landmark template."""
        return self.combo_gestures.get(gesture_name)
    
    def match_static_gesture(self, live_landmarks, threshold=0.1):
        """
        Match live landmarks against recorded static gestures.
        
        Args:
            live_landmarks: List of 21 [x,y,z] landmark positions
            threshold: Maximum distance for a match
        
        Returns:
            (gesture_name, confidence) or (None, 0.0)
        """
        best_match = None
        best_distance = float('inf')
        
        for name, gesture in self.static_gestures.items():
            template = np.array(gesture["landmarks"])
            live = np.array(live_landmarks)
            
            # Normalize both to handle scale differences
            template_norm = self._normalize_landmarks(template)
            live_norm = self._normalize_landmarks(live)
            
            # Calculate Euclidean distance
            distance = np.linalg.norm(template_norm - live_norm)
            
            if distance < best_distance:
                best_distance = distance
                best_match = name
        
        if best_distance < threshold:
            confidence = max(0.0, 1.0 - (best_distance / threshold))
            return best_match, confidence
        
        return None, 0.0
    
    def match_dynamic_gesture(self, live_sequence, threshold=0.15):
        """
        Match live motion sequence against recorded dynamic gestures.
        
        Args:
            live_sequence: List of landmark frames (each frame has 21 [x,y,z] points)
            threshold: Maximum DTW distance for a match
        
        Returns:
            (gesture_name, confidence) or (None, 0.0)
        """
        if len(live_sequence) < 5:
            return None, 0.0
        
        best_match = None
        best_distance = float('inf')
        
        for name, gesture in self.dynamic_gestures.items():
            template_seq = gesture["landmarks_sequence"]
            
            # Use Dynamic Time Warping to compare sequences
            distance = self._dtw_distance(live_sequence, template_seq)
            
            if distance < best_distance:
                best_distance = distance
                best_match = name
        
        if best_distance < threshold:
            confidence = max(0.0, 1.0 - (best_distance / threshold))
            return best_match, confidence
        
        return None, 0.0
    
    def _normalize_landmarks(self, landmarks):
        """Normalize landmarks to be scale and translation invariant."""
        landmarks = np.array(landmarks)
        
        # Center around wrist (landmark 0)
        centered = landmarks - landmarks[0]
        
        # Scale by maximum distance from wrist
        max_dist = np.max(np.linalg.norm(centered, axis=1))
        if max_dist > 0:
            normalized = centered / max_dist
        else:
            normalized = centered
        
        return normalized.flatten()
    
    def _dtw_distance(self, seq1, seq2):
        """
        Calculate Dynamic Time Warping distance between two sequences.
        Simplified version using Euclidean distance between frames.
        """
        n, m = len(seq1), len(seq2)
        dtw_matrix = np.full((n + 1, m + 1), float('inf'))
        dtw_matrix[0, 0] = 0
        
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                # Extract landmarks from each frame
                frame1 = self._extract_frame_landmarks(seq1[i-1])
                frame2 = self._extract_frame_landmarks(seq2[j-1])
                
                if frame1 is None or frame2 is None:
                    continue
                
                # Normalize and compare
                norm1 = self._normalize_landmarks(frame1)
                norm2 = self._normalize_landmarks(frame2)
                
                cost = np.linalg.norm(norm1 - norm2)
                dtw_matrix[i, j] = cost + min(
                    dtw_matrix[i-1, j],    # insertion
                    dtw_matrix[i, j-1],    # deletion
                    dtw_matrix[i-1, j-1]   # match
                )
        
        return dtw_matrix[n, m] / (n + m)  # Normalize by path length
    
    def _extract_frame_landmarks(self, frame_data):
        """Extract landmarks array from frame data structure."""
        if isinstance(frame_data, dict):
            if "hands" in frame_data and len(frame_data["hands"]) > 0:
                return frame_data["hands"][0]["landmarks"]
        elif isinstance(frame_data, list):
            return frame_data
        return None
    
    def list_gestures(self):
        """Print all available gestures."""
        print("\n" + "="*70)
        print("RECORDED GESTURES")
        print("="*70)
        
        if self.static_gestures:
            print("\n📌 STATIC GESTURES:")
            for name, gesture in self.static_gestures.items():
                print(f"   • {name}")
                print(f"     Recorded: {gesture.get('recorded_at', 'unknown')}")
                print(f"     Frames: {gesture.get('num_frames', 0)}")
        
        if self.dynamic_gestures:
            print("\n🔄 DYNAMIC GESTURES:")
            for name, gesture in self.dynamic_gestures.items():
                stats = gesture.get('motion_stats', {})
                direction = stats.get('direction', 'unknown')
                displacement = stats.get('displacement', 0)
                print(f"   • {name}")
                print(f"     Direction: {direction}")
                print(f"     Displacement: {displacement:.3f}")
                print(f"     Duration: {gesture.get('duration_seconds', 0)}s")
        
        if self.combo_gestures:
            print("\n🤝 COMBO GESTURES (Two Hands):")
            for name, gesture in self.combo_gestures.items():
                print(f"   • {name}")
                print(f"     Recorded: {gesture.get('recorded_at', 'unknown')}")
        
        print("="*70 + "\n")
    
    def export_for_detector(self, output_path="custom_gestures.py"):
        """
        Export gestures in a format that can be imported by mediapipe_detection.py
        """
        with open(output_path, 'w') as f:
            f.write('"""Auto-generated custom gesture definitions"""\n\n')
            f.write('CUSTOM_GESTURES = {\n')
            
            # Export static gestures
            for name, gesture in self.static_gestures.items():
                f.write(f'    "{name}": {{\n')
                f.write(f'        "type": "static",\n')
                f.write(f'        "landmarks": {gesture["landmarks"]},\n')
                f.write(f'    }},\n')
            
            # Export dynamic gestures
            for name, gesture in self.dynamic_gestures.items():
                f.write(f'    "{name}": {{\n')
                f.write(f'        "type": "dynamic",\n')
                f.write(f'        "landmarks_sequence": {gesture["landmarks_sequence"]},\n')
                f.write(f'        "motion_stats": {gesture.get("motion_stats", {{}})},\n')
                f.write(f'    }},\n')
            
            f.write('}\n')
        
        print(f"✓ Exported to {output_path}")


# Example usage
if __name__ == "__main__":
    import sys
    
    dataset_file = sys.argv[1] if len(sys.argv) > 1 else "gesture_dataset.json"
    
    library = RecordedGestureLibrary(dataset_file)
    library.list_gestures()
    
    # Export for use with detector
    if library.gestures:
        library.export_for_detector()
        print("\n💡 To use these gestures in mediapipe_detection.py:")
        print("   1. Import: from custom_gestures import CUSTOM_GESTURES")
        print("   2. Add custom matching in detect_static_gesture()")
        print("   3. Add custom matching in detect_dynamic_gesture()")
