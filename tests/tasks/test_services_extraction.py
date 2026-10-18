"""构造样本测试 T07 提取服务层与模型适配器。

所有数据均为构造样本，不代表真实模型结果。真实 DeepSeek 调用仅在本文件
末尾的凭据用例中进行，无凭据时 skip。
"""

from __future__ import annotations

import hashlib
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.tasks.domain import DraftSet
from app.modules.tasks.services.extraction import (
    DraftSetCache,
    DraftValidationError,
    run_extraction,
)
from app.modules.tasks.services.model_adapter import (
    DeepSeekExtractionModel,
    MockExtractionModel,
    ModelOutputInvalidError,
    ModelResult,
    ModelTimeoutError,
    ModelUnavailableError,
    credential_available,
)


SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=SHANGHAI)
TEXT = "请于10月20日10:00前交报告，需打印纸质版。"

DRAFT_ONE = {
    "title": "交报告",
    "startTime": None,
    "dueTime": {
        "rawExpression": "10月20日10:00",
        "precision": "datetime",
        "resolvedValue": "2026-10-20T10:00:00+08:00",
        "status": "resolved",
    },
    "requirements": ["打印纸质版"],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "请于10月20日10:00前交报告",
}

DRAFT_TWO = {
    "title": "交周报",
    "startTime": None,
    "dueTime": None,
    "requirements": [],
    "applicability": {"text": "仅限本班同学", "status": "needs_confirmation"},
    "sourceExcerpt": "另需交周报",
}

DRAFT_UNCERTAIN = {
    "title": "准备材料",
    "startTime": None,
    "dueTime": {
        "rawExpression": "周五前",
        "precision": "relative",
        "resolvedValue": None,
        "status": "needs_confirmation",
    },
    "requirements": [],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": None,
}


def test_mock_adapter_returns_independent_copies_and_records_calls():
    model = MockExtractionModel(drafts=[DRAFT_ONE])

    first = model.extract_drafts(TEXT, None)
    second = model.extract_drafts(TEXT, "2026-10-19")

    assert isinstance(first, ModelResult)
    assert first.drafts[0]["title"] == "交报告"
    # 调用方修改结果不应污染 mock 预设
    first.drafts[0]["title"] = "被改写"
    assert model.extract_drafts(TEXT, None).drafts[0]["title"] == "交报告"
    assert model.calls == [(TEXT, None), (TEXT, "2026-10-19"), (TEXT, None)]
    assert second.drafts[0]["title"] == "交报告"


def test_mock_adapter_raises_preset_error():
    model = MockExtractionModel(error=ModelTimeoutError("超时"))

    with pytest.raises(ModelTimeoutError):
        model.extract_drafts(TEXT, None)


def test_extraction_zero_tasks_is_no_tasks_not_error():
    model = MockExtractionModel(drafts=[])

    draft_set, entry = run_extraction(model, TEXT, None, NOW)

    assert isinstance(draft_set, DraftSet)
    assert draft_set.status == "no_tasks"
    assert draft_set.drafts == []
    dumped = draft_set.model_dump(mode="json", by_alias=True)
    assert dumped["drafts"] == []
    assert set(dumped) == {"draftSetId", "source", "status", "drafts"}
    # 来源仍是完整九键缓存在服务端
    assert set(dumped["source"]) == {
        "id",
        "kind",
        "mimeType",
        "fileName",
        "messageDate",
        "importedAt",
        "contentSha256",
    }
    assert entry.source["originalText"] == TEXT


def test_extraction_one_task_review_status_and_source_fields():
    model = MockExtractionModel(drafts=[DRAFT_ONE])

    draft_set, entry = run_extraction(model, TEXT, "2026-10-19", NOW)

    assert draft_set.status == "review"
    dumped = draft_set.model_dump(mode="json", by_alias=True)
    source = dumped["source"]

    # 服务端生成字段
    assert source["kind"] == "text"
    assert source["mimeType"] == "text/plain; charset=utf-8"
    assert source["fileName"] is None
    assert source["messageDate"] == "2026-10-19"
    assert source["importedAt"] == NOW.isoformat()
    assert source["contentSha256"] == hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
    # 元数据不泄露内部字段
    assert "originalText" not in source
    assert "relativePath" not in source
    # 内部缓存保留原文
    assert entry.source["originalText"] == TEXT
    assert entry.source["relativePath"] is None

    draft = dumped["drafts"][0]
    assert draft["sourceId"] == source["id"]
    assert draft["title"] == "交报告"
    assert draft["dueTime"]["timeZone"] == "Asia/Shanghai"
    assert draft["reminder"]["mode"] == "none"
    assert draft["reminder"]["revision"] is None
    assert draft["reviewIssues"] == []
    # id 为规范小写 UUID
    assert len(draft["id"]) == 36
    assert draft["id"] == draft["id"].lower()


