"""
http_server.py
──────────────
Flask-based HTTP server that replaces WebSocket server.
Uses Server-Sent Events (SSE) for pipeline → extension streaming.

No websockets dependency needed - just Flask.

Install:
    pip install flask flask-cors

Endpoints:
    GET  /events - SSE stream (extension listens here)
    POST /command - Inbound messages from extension
    GET  /status - Health check
"""

import json
import logging
import queue
import threading
import time
from typing import Optional, TYPE_CHECKING

from flask import Flask, Response, request, jsonify
from flask_cors import CORS

from pipeline.config_manager import ConfigManager
from pipeline.gesture_router import ActionEvent

if TYPE_CHECKING:
    from pipeline.recorder import Recorder

logger = logging.getLogger(__name__)


class HTTPServer:
    """
    Flask-based HTTP server for the gesture pipeline.
    
    Uses Server-Sent Events (SSE) to stream events to the extension.
    Simpler and more reliable than WebSocket on Windows.
    
    Usage:
        server = HTTPServer(config)
        server.start()                    # non-blocking
        server.broadcast(action_event)    # thread-safe
        server.stop()
    """

    def __init__(self, config: ConfigManager, recorder: Optional["Recorder"] = None):
        self.cfg = config
        self._recorder = recorder
        self.app = Flask(__name__)
        CORS(self.app)  # Allow extension to connect
        
        # Event queue for SSE streaming
        self._event_queue: queue.Queue = queue.Queue(maxsize=100)
        self._clients: set = set()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # FPS tracking
        self._frame_times: list[float] = []
        self._last_status_broadcast = 0.0
        
        # Setup routes
        self._setup_routes()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        """Start the Flask server in a background thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name="HTTPServer"
        )
        self._thread.start()
        logger.info(f"HTTP server starting on http://{self.cfg.ws_host}:{self.cfg.ws_port}")

    def stop(self):
        """Stop the server."""
        self._running = False
        logger.info("HTTP server stopped")

    def _run_server(self):
        """Run Flask server (blocking, called in thread)."""
        # Suppress Flask startup messages
        import sys
        from werkzeug.serving import make_server
        
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        
        server = make_server(
            self.cfg.ws_host,
            self.cfg.ws_port,
            self.app,
            threaded=True
        )
        
        logger.info(f"HTTP server live on http://{self.cfg.ws_host}:{self.cfg.ws_port}")
        
        with server:
            server.serve_forever()

    # ── Broadcasting ───────────────────────────────────────────────────────────

    def broadcast(self, event: ActionEvent):
        """Send an ActionEvent to all connected clients."""
        message = {"type": "ACTION", **event.to_dict()}
        self._send_event(message)

    def broadcast_execution(self, result_dict: dict):
        """Send an EXECUTION result to all connected clients."""
        self._send_event({"type": "EXECUTION", **result_dict})

    def broadcast_status(self, status: str):
        """Send a STATUS heartbeat."""
        now = time.time()
        
        # FPS calculation
        self._frame_times.append(now)
        self._frame_times = [t for t in self._frame_times if now - t < 1.0]
        fps = len(self._frame_times)
        
        # Rate-limit to once per second
        if now - self._last_status_broadcast < 1.0:
            return
        self._last_status_broadcast = now
        
        message = {
            "type": "STATUS",
            "status": status,
            "fps": fps,
            "timestamp": now
        }
        self._send_event(message)

    def _send_event(self, data: dict):
        """Queue an event for SSE streaming."""
        try:
            self._event_queue.put_nowait(json.dumps(data))
        except queue.Full:
            logger.warning("Event queue full, dropping message")

    # ── Routes ─────────────────────────────────────────────────────────────────

    def _setup_routes(self):
        """Setup Flask routes."""
        
        @self.app.route('/events')
        def events():
            """SSE endpoint - streams events to the extension."""
            def generate():
                # Send initial config
                config_snapshot = {
                    "type": "CONFIG_SNAPSHOT",
                    "settings": self.cfg.settings,
                    "actions": self.cfg.actions,
                    "gestures": self.cfg.gestures,
                    "bindings": self.cfg.bindings,
                    "custom_gestures": self.cfg.custom_gestures,
                }
                yield f"data: {json.dumps(config_snapshot)}\n\n"
                
                # Stream events
                client_id = id(threading.current_thread())
                self._clients.add(client_id)
                logger.info(f"Client connected (total: {len(self._clients)})")
                
                try:
                    while self._running:
                        try:
                            # Wait for event with timeout
                            event_data = self._event_queue.get(timeout=1.0)
                            yield f"data: {event_data}\n\n"
                        except queue.Empty:
                            # Send keepalive ping
                            yield f": keepalive\n\n"
                except GeneratorExit:
                    pass
                finally:
                    self._clients.discard(client_id)
                    logger.info(f"Client disconnected (total: {len(self._clients)})")
            
            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no'
                }
            )
        
        @self.app.route('/command', methods=['POST'])
        def command():
            """Handle inbound commands from extension."""
            try:
                msg = request.get_json()
                if not msg:
                    return jsonify({"error": "Invalid JSON"}), 400
                
                response = self._handle_command(msg)
                return jsonify(response)
            
            except Exception as e:
                logger.error(f"Command error: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/status')
        def status():
            """Health check endpoint."""
            return jsonify({
                "status": "running",
                "clients": len(self._clients),
                "host": self.cfg.ws_host,
                "port": self.cfg.ws_port
            })

    # ── Command Handling ───────────────────────────────────────────────────────

    def _handle_command(self, msg: dict) -> dict:
        """Process inbound command from extension."""
        msg_type = msg.get("type")
        
        if msg_type == "PING":
            return {"type": "PONG", "timestamp": time.time()}
        
        elif msg_type == "UPDATE_SETTING":
            key = msg.get("key")
            value = msg.get("value")
            if key and value is not None:
                self.cfg.set_setting(key, value)
                logger.info(f"Setting updated via HTTP: {key}={value}")
                return {"type": "ACK", "key": key, "value": value}
            return {"error": "Missing key or value"}
        
        elif msg_type == "UPDATE_BINDING":
            gid = msg.get("gesture_id")
            aid = msg.get("action_id")
            if gid and aid:
                self.cfg.set_binding(gid, aid)
                logger.info(f"Binding updated via HTTP: {gid}→{aid}")
                return {"type": "ACK", "gesture_id": gid, "action_id": aid}
            return {"error": "Missing gesture_id or action_id"}
        
        elif msg_type == "SAVE_CUSTOM_GESTURE":
            gid = msg.get("gesture_id")
            data = msg.get("data")
            if gid and data:
                self.cfg.save_custom_gesture(gid, data)
                return {"type": "ACK", "gesture_id": gid, "saved": True}
            return {"error": "Missing gesture_id or data"}
        
        elif msg_type == "DELETE_CUSTOM_GESTURE":
            gid = msg.get("gesture_id")
            if gid:
                self.cfg.delete_custom_gesture(gid)
                return {"type": "ACK", "gesture_id": gid, "deleted": True}
            return {"error": "Missing gesture_id"}
        
        elif msg_type == "GET_CONFIG":
            return {
                "type": "CONFIG_SNAPSHOT",
                "settings": self.cfg.settings,
                "actions": self.cfg.actions,
                "gestures": self.cfg.gestures,
                "bindings": self.cfg.bindings,
                "custom_gestures": self.cfg.custom_gestures,
            }
        
        elif msg_type == "START_RECORDING":
            if self._recorder is None:
                return {"error": "Recorder not available"}
            self._recorder.start_session(
                gesture_id     = msg.get("gesture_id", f"custom_{int(time.time())}"),
                label          = msg.get("label", "Custom Gesture"),
                gesture_type   = msg.get("gesture_type", "static"),
                preferred_hand = msg.get("hand", "Right").capitalize()
            )
            return {
                "type": "ACK",
                "recording_started": True,
                "gesture_id": msg.get("gesture_id")
            }
        
        elif msg_type == "CANCEL_RECORDING":
            if self._recorder is None:
                return {"error": "Recorder not available"}
            event = self._recorder.cancel()
            if event:
                self._send_event(event.to_dict())
            return {"type": "ACK", "recording_cancelled": True}
        
        else:
            logger.warning(f"Unknown command type: {msg_type}")
            return {"error": f"Unknown command type: {msg_type}"}

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Alias for backward compatibility with main.py
WebSocketServer = HTTPServer
