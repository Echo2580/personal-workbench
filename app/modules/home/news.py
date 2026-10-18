"""世界快讯：从公开 RSS 抓真实新闻，AI 只做筛选与一句话解读。

设计原则：
- 新闻标题与链接**必须来自真实 RSS**，模型不得生成、补写或修改事实；
- 模型只输出「选中第几条 + 一句话解读」，解析失败或不可用时退回纯标题列表；
- 抓取失败时回退到上一次成功缓存（persisted），不编造内容。
"""

from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

SHANGHAI = timezone(timedelta(hours=8))
FETCH_TIMEOUT = 8.0
MAX_FEED_BYTES = 1_500_000

FEEDS: tuple[dict[str, str], ...] = (
    {"id": "bbc_zh", "name": "BBC 中文", "category": "国际", "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"},
    {"id": "chinanews", "name": "中国新闻网", "category": "要闻", "url": "https://www.chinanews.com.cn/rss/scroll-news.xml"},
    {"id": "jiemian", "name": "界面新闻", "category": "财经", "url": "https://a.jiemian.com/index.php?m=article&a=rss"},
    {"id": "thepaper", "name": "澎湃要闻", "category": "要闻", "url": "https://feedx.net/rss/thepaper.xml"},
    {"id": "infoq", "name": "InfoQ 中文", "category": "科技", "url": "https://www.infoq.cn/feed"},
    {"id": "sspai", "name": "少数派", "category": "数码", "url": "https://sspai.com/feed"},
    {"id": "hackernews", "name": "Hacker News", "category": "科技", "url": "https://hnrss.org/frontpage"},
    {"id": "mit_tr", "name": "MIT Tech Review", "category": "科技", "url": "https://www.technologyreview.com/feed/"},
)

CACHE_TTL_SECONDS = 1800
TAG_RE = re.compile(r"<[^>]+>")

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"fetched_at": 0.0, "items": []}


class NewsError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _home_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "home"


