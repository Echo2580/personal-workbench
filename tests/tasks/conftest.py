"""pytest 全局防复发配置（T13 Part B）。

默认阻断一切对**外部域名**的真实网络调用（httpx 同步/异步传输层 + urllib），
避免再出现 T12 那种"未注入 mock 就直连真实模型"的意外计费。

- 放行方式：环境变量 ``SNAP2TODO_ALLOW_REAL_CALLS=1``（仅限任务单授权的真实调用轮次）。
- 本地地址（127.0.0.1 / localhost / ::1 / testserver / 0.0.0.0）不受影响。
- ``TestClient`` 走 ``ASGITransport``，根本不经过 ``HTTPTransport``，因此不会被误伤
  （由 ``tests/test_services_extraction.py`` 的回归用例断言）。
"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import httpx
import pytest

# 移植说明：本文件来自源项目 tests/conftest.py，随测试套件一并迁移到
# wb/tests/tasks/。app.* 导入已改写为 app.modules.tasks.*；对外网络拦截逻辑
# 保持原样。此处把本目录插入 sys.path，保证同目录的 tasks_test_app
# （create_app 的 / 与 /static 包装）在任意调用方式下都可导入。
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

ALLOW_ENV = "SNAP2TODO_ALLOW_REAL_CALLS"

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "testserver", "0.0.0.0"})


def _is_external(url: object) -> bool:
    try:
        parsed = httpx.URL(str(url))
    except Exception:  # noqa: BLE001 - 解析不了的按外部处理
        return True
    host = (parsed.host or "").lower()
    return host not in _LOCAL_HOSTS


def _blocked(target: object) -> RuntimeError:
    return RuntimeError(
        f"测试默认禁止对外网络调用（{target}）。"
        f"只有授权的真实调用轮次才设置 {ALLOW_ENV}=1；其余情况请注入 mock 模型。"
    )


@pytest.fixture(autouse=True)
def block_real_outbound_calls(monkeypatch):
    """默认拦截对外网络；``SNAP2TODO_ALLOW_REAL_CALLS=1`` 时整体放行。"""
    if os.environ.get(ALLOW_ENV) == "1":
        return

    real_handle = httpx.HTTPTransport.handle_request

    def guarded_handle(self, request):
        if _is_external(request.url):
            raise _blocked(request.url.host)
        return real_handle(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_handle)

    real_async_handle = httpx.AsyncHTTPTransport.handle_async_request

    async def guarded_async_handle(self, request):
        if _is_external(request.url):
            raise _blocked(request.url.host)
        return await real_async_handle(self, request)

    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", guarded_async_handle
    )

    real_urlopen = urllib.request.urlopen

    def guarded_urlopen(url, *args, **kwargs):
        target = getattr(url, "full_url", None) or str(url)
        if _is_external(target):
            raise _blocked(target)
        return real_urlopen(url, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", guarded_urlopen)
