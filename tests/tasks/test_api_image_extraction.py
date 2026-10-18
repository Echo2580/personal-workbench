"""T12 图片提取端点：multipart 501 骨架 → 真实视觉提取 DraftSet 200。

mock 注入（app.state.extraction_model = MockExtractionModel(...)），零真实调用。
图片确认走 T11 全流程（真实路径，无缓存注入）。
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.modules.tasks.api.extractions import _skeleton_batch_view
from tasks_test_app import create_app
from app.modules.tasks.services.model_adapter import (
    MockExtractionModel,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.modules.tasks.services.source_files import list_orphan_images, sources_dir

TZ = timezone(timedelta(hours=8))


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
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "在线提交周报",
}

FOREIGN_DRAFT_ID = "eeeeeeee-0000-4000-8000-0000000000ff"


def png_file(name: str = "shot.png", data: bytes | None = None):
    return ("file", (name, io.BytesIO(data if data is not None else PNG), "image/png"))


def make_client(tmp_path: Path, model: MockExtractionModel | None = None) -> TestClient:
    app = create_app(tmp_path)
    app.state.extraction_model = model or MockExtractionModel(image_drafts=[DRAFT_ONE])
    return TestClient(app)


def extract(client: TestClient, **kwargs) -> dict:
    response = client.post("/api/v1/extractions", files=[png_file()], **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def confirmation_for(draft_set: dict, *, draft_id: str | None = None,
                     title: str | None = None, sha: str | None = None) -> dict:
    drafts = draft_set["drafts"]
    source = draft_set["source"]
    tasks = []
    for index, draft in enumerate(drafts):
        tasks.append({
            "draftId": draft_id if draft_id is not None and index == 0 else draft["id"],
            "title": title if title is not None and index == 0 else draft["title"],
            "startTime": draft["startTime"],
            "dueTime": None if draft["dueTime"] is None else {
                "rawExpression": draft["dueTime"]["rawExpression"],
                "precision": draft["dueTime"]["precision"],
                "resolvedValue": draft["dueTime"]["resolvedValue"],
                "status": draft["dueTime"]["status"],
            },
            "requirements": draft["requirements"],
            "applicability": draft["applicability"],
            "sourceExcerpt": draft["sourceExcerpt"],
            "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None,
                         "offsetMinutes": None},
        })
    return {
        "source": {
            "id": source["id"],
            "kind": "image",
            "originalText": None,
            "messageDate": source["messageDate"],
            "importedAt": source["importedAt"],
            "mimeType": source["mimeType"],
            "fileName": source["fileName"],
            "contentSha256": sha or source["contentSha256"],
        },
        "confirmedTasks": tasks,
    }


def confirm(client: TestClient, draft_set_id: str, payload: dict):
    return client.post(
        f"/api/v1/draft-sets/{draft_set_id}/confirm",
        files=[png_file()],
        data={"confirmation": json.dumps(payload)},
    )


# --------------------------------------------------------------------------- #
# 1. 提取成功：一/零/多草稿
# --------------------------------------------------------------------------- #


def test_image_extraction_returns_review_draft_set(tmp_path: Path):
    client = make_client(tmp_path, MockExtractionModel(image_drafts=[DRAFT_ONE, DRAFT_TWO]))

    body = extract(client)

    assert set(body) == {"draftSetId", "source", "status", "drafts"}
    assert body["status"] == "review"
    assert len(body["drafts"]) == 2
    assert [d["title"] for d in body["drafts"]] == ["交实验报告", "在线提交周报"]
    assert body["source"]["kind"] == "image"
    assert body["source"]["mimeType"] == "image/png"
    assert body["source"]["fileName"] == "shot.png"
    assert body["source"]["contentSha256"] == hashlib.sha256(PNG).hexdigest()
    assert "relativePath" not in body["source"]
    assert {d["sourceId"] for d in body["drafts"]} == {body["source"]["id"]}


def test_image_extraction_stores_file_and_caches_real_drafts(tmp_path: Path):
    app = create_app(tmp_path)
    model = MockExtractionModel(image_drafts=[DRAFT_ONE])
    app.state.extraction_model = model
    client = TestClient(app)

    body = extract(client)

    relative = f"data/sources/{body['source']['id']}.png"
    assert (tmp_path / relative).read_bytes() == PNG
    assert list(sources_dir(tmp_path).glob("*.tmp")) == []
    entry = get_cache_for(app).get(body["draftSetId"])
    assert entry is not None
    assert len(entry.drafts) == 1
    assert entry.drafts[0]["id"] == body["drafts"][0]["id"]
    assert entry.source["relativePath"] == relative
    assert model.image_calls and model.image_calls[0][0] == "image/png"


def test_image_extraction_zero_tasks_is_no_tasks(tmp_path: Path):
    client = make_client(tmp_path, MockExtractionModel(image_drafts=[]))

    body = extract(client)

    assert body["status"] == "no_tasks"
    assert body["drafts"] == []
    # 无任务时图片已落盘但未入快照 → 预期 orphan（契约允许，不自动删除）
    assert list_orphan_images(tmp_path) == [f"data/sources/{body['source']['id']}.png"]


def test_image_extraction_does_not_write_state_json(tmp_path: Path):
    client = make_client(tmp_path)

    extract(client)

    assert not (tmp_path / "state.json").exists()


# --------------------------------------------------------------------------- #
# 2. 图片确认全流程（T11 路径，零缓存注入）
# --------------------------------------------------------------------------- #


def test_image_extraction_then_confirm_end_to_end(tmp_path: Path):
    from app.modules.tasks.storage import load_snapshot

    client = make_client(tmp_path, MockExtractionModel(image_drafts=[DRAFT_ONE]))
    draft_set = extract(client)

    response = confirm(client, draft_set["draftSetId"], confirmation_for(draft_set))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"source", "tasks", "savedAt"}
    assert body["source"]["id"] == draft_set["source"]["id"]
    assert body["tasks"][0]["draftId"] == draft_set["drafts"][0]["id"]
    snapshot = load_snapshot(tmp_path).snapshot
    assert set(snapshot.sources) == {draft_set["source"]["id"]}
    assert len(snapshot.tasks) == 1
    assert snapshot.sources[draft_set["source"]["id"]].relative_path == (
        f"data/sources/{draft_set['source']['id']}.png"
    )
    assert list_orphan_images(tmp_path) == []


def test_image_confirm_foreign_draft_id_is_422_not_in_batch(tmp_path: Path):
    """回收断言：drafts 非空条目不再使用骨架期批次视图，成员校验真实生效。"""
    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(image_drafts=[DRAFT_ONE])
    client = TestClient(app)
    draft_set = extract(client)

    response = confirm(
        client, draft_set["draftSetId"],
        confirmation_for(draft_set, draft_id=FOREIGN_DRAFT_ID),
    )

    assert response.status_code == 422, response.text
    errors = response.json()["error"]["details"]["fieldErrors"]
    assert any(item["code"] == "not_in_batch" for item in errors), errors


def test_skeleton_batch_view_is_inert_for_non_empty_drafts(tmp_path: Path):
    """回收断言（直接检查）：条目自带草稿时 _skeleton_batch_view 返回 None。"""
    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(image_drafts=[DRAFT_ONE])
    client = TestClient(app)
    draft_set = extract(client)

    view = _skeleton_batch_view(
        get_cache_for(app),
        draft_set["draftSetId"],
        {"confirmedTasks": [{"draftId": FOREIGN_DRAFT_ID}]},
    )

    assert view is None


# --------------------------------------------------------------------------- #
# 3. 失败分型：不落 JSON、不伪装 no_tasks
# --------------------------------------------------------------------------- #


def _assert_failed(client: TestClient, tmp_path: Path, response, status: int, code: str):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert not (tmp_path / "state.json").exists()


def test_image_extraction_unavailable_is_503(tmp_path: Path):
    client = make_client(tmp_path, MockExtractionModel(error=ModelUnavailableError("x")))

    response = client.post("/api/v1/extractions", files=[png_file()])

    _assert_failed(client, tmp_path, response, 503, "model_unavailable")
    # 固定文案，细节不进响应
    assert response.json()["error"]["message"] == "模型服务暂不可用，请稍后重试。"


def test_image_extraction_timeout_is_504(tmp_path: Path):
    client = make_client(tmp_path, MockExtractionModel(error=ModelTimeoutError("x")))

    response = client.post("/api/v1/extractions", files=[png_file()])

    _assert_failed(client, tmp_path, response, 504, "extraction_timeout")


def test_image_extraction_output_invalid_is_502(tmp_path: Path):
    client = make_client(tmp_path, MockExtractionModel(error=ModelOutputInvalidError("x")))

    response = client.post("/api/v1/extractions", files=[png_file()])

    _assert_failed(client, tmp_path, response, 502, "model_output_invalid")


def test_image_extraction_invalid_draft_is_502_draft_validation_failed(tmp_path: Path):
    client = make_client(
        tmp_path, MockExtractionModel(image_drafts=[{**DRAFT_ONE, "title": "  "}])
    )

    response = client.post("/api/v1/extractions", files=[png_file()])

    _assert_failed(client, tmp_path, response, 502, "draft_validation_failed")
    details = response.json()["error"]["details"]
    assert details["fieldErrors"][0]["field"].startswith("drafts[0]")


def test_image_extraction_failure_does_not_register_cache_entry(tmp_path: Path):
    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(error=ModelTimeoutError("x"))
    client = TestClient(app)

    client.post("/api/v1/extractions", files=[png_file()])

    assert len(get_cache_for(app)) == 0


def test_text_only_injected_model_yields_503_for_image(tmp_path: Path):
    """注入的适配器不支持图片入口时如实 503，而不是 500 或静默空结果。"""

    class TextOnly:
        def extract_drafts(self, original_text, message_date):
            raise AssertionError("不应走文字入口")

    app = create_app(tmp_path)
    app.state.extraction_model = TextOnly()
    client = TestClient(app)

    response = client.post("/api/v1/extractions", files=[png_file()])

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "model_unavailable"
    assert not (tmp_path / "state.json").exists()


# --------------------------------------------------------------------------- #
# 4. 校验矩阵零回退（T11 行为不变）
# --------------------------------------------------------------------------- #


def test_invalid_image_still_400_413_415_422(tmp_path: Path):
    client = make_client(tmp_path)

    missing = client.post("/api/v1/extractions", files={})
    assert missing.status_code == 400

    not_image = client.post(
        "/api/v1/extractions",
        files=[("file", ("a.png", io.BytesIO(b"just text"), "image/png"))],
    )
    assert not_image.status_code == 415
    assert not_image.json()["error"]["code"] == "unsupported_media_type"

    truncated = client.post(
        "/api/v1/extractions", files=[png_file(data=PNG[: len(PNG) // 2])]
    )
    assert truncated.status_code == 422

    empty_date = client.post(
        "/api/v1/extractions", files=[png_file()], data={"messageDate": ""}
    )
    assert empty_date.status_code == 400


def get_cache_for(app):
    """get_cache 只访问 request.app.state；用最小桩代替 Request。"""
    from types import SimpleNamespace

    from app.modules.tasks.api.extractions import get_cache

    return get_cache(SimpleNamespace(app=app))
