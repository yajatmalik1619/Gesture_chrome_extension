"""
websocket_server.py
────────────────────
Async WebSocket server that bridges the Python pipeline to the Chrome extension.

Roles:
  - Broadcasts ActionEvents (as JSON) to all connected extension clients.
  - Accepts inbound messages from the extension (config writes, custom gesture
    recordings, UI setting changes).
  - Runs in a background thread so it doesn't block the OpenCV capture loop.

Message protocol (both directions are JSON):

  OUTBOUND (pipeline → extension):
    {
      "type": "ACTION",
      "action_id": "tab_switch_left",
      "gesture_id": "SWIPE_LEFT",
      "hand": "Right",
      "magnitude": 3,
      "repeatable": false,
      "timestamp": 1708166400.123,
      "meta": {}
    }

    {
      "type": "STATUS",
      "status": "running" | "no_hands" | "error",
      "fps": 28.4
    }

  INBOUND (extension → pipeline):
    { "type": "UPDATE_SETTING", "key": "scroll_speed", "value": 5 }
    { "type": "UPDATE_BINDING", "gesture_id": "FIST", "action_id": "tab_close" }
    { "type": "SAVE_CUSTOM_GESTURE", "gesture_id": "custom_x", "data": { ... } }
    { "type": "DELETE_CUSTOM_GESTURE", "gesture_id": "custom_x" }
    { "type": "PING" }
"""

import asyncio
import json
import logging
import threading
import time
from typing import Optional

import websockets
from websockets.server import WebSocketServerProtocol

from pipeline.config_manager import ConfigManager
from pipeline.gesture_router import ActionEvent

logger = logging.getLogger(__name__)


class WebSocketServer:
    """
    Manages the WebSocket lifecycle in a background thread.

    Usage:
        server = WebSocketServer(config)
        server.start()                        # non-blocking
        server.broadcast(action_event)        # thread-safe
        server.stop()
    """

    def __init__(self, config: ConfigManager):
        self.cfg = config
        self._clients: set[WebSocketServerProtocol] = set()
        self._loop:    Optional[asyncio.AbstractEventLoop] = None
        self._thread:  Optional[threading.Thread] = None
        self._running  = False

        # FPS tracking for STATUS messages
        self._frame_times: list[float] = []
        self._last_status_broadcast = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        """Spawn the asyncio event loop in a daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="WebSocketServer"
        )
        self._thread.start()
        logger.info(f"WebSocket server starting on ws://{self.cfg.ws_host}:{self.cfg.ws_port}")

    def stop(self):
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ── Broadcasting (thread-safe, called from OpenCV thread) ─────────────────

    def broadcast(self, event: ActionEvent):
        """
        Send an ActionEvent to all connected extension clients.
        Thread-safe — schedules on the asyncio loop.
        """
        if not self._loop or not self._clients:
            return
        payload = json.dumps({"type": "ACTION", **event.to_dict()})
        asyncio.run_coroutine_threadsafe(
            self._broadcast_raw(payload), self._loop
        )

    def broadcast_status(self, status: str):
        """Send a STATUS heartbeat. Called from the pipeline loop."""
        if not self._loop or not self._clients:
            return
        now = time.time()

        # FPS calculation
        self._frame_times.append(now)
        self._frame_times = [t for t in self._frame_times if now - t < 1.0]
        fps = len(self._frame_times)

        # Rate-limit status messages to once per second
        if now - self._last_status_broadcast < 1.0:
            return
        self._last_status_broadcast = now

        payload = json.dumps({
            "type": "STATUS",
            "status": status,
            "fps": fps,
            "timestamp": now
        })
        asyncio.run_coroutine_threadsafe(
            self._broadcast_raw(payload), self._loop
        )

    # ── Async internals ────────────────────────────────────────────────────────

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            logger.error(f"WebSocket loop error: {e}")

    async def _serve(self):
        async with websockets.serve(
            self._handler,
            self.cfg.ws_host,
            self.cfg.ws_port,
            ping_interval=20,
            ping_timeout=10,
        ):
            logger.info(f"WebSocket server live on ws://{self.cfg.ws_host}:{self.cfg.ws_port}")
            await asyncio.Future()   # run forever until loop is stopped

    async def _handler(self, websocket: WebSocketServerProtocol):
        """Handle a new client connection."""
        client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        self._clients.add(websocket)
        logger.info(f"Client connected: {client_id}  (total: {len(self._clients)})")

        # Send current config snapshot on connect
        await self._send_config_snapshot(websocket)

        try:
            async for raw in websocket:
                await self._handle_inbound(websocket, raw)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info(f"Client disconnected: {client_id}  (total: {len(self._clients)})")

    async def _broadcast_raw(self, payload: str):
        """Send raw JSON string to all connected clients."""
        if not self._clients:
            return
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(payload)
            except websockets.ConnectionClosed:
                dead.add(ws)
        self._clients -= dead

    # ── Inbound Message Handling ───────────────────────────────────────────────

    async def _handle_inbound(self, websocket: WebSocketServerProtocol, raw: str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from client: {raw[:80]}")
            return

        msg_type = msg.get("type")

        if msg_type == "PING":
            await websocket.send(json.dumps({"type": "PONG", "timestamp": time.time()}))

        elif msg_type == "UPDATE_SETTING":
            key   = msg.get("key")
            value = msg.get("value")
            if key and value is not None:
                self.cfg.set_setting(key, value)
                logger.info(f"Setting updated via WS: {key}={value}")
                await websocket.send(json.dumps({"type": "ACK", "key": key, "value": value}))

        elif msg_type == "UPDATE_BINDING":
            gid = msg.get("gesture_id")
            aid = msg.get("action_id")
            if gid and aid:
                self.cfg.set_binding(gid, aid)
                logger.info(f"Binding updated via WS: {gid}→{aid}")
                await websocket.send(json.dumps({"type": "ACK", "gesture_id": gid, "action_id": aid}))

        elif msg_type == "SAVE_CUSTOM_GESTURE":
            gid  = msg.get("gesture_id")
            data = msg.get("data")
            if gid and data:
                self.cfg.save_custom_gesture(gid, data)
                await websocket.send(json.dumps({"type": "ACK", "gesture_id": gid, "saved": True}))

        elif msg_type == "DELETE_CUSTOM_GESTURE":
            gid = msg.get("gesture_id")
            if gid:
                self.cfg.delete_custom_gesture(gid)
                await websocket.send(json.dumps({"type": "ACK", "gesture_id": gid, "deleted": True}))

        elif msg_type == "GET_CONFIG":
            await self._send_config_snapshot(websocket)

        else:
            logger.warning(f"Unknown inbound message type: {msg_type}")

    async def _send_config_snapshot(self, websocket: WebSocketServerProtocol):
        """Push the full current config to a newly connected client."""
        snapshot = {
            "type": "CONFIG_SNAPSHOT",
            "settings": self.cfg.settings,
            "actions":  self.cfg.actions,
            "gestures": self.cfg.gestures,
            "bindings": self.cfg.bindings,
            "custom_gestures": self.cfg.custom_gestures,
        }
        await websocket.send(json.dumps(snapshot))

    @property
    def client_count(self) -> int:
        return len(self._clients)
