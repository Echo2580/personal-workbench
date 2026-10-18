"""Extraction model adapters (T07).

Credential handling (D-016): the API key is read **only inside this module**,
never logged, never placed in exception messages, HTTP responses, evidence
files or reports. Only the variable name may appear anywhere in the codebase.

Read order:
  1. ``os.environ["DEEPSEEK_API_KEY"]``
  2. Windows fallback: ``HKCU\\Environment`` (already-running host processes do
     not see user-level variables set after they started)
  3. unavailable → ModelUnavailableError (mapped to 503 by the API layer)
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


CREDENTIAL_ENV_VAR = "DEEPSEEK_API_KEY"

DEFAULT_MODEL = "deepseek-flash"
# D-022：截图链路走 deepseek-flash（DeepSeek-V4.1-Flash，input_modalities 含 image）
VISION_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT_SECONDS = 30.0

_IMAGE_MIMES = ("image/png", "image/jpeg")


class ModelUnavailableError(Exception):
    """模型服务不可用（含凭据缺失）→ 503 model_unavailable。"""


class ModelTimeoutError(Exception):
    """模型调用超时 → 504 extraction_timeout。"""


class ModelOutputInvalidError(Exception):
    """模型输出不可解析 → 502 model_output_invalid。"""


@dataclass
class ModelResult:
    """模型返回的草稿内容（camelCase，仅内容字段；身份/状态由服务端生成）。"""

    drafts: list[dict[str, Any]] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 期 3：长期任务规划模型（GoalPlanningModel）
# --------------------------------------------------------------------------- #


@dataclass
class GoalPlanningRequest:
    """一次规划轮次的完整模型输入（目标 + 区间 + 容量 + 不可用日 + 已有任务）。"""

    goal_id: str
    title: str
    description: str | None
    constraints: list[str]
    start_date: str
    target_date: str
    daily_capacity: int
    window_start: str
    window_end: str
    # 需要补齐的自然日（YYYY-MM-DD，已排除已有任务日与不可用日）
    gap_dates: list[str]
    # 区间内已有任务（供模型避开/衔接）：[{"date": "YYYY-MM-DD", "title": "..."}]
    existing_tasks: list[dict[str, str]]
    unavailable_dates: list[str]


@dataclass
class GoalPlanResult:
    """模型返回的规划建议（不写库；由用户在确认保存时落库）。"""

    target_date: str | None = None
    tasks: list[dict[str, Any]] = field(default_factory=list)


class GoalPlanningModel(Protocol):
    def plan_goal(self, request: GoalPlanningRequest) -> GoalPlanResult: ...


class ExtractionModel(Protocol):
    def extract_drafts(
        self, original_text: str, message_date: str | None
    ) -> ModelResult: ...


class ImageExtractionModel(Protocol):
    """图片入口协议（T12，D-022）：适配器按这份签名接收原始图片字节。"""

    def extract_drafts_from_image(
        self, image_bytes: bytes, content_type: str, message_date: str | None
    ) -> ModelResult: ...


def build_image_data_url(image_bytes: bytes, content_type: str) -> str:
    """把原始图片字节编成 chat completions 可接收的 base64 data URL（D-022）。

    编码在调用方（API 层）的锁外流程中完成；本函数只做纯内存转换，不产生 IO。
    """
    if content_type not in _IMAGE_MIMES:
        raise ValueError(f"unsupported image content type: {content_type}")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


# --------------------------------------------------------------------------- #
# credential reading
# --------------------------------------------------------------------------- #


def _read_windows_user_variable(name: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
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
    stripped = raw.strip()
    return stripped or None


def read_api_key() -> str | None:
    """Return the credential, or None. The value is never logged."""
    value = os.environ.get(CREDENTIAL_ENV_VAR)
    if value and value.strip():
        return value.strip()
    return _read_windows_user_variable(CREDENTIAL_ENV_VAR)


def credential_available() -> bool:
    return read_api_key() is not None


# --------------------------------------------------------------------------- #
# DeepSeek adapter
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """你是把中文通知整理成待办事项的抽取器。
只输出一个 JSON 对象，格式为 {"tasks": [ ... ]}，不要输出任何其他文字。
每个任务对象必须且只能包含以下键：
  title          字符串，非空，事项标题
  startTime      开始时间或 null
  dueTime        截止时间或 null
  requirements   字符串数组，原文中的要求（材料、地点、格式等），没有则为 []
  applicability  适用条件对象 {"text": string|null, "status": "not_stated"|"needs_confirmation"}
  sourceExcerpt  该任务对应的原文片段，无法可靠引用时为 null
