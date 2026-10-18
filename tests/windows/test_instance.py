import sys, json, time, subprocess, socket, urllib.request
from app.core.instance import find_existing_instance


def wait_instance(path):
    for _ in range(160):
        found = find_existing_instance(path)
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError("服务未在期限内就绪")


def launch(data, ports):
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.launcher",
            "--no-browser",
            "--data-dir",
            str(data),
            "--ports",
            ports,
        ],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def call(info, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{info['port']}/api/v1" + path,
        data=data,
        headers={
            "X-Workbench-Token": info["token"],
            "Origin": f"http://127.0.0.1:{info['port']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)


def test_double_launch_port_conflict_and_shutdown(tmp_path):
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    port = occupied.getsockname()[1]
    occupied.listen()
    proc = launch(tmp_path, f"{port}:{port + 2}")
    try:
        info = wait_instance(tmp_path)
        assert info["port"] != port
        duplicate = launch(tmp_path, f"{port}:{port + 2}")
        # 全量测试并行时进程启动会变慢，给足等待时间（断言不变）。
        assert duplicate.wait(timeout=30) == 0
        assert find_existing_instance(tmp_path)["instance_id"] == info["instance_id"]
        assert proc.poll() is None
        call(info, "/system/shutdown", {"confirmed_stop_running": True})
        assert proc.wait(timeout=20) == 0
    finally:
        occupied.close()
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)


def test_all_ports_occupied_returns_failure_and_no_false_instance(tmp_path):
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    port = occupied.getsockname()[1]
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "instance.json").write_text(
        json.dumps({"port": port, "token": "stale", "instance_id": "wrong"})
    )
    proc = launch(tmp_path, f"{port}:{port}")
    try:
        assert proc.wait(timeout=30) != 0
    finally:
        occupied.close()
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
