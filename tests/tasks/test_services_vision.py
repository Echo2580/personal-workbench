"""T12 视觉提取：适配器请求形状、失败分型、提示词约束、图片提取服务。

全部为构造样本；真实 DeepSeek 调用在 协作/证据/T12/real_calls.py（计数闸门），
不在 pytest 中发生。
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import uuid
import zlib
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.tasks.domain import DraftSet
from app.modules.tasks.services import model_adapter
from app.modules.tasks.services.extraction import DraftValidationError, run_image_extraction
from app.modules.tasks.services.model_adapter import (
    IMAGE_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    VISION_MODEL,
    DeepSeekExtractionModel,
    MockExtractionModel,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
)


SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=SHANGHAI)


def make_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


PNG = make_png()
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

DRAFT_ONE = {
    "title": "交实验报告",
    "startTime": None,
    "dueTime": {
        "rawExpression": "10月20日10:00",
        "precision": "datetime",
        "resolvedValue": "2026-10-20T10:00:00+08:00",
        "status": "resolved",
    },
    "requirements": ["打印装订"],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "10月20日10:00前把实验报告",
}

DRAFT_TWO = {
    "title": "在线提交周报",
    "startTime": None,
    "dueTime": None,
    "requirements": [],
    "applicability": {"text": "仅限本班同学", "status": "needs_confirmation"},
    "sourceExcerpt": "在线提交周报",
}


# --------------------------------------------------------------------------- #
# httpx 桩：捕获请求体，不发网络
# --------------------------------------------------------------------------- #


class _StubResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _StubClient:
    def __init__(self, recorder: dict, response: _StubResponse):
        self._recorder = recorder
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def post(self, url, headers=None, json=None):
        self._recorder["url"] = url
        self._recorder["headers"] = dict(headers or {})
        self._recorder["json"] = json
        return self._response


def stub_http(monkeypatch, response: _StubResponse) -> dict:
    recorder: dict = {}
    monkeypatch.setattr(
        model_adapter.httpx,
        "Client",
        lambda timeout=None: _StubClient(recorder, response),
    )
    recorder["timeout"] = None
    return recorder


def ok_response(content: str = '{"tasks": []}') -> _StubResponse:
    return _StubResponse(200, {"choices": [{"message": {"content": content}}]})


def vision_call(adapter: DeepSeekExtractionModel, data: bytes = PNG, ct: str = "image/png",
                message_date: str | None = "2026-10-16"):
    return adapter.extract_drafts_from_image(data, ct, message_date)


# --------------------------------------------------------------------------- #
# 1. 请求形状：模型分流 + data URL base64
# --------------------------------------------------------------------------- #


def test_vision_uses_deepseek_flash_and_base64_data_url(monkeypatch):
    recorder = stub_http(monkeypatch, ok_response())
    adapter = DeepSeekExtractionModel(api_key="sk-test-fake")

    vision_call(adapter, PNG, "image/png")

    body = recorder["json"]
    assert body["model"] == "deepseek-flash"
    assert VISION_MODEL == "deepseek-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0
    assert body["stream"] is False

    system, user = body["messages"]
    assert system["role"] == "system" and system["content"] == IMAGE_SYSTEM_PROMPT
    assert user["role"] == "user"
    text_part, image_part = user["content"]
    assert text_part["type"] == "text"
    assert "2026-10-16" in text_part["text"]
    assert image_part["type"] == "image_url"
    data_url = image_part["image_url"]["url"]
    assert data_url.startswith("data:image/png;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == PNG


def test_vision_jpeg_uses_jpeg_mime(monkeypatch):
    recorder = stub_http(monkeypatch, ok_response())

    vision_call(DeepSeekExtractionModel(api_key="sk-test-fake"), JPEG, "image/jpeg")

    data_url = recorder["json"]["messages"][1]["content"][1]["image_url"]["url"]
    assert data_url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == JPEG


def test_text_extraction_keeps_deepseek_chat(monkeypatch):
    recorder = stub_http(monkeypatch, ok_response())

    DeepSeekExtractionModel(api_key="sk-test-fake").extract_drafts("请交报告", None)

    body = recorder["json"]
    assert body["model"] == "deepseek-flash"
    assert isinstance(body["messages"][1]["content"], str)


def test_vision_message_date_null_is_passed_through(monkeypatch):
    recorder = stub_http(monkeypatch, ok_response())

    vision_call(DeepSeekExtractionModel(api_key="sk-test-fake"), PNG, "image/png", None)

    assert "未知" in recorder["json"]["messages"][1]["content"][0]["text"]


def test_adapter_declares_both_models():
    adapter = DeepSeekExtractionModel()
    assert adapter.model == "deepseek-flash"
    assert adapter.vision_model == "deepseek-flash"
    assert adapter.timeout > 0


def test_vision_parses_tasks_array(monkeypatch):
    payload = ok_response(json.dumps({"tasks": [DRAFT_ONE, DRAFT_TWO]}, ensure_ascii=False))
    stub_http(monkeypatch, payload)

    result = vision_call(DeepSeekExtractionModel(api_key="sk-test-fake"))

    assert [d["title"] for d in result.drafts] == ["交实验报告", "在线提交周报"]


# --------------------------------------------------------------------------- #
# 2. 失败分型与密钥零泄漏
# --------------------------------------------------------------------------- #


def test_vision_missing_credential_is_model_unavailable():
    adapter = DeepSeekExtractionModel(api_key="")

    with pytest.raises(ModelUnavailableError) as excinfo:
        vision_call(adapter)

    message = str(excinfo.value)
    assert "DEEPSEEK_API_KEY" in message
    assert "sk-" not in message


def test_vision_timeout_maps_to_model_timeout(monkeypatch):
    def boom(self, url, headers=None, json=None):
        raise model_adapter.httpx.TimeoutException("timeout")

    monkeypatch.setattr(_StubClient, "post", boom)
    monkeypatch.setattr(
        model_adapter.httpx, "Client", lambda timeout=None: _StubClient({}, ok_response())
    )

    with pytest.raises(ModelTimeoutError):
        vision_call(DeepSeekExtractionModel(api_key="sk-test-fake"))


@pytest.mark.parametrize("status", [401, 429, 500])
def test_vision_http_error_maps_to_unavailable(monkeypatch, status):
    stub_http(monkeypatch, _StubResponse(status, {"error": "nope"}))

    with pytest.raises(ModelUnavailableError) as excinfo:
        vision_call(DeepSeekExtractionModel(api_key="sk-test-fake"))

    assert "sk-test-fake" not in str(excinfo.value)


def test_vision_broken_json_maps_to_output_invalid(monkeypatch):
    stub_http(monkeypatch, ok_response("{not json"))

    with pytest.raises(ModelOutputInvalidError):
        vision_call(DeepSeekExtractionModel(api_key="sk-test-fake"))


def test_vision_missing_tasks_key_maps_to_output_invalid(monkeypatch):
    stub_http(monkeypatch, ok_response('{"drafts": []}'))

    with pytest.raises(ModelOutputInvalidError):
        vision_call(DeepSeekExtractionModel(api_key="sk-test-fake"))


def test_credential_value_never_in_request_body(monkeypatch):
    recorder = stub_http(monkeypatch, ok_response())
    secret = "sk-very-secret-value-123456"

    vision_call(DeepSeekExtractionModel(api_key=secret))

    assert recorder["headers"]["Authorization"] == f"Bearer {secret}"
    assert secret not in json.dumps(recorder["json"], ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 3. 提示词约束（文字版同步 + 视觉版新写）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT, IMAGE_SYSTEM_PROMPT])
def test_prompts_constrain_applicability_combinations(prompt):
    assert "not_stated" in prompt
    assert "applicability" in prompt
    # not_stated ⇒ text 必须为 null
    assert "text 必须为 null" in prompt or "text=null" in prompt
    # 非 not_stated ⇒ text 非空
    assert "needs_confirmation" in prompt
    assert "非空" in prompt


def test_vision_prompt_forbids_fabrication_and_requires_verbatim_excerpt():
    assert "不要编造" in IMAGE_SYSTEM_PROMPT or "不臆造" in IMAGE_SYSTEM_PROMPT
    assert "逐字" in IMAGE_SYSTEM_PROMPT
    assert "tasks" in IMAGE_SYSTEM_PROMPT


def test_vision_prompt_is_distinct_from_text_prompt():
    assert IMAGE_SYSTEM_PROMPT != SYSTEM_PROMPT
    assert "截图" in IMAGE_SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# 4. mock 图片入口
# --------------------------------------------------------------------------- #


def test_mock_image_entry_returns_image_drafts_and_records_calls():
    model = MockExtractionModel(drafts=[DRAFT_ONE], image_drafts=[DRAFT_TWO])

    result = model.extract_drafts_from_image(PNG, "image/png", "2026-10-16")

    assert [d["title"] for d in result.drafts] == ["在线提交周报"]
    assert model.image_calls == [("image/png", len(PNG), "2026-10-16")]
    assert model.calls == []  # 图片入口不误记到文字调用
    assert model.extract_drafts("文本", None).drafts[0]["title"] == "交实验报告"


def test_mock_image_entry_defaults_to_drafts_when_image_drafts_absent():
    model = MockExtractionModel(drafts=[DRAFT_ONE])

    result = model.extract_drafts_from_image(PNG, "image/png", None)

    assert [d["title"] for d in result.drafts] == ["交实验报告"]
    assert model.image_calls == [("image/png", len(PNG), None)]


def test_mock_image_entry_raises_preset_error():
    model = MockExtractionModel(error=ModelUnavailableError("服务不可用"))

    with pytest.raises(ModelUnavailableError):
        model.extract_drafts_from_image(PNG, "image/png", None)


# --------------------------------------------------------------------------- #
# 5. 图片提取服务：DraftSet 形状与缓存条目
# --------------------------------------------------------------------------- #


def _run(model, *, data: bytes = PNG, ct: str = "image/png",
         message_date: str | None = "2026-10-16", file_name: str | None = "shot.png"):
    source_id = str(uuid.uuid4())
    extension = "png" if ct == "image/png" else "jpg"
    return run_image_extraction(
        model,
        image_bytes=data,
        content_type=ct,
        message_date=message_date,
        now=NOW,
        source_id=source_id,
        relative_path=f"data/sources/{source_id}.{extension}",
        content_sha256=hashlib.sha256(data).hexdigest(),
        file_name=file_name,
    )


def test_run_image_extraction_zero_tasks_is_no_tasks():
    model = MockExtractionModel(image_drafts=[])

    draft_set, entry = _run(model)

    assert isinstance(draft_set, DraftSet)
    assert draft_set.status == "no_tasks"
    dumped = draft_set.model_dump(mode="json", by_alias=True)
    assert set(dumped) == {"draftSetId", "source", "status", "drafts"}
    assert dumped["drafts"] == []
    assert set(dumped["source"]) == {
        "id", "kind", "mimeType", "fileName", "messageDate", "importedAt", "contentSha256",
    }
    assert dumped["source"]["kind"] == "image"
    assert dumped["source"]["mimeType"] == "image/png"
    assert dumped["source"]["fileName"] == "shot.png"
    assert dumped["source"]["messageDate"] == "2026-10-16"
    assert "relativePath" not in dumped["source"]
    assert "originalText" not in dumped["source"]
    assert entry.drafts == []
    assert entry.source["originalText"] is None
    assert model.image_calls == [("image/png", len(PNG), "2026-10-16")]


def test_run_image_extraction_review_status_and_entry_shape():
    model = MockExtractionModel(image_drafts=[DRAFT_ONE, DRAFT_TWO])

    draft_set, entry = _run(model)

    dumped = draft_set.model_dump(mode="json", by_alias=True)
    assert dumped["status"] == "review"
    assert len(dumped["drafts"]) == 2
    assert {d["sourceId"] for d in dumped["drafts"]} == {dumped["source"]["id"]}
    assert dumped["drafts"][0]["dueTime"]["timeZone"] == "Asia/Shanghai"
    assert dumped["drafts"][0]["reminder"]["mode"] == "none"
    assert len(entry.drafts) == 2
    # 缓存条目持有九键 Source（含 relativePath），与确认链路契约一致
    assert set(entry.source) == {
        "id", "kind", "originalText", "relativePath", "mimeType", "fileName",
        "messageDate", "importedAt", "contentSha256",
    }
    assert entry.source["relativePath"].startswith("data/sources/")
    assert entry.source["kind"] == "image"
    assert entry.source["originalText"] is None


def test_run_image_extraction_rejects_invalid_draft():
    model = MockExtractionModel(image_drafts=[{**DRAFT_ONE, "title": "   "}])

    with pytest.raises(DraftValidationError) as excinfo:
        _run(model)

    assert excinfo.value.index == 0


def test_run_image_extraction_forces_server_owned_fields():
    polluted = {
        **DRAFT_ONE,
        "id": "99999999-9999-4999-8999-999999999999",
        "sourceId": "88888888-8888-4888-8888-888888888888",
        "reviewIssues": [{"code": "source_excerpt_missing", "field": "sourceExcerpt",
                          "message": "伪造"}],
        "reminder": {"mode": "manual", "requestedAt": "2026-10-20T09:00:00+08:00",
                     "scheduledAt": "2026-10-20T09:00:00+08:00", "relativeTo": None,
                     "offsetMinutes": None, "state": "scheduled", "acknowledgedAt": None,
                     "revision": "77777777-7777-4777-8777-777777777777"},
    }
    model = MockExtractionModel(image_drafts=[polluted])

    draft_set, _ = _run(model)

    draft = draft_set.model_dump(mode="json", by_alias=True)["drafts"][0]
    assert draft["id"] != polluted["id"]
    assert draft["sourceId"] != polluted["sourceId"]
    assert draft["reminder"]["mode"] == "none"
    assert draft["reviewIssues"] == []


def test_run_image_extraction_propagates_model_errors():
    model = MockExtractionModel(error=ModelTimeoutError("超时"))

    with pytest.raises(ModelTimeoutError):
        _run(model)