时间对象（startTime/dueTime）非 null 时必须且只能包含：
  rawExpression  原文中的时间片段
  precision      "datetime" | "date" | "day_part" | "relative" | "unknown"
  resolvedValue  能唯一确定时：datetime 用带 +08:00 的 RFC 3339，date 用 YYYY-MM-DD；否则 null
  status         "resolved" | "needs_confirmation"
规则：
- 原文没有明确时间就不要编造，不要用当前时间或导入时间推算。
- 原文给出明确的日期和钟点时，必须自动填写对应时间，不能仅抄进 requirements 或保守标为待确认。
- 开会、集合、活动开始的时间填 startTime；“之前提交、截止、最晚”的时间填 dueTime；同时给出时分别保留。
- 已提供消息日期时，缺少年份的月日采用消息日期所在年份；仅给钟点时采用消息日期；“明天、后天、下周几”可唯一换算时必须填 resolvedValue 并设 status="resolved"。
- 只有日期没有钟点时用 precision="date"，不要补成午夜。
- 日期可确定但只写“上午/下午/晚上”时，也应自动填写 precision="date" 的具体日期，rawExpression 保留完整时段原文，不要因缺少钟点而把整个日期留空；真正写“日期待定、某天”等仍待确认。
- "周五""明天上午"等相对或模糊表达无法唯一确定时：status="needs_confirmation"，resolvedValue=null。
- applicability 与 text 必须匹配：status="not_stated" 时 text 必须为 null；status 非 "not_stated"（含 "needs_confirmation"）时 text 必须是非空字符串，且只能写原文中的适用条件。
- 不要编造原文没有的要求或引文；无法引用时 sourceExcerpt 用 null。
- 通知里没有可执行的待办事项时返回 {"tasks": []}。"""


IMAGE_SYSTEM_PROMPT = """你是把中文截图（群通知、学校/教务通知、日程消息等）中的待办事项抽取成任务草稿的抽取器。
只依据图片中清晰可见的文字判断；看不清、被遮挡或图中未出现的内容一律不要编造。
只输出一个 JSON 对象，格式为 {"tasks": [ ... ]}，不要输出任何其他文字。
每个任务对象必须且只能包含以下键：
  title          字符串，非空，事项标题（用图中原意概括，不要加入图中没有的信息）
  startTime      开始时间或 null
  dueTime        截止时间或 null
  requirements   字符串数组，图中明确写出的要求（材料、地点、格式、提交对象等），没有则为 []
  applicability  适用条件对象 {"text": string|null, "status": "not_stated"|"needs_confirmation"}
  sourceExcerpt  该任务对应的图中原文片段（逐字引用），无法可靠引用时为 null
时间对象（startTime/dueTime）非 null 时必须且只能包含：
  rawExpression  图中原文的时间片段（逐字引用，不要改写）
  precision      "datetime" | "date" | "day_part" | "relative" | "unknown"
  resolvedValue  能唯一确定时：datetime 用带 +08:00 的 RFC 3339，date 用 YYYY-MM-DD；否则 null
  status         "resolved" | "needs_confirmation"
