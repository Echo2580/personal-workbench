"""每日段子的模型实现（DeepSeek flash）与测试用 Mock。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import httpx

from app.modules.home.services import JOKE_PROMPT, JokeModelError

CREDENTIAL_ENV_VAR = "DEEPSEEK_API_KEY"


def _read_windows_user_variable(name: str) -> str | None:
    """从 Windows 用户环境读取（launcher 由快捷方式启动时不一定继承当前进程环境）。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - 非 Windows
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            raw, kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    if not isinstance(raw, str):
        return None
    if kind == getattr(winreg, "REG_EXPAND_SZ", None):
        raw = os.path.expandvars(raw)
    value = raw.strip()
    return value or None


def resolve_api_key() -> str | None:
    return os.environ.get(CREDENTIAL_ENV_VAR, "").strip() or _read_windows_user_variable(CREDENTIAL_ENV_VAR)
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass
class DeepSeekJokeModel:
    """调用 DeepSeek chat completions 生成一条段子。"""

    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def generate(self, now_iso: str) -> str:
        key = resolve_api_key()
        if not key:
            raise JokeModelError("未配置模型密钥，无法生成段子。")
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": JOKE_PROMPT},
                        {"role": "user", "content": f"当前时间：{now_iso}。写一条今天的段子。"},
                    ],
                    "temperature": 1.0,
                    "max_tokens": 2000,
                },
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise JokeModelError("段子生成超时。") from exc
        except httpx.HTTPError as exc:
            raise JokeModelError("段子生成服务不可用。") from exc
        if response.status_code >= 400:
            raise JokeModelError(f"段子生成服务返回 HTTP {response.status_code}。")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise JokeModelError("段子生成结果无法解析。") from exc
        if not isinstance(content, str) or not content.strip():
            raise JokeModelError("段子生成结果为空。")
        return content.strip()


@dataclass
class MockJokeModel:
    """测试用：按预设返回或抛错。"""

    joke: str = "今天在地铁上看见一个人对着手机傻笑，我凑近一看，原来他在看自己的待办清单。"
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def generate(self, now_iso: str) -> str:
        self.calls.append(now_iso)
        if self.error is not None:
            raise self.error
        return self.joke
