#!/usr/bin/env python3
"""
gesture_landmark_recorder.py
────────────────────────────
Records hand landmarks for training custom gestures.

Usage:
    python gesture_landmark_recorder.py

Controls:
    's' - Start/Stop recording STATIC gesture (single frame capture)
    'd' - Start/Stop recording DYNAMIC gesture (motion sequence)
    'c' - Start/Stop recording COMBO gesture (two-hand static)
    'r' - Reset current recording
    'q' - Quit

Output:
    Saves to gesture_dataset.json in format compatible with mediapipe_detection.py
"""

import cv2
import mediapipe as mp
import numpy as np
import json
import time
from pathlib import Path
from collections import deque

class GestureLandmarkRecorder:
    def __init__(self, output_file="gesture_dataset.json"):
        # MediaPipe setup
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.8,
            min_tracking_confidence=0.7,
            model_complexity=1
        )
        self.mp_draw = mp.solutions.drawing_utils
        
        # Recording state
        self.recording_mode = None  # 'static', 'dynamic', or 'combo'
        self.is_recording = False
        self.recorded_frames = []
        self.start_time = 0
        self.gesture_name = ""
        
        # Dynamic gesture tracking
        self.position_history = deque(maxlen=30)
        self.dynamic_duration = 2.0  # seconds to record dynamic gesture
        
        # Output
        self.output_file = Path(output_file)
        self.dataset = self._load_dataset()
        
        print("\n" + "="*70)
        print("GESTURE LANDMARK RECORDER")
        print("="*70)
        print("\nControls:")
        print("  's' - Record STATIC gesture (single pose)")
        print("  'd' - Record DYNAMIC gesture (motion)")
        print("  'c' - Record COMBO gesture (two-hand pose)")
        print("  'r' - Reset current recording")
        print("  'q' - Quit and save")
        print("\nTips:")
        print("  - Ensure good lighting")
        print("  - Position hand clearly in frame")
        print("  - For static: hold pose steady for 1 second")
        print("  - For dynamic: perform smooth motion within 2 seconds")
        print("  - For combo: both hands must be visible")
        print("="*70 + "\n")
    
    def _load_dataset(self):
        """Load existing dataset or create new one."""
        if self.output_file.exists():
            with open(self.output_file, 'r') as f:
                return json.load(f)
        return {"gestures": []}
    
    def _save_dataset(self):
        """Save dataset to JSON file."""
        with open(self.output_file, 'w') as f:
            json.dump(self.dataset, indent=2, fp=f)
        print(f"✓ Dataset saved to {self.output_file}")
    
    def _prompt_gesture_name(self):
        """Prompt user for gesture class name."""
        print("\n" + "─"*70)
        print("Enter gesture name (e.g., 'thumbs_up', 'wave', 'peace_sign'):")
        name = input("> ").strip().upper()
        if not name:
            print("❌ Invalid name. Recording cancelled.")
            return None
        return name
    
    def _extract_landmarks(self, hand_landmarks):
        """Extract landmarks as array of [x, y, z] coordinates."""
        landmarks = []
        for lm in hand_landmarks.landmark:
            landmarks.append([lm.x, lm.y, lm.z])
        return landmarks
    
    def _start_recording(self, mode):
        """Start recording in specified mode."""
        if self.is_recording:
            print("⚠ Already recording! Press 'r' to reset first.")
            return
        
        self.gesture_name = self._prompt_gesture_name()
        if not self.gesture_name:
            return
        
        self.recording_mode = mode
        self.is_recording = True
        self.recorded_frames = []
        self.position_history.clear()
        self.start_time = time.time()
        
        mode_text = {
            'static': 'STATIC (hold pose)',
            'dynamic': 'DYNAMIC (perform motion)',
            'combo': 'COMBO (two hands)'
        }
        print(f"\n🔴 Recording {mode_text[mode]}: {self.gesture_name}")
        if mode == 'static':
            print("   Hold your pose steady...")
        elif mode == 'dynamic':
            print("   Perform your motion now! (2 seconds)")
        elif mode == 'combo':
            print("   Show both hands in pose...")
    
    def _stop_recording(self):
        """Stop recording and save gesture."""
        if not self.is_recording:
            return
        
        elapsed = time.time() - self.start_time
        
        if not self.recorded_frames:
            print("❌ No frames recorded!")
            self._reset_recording()
            return
        
        # Build gesture data based on mode
        gesture_data = {
            "name": self.gesture_name,
            "type": self.recording_mode,
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": round(elapsed, 2),
            "num_frames": len(self.recorded_frames)
        }
        
        if self.recording_mode == 'static':
            # Take median frame for stability
            if len(self.recorded_frames) >= 5:
                mid_idx = len(self.recorded_frames) // 2
                gesture_data["landmarks"] = self.recorded_frames[mid_idx]
                gesture_data["hand"] = "single"
            else:
                gesture_data["landmarks"] = self.recorded_frames[-1]
                gesture_data["hand"] = "single"
        
        elif self.recording_mode == 'dynamic':
            # Store full sequence
            gesture_data["landmarks_sequence"] = self.recorded_frames
            gesture_data["initial_position"] = self.recorded_frames[0]
            gesture_data["ending_position"] = self.recorded_frames[-1]
            gesture_data["hand"] = "single"
            
            # Calculate motion statistics
            if len(self.recorded_frames) >= 2:
                initial = np.array(self.recorded_frames[0]["hands"][0]["landmarks"][8][:2])  # Index tip
                ending = np.array(self.recorded_frames[-1]["hands"][0]["landmarks"][8][:2])
                displacement = np.linalg.norm(ending - initial)
                angle = np.degrees(np.arctan2(ending[1] - initial[1], ending[0] - initial[0]))
                
                gesture_data["motion_stats"] = {
                    "displacement": float(displacement),
                    "angle_degrees": float(angle),
                    "direction": self._get_direction(angle)
                }
        
        elif self.recording_mode == 'combo':
            # Store both hands
            gesture_data["landmarks"] = self.recorded_frames[-1]  # Use last stable frame
            gesture_data["hand"] = "both"
        
        # Add to dataset
        self.dataset["gestures"].append(gesture_data)
        self._save_dataset()
        
        print(f"✓ Gesture '{self.gesture_name}' saved!")
        print(f"   Type: {self.recording_mode}")
        print(f"   Frames: {len(self.recorded_frames)}")
        print(f"   Duration: {elapsed:.2f}s")
        
        self._reset_recording()
    
    def _get_direction(self, angle):
        """Convert angle to cardinal direction."""
        if -45 <= angle < 45:
            return "RIGHT"
        elif 45 <= angle < 135:
            return "DOWN"
        elif angle >= 135 or angle < -135:
            return "LEFT"
        else:
            return "UP"
    
    def _reset_recording(self):
        """Reset recording state."""
        self.is_recording = False
        self.recording_mode = None
        self.recorded_frames = []
        self.position_history.clear()
        self.gesture_name = ""
        print("↻ Recording reset")
    
    def _process_frame(self, frame, results):
        """Process detected hands and record if in recording mode."""
        if not results.multi_hand_landmarks or not results.multi_handedness:
            return
        
        if not self.is_recording:
            return
        
        elapsed = time.time() - self.start_time
        
        # Process based on mode
        if self.recording_mode == 'static':
            # Record for 1 second, capture multiple frames for stability
            if elapsed < 1.0:
                frame_data = self._capture_frame_data(results)
                if frame_data:
                    self.recorded_frames.append(frame_data)
            else:
                self._stop_recording()
        
        elif self.recording_mode == 'dynamic':
            # Record motion sequence for 2 seconds
            if elapsed < self.dynamic_duration:
                frame_data = self._capture_frame_data(results)
                if frame_data:
                    self.recorded_frames.append(frame_data)
            else:
                self._stop_recording()
        
        elif self.recording_mode == 'combo':
            # Check for two hands
            if len(results.multi_hand_landmarks) == 2:
                if elapsed > 0.5 and elapsed < 1.5:  # Capture stable frame
                    frame_data = self._capture_frame_data(results)
                    if frame_data and len(frame_data["hands"]) == 2:
                        self.recorded_frames.append(frame_data)
                elif elapsed >= 1.5:
                    self._stop_recording()
            else:
                if elapsed > 1.0:
                    print("⚠ Both hands not detected! Extending recording time...")
    
    def _capture_frame_data(self, results):
        """Capture landmark data from current frame."""
        frame_data = {"hands": []}
        
        for hand_landmarks, handedness in zip(results.multi_hand_landmarks, results.multi_handedness):
            hand_label = handedness.classification[0].label
            confidence = handedness.classification[0].score
            landmarks = self._extract_landmarks(hand_landmarks)
            
            hand_info = {
                "hand": hand_label,
                "confidence": float(confidence),
                "landmarks": landmarks
            }
            frame_data["hands"].append(hand_info)
        
        return frame_data
    
    def _draw_ui(self, frame):
        """Draw UI overlay on frame."""
        h, w = frame.shape[:2]
        
        # Status bar
        cv2.rectangle(frame, (0, 0), (w, 80), (0, 0, 0), -1)
        
        # Title
        cv2.putText(frame, "Gesture Landmark Recorder", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        
        # Recording status
        if self.is_recording:
            elapsed = time.time() - self.start_time
            status_text = f"RECORDING: {self.gesture_name} ({self.recording_mode.upper()})"
            time_text = f"Time: {elapsed:.1f}s | Frames: {len(self.recorded_frames)}"
            
            cv2.putText(frame, status_text, (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.putText(frame, time_text, (400, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            
            # Recording indicator
            cv2.circle(frame, (w - 30, 40), 15, (0, 0, 255), -1)
        else:
            status_text = "Ready - Press 's' (static) / 'd' (dynamic) / 'c' (combo)"
            cv2.putText(frame, status_text, (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 255, 100), 1)
        
        # Dataset info
        cv2.putText(frame, f"Gestures in dataset: {len(self.dataset['gestures'])}", 
                    (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        
        # Controls hint
        controls = "Controls: 's'=Static | 'd'=Dynamic | 'c'=Combo | 'r'=Reset | 'q'=Quit"
        cv2.putText(frame, controls, (10, h - 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
    
    def run(self):
        """Main capture loop."""
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("❌ Error: Could not open camera")
            return
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    print("❌ Error: Could not read frame")
                    break
                
                # Flip for mirror view
                frame = cv2.flip(frame, 1)
                
                # Process with MediaPipe
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self.hands.process(rgb_frame)
                
                # Draw hand landmarks
                if results.multi_hand_landmarks:
                    for hand_landmarks, handedness in zip(results.multi_hand_landmarks, results.multi_handedness):
                        hand_label = handedness.classification[0].label
                        color = (0, 255, 0) if hand_label == "Left" else (255, 0, 0)
                        
                        self.mp_draw.draw_landmarks(
                            frame,
                            hand_landmarks,
                            self.mp_hands.HAND_CONNECTIONS,
                            self.mp_draw.DrawingSpec(color=color, thickness=2, circle_radius=2),
                            self.mp_draw.DrawingSpec(color=color, thickness=2)
                        )
                
                # Process frame for recording
                self._process_frame(frame, results)
                
                # Draw UI
                self._draw_ui(frame)
                
                # Show frame
                cv2.imshow('Gesture Landmark Recorder', frame)
                
                # Handle keyboard input
                key = cv2.waitKey(1) & 0xFF
                
                if key == ord('s'):
                    if not self.is_recording:
                        self._start_recording('static')
                
                elif key == ord('d'):
                    if not self.is_recording:
                        self._start_recording('dynamic')
                
                elif key == ord('c'):
                    if not self.is_recording:
                        self._start_recording('combo')
                
                elif key == ord('r'):
                    self._reset_recording()
                
                elif key == ord('q'):
                    print("\n👋 Exiting...")
                    break
        
        finally:
            cap.release()
            cv2.destroyAllWindows()
            self.hands.close()
            
            # Final save
            if self.dataset["gestures"]:
                self._save_dataset()
                print(f"\n✓ Final dataset saved: {len(self.dataset['gestures'])} gestures")
                print(f"   File: {self.output_file.absolute()}")

def main():
    recorder = GestureLandmarkRecorder()
    recorder.run()

if __name__ == "__main__":
    main()