规则：
- 图片里没有明确时间就不要编造，不要用截图时间、导入时间或"今天"推算。
- 图片给出明确的日期和钟点时，必须自动填写对应时间，不能仅抄进 requirements 或保守标为待确认。
- 开会、集合、活动开始的时间填 startTime；“之前提交、截止、最晚”的时间填 dueTime；同时给出时分别保留。
- 已提供消息日期时，缺少年份的月日采用消息日期所在年份；仅给钟点时采用消息日期；可唯一确定的时间必须 resolved。
- 只有日期没有钟点时用 precision="date"，不要补成午夜。
- 日期可确定但只写“上午/下午/晚上”时，也应自动填写 precision="date" 的具体日期，rawExpression 保留完整时段原文，不要因缺少钟点而把整个日期留空；真正写“日期待定、某天”等仍待确认。
- "下周一""明天上午""从今晚开始"等相对表达：以对话里给出的消息日期为基准，能唯一确定则 resolved 并填 resolvedValue；不能确定时 status="needs_confirmation"，resolvedValue=null。
- applicability 与 text 必须匹配：status="not_stated" 时 text 必须为 null；status 非 "not_stated"（含 "needs_confirmation"）时 text 必须是非空字符串，且只能写图中可见的适用条件。
- requirements 与 sourceExcerpt 只能来自图中可见文字，不要编造；无法逐字引用时 sourceExcerpt 用 null。
- 截图里有互不相关的多件事时分别成条；同一件事的多项要求不要拆成多条。
- 截图里没有可执行的待办事项（纯寒暄、纯告知且无行动要求）时返回 {"tasks": []}。"""


def _build_user_message(original_text: str, message_date: str | None) -> str:
    date_line = message_date if message_date else "未知"
    return (
        f"消息日期（用于解释相对日期，未知则为 null）：{date_line}\n"
        f"通知原文：\n{original_text}"
    )


PLANNING_SYSTEM_PROMPT = """你是长期目标的计划排期助手。
只输出一个 JSON 对象，格式为 {"targetDate": "YYYY-MM-DD"|null, "tasks": [ ... ]}，不要输出任何其他文字。
- targetDate：若原目标日期明显不可行，可给出更合理的目标完成日期；否则为 null。
- tasks：需要补进空缺自然日的任务，按 plannedDate 升序。每个任务对象必须且只能包含：
  plannedDate    YYYY-MM-DD，必须落在「需要补齐的自然日」清单内；**不得省略、不得为 null**（缺少可用日期的任务会被整条丢弃）
  title          字符串，非空，具体可执行的当日任务
  startTime      开始时间或 null
  dueTime        截止时间或 null
  requirements   字符串数组，没有则为 []
时间对象（startTime/dueTime）非 null 时必须且只能包含：
  rawExpression  时间表述
  precision      "datetime" | "date" | "day_part" | "relative" | "unknown"
  resolvedValue  能唯一确定时：datetime 用带 +08:00 的 RFC 3339，date 用 YYYY-MM-DD；否则 null
  status         "resolved" | "needs_confirmation"
规则：
- 每条任务都必须给出 plannedDate；即使不知道具体做什么/几点做，也必须先给出 plannedDate，不得省略或用 null 代替。
- 只能把任务安排在「需要补齐的自然日」清单中的日期，不得安排在清单之外的日期。
- 每个自然日安排的任务数不得超过每日容量。
- 结合目标标题/说明、约束、已有任务与剩余天数排期；任务内容必须服务于目标，不要编造无关任务。
- 必须尊重不可用日期，不得在其上安排任务。
- 时间必须是真实日历日；给出明确日期时必须 resolved 并填写 resolvedValue，不要编造时间。
- 没有可补日期或无需安排时返回 {"targetDate": null, "tasks": []}。"""


def _build_planning_user_message(request: "GoalPlanningRequest") -> str:
    lines = [
        f"目标标题：{request.title}",
        f"目标说明：{request.description or '无'}",
        f"开始日期：{request.start_date}",
        f"目标完成日期：{request.target_date}",
        f"每日容量（每天最多任务数）：{request.daily_capacity}",
        f"规划区间：{request.window_start} ~ {request.window_end}",
        "需要补齐的自然日（只能安排在这些日期）："
        + ("、".join(request.gap_dates) if request.gap_dates else "无"),
    ]
    if request.unavailable_dates:
        lines.append("不可用日期（不得安排）：" + "、".join(request.unavailable_dates))
    if request.constraints:
        lines.append("约束：" + "；".join(request.constraints))
    if request.existing_tasks:
        lines.append(
            "区间内已有任务（日期/标题）："
            + "；".join(
                f"{item['date']} {item['title']}" for item in request.existing_tasks
            )
        )
    return "\n".join(lines)


def _post_chat_json(
    *,
    base_url: str,
    timeout: float,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
) -> Any:
    """发一次 chat completions 并返回 message.content 解析后的 JSON。

    提取/视觉/规划三条链路共用同一 HTTP 客户端与错误分类：
    超时 → ModelTimeoutError；不可达/HTTP ≥400 → ModelUnavailableError；
    内容不是合法 JSON → ModelOutputInvalidError。凭据只进请求头，不进日志/消息。
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    request_body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
    except httpx.TimeoutException as exc:
        raise ModelTimeoutError("模型调用超时。") from exc
    except httpx.HTTPError as exc:
        # 异常文本可能含 URL，但不含请求头/密钥
        raise ModelUnavailableError("模型服务不可达。") from exc

    if response.status_code >= 400:
        raise ModelUnavailableError(f"模型服务返回 HTTP {response.status_code}。")

    try:
        envelope = response.json()
        content = envelope["choices"][0]["message"]["content"]
        return json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ModelOutputInvalidError("模型输出不是可解析的 JSON。") from exc