def test_extraction_multiple_tasks_share_one_source():
    model = MockExtractionModel(drafts=[DRAFT_ONE, DRAFT_TWO, DRAFT_UNCERTAIN])

    draft_set, entry = run_extraction(model, TEXT, None, NOW)

    dumped = draft_set.model_dump(mode="json", by_alias=True)
    assert dumped["status"] == "review"
    assert len(dumped["drafts"]) == 3
    source_ids = {d["sourceId"] for d in dumped["drafts"]}
    assert source_ids == {dumped["source"]["id"]}
    draft_ids = [d["id"] for d in dumped["drafts"]]
    assert len(set(draft_ids)) == 3
    assert len(entry.drafts) == 3
    # 待核对时间派生 issue
    uncertain = dumped["drafts"][2]
    assert [i["code"] for i in uncertain["reviewIssues"]] == [
        "time_needs_confirmation",
        "source_excerpt_missing",
    ]


def test_extraction_forces_timezone_and_drops_model_supplied_read_only_keys():
    polluted = {
        **DRAFT_ONE,
        "id": "99999999-9999-4999-8999-999999999999",
        "sourceId": "88888888-8888-4888-8888-888888888888",
        "reviewIssues": [
            {"code": "source_excerpt_missing", "field": "sourceExcerpt", "message": "伪造"}
        ],
        "reminder": {
            "mode": "manual",
            "requestedAt": "2026-10-20T09:00:00+08:00",
            "scheduledAt": "2026-10-20T09:00:00+08:00",
            "relativeTo": None,
            "offsetMinutes": None,
            "state": "scheduled",
            "acknowledgedAt": None,
            "revision": "77777777-7777-4777-8777-777777777777",
        },
        "dueTime": {**DRAFT_ONE["dueTime"], "timeZone": "UTC"},
    }
    model = MockExtractionModel(drafts=[polluted])

    draft_set, _ = run_extraction(model, TEXT, None, NOW)

    draft = draft_set.model_dump(mode="json", by_alias=True)["drafts"][0]
    # 服务端生成的身份与状态覆盖模型提供的只读字段
    assert draft["id"] != "99999999-9999-4999-8999-999999999999"
    assert draft["sourceId"] != "88888888-8888-4888-8888-888888888888"
    assert draft["reminder"]["mode"] == "none"
    assert draft["reminder"]["revision"] is None
    assert draft["dueTime"]["timeZone"] == "Asia/Shanghai"
    assert draft["reviewIssues"] == []


@pytest.mark.parametrize(
    "bad_draft",
    [
        {**DRAFT_ONE, "title": "   "},                      # 空白标题
        {**DRAFT_ONE, "unexpected": 1},                     # 未知键
        {k: v for k, v in DRAFT_ONE.items() if k != "title"},  # 缺必填键
        {**DRAFT_ONE, "requirements": "不是数组"},
    ],
)
def test_extraction_invalid_draft_raises_draft_validation_error(bad_draft):
    model = MockExtractionModel(drafts=[bad_draft])

    with pytest.raises(DraftValidationError) as excinfo:
        run_extraction(model, TEXT, None, NOW)

    assert excinfo.value.index == 0


def test_extraction_non_object_draft_is_rejected():
    model = MockExtractionModel(drafts=["不是对象"])

    with pytest.raises(DraftValidationError):
        run_extraction(model, TEXT, None, NOW)


@pytest.mark.parametrize(
    "error",
    [
        ModelUnavailableError("服务不可用"),
        ModelTimeoutError("超时"),
        ModelOutputInvalidError("输出不可解析"),
    ],
)
def test_extraction_propagates_model_failures(error):
    model = MockExtractionModel(error=error)

    with pytest.raises(type(error)):
        run_extraction(model, TEXT, None, NOW)


def test_cache_put_get_and_isolation():
    cache = DraftSetCache()
    model = MockExtractionModel(drafts=[DRAFT_ONE])
    draft_set, entry = run_extraction(model, TEXT, None, NOW)

    assert cache.get(entry.draft_set_id) is None
    cache.put(entry)
    fetched = cache.get(entry.draft_set_id)

    assert fetched is not None
    assert fetched.draft_set_id == entry.draft_set_id
    assert fetched.source["originalText"] == TEXT
    assert [d["id"] for d in fetched.drafts] == [d["id"] for d in entry.drafts]
    assert cache.get("00000000-0000-4000-8000-000000000000") is None


def test_deepseek_adapter_missing_credential_is_model_unavailable():
    adapter = DeepSeekExtractionModel(api_key="")

    with pytest.raises(ModelUnavailableError) as excinfo:
        adapter.extract_drafts(TEXT, None)

    # 只允许出现变量名，绝不能出现任何凭据值
    message = str(excinfo.value)
    assert "sk-" not in message
    assert len(message) < 200


