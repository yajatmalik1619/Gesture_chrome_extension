"""
pipeline/mjpeg_server.py
─────────────────────────
Lightweight MJPEG HTTP stream server.

Runs in a background thread. main.py pushes frames via push_frame().
The Chrome extension popup reads the stream from http://localhost:8767/stream.

Usage:
    server = MJPEGServer(port=8767)
    server.start()          # starts background thread
    server.push_frame(frame)   # call each loop iteration with BGR numpy array
    server.stop()
"""

import io
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class MJPEGServer:
    def __init__(self, port: int = 8767, quality: int = 60):
        self.port    = port
        self.quality = quality
        self._frame_lock   = threading.Lock()
        self._current_jpeg = b""
        self._frame_event  = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def push_frame(self, frame: np.ndarray):
        """Encode a BGR frame to JPEG and store it for streaming. Thread-safe."""
        ok, buf = cv2.imencode(
            ".jpg", frame,
            [cv2.IMWRITE_JPEG_QUALITY, self.quality],
        )
        if ok:
            with self._frame_lock:
                self._current_jpeg = buf.tobytes()
            self._frame_event.set()
            self._frame_event.clear()

    def get_jpeg(self) -> bytes:
        with self._frame_lock:
            return self._current_jpeg

    def start(self):
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass  # suppress access log

            def do_GET(self):
                path = self.path.split('?')[0]  # strip cache-bust query params
                if path == "/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    try:
                        while True:
                            jpg = server_ref.get_jpeg()
                            if jpg:
                                self.wfile.write(b"--frame\r\n")
                                self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                                self.wfile.write(jpg)
                                self.wfile.write(b"\r\n")
                            server_ref._frame_event.wait(timeout=0.1)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                elif path == "/snapshot":
                    jpg = server_ref.get_jpeg()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(jpg)))
                    self.end_headers()
                    self.wfile.write(jpg)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

        self._server = ThreadingHTTPServer(("localhost", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"MJPEG stream: http://localhost:{self.port}/stream")

    def stop(self):
        if self._server:
            self._server.shutdown()