@dataclass
class DeepSeekExtractionModel:
    """DeepSeek chat/completions 适配器（JSON mode 经 prompt + response_format 约定）。

    文字与图片统一走 DeepSeek-V4.1-Flash（D-022 原选 chat 作文本，2026-10-18 用户决定统一 flash），
    图片以 base64 data URL 传入同一条 chat completions（OpenAI 兼容消息形状）。
    """

    model: str = DEFAULT_MODEL
    vision_model: str = VISION_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    # 仅测试注入使用；正常运行从环境/注册表读取
    api_key: str | None = None

    def _resolve_key(self) -> str:
        key = self.api_key if self.api_key is not None else read_api_key()
        if not key or not key.strip():
            # 消息中只出现变量名，绝不包含值
            raise ModelUnavailableError(
                f"模型凭据不可用（{CREDENTIAL_ENV_VAR} 未配置）。"
            )
        return key.strip()

    def _request(self, model: str, messages: list[dict[str, Any]]) -> ModelResult:
        """发一次 chat completions 并把输出解析成 ModelResult。

        失败分型：超时 → ModelTimeoutError；不可达/HTTP ≥400 → ModelUnavailableError；
        输出不是合法 JSON 或缺 tasks 数组 → ModelOutputInvalidError。
        """
        key = self._resolve_key()
        parsed = _post_chat_json(
            base_url=self.base_url,
            timeout=self.timeout,
            api_key=key,
            model=model,
            messages=messages,
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("tasks"), list):
            raise ModelOutputInvalidError("模型输出缺少 tasks 数组。")

        drafts = [item for item in parsed["tasks"]]
        return ModelResult(drafts=drafts)

    def extract_drafts(
        self, original_text: str, message_date: str | None
    ) -> ModelResult:
        return self._request(
            self.model,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_message(original_text, message_date),
                },
            ],
        )

    def extract_drafts_from_image(
        self, image_bytes: bytes, content_type: str, message_date: str | None
    ) -> ModelResult:
        """图片提取：base64 data URL + 视觉 SYSTEM_PROMPT（D-022）。"""
        date_line = message_date if message_date else "未知"
        return self._request(
            self.vision_model,
            [
                {"role": "system", "content": IMAGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"消息日期（用于解释相对日期，未知则为 null）：{date_line}\n"
                                "请从这张截图中抽取待办事项。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": build_image_data_url(image_bytes, content_type)
                            },
                        },
                    ],
                },
            ],
        )


# --------------------------------------------------------------------------- #
# 期 3：长期任务规划适配器（deepseek-flash）
# --------------------------------------------------------------------------- #


