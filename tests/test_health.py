"""Tests for notmarket_common.health — HTTP health check server."""

import json
import threading
import urllib.request

from notmarket_common.health import start_health_server


def _get(port, path="/health"):
    url = f"http://127.0.0.1:{port}{path}"
    try:
        resp = urllib.request.urlopen(url, timeout=2)
        return resp.getcode(), json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestHealthServer:
    def test_returns_200_when_healthy(self):
        server = start_health_server(0, lambda: True)
        port = server.server_address[1]
        try:
            code, body = _get(port)
            assert code == 200
            assert body["status"] == "ok"
        finally:
            server.shutdown()

    def test_returns_503_when_unhealthy(self):
        server = start_health_server(0, lambda: False)
        port = server.server_address[1]
        try:
            code, body = _get(port)
            assert code == 503
            assert body["status"] == "unavailable"
        finally:
            server.shutdown()

    def test_returns_503_for_unknown_path(self):
        server = start_health_server(0, lambda: True)
        port = server.server_address[1]
        try:
            code, body = _get(port, "/unknown")
            assert code == 503
        finally:
            server.shutdown()

    def test_healthy_fn_toggling(self):
        healthy = [True]
        server = start_health_server(0, lambda: healthy[0])
        port = server.server_address[1]
        try:
            code, _ = _get(port)
            assert code == 200

            healthy[0] = False
            code, _ = _get(port)
            assert code == 503

            healthy[0] = True
            code, _ = _get(port)
            assert code == 200
        finally:
            server.shutdown()

    def test_server_runs_on_daemon_thread(self):
        server = start_health_server(0, lambda: True)
        try:
            daemon_threads = [
                t
                for t in threading.enumerate()
                if t.daemon and t.is_alive() and "Thread" in type(t).__name__
            ]
            assert len(daemon_threads) >= 1
        finally:
            server.shutdown()

    def test_default_healthy_fn_returns_ok(self):
        server = start_health_server(0)
        port = server.server_address[1]
        try:
            code, body = _get(port)
            assert code == 200
            assert body["status"] == "ok"
        finally:
            server.shutdown()
