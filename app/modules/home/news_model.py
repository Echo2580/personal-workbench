"""世界快讯的 AI 筛选器：只从真实标题中挑选并写一句话解读，禁止编造事实。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

import httpx

CREDENTIAL_ENV_VAR = "DEEPSEEK_API_KEY"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_TIMEOUT_SECONDS = 40.0

CURATOR_PROMPT = """你是个人工作台的「世界快讯」编辑。用户会给你一份真实的新闻标题列表（带编号、来源、分类）。
你的任务：从中挑出最值得了解的 5 条（优先国际要闻、重大科技与 AI 进展、教育/社会重大变化，兼顾多样性），
并为每条写一句中文解读。

严格遵守：
- 只能使用列表里已有的新闻，不得新增、不得改写标题、不得编造列表中没有的事件、数字或人物；
- 解读只做「为什么值得关注/它意味着什么」的简短说明，不超过 40 字，不得引入标题之外的猜测性事实；
- 只输出 JSON 对象：{"picks":[{"index":1,"summary":"一句话解读"}]}，不要输出任何其他文字。"""


def _read_windows_user_variable(name: str) -> str | None:
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


@dataclass
class DeepSeekNewsCurator:
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def select(self, items, count: int = 5):
        key = resolve_api_key()
        if not key:
            raise RuntimeError("未配置模型密钥")
        lines = [
            f"{index}. [{item.get('category') or '资讯'}] {item['title']} —— {item.get('source') or ''}"
            for index, item in enumerate(items, start=1)
        ]
        user_content = "新闻列表：\n" + "\n".join(lines) + f"\n\n请挑选 {count} 条并输出 JSON。"
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": CURATOR_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2000,
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("新闻筛选模型不可用") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"新闻筛选模型返回 HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("新闻筛选结果无法解析") from exc
        return _parse_picks(content)


def _parse_picks(content: str):
    text = (content or "").strip()
    if "```" in text:
        text = text.split("```")[1] if len(text.split("```")) > 1 else text
        text = text.removeprefix("json").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("新闻筛选结果不是 JSON")
    data = json.loads(text[start : end + 1])
    picks = data.get("picks")
    if not isinstance(picks, list) or not picks:
        raise RuntimeError("新闻筛选结果为空")
    return picks


@dataclass
class MockNewsCurator:
    """测试用：按固定索引返回，或抛错。"""

    indexes: list[int] = field(default_factory=lambda: [1, 3, 5])
    summaries: list[str] = field(default_factory=lambda: ["值得关注。", "值得关注。", "值得关注。"])
    error: Exception | None = None
    calls: list[int] = field(default_factory=list)

    def select(self, items, count: int = 5):
        self.calls.append(len(items))
        if self.error is not None:
            raise self.error
        picks = []
        for position, index in enumerate(self.indexes[:count]):
            summary = self.summaries[position] if position < len(self.summaries) else "值得关注。"
            picks.append({"index": index, "summary": summary})
        return picks
