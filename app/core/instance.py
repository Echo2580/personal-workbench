"""Single instance per Windows user and data directory; never trust a bare port/PID."""

import hashlib
import json
import os
import logging
import time
import urllib.request
from pathlib import Path
import win32api, win32con, win32event, win32security
from .config_files import read_json


def mutex_name(data_dir):
    process_token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    try:
        sid = win32security.ConvertSidToStringSid(
            win32security.GetTokenInformation(process_token, win32security.TokenUser)[0]
        )
    finally:
        process_token.Close()
    identity = sid + "|" + os.path.normcase(str(Path(data_dir).resolve()))
    return (
        "Local\\PersonalWorkbench."
        + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    )


class InstanceOwnership:
    def __init__(self, data_dir):
        self.handle = win32event.CreateMutex(None, False, mutex_name(data_dir))
        self.owned = False

    def acquire(self):
        if self.owned:
            return True
        self.owned = win32event.WaitForSingleObject(self.handle, 0) in (
            win32event.WAIT_OBJECT_0,
            win32event.WAIT_ABANDONED,
        )
        return self.owned

    def close(self):
        if self.owned:
            win32event.ReleaseMutex(self.handle)
            self.owned = False
        self.handle.Close()


def acquire_instance_mutex(data_dir):
    ownership = InstanceOwnership(data_dir)
    ownership.acquire()
    return ownership


class _NoInstanceRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _instance_json(port, path, token=None):
    headers = {"X-Workbench-Token": token} if token else {}
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1{path}", headers=headers
    )
    # Both cached and recovery handshakes must ignore machine proxy settings.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoInstanceRedirect()
    )
    with opener.open(request, timeout=0.35) as response:
        body = response.read(65537)
    if len(body) > 65536:
        raise ValueError("Instance response exceeds limit")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("Instance response must be an object")
    return result


def verify_instance(instance, data_dir):
    """Authenticate a known live service and check its configured directory."""
    try:
        port, token, identity = (instance[k] for k in ("port", "token", "instance_id"))
        if type(port) is not int or not 1 <= port <= 65535:
            return False
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(identity, str)
            or not identity
        ):
            return False
        if _instance_json(port, "/instance", token).get("instance_id") != identity:
            return False
        actual = _instance_json(port, "/system/about", token).get("data_dir")
        if not isinstance(actual, str) or not Path(actual).is_absolute():
            return False
        return os.path.normcase(str(Path(actual).resolve())) == os.path.normcase(
            str(Path(data_dir).resolve())
        )
    except Exception:
        return False


def find_existing_instance(data_dir, ports=(), *, deadline=None):
    try:
        instance = read_json(Path(data_dir) / "runtime" / "instance.json", {})
    except Exception:
        instance = {}
    if verify_instance(instance, data_dir):
        return instance
    # A missing/stale metadata file must not strand an otherwise healthy owner.
    # Candidate ports alone are never sufficient: validate token, identity AND directory.
    for port in ports:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            bootstrap = _instance_json(port, "/bootstrap")
            candidate = {
                "port": port,
                "token": bootstrap["token"],
                "instance_id": bootstrap["instance_id"],
            }
            if verify_instance(candidate, data_dir):
                logging.warning(
                    "实例记录不可用，已验证服务身份并恢复连接 port=%d instance=%s",
                    port,
                    candidate["instance_id"],
                )
                return candidate
        except Exception:
            continue
    return None
