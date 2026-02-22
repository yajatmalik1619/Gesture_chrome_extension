#!/usr/bin/env python3
"""
capture_user_gestures.py
────────────────────────
Efficient CLI tool for recording custom hand gestures.

Usage:
    python capture_user_gestures.py
    python capture_user_gestures.py --list
    python capture_user_gestures.py --gesture my_wave --label "My Wave" --type static
"""

import argparse
import cv2
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.config_manager import ConfigManager
from pipeline.gesture_detector_fixed import GestureDetector
from pipeline.recorder import Recorder
from pipeline.dtw_matcher import DTWMatcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

CONFIG_PATH = "gestures_config_v2.json"

# Colors

C_RESET  = "\033[0m"
C_BOLD   = "\033[1m"
C_PURPLE = "\033[35m"
C_CYAN   = "\033[36m"
C_GREEN  = "\033[32m"
C_YELLOW = "\033[33m"
C_RED    = "\033[31m"
C_GRAY   = "\033[90m"

def p(text, color=C_RESET):
    print(f"{color}{text}{C_RESET}")

def header(text):
    print(f"\n{C_BOLD}{C_PURPLE}{'─' * 60}{C_RESET}")
    print(f"{C_BOLD}{C_PURPLE}  {text}{C_RESET}")
    print(f"{C_BOLD}{C_PURPLE}{'─' * 60}{C_RESET}\n")

#  Capture Session 

