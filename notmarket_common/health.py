"""HTTP health check server on a daemon thread."""

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health" and self.server.healthy_fn():
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"status":"unavailable"}')

    def log_message(self, _fmt, *_args):
        pass


def start_health_server(port, healthy_fn=None):
    """Start an HTTP health check server on a daemon thread.

    Args:
        port: TCP port to listen on. Use 0 for auto-assign.
        healthy_fn: Optional callable returning bool. Defaults to always healthy.

    Returns:
        The HTTPServer instance (useful for testing / shutdown).
    """
    if healthy_fn is None:
        healthy_fn = lambda: True  # noqa: E731
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    server.healthy_fn = healthy_fn
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info("Health check listening on :%d/health", port)
    return server
