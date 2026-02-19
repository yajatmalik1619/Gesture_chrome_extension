"""
main.py
───────
Entry point for the GestureSelect Python pipeline.

Wires together:
  ConfigManager → GestureDetector → GestureRouter → ActionExecutor → WebSocketServer
  + DTWMatcher (custom gestures)
  + Recorder   (custom gesture recording sessions)

Run:
    python main.py
    python main.py --config path/to/gestures_config.json
    python main.py --no-preview       # headless mode (no cv2 window)
    python main.py --debug            # verbose logging

The pipeline loop:
  1. Read frame from webcam
  2. GestureDetector processes landmarks → FrameResult
  3. Recorder intercepts frame if a session is active
  4. GestureRouter maps FrameResult → ActionEvents
  5. ActionExecutor translates ActionEvents → browser commands
  6. WebSocketServer broadcasts events + execution results to extension
  7. Display annotated preview (unless --no-preview)
"""

import argparse
import asyncio
import json
import logging
import sys
import time

import cv2

from pipeline.config_manager import ConfigManager
from pipeline.gesture_detector_fixed import GestureDetector
from pipeline.gesture_router import GestureRouter
from pipeline.dtw_matcher import DTWMatcher
from pipeline.websocket_server import WebSocketServer
from pipeline.recorder import Recorder
from Mapping.action_executor_v2 import ActionExecutor

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="GestureSelect Pipeline")
    p.add_argument("--config",     default="gestures_config_v2.json",
                   help="Path to gestures_config.json")
    p.add_argument("--no-preview", action="store_true",
                   help="Disable OpenCV window (headless mode)")
    p.add_argument("--debug",      action="store_true",
                   help="Enable verbose debug logging")
    return p.parse_args()


# ── Main Pipeline Loop ────────────────────────────────────────────────────────

def run(args):
    logger = logging.getLogger("main")
    logger.info("Starting GestureSelect pipeline…")

    # ── Boot components ───────────────────────────────────────────────────────
    cfg      = ConfigManager(args.config)
    cfg.start_watching()                  # live-reload on UI config changes

    dtw      = DTWMatcher(cfg)
    detector = GestureDetector(cfg)
    router   = GestureRouter(cfg, dtw)
    executor = ActionExecutor(cfg)        # NEW: translates actions → commands
    recorder = Recorder(cfg, dtw)
    server   = WebSocketServer(cfg)
    server.start()

    # Attach a recorder reference to the server so inbound WS messages can
    # trigger recording sessions from the UI
    _attach_recorder_commands(server, recorder, cfg)

    # ── Camera setup ──────────────────────────────────────────────────────────
    s = cfg.settings
    cam = cv2.VideoCapture(s.get("camera_index", 0))
    cam.set(cv2.CAP_PROP_FRAME_WIDTH,  s.get("camera_width",  1280))
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, s.get("camera_height", 720))

    if not cam.isOpened():
        logger.error("Cannot open camera. Check camera_index in settings.")
        sys.exit(1)

    logger.info(
        f"Camera opened: {int(cam.get(cv2.CAP_PROP_FRAME_WIDTH))}×"
        f"{int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
    )
    logger.info(f"WebSocket: ws://{cfg.ws_host}:{cfg.ws_port}")
    logger.info("Pipeline running. Press 'q' to quit.")

    # ── Main loop ─────────────────────────────────────────────────────────────
    fps_times: list[float] = []
    try:
        while True:
            ret, frame = cam.read()
            if not ret:
                logger.warning("Frame capture failed — retrying.")
                time.sleep(0.05)
                continue

            # 1. Detect gestures
            annotated, frame_result = detector.process_frame(frame)

            # 2. Recording session (intercepts frames if active)
            if recorder.is_active:
                rec_event = recorder.update(frame_result)
                if rec_event:
                    # Forward recording progress to the extension UI
                    _broadcast_recording_event(server, rec_event)

            # 3. Route gestures → ActionEvents
            events = router.route(frame_result)

            # 4. Execute actions and broadcast results
            for event in events:
                # Execute the action (translates to browser command)
                result = executor.execute(event)
                
                # Log execution
                cmd_str = result.command or 'N/A'
                logger.info(
                    f"→ {event.action_id:25s}  gesture={event.gesture_id:15s} "
                    f"hand={event.hand:6s}  cmd={cmd_str:20s}  "
                    f"success={result.success}  clients={server.client_count}"
                )
                
                # Broadcast ActionEvent (gesture detection info)
                server.broadcast(event)
                
                # Broadcast ExecutionResult (what the extension should do)
                if result.success and result.command:
                    payload = json.dumps({"type": "EXECUTION", **result.to_dict()})
                    if server._loop and server._clients:
                        asyncio.run_coroutine_threadsafe(
                            server._broadcast_raw(payload), server._loop
                        )

            # 5. Status heartbeat
            status = "running" if frame_result.hands else "no_hands"
            server.broadcast_status(status)

            # 6. FPS overlay
            now = time.time()
            fps_times.append(now)
            fps_times = [t for t in fps_times if now - t < 1.0]
            fps = len(fps_times)
            cv2.putText(annotated, f"FPS: {fps}", (10, annotated.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.putText(annotated, f"WS clients: {server.client_count}",
                        (10, annotated.shape[0] - 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # 7. Preview window
            if not args.no_preview:
                cv2.imshow("GestureSelect — Press Q to quit", annotated)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                elif key == ord("r"):
                    logger.info("Manual config reload triggered.")
                    cfg._load()
                elif key == ord("c"):
                    logger.info("Buffers cleared — reset gesture history.")
                    # Clear detector buffers
                    for side in ("Left", "Right"):
                        detector._static_buf[side].clear()
                        detector._dynamic_buf[side].clear()
                        detector._pos_history[side].clear()
                        detector._wrist_history[side].clear()

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        cam.release()
        cv2.destroyAllWindows()
        detector.close()
        server.stop()
        logger.info("Pipeline shut down cleanly.")


# ── Recorder ↔ WebSocket Bridge ───────────────────────────────────────────────

def _attach_recorder_commands(
    server: WebSocketServer,
    recorder: Recorder,
    cfg: ConfigManager
):
    """
    Monkey-patch the server's inbound handler to also handle
    recording session commands sent from the extension UI.

    New inbound message types:
      { "type": "START_RECORDING", "gesture_id": "...", "label": "...",
        "gesture_type": "static"|"dynamic", "hand": "right"|"left" }
      { "type": "CANCEL_RECORDING" }
    """
    original_handler = server._handle_inbound

    async def patched_handler(ws, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            await original_handler(ws, raw)
            return

        if msg.get("type") == "START_RECORDING":
            recorder.start_session(
                gesture_id   = msg.get("gesture_id", f"custom_{int(time.time())}"),
                label        = msg.get("label", "Custom Gesture"),
                gesture_type = msg.get("gesture_type", "static"),
                preferred_hand = msg.get("hand", "Right").capitalize()
            )
            await ws.send(json.dumps({
                "type": "ACK",
                "recording_started": True,
                "gesture_id": msg.get("gesture_id")
            }))
        elif msg.get("type") == "CANCEL_RECORDING":
            event = recorder.cancel()
            if event:
                _broadcast_recording_event(server, event)
        else:
            await original_handler(ws, raw)

    server._handle_inbound = patched_handler


def _broadcast_recording_event(server: WebSocketServer, event):
    """Forward a RecordingEvent to all connected clients."""
    payload = json.dumps(event.to_dict())
    if server._loop and server._clients:
        asyncio.run_coroutine_threadsafe(
            server._broadcast_raw(payload), server._loop
        )


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.debug)
    run(args)