@dataclass
class DeepSeekGoalPlanner:
    """把 plan 型长期任务的目标排期成当日任务草稿。

    与抽取链路共用 ``_post_chat_json``（同一 HTTP 客户端与错误分类），默认模型
    为 ``deepseek-flash``；凭据只在适配器内读取，不进入响应/日志。
    本适配器**不写库**：只返回模型建议，由 API 层决定是否落库。
    """

    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    # 仅测试注入使用；正常运行从环境/注册表读取
    api_key: str | None = None

    def _resolve_key(self) -> str:
        key = self.api_key if self.api_key is not None else read_api_key()
        if not key or not key.strip():
            raise ModelUnavailableError(
                f"模型凭据不可用（{CREDENTIAL_ENV_VAR} 未配置）。"
            )
        return key.strip()

    def plan_goal(self, request: GoalPlanningRequest) -> GoalPlanResult:
        key = self._resolve_key()
        parsed = _post_chat_json(
            base_url=self.base_url,
            timeout=self.timeout,
            api_key=key,
            model=self.model,
            messages=[
                {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_planning_user_message(request),
                },
            ],
        )
        if not isinstance(parsed, dict):
            raise ModelOutputInvalidError("模型输出不是 JSON 对象。")
        tasks = parsed.get("tasks")
        if not isinstance(tasks, list):
            raise ModelOutputInvalidError("模型输出缺少 tasks 数组。")
        target_date = parsed.get("targetDate")
        if target_date is not None and not isinstance(target_date, str):
            raise ModelOutputInvalidError("模型输出的 targetDate 必须是字符串或 null。")
        return GoalPlanResult(target_date=target_date, tasks=list(tasks))


# --------------------------------------------------------------------------- #
# mock adapter (tests / QA injection)
# --------------------------------------------------------------------------- #


@dataclass
class MockExtractionModel:
    """按预设草稿或预设异常返回；记录调用参数供断言。

    图片入口（T12）：``image_drafts`` 为 None 时回落到 ``drafts``，便于 QA 只写一份
    预设就覆盖两条链路；``image_calls`` 记录 (content_type, 字节长度, messageDate)。
    """

    drafts: list[dict[str, Any]] = field(default_factory=list)
    image_drafts: list[dict[str, Any]] | None = None
    error: Exception | None = None
    calls: list[tuple[str, str | None]] = field(default_factory=list)
    image_calls: list[tuple[str, int, str | None]] = field(default_factory=list)

    def extract_drafts(
        self, original_text: str, message_date: str | None
    ) -> ModelResult:
        self.calls.append((original_text, message_date))
        if self.error is not None:
            raise self.error
        # 忠实返回预设内容（非对象项原样返回，交由服务层判定非法）
        return ModelResult(
            drafts=[dict(item) if isinstance(item, dict) else item for item in self.drafts]
        )

    def extract_drafts_from_image(
        self, image_bytes: bytes, content_type: str, message_date: str | None
    ) -> ModelResult:
        self.image_calls.append((content_type, len(image_bytes), message_date))
        if self.error is not None:
            raise self.error
        preset = self.drafts if self.image_drafts is None else self.image_drafts
        return ModelResult(
            drafts=[dict(item) if isinstance(item, dict) else item for item in preset]
        )


@dataclass
class MockGoalPlanner:
    """规划链路测试替身：返回预设规划结果或预设异常，并记录调用输入。

    ``target_date`` 为模型建议的目标日期；``tasks``（或等价的 ``drafts``）为模型
    输出的原始任务列表（服务层负责校验/补空缺/截断）。``result`` 可直接给完整
    的 ``GoalPlanResult`` 以覆盖空结果等场景。
    """

    tasks: list[dict[str, Any]] = field(default_factory=list)
    drafts: list[dict[str, Any]] | None = None
    target_date: str | None = None
    error: Exception | None = None
    result: GoalPlanResult | None = None
    calls: list[GoalPlanningRequest] = field(default_factory=list)

    def plan_goal(self, request: GoalPlanningRequest) -> GoalPlanResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return GoalPlanResult(
                target_date=self.result.target_date,
                tasks=[
                    dict(item) if isinstance(item, dict) else item
                    for item in self.result.tasks
                ],
            )
        preset = self.tasks if self.drafts is None else self.drafts
        return GoalPlanResult(
            target_date=self.target_date,
            tasks=[
                dict(item) if isinstance(item, dict) else item for item in preset
            ],
        )
