#!/usr/bin/env python3
"""
capture_user_gestures.py
────────────────────────
Script to capture landmarks for user-defined Chrome shortcut gestures.

This script:
1. Shows which actions need gestures captured
2. Guides user through recording each gesture (6 samples)
3. Automatically updates gestures_config_v2.json
4. Creates custom gesture entries with DTW matching

Usage:
    python capture_user_gestures.py
"""

import cv2
import json
import logging
import time
import sys
from pathlib import Path
from collections import deque


# Add project root (one level up) to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))


from pipeline.config_manager import ConfigManager
from pipeline.gesture_detector_fixed import GestureDetector
from pipeline.recorder import Recorder
from pipeline.dtw_matcher import DTWMatcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Actions that need user-defined gestures
USER_DEFINED_ACTIONS = {
    "new_window": {
        "label": "New Window",
        "description": "Open a new browser window",
        "shortcut": "Ctrl+N",
        "suggested_type": "static"
    },
    "new_incognito_window": {
        "label": "New Incognito Window",
        "description": "Open incognito/private window",
        "shortcut": "Ctrl+Shift+N",
        "suggested_type": "static"
    },
    "tab_reopen": {
        "label": "Reopen Closed Tab",
        "description": "Restore last closed tab",
        "shortcut": "Ctrl+Shift+T",
        "suggested_type": "static"
    },
    "tab_jump_rightmost": {
        "label": "Jump to Last Tab",
        "description": "Switch to rightmost tab",
        "shortcut": "Ctrl+9",
        "suggested_type": "static"
    },
    "go_home": {
        "label": "Go Home",
        "description": "Navigate to home page",
        "shortcut": "Alt+Home",
        "suggested_type": "static"
    },
    "window_close": {
        "label": "Close Window",
        "description": "Close entire browser window",
        "shortcut": "Ctrl+Shift+W",
        "suggested_type": "static"
    },
    "tab_move_right": {
        "label": "Move Tab Right",
        "description": "Move current tab to the right",
        "shortcut": "Ctrl+Shift+PgDn",
        "suggested_type": "dynamic"
    },
    "tab_move_left": {
        "label": "Move Tab Left",
        "description": "Move current tab to the left",
        "shortcut": "Ctrl+Shift+PgUp",
        "suggested_type": "dynamic"
    },
    "back": {
        "label": "Go Back",
        "description": "Navigate back in history",
        "shortcut": "Alt+Left",
        "suggested_type": "dynamic"
    },
    "forward": {
        "label": "Go Forward",
        "description": "Navigate forward in history",
        "shortcut": "Alt+Right",
        "suggested_type": "dynamic"
    }
}