def test_deepseek_defaults_are_declared():
    adapter = DeepSeekExtractionModel()

    assert adapter.model == "deepseek-flash"
    assert adapter.base_url.startswith("https://")
    assert adapter.timeout > 0


# ---------------------------------------------------------------- 真实调用

ALLOW_REAL_CALLS = "SNAP2TODO_ALLOW_REAL_CALLS"


@pytest.mark.skipif(
    os.environ.get(ALLOW_REAL_CALLS) != "1" or not credential_available(),
    reason=(
        "真实调用默认跳过（T13 防复发）：只有 SNAP2TODO_ALLOW_REAL_CALLS=1 "
        "且 DEEPSEEK_API_KEY 可读时才执行"
    ),
)
def test_real_deepseek_extraction(tmp_path):
    """有凭据 + 显式放行时做一次真实文字提取；网络/服务不可用则 skip 并如实记录。"""
    import json
    import time
    from pathlib import Path

    real_text = "请于10月20日上午10点前把实验报告交到教务处，需要打印纸质版。"
    adapter = DeepSeekExtractionModel(timeout=60.0)

    started = time.monotonic()
    try:
        result = adapter.extract_drafts(real_text, None)
    except (ModelUnavailableError, ModelTimeoutError) as exc:
        pytest.skip(f"真实模型调用不可用：{type(exc).__name__}")
    elapsed = time.monotonic() - started

    assert isinstance(result, ModelResult)
    assert isinstance(result.drafts, list)

    # 项⑥：输出路径可用环境变量重定向（默认原位置），便于验收方隔离产出
    # 移植说明：证据目录锚点由源项目 parents[1]（仓库根）改为 parent（测试目录），
    # 因为本文件已下移到 tests/tasks/；默认仍跳过真实调用，仅避免万一放行时写出测试目录。
    env_dir = os.environ.get("SNAP2TODO_EVIDENCE_DIR")
    if env_dir:
        evidence = Path(env_dir)
    else:
        evidence = Path(__file__).resolve().parent / "协作" / "证据" / "T07"
    evidence.mkdir(parents=True, exist_ok=True)
    record = {
        "model": adapter.model,
        "base_url": adapter.base_url,
        "timeout_seconds": adapter.timeout,
        "elapsed_seconds": round(elapsed, 3),
        "messageDate": None,
        "input_text": real_text,
        "draft_count": len(result.drafts),
        "raw_drafts": result.drafts,
    }
    (evidence / "真实调用记录.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 真实输出必须能被提取服务接受（否则是适配器/提示词问题）
    draft_set, _ = run_extraction(adapter, real_text, None, NOW)
    assert draft_set.status in ("no_tasks", "review")


# ---------------------------------------------------------------- 防复发护栏（T13 Part B）


def test_text_real_calls_are_blocked_by_default():
    """未放行时，文字适配器在触网前就被 conftest 拦住（不消耗真实额度）。"""
    if os.environ.get(ALLOW_REAL_CALLS) == "1":
        pytest.skip("本轮为放行轮次（SNAP2TODO_ALLOW_REAL_CALLS=1）")
    adapter = DeepSeekExtractionModel(api_key="sk-test-fake")

    with pytest.raises(RuntimeError) as excinfo:
        adapter.extract_drafts("请交报告", None)

    assert ALLOW_REAL_CALLS in str(excinfo.value)


def test_vision_real_calls_are_blocked_by_default():
    if os.environ.get(ALLOW_REAL_CALLS) == "1":
        pytest.skip("本轮为放行轮次（SNAP2TODO_ALLOW_REAL_CALLS=1）")
    adapter = DeepSeekExtractionModel(api_key="sk-test-fake")

    with pytest.raises(RuntimeError) as excinfo:
        adapter.extract_drafts_from_image(b"\x89PNG\r\n\x1a\n", "image/png", None)

    assert ALLOW_REAL_CALLS in str(excinfo.value)


def test_urllib_external_calls_are_blocked_by_default():
    if os.environ.get(ALLOW_REAL_CALLS) == "1":
        pytest.skip("本轮为放行轮次（SNAP2TODO_ALLOW_REAL_CALLS=1）")
    import urllib.request

    with pytest.raises(RuntimeError) as excinfo:
        urllib.request.urlopen("https://api.deepseek.com/models", timeout=1)

    assert ALLOW_REAL_CALLS in str(excinfo.value)


def test_testclient_local_requests_are_not_blocked(tmp_path):
    """阻断只针对外部域名：TestClient（ASGITransport）与本地服务不受影响。"""
    from fastapi.testclient import TestClient

    from tasks_test_app import create_app

    client = TestClient(create_app(tmp_path))

    assert client.get("/health").status_code == 200
