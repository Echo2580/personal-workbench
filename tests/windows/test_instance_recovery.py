import json
import subprocess

import pytest

from app.core.instance import find_existing_instance
from test_instance import call, launch, wait_instance


@pytest.mark.parametrize("damage", ["missing", "stale", "invalid_json"])
def test_duplicate_recovers_live_instance_when_record_is_unusable(tmp_path, damage):
    data = tmp_path / "data"
    proc = launch(data, "17843:17852")
    duplicate = None
    try:
        info = wait_instance(data)
        path = data / "runtime/instance.json"
        if damage == "missing":
            path.unlink()
        elif damage == "stale":
            path.write_text(
                json.dumps(
                    info | {"token": "old-token", "instance_id": "old-instance"}
                ),
                encoding="utf-8",
            )
        else:
            path.write_text("{broken", encoding="utf-8")
        duplicate = launch(data, "17843:17852")
        assert duplicate.wait(timeout=15) == 0, (
            "A healthy owned service must be reopened, not reported as unready."
        )
        assert proc.poll() is None
        assert call(info, "/instance")["instance_id"] == info["instance_id"]
    finally:
        if duplicate and duplicate.poll() is None:
            duplicate.terminate()
            duplicate.wait(timeout=5)
        if proc.poll() is None:
            call(info, "/system/shutdown", {"confirmed_stop_running": False})
            proc.wait(timeout=10)


def test_matching_token_and_identity_from_other_data_directory_is_rejected(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    proc = launch(first, "17843:17852")
    try:
        info = wait_instance(first)
        path = second / "runtime/instance.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(info), encoding="utf-8")
        assert find_existing_instance(second, ports=[info["port"]]) is None
    finally:
        if proc.poll() is None:
            call(info, "/system/shutdown", {"confirmed_stop_running": False})
            proc.wait(timeout=10)


def test_startup_readiness_does_not_depend_on_instance_file(tmp_path):
    import socket
    import sys
    import time
    import urllib.request

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    code = """
import sys
from pathlib import Path
import app.launcher as launcher
original = launcher.write_json
def write_then_remove(path, value):
    original(path, value)
    Path(path).unlink()
launcher.write_json = write_then_remove
launcher.start_or_open(Path(sys.argv[1]), False, range(int(sys.argv[2]), int(sys.argv[2])+1))
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path), str(port)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    info = None
    try:
        deadline = time.monotonic() + 13
        ready = False
        while time.monotonic() < deadline:
            log = tmp_path / "logs/service.log"
            if log.exists() and "工作台已就绪" in log.read_text(encoding="utf-8"):
                ready = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        assert ready, (
            "A service that answers its own handshake must not fail because metadata disappeared."
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        bootstrap = json.load(
            opener.open(f"http://127.0.0.1:{port}/api/v1/bootstrap", timeout=2)
        )
        info = {"port": port, **bootstrap}
        assert call(info, "/instance")["instance_id"] == bootstrap["instance_id"]
    finally:
        if proc.poll() is None and info:
            call(info, "/system/shutdown", {"confirmed_stop_running": False})
            proc.wait(timeout=10)
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