class GestureCaptureSession:
    """Interactive session for capturing user gestures."""
    
    def __init__(self, config_path: str = "gestures_config_v2.json"):
        self.config_path = config_path
        self.cfg = ConfigManager(config_path)
        self.dtw = DTWMatcher(self.cfg)
        self.detector = GestureDetector(self.cfg)
        self.recorder = Recorder(self.cfg, self.dtw)
        self.cap = None
        
    def show_menu(self):
        """Display menu of actions that need gestures."""
        print("\n" + "="*70)
        print("USER-DEFINED GESTURE CAPTURE")
        print("="*70)
        print("\nThe following actions need custom gestures:\n")
        
        for i, (action_id, info) in enumerate(USER_DEFINED_ACTIONS.items(), 1):
            print(f"{i:2}. {info['label']:25} ({info['shortcut']})")
            print(f"    {info['description']}")
            print(f"    Type: {info['suggested_type']}")
            print()
        
        print("="*70)
        print("\nOptions:")
        print("  1-10: Capture specific gesture")
        print("  all:  Capture all gestures")
        print("  q:    Quit")
        print("\nYour choice: ", end="")
        
        return input().strip().lower()
    
    def capture_gesture(self, action_id: str, info: dict):
        """Capture landmarks for a specific action."""
        gesture_id = f"user_{action_id}"
        
        print("\n" + "─"*70)
        print(f"CAPTURING: {info['label']}")
        print("─"*70)
        print(f"Description: {info['description']}")
        print(f"Shortcut:    {info['shortcut']}")
        print(f"Type:        {info['suggested_type']}")
        print("\nInstructions:")
        
        if info['suggested_type'] == "static":
            print("  • Hold a distinctive POSE for 2 seconds")
            print("  • Repeat 6 times for reliability")
            print("  • Keep your hand steady and well-lit")
        else:
            print("  • Perform a distinctive MOTION within 1 second")
            print("  • Repeat 6 times for reliability")
            print("  • Make the motion clear and consistent")
        
        print("\nTips:")
        print("  • Use gestures different from built-in ones")
        print("  • Make sure lighting is good")
        print("  • Position hand clearly in frame")
        print("\nPress ENTER when ready (or 's' to skip): ", end="")
        
        choice = input().strip().lower()
        if choice == 's':
            logger.info(f"Skipped {action_id}")
            return False
        
        # Open camera if not already open
        if not self.cap:
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                logger.error("Failed to open camera")
                return False
        
        # Start recording session
        hand_preference = "Right"  # Can be made configurable
        self.recorder.start_session(
            gesture_id=gesture_id,
            label=info['label'],
            gesture_type=info['suggested_type'],
            preferred_hand=hand_preference
        )
        
        # Recording loop
        sample_count = 0
        while self.recorder.is_active:
            ret, frame = self.cap.read()
            if not ret:
                logger.error("Failed to read frame")
                break
            
            # Process frame
            annotated_frame, frame_result = self.detector.process_frame(frame)
            event = self.recorder.update(frame_result)
            
            # Display instructions on frame
            if event:
                # Main instruction
                cv2.putText(
                    annotated_frame,
                    event.message,
                    (50, 80),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 255, 255),
                    2
                )
                
                # Countdown
                if event.countdown:
                    cv2.putText(
                        annotated_frame,
                        str(event.countdown),
                        (annotated_frame.shape[1]//2 - 50, annotated_frame.shape[0]//2),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        4,
                        (0, 255, 0),
                        6
                    )
                
                # Progress
                progress = f"Sample {event.samples_done}/{event.samples_total}"
                cv2.putText(
                    annotated_frame,
                    progress,
                    (50, 130),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (255, 255, 255),
                    2
                )
                
                if event.samples_done != sample_count:
                    sample_count = event.samples_done
                    logger.info(f"Sample {sample_count}/6 captured")
            
            # Display action info
            cv2.putText(
                annotated_frame,
                f"Action: {info['label']} ({info['shortcut']})",
                (50, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 0),
                2
            )
            
            cv2.imshow("Gesture Capture", annotated_frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                self.recorder.cancel()
                return False
        
        # Gesture captured successfully, now bind it
        self.cfg.set_binding(gesture_id, action_id)
        logger.info(f"✓ Gesture '{gesture_id}' bound to action '{action_id}'")
        
        print(f"\n✓ Successfully captured: {info['label']}")
        time.sleep(1)
        
        return True
    
    def capture_all(self):
        """Capture all user-defined gestures in sequence."""
        print("\n" + "="*70)
        print("CAPTURING ALL USER-DEFINED GESTURES")
        print("="*70)
        print(f"\nYou will capture {len(USER_DEFINED_ACTIONS)} gestures.")
        print("Each gesture requires 6 samples.")
        print("\nThis will take approximately 10-15 minutes.")
        print("\nPress ENTER to start, or 'q' to cancel: ", end="")
        
        if input().strip().lower() == 'q':
            return
        
        for i, (action_id, info) in enumerate(USER_DEFINED_ACTIONS.items(), 1):
            print(f"\n[{i}/{len(USER_DEFINED_ACTIONS)}] Next gesture...")
            time.sleep(1)
            
            if not self.capture_gesture(action_id, info):
                print("\nCapture cancelled or failed.")
                cont = input("Continue with next gesture? (y/n): ").strip().lower()
                if cont != 'y':
                    break
        
        print("\n" + "="*70)
        print("ALL GESTURES CAPTURED!")
        print("="*70)
        print("\nYour custom gestures have been saved to:")
        print(f"  {self.config_path}")
        print("\nYou can now use these gestures in the pipeline!")
    
    def run(self):
        """Main interactive loop."""
        try:
            while True:
                choice = self.show_menu()
                
                if choice == 'q':
                    break
                elif choice == 'all':
                    self.capture_all()
                    break
                elif choice.isdigit():
                    idx = int(choice) - 1
                    actions_list = list(USER_DEFINED_ACTIONS.items())
                    
                    if 0 <= idx < len(actions_list):
                        action_id, info = actions_list[idx]
                        self.capture_gesture(action_id, info)
                    else:
                        print("Invalid choice!")
                else:
                    print("Invalid choice!")
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
        
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources."""
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()
        self.detector.close()
        logger.info("Cleanup complete")


def show_summary():
    """Show summary of captured gestures."""
    config = ConfigManager("gestures_config_v2.json")
    
    print("\n" + "="*70)
    print("CAPTURED GESTURES SUMMARY")
    print("="*70)
    
    captured_count = 0
    for action_id in USER_DEFINED_ACTIONS.keys():
        gesture_id = f"user_{action_id}"
        
        if config.get_binding(gesture_id):
            captured_count += 1
            status = "✓ Captured"
        else:
            status = "✗ Not captured"
        
        print(f"{status:15} {USER_DEFINED_ACTIONS[action_id]['label']}")
    
    print("\n" + "="*70)
    print(f"Total: {captured_count}/{len(USER_DEFINED_ACTIONS)} gestures captured")
    print("="*70)


def main():
    print("\n" + "="*70)
    print("GESTURE LANDMARK CAPTURE TOOL")
    print("="*70)
    print("\nThis tool helps you capture custom gestures for Chrome shortcuts.")
    print("\nPredefined gestures (already mapped):")
    print("  • PALM → New Tab")
    print("  • FIST → Close Tab")
    print("  • SWIPE_RIGHT → Next Tab")
    print("  • SWIPE_LEFT → Previous Tab")
    print("  • SWIPE_UP → Minimize Window")
    print("  • SWIPE_DOWN → Maximize Window")
    print("  • WAVE → Refresh")
    print("  • PEACE → Activate Cursor")
    print("  • INDEX_ONLY → Start Text Selection")
    print("  • OK → Search on Google")
    print("\nYou will now capture gestures for the remaining actions.")
    print("\nPress ENTER to continue...")
    input()
    
    session = GestureCaptureSession()
    session.run()
    
    show_summary()
    
    print("\n✓ All done! You can now run the pipeline with your custom gestures.")


if __name__ == "__main__":
    main()