def _clean_title(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(TAG_RE.sub(" ", text).replace("&amp;", "&").split())[:160]


def _clean_url(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        return ""
    return value[:600]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(element: ET.Element, names: tuple[str, ...]) -> str | None:
    for child in element:
        if _local(child.tag) in names:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def _rss_link(element: ET.Element) -> str:
    for child in element:
        if _local(child.tag) != "link":
            continue
        text = (child.text or "").strip()
        if text:
            return text
        href = child.get("href")
        if href:
            return href
    return ""


def _parse_date(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    try:
        return parsedate_to_datetime(value).astimezone(SHANGHAI).isoformat(timespec="minutes")
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(SHANGHAI).isoformat(timespec="minutes")
    except ValueError:
        return ""


def parse_feed(xml_text: str, feed: dict[str, str], limit: int = 12) -> list[dict[str, Any]]:
    """解析 RSS 2.0 / Atom，返回真实条目（不做任何改写）。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    nodes: list[ET.Element] = []
    for node in root.iter():
        local = _local(node.tag)
        if local == "item":
            nodes.append(node)
        elif local == "entry":
            nodes.append(node)
    items: list[dict[str, Any]] = []
    for node in nodes[:limit]:
        title = _clean_title(_child_text(node, ("title",)))
        link = _clean_url(_rss_link(node))
        if not title or not link:
            continue
        published = _parse_date(
            _child_text(node, ("pubDate", "published", "updated", "date"))
        )
        items.append(
            {
                "title": title,
                "url": link,
                "source": feed["name"],
                "category": feed["category"],
                "publishedAt": published,
            }
        )
    return items


def _fetch_feed(feed: dict[str, str]) -> list[dict[str, Any]]:
    try:
        with httpx.Client(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 Workbench/0.1"},
        ) as client:
            response = client.get(feed["url"])
            if response.status_code >= 400:
                return []
            content = response.content[:MAX_FEED_BYTES]
            text = content.decode(response.encoding or "utf-8", errors="replace")
    except (httpx.HTTPError, LookupError, UnicodeError):
        return []
    return parse_feed(text, feed)


def _read_cached_items(data_dir: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        import json

        payload = json.loads((_home_dir(data_dir) / "news.json").read_text(encoding="utf-8"))
        items = payload.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)], str(payload.get("fetchedAt") or "")
    except (FileNotFoundError, ValueError, OSError):
        pass
    return [], ""


def _write_cached_items(data_dir: Path, items: list[dict[str, Any]]) -> str:
    import json

    fetched_at = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    path = _home_dir(data_dir) / "news.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"items": items, "fetchedAt": fetched_at}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return fetched_at


def collect_items(refresh: bool = False) -> tuple[list[dict[str, Any]], bool]:
    """并发抓取所有源；返回 (items, from_cache)。"""
    now = time.time()
    with _cache_lock:
        cached_items = list(_cache["items"])
        fresh_enough = cached_items and not refresh and now - float(_cache["fetched_at"]) < CACHE_TTL_SECONDS
    if fresh_enough:
        return cached_items, True

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_fetch_feed, FEEDS))
    items = [item for group in results for item in group]

    # 去重（同标题）+ 按发布时间倒序 + 限制数量
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = item["title"].casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda item: item.get("publishedAt") or "", reverse=True)
    unique = unique[:40]

    with _cache_lock:
        _cache["items"] = unique
        _cache["fetched_at"] = now
    return unique, False


def _fallback_picks(items: list[dict[str, Any]], count: int = 5) -> list[dict[str, Any]]:
    picks: list[dict[str, Any]] = []
    for item in items[:count]:
        picks.append({**item, "summary": ""})
    return picks


_curated_cache: dict[str, Any] = {"fetched_at": "", "payload": None}
_curated_lock = threading.Lock()


def build_briefing(data_dir: Path, refresh: bool, model: Any) -> dict[str, Any]:
    """返回世界快讯：真实新闻条目标题/链接 + AI 筛选与一句话解读。

    AI 不可用或输出不合法时退回纯标题（aiUsed=false），不会编造内容。
    """
    items, from_memory = collect_items(refresh=refresh)

    if not items:
        persisted, fetched_at = _read_cached_items(data_dir)
        if not persisted:
            raise NewsError("暂时无法获取新闻源，请稍后再试。")
        items = persisted
        from_memory = True
        fetched_at_cached = fetched_at
    else:
        fetched_at_cached = ""

    _ = from_memory
    stamp = fetched_at_cached or _write_cached_items(data_dir, items)

    with _curated_lock:
        cached_payload = _curated_cache["payload"]
        if (
            not refresh
            and cached_payload
            and _curated_cache["fetched_at"] == stamp
        ):
            return {**cached_payload, "cached": True}

    picks: list[dict[str, Any]] = []
    ai_used = False
    ai_error = ""
    if model is not None:
        try:
            picks = curate(items, model)
            ai_used = bool(picks)
        except Exception as exc:  # noqa: BLE001 - AI 失败不影响真实新闻展示
            ai_error = str(exc)
            picks = []
    if not picks:
        picks = _fallback_picks(items)

    payload = {
        "items": picks,
        "fetchedAt": stamp,
        "cached": False,
        "aiUsed": ai_used,
        "aiError": ai_error,
        "sourceCount": len({item["source"] for item in items}),
        "totalFetched": len(items),
    }
    with _curated_lock:
        _curated_cache["fetched_at"] = stamp
        _curated_cache["payload"] = payload
    _write_cached_items(data_dir, items)
    return payload


def curate(items: list[dict[str, Any]], model: Any, count: int = 5) -> list[dict[str, Any]]:
    """让模型从真实标题中挑选并写一句话解读；索引越界/重复一律视为无效。"""
    candidates = items[:24]
    picks = model.select(candidates, count=count)
    if not isinstance(picks, list) or not picks:
        return []
    chosen: list[dict[str, Any]] = []
    used: set[int] = set()
    for pick in picks:
        try:
            index = int(pick["index"])
            summary = str(pick["summary"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if index in used or not 1 <= index <= len(candidates) or not summary:
            continue
        used.add(index)
        chosen.append({**candidates[index - 1], "summary": " ".join(summary.split())[:60]})
        if len(chosen) >= count:
            break
    if len(chosen) < 3:
        return []
    return chosen