class CaptureSession:
    SAMPLES_NEEDED = 6

    def __init__(self):
        self.cfg = ConfigManager(CONFIG_PATH)
        self.dtw = DTWMatcher(self.cfg)
        self.detector = GestureDetector(self.cfg)
        self.recorder = Recorder(self.cfg, self.dtw)
        self.cap = None

    def _open_camera(self):
        if self.cap and self.cap.isOpened():
            return True
        idx = self.cfg.settings.get("camera_index", 0)
        self.cap = cv2.VideoCapture(idx)
        if not self.cap.isOpened():
            p(f"  Cannot open camera (index {idx}). Check your camera.", C_RED)
            return False
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
        return True

    def capture(self, gesture_id: str, label: str, gesture_type: str, hand: str = "Right") -> bool:
        """Run the interactive capture loop for a single gesture."""
        if not self._open_camera():
            return False

        header(f"Recording: {label}")
        p(f"  ID    : {gesture_id}", C_CYAN)
        p(f"  Type  : {gesture_type}  |  Hand: {hand}", C_CYAN)
        if gesture_type == "static":
            p("  Hold a clear, steady pose for each sample.", C_GRAY)
        else:
            p("  Perform a distinct motion for each sample.", C_GRAY)
        p(f"\n  {self.SAMPLES_NEEDED} samples needed. Keep hand visible and well-lit.", C_GRAY)
        p("\n  Press ENTER to start, S to skip, Q to quit: ", C_YELLOW)

        choice = input().strip().lower()
        if choice == 's':
            p("  Skipped.", C_GRAY); return False
        if choice == 'q':
            return None  # signal quit

        self.recorder.start_session(
            gesture_id=gesture_id,
            label=label,
            gesture_type=gesture_type,
            preferred_hand=hand.capitalize()
        )

        sample_count = 0
        last_message = ""
        last_countdown = None

        while self.recorder.is_active:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.03)
                continue

            annotated, frame_result = self.detector.process_frame(frame)
            event = self.recorder.update(frame_result)

            if event:
                # Console feedback
                if event.message and event.message != last_message:
                    last_message = event.message
                if event.countdown != last_countdown:
                    last_countdown = event.countdown

                if event.samples_done != sample_count:
                    sample_count = event.samples_done
                    bar = "[" + "#" * sample_count + "·" * (self.SAMPLES_NEEDED - sample_count) + "]"
                    p(f"\r  {bar} {sample_count}/{self.SAMPLES_NEEDED}", C_GREEN, end='', flush=True)
                    sys.stdout.flush()

            # Overlay on camera frame
            h, w = annotated.shape[:2]
            overlay = annotated.copy()
            cv2.rectangle(overlay, (0, 0), (w, 80), (20, 5, 45), -1)
            cv2.addWeighted(overlay, 0.75, annotated, 0.25, 0, annotated)

            cv2.putText(annotated, f"{label}  [{gesture_type}]",
                        (14, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 160, 255), 1, cv2.LINE_AA)

            msg = (event.message if event else last_message) or "Waiting for hand..."
            cv2.putText(annotated, msg, (14, 54),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.56, (160, 220, 255), 1, cv2.LINE_AA)

            # Progress bar
            if event:
                done = event.samples_done
                total = event.samples_total or self.SAMPLES_NEEDED
                bar_w = int((done / total) * (w - 28))
                cv2.rectangle(annotated, (14, 66), (w - 14, 70), (60, 30, 90), -1)
                if bar_w > 0:
                    cv2.rectangle(annotated, (14, 66), (14 + bar_w, 70), (168, 85, 247), -1)

            # Countdown
            if event and event.countdown:
                cv2.putText(annotated, str(event.countdown),
                            (w // 2 - 24, h // 2 + 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 3.0, (168, 85, 247), 4, cv2.LINE_AA)

            cv2.imshow("GestureSelect — Recording (Q to cancel)", annotated)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                self.recorder.cancel()
                p("\n  Cancelled.", C_RED)
                return False

        print()  # newline after inline bar
        self.cfg.set_binding(gesture_id, gesture_id)
        p(f"  Captured and saved: {gesture_id}", C_GREEN)
        time.sleep(0.8)
        return True

    def interactive_menu(self):
        """List and manage recorded gestures, or add new ones."""
        header("GestureSelect — Gesture Capture Tool")
        p("  Capture custom gestures to use with the Chrome extension.\n", C_GRAY)

        while True:
            p("  Options:", C_BOLD)
            p("    1. Capture a new gesture", C_CYAN)
            p("    2. List captured gestures", C_CYAN)
            p("    Q. Quit\n", C_CYAN)
            choice = input(f"  {C_YELLOW}>{C_RESET} ").strip().lower()

            if choice == '1':
                self._capture_interactive()
            elif choice == '2':
                self._list_gestures()
            elif choice in ('q', ''):
                break
            else:
                p("  Invalid choice.", C_RED)

    def _capture_interactive(self):
        print()
        gesture_id = input(f"  {C_CYAN}Gesture ID{C_RESET} (e.g. my_wave): ").strip().replace(' ', '_').lower()
        if not gesture_id:
            return

        label = input(f"  {C_CYAN}Label{C_RESET} [{gesture_id}]: ").strip() or gesture_id
        print(f"  {C_CYAN}Type{C_RESET}: (1) Static  (2) Dynamic  [1]: ", end='')
        t = input().strip()
        gesture_type = "dynamic" if t == '2' else "static"
        print(f"  {C_CYAN}Hand{C_RESET}: (1) Right  (2) Left  [1]: ", end='')
        h = input().strip()
        hand = "Left" if h == '2' else "Right"

        result = self.capture(gesture_id, label, gesture_type, hand)
        if result is None:
            raise SystemExit(0)

    def _list_gestures(self):
        header("Captured Gestures")
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
        except Exception as e:
            p(f"  Could not load config: {e}", C_RED)
            return

        custom = cfg.get("custom_gestures", {})
        bindings = cfg.get("bindings", {})
        count = 0
        for gid, info in custom.items():
            if gid == "_metadata":
                continue
            label = info.get("label", gid)
            bound_to = bindings.get(gid, "(unbound)")
            p(f"  {C_CYAN}{gid:<30}{C_RESET} {label}  →  {C_GRAY}{bound_to}{C_RESET}")
            count += 1

        if count == 0:
            p("  No custom gestures captured yet.", C_GRAY)
        print()

    def cleanup(self):
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()
        self.detector.close()


# CLI 

def main():
    parser = argparse.ArgumentParser(description="GestureSelect Capture Tool")
    parser.add_argument("--gesture", help="Gesture ID to capture directly")
    parser.add_argument("--label", help="Display label")
    parser.add_argument("--type", choices=["static", "dynamic"], default="static")
    parser.add_argument("--hand", choices=["right", "left"], default="right")
    parser.add_argument("--list", action="store_true", help="List captured gestures and exit")
    args = parser.parse_args()

    session = CaptureSession()

    try:
        if args.list:
            session._list_gestures()
        elif args.gesture:
            label = args.label or args.gesture
            session.capture(args.gesture, label, args.type, args.hand.capitalize())
        else:
            session.interactive_menu()
    except KeyboardInterrupt:
        p("\n\n  Interrupted.", C_YELLOW)
    finally:
        session.cleanup()


if __name__ == "__main__":
    main()
