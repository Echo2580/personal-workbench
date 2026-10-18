"""构造样本测试 T07 提取/确认 HTTP 端点（闭环、错误分型、重启语义）。"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tasks_test_app import create_app
from app.modules.tasks.services.model_adapter import (
    MockExtractionModel,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
)


TEXT = "请于10月20日10:00前交报告，需打印纸质版。"

DRAFT_DATED = {
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

DRAFT_CONDITIONAL = {
    "title": "交周报",
    "startTime": None,
    "dueTime": None,
    "requirements": [],
    "applicability": {"text": "仅限本班同学", "status": "needs_confirmation"},
    "sourceExcerpt": "另需交周报",
}


def make_client(root: Path, *, drafts=None, error=None) -> TestClient:
    app = create_app(root)
    app.state.extraction_model = MockExtractionModel(
        drafts=deepcopy(drafts) if drafts is not None else [],
        error=error,
    )
    return TestClient(app)


def extract(client: TestClient, text: str = TEXT, message_date: Any = "omit"):
    source: dict[str, Any] = {"kind": "text", "originalText": text}
    if message_date != "omit":
        source["messageDate"] = message_date
    return client.post("/api/v1/extractions", json={"source": source})


def strip_timezone(info):
    if info is None:
        return None
    return {
        key: info[key]
        for key in ("rawExpression", "precision", "resolvedValue", "status")
    }


def confirmation_body(extraction: dict, text: str = TEXT) -> dict:
    src = extraction["source"]
    tasks = []
    for draft in extraction["drafts"]:
        tasks.append(
            {
                "draftId": draft["id"],
                "title": draft["title"],
                "startTime": strip_timezone(draft["startTime"]),
                "dueTime": strip_timezone(draft["dueTime"]),
                "requirements": list(draft["requirements"]),
                "applicability": dict(draft["applicability"]),
                "sourceExcerpt": draft["sourceExcerpt"],
                "reminder": {
                    "mode": "none",
                    "requestedAt": None,
                    "relativeTo": None,
                    "offsetMinutes": None,
                },
            }
        )
    return {
        "source": {
            "id": src["id"],
            "kind": "text",
            "originalText": text,
            "messageDate": src["messageDate"],
            "importedAt": src["importedAt"],
            "mimeType": src["mimeType"],
            "fileName": src["fileName"],
            "contentSha256": src["contentSha256"],
        },
        "confirmedTasks": tasks,
    }


# ---------------------------------------------------------------- 完整闭环

def test_closed_loop_extract_confirm_then_read_back(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED, DRAFT_CONDITIONAL])

    extraction = extract(client)
    assert extraction.status_code == 200
    body = extraction.json()
    assert body["status"] == "review"
    assert len(body["drafts"]) == 2
    draft_set_id = body["draftSetId"]

    # 提取阶段不落盘
    assert not (tmp_path / "state.json").exists()

    confirmed = client.post(
        f"/api/v1/draft-sets/{draft_set_id}/confirm",
        json=confirmation_body(body),
    )
    assert confirmed.status_code == 200
    result = confirmed.json()
    assert set(result) == {"source", "tasks", "savedAt"}
    assert len(result["tasks"]) == 2

    # 列表可见
    listing = client.get("/api/v1/tasks")
    assert listing.status_code == 200
    ids = {t["id"] for t in listing.json()["tasks"]}
    assert ids == {t["id"] for t in result["tasks"]}

    # 详情七键来源
    first_task_id = result["tasks"][0]["id"]
    detail = client.get(f"/api/v1/tasks/{first_task_id}")
    assert detail.status_code == 200
    assert set(detail.json()["source"]) == {
        "id",
        "kind",
        "mimeType",
        "fileName",
        "messageDate",
        "importedAt",
        "contentSha256",
    }

    # 原文回看
    content = client.get(f"/api/v1/sources/{result['source']['id']}/content")
    assert content.status_code == 200
    assert content.content.decode("utf-8") == TEXT

    # 服务端生成字段
    task = result["tasks"][0]
    assert task["status"] == "open"
    assert task["reminder"]["revision"] is not None
    assert task["sourceId"] == result["source"]["id"]


def test_extraction_zero_tasks_returns_no_tasks_and_writes_nothing(tmp_path: Path):
    client = make_client(tmp_path, drafts=[])

    response = extract(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_tasks"
    assert body["drafts"] == []
    assert not (tmp_path / "state.json").exists()


def test_message_date_omitted_and_null_both_normalise_to_null(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])

    omitted = extract(client).json()
    explicit = extract(client, message_date=None).json()

    assert omitted["source"]["messageDate"] is None
    assert explicit["source"]["messageDate"] is None


def test_message_date_is_recorded_and_content_sha256_matches(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])

    body = extract(client, message_date="2026-10-19").json()

    assert body["source"]["messageDate"] == "2026-10-19"
    assert body["source"]["contentSha256"] == hashlib.sha256(
        TEXT.encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------- 提取错误分型

@pytest.mark.parametrize(
    "error,expected_status,expected_code",
    [
        (ModelUnavailableError("不可用"), 503, "model_unavailable"),
        (ModelTimeoutError("超时"), 504, "extraction_timeout"),
        (ModelOutputInvalidError("不可解析"), 502, "model_output_invalid"),
    ],
)
def test_model_failure_classification(
    tmp_path: Path, error: Exception, expected_status: int, expected_code: str
):
    client = make_client(tmp_path, error=error)

    response = extract(client)

    assert response.status_code == expected_status
    payload = response.json()
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["details"] == {}
    # 失败不得伪装成 no_tasks，也不得落盘
    assert "no_tasks" not in response.text
    assert not (tmp_path / "state.json").exists()


def test_invalid_draft_fields_are_502_draft_validation_failed(tmp_path: Path):
    client = make_client(tmp_path, drafts=[{**DRAFT_DATED, "title": "   "}])

    response = extract(client)

    assert response.status_code == 502
    payload = response.json()
    assert payload["error"]["code"] == "draft_validation_failed"
    assert payload["error"]["details"]["fieldErrors"]
    assert not (tmp_path / "state.json").exists()


def test_image_kind_is_415(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])

    response = client.post(
        "/api/v1/extractions",
        json={"source": {"kind": "image", "originalText": None}},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.parametrize(
    "body",
    [
        {},                                                        # 缺 source
        {"source": None},                                          # source 为 null
        {"source": "text"},                                        # source 非对象
        {"source": {"kind": "text"}},                               # 缺 originalText
        {"source": {"kind": "text", "originalText": "   "}},        # 空白原文
        {"source": {"kind": "text", "originalText": TEXT, "x": 1}}, # 未知子键
        {"source": {"kind": "text", "originalText": TEXT}, "y": 1}, # 未知根键
        {"source": {"kind": "text", "originalText": TEXT, "messageDate": "2026-2-3"}},
        {"source": {"kind": "text", "originalText": TEXT, "messageDate": ""}},
        {"source": {"kind": "text", "originalText": 3}},
        {"source": {"kind": "text", "originalText": TEXT, "messageDate": 5}},
    ],
)
def test_invalid_extraction_requests_are_400(tmp_path: Path, body: dict):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])

    response = client.post("/api/v1/extractions", json=body)

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_request"
    assert not (tmp_path / "state.json").exists()


def test_extraction_rejects_non_object_body(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])

    response = client.post("/api/v1/extractions", json=["x"])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


# ---------------------------------------------------------------- 确认错误分型

def test_confirm_unknown_draft_set_is_404(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])
    body = confirmation_body(extract(client).json())

    response = client.post(
        "/api/v1/draft-sets/00000000-0000-4000-8000-000000000000/confirm",
        json=body,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "draft_set_not_found"


def test_confirm_idempotent_replay_and_conflict(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])
    extraction = extract(client).json()
    draft_set_id = extraction["draftSetId"]
    body = confirmation_body(extraction)

    first = client.post(f"/api/v1/draft-sets/{draft_set_id}/confirm", json=body)
    assert first.status_code == 200

    replay = client.post(
        f"/api/v1/draft-sets/{draft_set_id}/confirm", json=deepcopy(body)
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()

    changed = deepcopy(body)
    changed["confirmedTasks"][0]["title"] = "改过的标题"
    conflict = client.post(f"/api/v1/draft-sets/{draft_set_id}/confirm", json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"

    # 只有一批任务
    assert len(client.get("/api/v1/tasks").json()["tasks"]) == 1


def test_confirm_content_mismatch_is_409(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])
    extraction = extract(client).json()
    body = confirmation_body(extraction)
    body["source"]["originalText"] = "另一段原文"

    response = client.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm", json=body
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "source_content_mismatch"


def test_confirm_empty_tasks_is_422_empty_confirmation(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])
    extraction = extract(client).json()
    body = confirmation_body(extraction)
    body["confirmedTasks"] = []

    response = client.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm", json=body
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_confirmation"


def test_confirm_task_validation_failure_is_422_with_paths(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED, DRAFT_CONDITIONAL])
    extraction = extract(client).json()
    body = confirmation_body(extraction)
    body["confirmedTasks"][1]["title"] = None

    response = client.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm", json=body
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "task_validation_failed"
    paths = [fe["field"] for fe in error["details"]["fieldErrors"]]
    assert any(p.startswith("confirmedTasks[1]") for p in paths), paths
    assert not (tmp_path / "state.json").exists()


@pytest.mark.parametrize(
    "mutate,expected_status,expected_code",
    [
        (lambda b: b.pop("source"), 400, "invalid_request"),
        (lambda b: b.pop("confirmedTasks"), 400, "invalid_request"),
        (lambda b: b.update({"extra": 1}), 400, "invalid_request"),
        (lambda b: b.update({"source": None}), 400, "invalid_request"),
        (lambda b: b.update({"confirmedTasks": None}), 400, "invalid_request"),
        (lambda b: b.update({"confirmedTasks": {}}), 400, "invalid_request"),
        (lambda b: b["source"].pop("messageDate"), 400, "invalid_request"),
        (lambda b: b["source"].pop("contentSha256"), 400, "invalid_request"),
        (lambda b: b["source"].update({"relativePath": None}), 400, "invalid_request"),
        (lambda b: b["source"].update({"contentSha256": None}), 400, "invalid_request"),
        (lambda b: b["confirmedTasks"][0].pop("reminder"), 422, "task_validation_failed"),
        (lambda b: b["confirmedTasks"][0].update({"id": "x"}), 400, "invalid_request"),
        (
            lambda b: b["confirmedTasks"][0].update(
                {"reminder": {"mode": "none"}}
            ),
            422,
            "task_validation_failed",
        ),
        (
            lambda b: b["confirmedTasks"][0].update({"dueTime": {"precision": "date"}}),
            422,
            "task_validation_failed",
        ),
    ],
)
def test_confirm_request_shape_errors(
    tmp_path: Path, mutate, expected_status: int, expected_code: str
):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])
    extraction = extract(client).json()
    body = confirmation_body(extraction)
    mutate(body)

    response = client.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm", json=body
    )

    assert response.status_code == expected_status, response.text
    assert response.json()["error"]["code"] == expected_code
    assert not (tmp_path / "state.json").exists()


def test_confirm_rejects_draft_id_from_another_batch(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])
    extraction = extract(client).json()
    body = confirmation_body(extraction)
    body["confirmedTasks"][0]["draftId"] = "99999999-9999-4999-8999-999999999999"

    response = client.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm", json=body
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "task_validation_failed"


def test_confirm_manual_reminder_in_past_is_422(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])
    extraction = extract(client).json()
    body = confirmation_body(extraction)
    body["confirmedTasks"][0]["reminder"] = {
        "mode": "manual",
        "requestedAt": "2020-01-01T00:00:00+08:00",
        "relativeTo": None,
        "offsetMinutes": None,
    }

    response = client.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm", json=body
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "reminder_time_in_past"


# ---------------------------------------------------------------- 重启语义

def test_restart_loses_draft_cache_but_keeps_confirmed_replay(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])
    extraction = extract(client).json()
    body = confirmation_body(extraction)
    first = client.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm", json=body
    )
    assert first.status_code == 200

    # 重启前再提取一份但**不确认**：它的缓存只存在于旧实例
    orphan = extract(client).json()
    assert orphan["draftSetId"] != extraction["draftSetId"]

    # 新 app 实例 = 重启：草稿缓存为空，但持久记录仍可回放
    restarted = make_client(tmp_path, drafts=[DRAFT_DATED])
    replay = restarted.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm",
        json=deepcopy(body),
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()

    # 任务在重启后仍可读
    assert len(restarted.get("/api/v1/tasks").json()["tasks"]) == 1

    # 未确认的 draftSetId 在重启后 404（旧实例的缓存已失效）
    miss = restarted.post(
        f"/api/v1/draft-sets/{orphan['draftSetId']}/confirm",
        json=confirmation_body(orphan),
    )
    assert miss.status_code == 404
    assert miss.json()["error"]["code"] == "draft_set_not_found"


def test_confirmation_record_shape_on_disk(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])
    extraction = extract(client).json()
    body = confirmation_body(extraction)
    client.post(f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm", json=body)

    payload = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    record = payload["confirmedDraftSets"][extraction["draftSetId"]]
    # D-015：键为 draftSetId，值恰为两键
    assert set(record) == {"requestSha256", "response"}
    assert len(record["requestSha256"]) == 64
    assert set(record["response"]) == {"source", "tasks", "savedAt"}
    # 来源只写一次
    assert list(payload["sources"]) == [extraction["source"]["id"]]


def test_health_and_home_still_work(tmp_path: Path):
    client = make_client(tmp_path, drafts=[DRAFT_DATED])

    assert client.get("/health").json() == {"status": "ok"}
    assert "Snap2Todo" in client.get("/").text
