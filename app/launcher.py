"""Hidden production entry; starts one Uvicorn worker without reload."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser
import uvicorn
from .main import create_app
from .core.instance import (
    acquire_instance_mutex,
    find_existing_instance,
    verify_instance,
)
from .core.config_files import resolve_data_dir, write_json
from .modules.projects.models import utcnow


def configure_logging(data_dir):
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        logs / "service.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def bind_port(ports):
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(2048)
            return sock, port
        except OSError:
            sock.close()
    raise RuntimeError("工作台候选端口均被占用。未停止任何其他程序，请释放端口后重试。")


def start_or_open(data_dir=None, open_browser=True, ports=range(17843, 17853)):
    data_dir = resolve_data_dir(data_dir).resolve()
    ports = tuple(ports)
    configure_logging(data_dir)
    ownership = acquire_instance_mutex(data_dir)
    sock = None
    instance_path = data_dir / "runtime" / "instance.json"
    try:
        deadline = time.monotonic() + 10
        while not ownership.owned:
            existing = find_existing_instance(data_dir, ports, deadline=deadline)
            if existing:
                if open_browser:
                    webbrowser.open(f"http://127.0.0.1:{existing['port']}/#/")
                return {"status": "opened", "instance_id": existing["instance_id"]}
            if ownership.acquire():
                break
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "现有工作台尚未就绪，超过 10 秒。请查看本地 service.log。"
                )
            time.sleep(0.1)
        sock, port = bind_port(ports)
        app = create_app(data_dir)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_config=None,
                access_log=False,
                workers=1,
                timeout_graceful_shutdown=5,
            )
        )
        app.state.shutdown_callback = lambda: threading.Timer(
            0.3, lambda: setattr(server, "should_exit", True)
        ).start()
        instance = {
            "pid": os.getpid(),
            "started_at": utcnow(),
            "port": port,
            "instance_id": app.state.instance_id,
            "token": app.state.token,
        }
        write_json(instance_path, instance)
        ready_error = []

        def ready():
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if verify_instance(instance, data_dir):
                    logging.info(
                        "工作台已就绪 port=%d instance=%s",
                        port,
                        instance["instance_id"],
                    )
                    if open_browser:
                        webbrowser.open(f"http://127.0.0.1:{port}/#/")
                    return
                if server.should_exit:
                    return
                time.sleep(0.1)
            ready_error.append("工作台未在 10 秒内就绪，请查看本地 service.log。")
            server.should_exit = True

        watcher = threading.Thread(target=ready, name="startup-readiness", daemon=True)
        watcher.start()
        server.run(sockets=[sock])
        watcher.join(1)
        if ready_error:
            raise RuntimeError(ready_error[0])
        return {"status": "exited", "instance_id": instance["instance_id"]}
    finally:
        if sock:
            sock.close()
        if ownership.owned:
            try:
                instance_path.unlink(missing_ok=True)
            except OSError:
                logging.exception("清理实例文件失败")
        ownership.close()


def main():
    parser = argparse.ArgumentParser(description="个人工作台本机入口")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--ports", default="17843:17852", help="本机端口范围（首:末）")
    args = parser.parse_args()
    try:
        first, last = map(int, args.ports.split(":"))
        if not 1 <= first <= last <= 65535:
            raise ValueError("端口范围无效")
        start_or_open(args.data_dir, not args.no_browser, range(first, last + 1))
        return 0
    except Exception as e:
        logging.exception("工作台启动失败")
        message = (
            f"{e}\n\n日志：{resolve_data_dir(args.data_dir) / 'logs' / 'service.log'}"
        )
        if sys.stderr:
            print(message, file=sys.stderr)
        if not args.no_browser:
            import win32api

            win32api.MessageBox(0, message, "个人工作台启动失败", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
