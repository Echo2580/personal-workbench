import threading
from urllib.error import HTTPError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core.instance import _instance_json


def test_instance_handshake_never_follows_redirect_or_forwards_token():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/v1/instance":
                self.send_response(302)
                self.send_header("Location", "/target")
                self.end_headers()
            else:
                received.append(self.headers.get("X-Workbench-Token"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"instance_id":"foreign"}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError):
            _instance_json(server.server_port, "/instance", "private-session-token")
        assert received == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
