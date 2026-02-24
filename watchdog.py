"""
watchdog.py
───────────
Lightweight always-on HTTP server that starts and stops the full pipeline
on demand from the Chrome extension.

Run at Windows boot (via Task Scheduler) instead of main.py:
    pythonw watchdog.py

The extension calls:
    POST http://localhost:8766/start   → spawns main.py --no-preview
    POST http://localhost:8766/stop    → terminates the pipeline
    GET  http://localhost:8766/status  → {"running": true/false, "pid": N}
"""

import json
import logging
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────

PORT         = 8766
PROJECT_ROOT = Path(__file__).parent.resolve()
VENV_PYTHON  = PROJECT_ROOT / "venv" / "Scripts" / "pythonw.exe"
MAIN_PY      = PROJECT_ROOT / "main.py"
LOG_FILE     = PROJECT_ROOT / "pipeline.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("watchdog")

# ── State ──────────────────────────────────────────────────────────────────────

_process: subprocess.Popen | None = None
_lock = threading.Lock()


def is_running() -> bool:
    with _lock:
        return _process is not None and _process.poll() is None


def start_pipeline() -> dict:
    global _process
    with _lock:
        if _process is not None and _process.poll() is None:
            return {"ok": True, "status": "already_running", "pid": _process.pid}

        python_exe = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
        log_handle = open(LOG_FILE, "a", encoding="utf-8")

        import os as _os
        env = _os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"]       = "1"

        _process = subprocess.Popen(
            [python_exe, str(MAIN_PY), "--no-preview"],
            cwd=str(PROJECT_ROOT),
            stdout=log_handle,
            stderr=log_handle,
            env=env,
            # No console window on Windows
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        logger.info(f"Pipeline started (PID {_process.pid})")
        return {"ok": True, "status": "started", "pid": _process.pid}


def stop_pipeline() -> dict:
    global _process
    with _lock:
        if _process is None or _process.poll() is not None:
            return {"ok": True, "status": "not_running"}

        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()

        pid = _process.pid
        _process = None
        logger.info(f"Pipeline stopped (was PID {pid})")
        return {"ok": True, "status": "stopped", "pid": pid}


# ── HTTP Handler ───────────────────────────────────────────────────────────────

class WatchdogHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def _send_json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            running = is_running()
            pid     = _process.pid if running and _process else None
            self._send_json(200, {"running": running, "pid": pid})
        elif self.path == "/config":
            # Serve the gestures config so the popup can load gestures/actions
            # without needing an active WebSocket connection
            config_path = PROJECT_ROOT / "gestures_config_v2.json"
            try:
                with open(config_path, encoding="utf-8") as f:
                    import json as _json
                    data = _json.load(f)
                self._send_json(200, data)
            except FileNotFoundError:
                self._send_json(404, {"error": "Config not found"})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/start":
            result = start_pipeline()
            self._send_json(200, result)
        elif self.path == "/stop":
            result = stop_pipeline()
            self._send_json(200, result)
        else:
            self._send_json(404, {"error": "Not found"})


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    logger.info(f"Watchdog listening on http://localhost:{PORT}")
    logger.info(f"Project: {PROJECT_ROOT}")
    server = HTTPServer(("localhost", PORT), WatchdogHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Watchdog stopped.")
        stop_pipeline()


if __name__ == "__main__":
    main()
