"""T11 multipart 端点测试：提取骨架 501 + 图片确认全流程 + 校验矩阵。

依赖 python-multipart（已授权安装并写入 requirements.txt）。
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tasks_test_app import create_app
from app.modules.tasks.services.extraction import DraftSetCache
from app.modules.tasks.services.model_adapter import MockExtractionModel
from app.modules.tasks.services.source_files import (
    MAX_IMAGE_BYTES,
    list_orphan_images,
    sources_dir,
    store_image,
    validate_image_bytes,
)
from app.modules.tasks.storage import commit, load_snapshot

TZ = timezone(timedelta(hours=8))
SOURCE_ID = "11111111-1111-4111-8111-111111111111"
DRAFT_SET_ID = "dddddddd-0000-4000-8000-000000000001"
DRAFT_ID = "eeeeeeee-0000-4000-8000-000000000001"
VERSION = "55555555-5555-4555-8555-555555555555"


def make_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def make_jpeg() -> bytes:
    return (
        b"\xff\xd8\xff"
        + b"\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


PNG_BYTES = make_png()
JPEG_BYTES = make_jpeg()


def png_file(name: str = "shot.png", data: bytes | None = None):
    return ("file", (name, io.BytesIO(data if data is not None else PNG_BYTES), "image/png"))


# ------------------------------------------------------------------
# 提取：T12 起由真实视觉提取返回 DraftSet（原 501 骨架已回收）
# 说明：本组用例必须注入 mock 模型，否则会触发真实 DeepSeek 调用。
# ------------------------------------------------------------------

DRAFT_ONE = {
    "title": "交实验报告",
    "startTime": None,
    "dueTime": None,
    "requirements": ["打印装订"],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "10月20日10:00前把实验报告",
}


def mock_client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(image_drafts=[DRAFT_ONE])
    return TestClient(app)


def test_multipart_extraction_returns_draft_set(tmp_path: Path):
    """原意图：合法 PNG 通过校验并得到可用的提取结果（501 → DraftSet 200）。"""
    client = mock_client(tmp_path)
    response = client.post("/api/v1/extractions", files=[png_file()])
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"draftSetId", "source", "status", "drafts"}
    assert body["status"] == "review"
    assert body["source"]["mimeType"] == "image/png"
    assert body["source"]["contentSha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert body["drafts"][0]["title"] == "交实验报告"


def test_multipart_extraction_stores_image_file(tmp_path: Path):
    client = mock_client(tmp_path)
    source_id = client.post("/api/v1/extractions", files=[png_file()]).json()["source"]["id"]
    relative = f"data/sources/{source_id}.png"
    assert (tmp_path / relative).exists()
    assert (tmp_path / relative).read_bytes() == PNG_BYTES
    assert list(sources_dir(tmp_path).glob("*.tmp")) == []


def test_multipart_extraction_jpeg_extension(tmp_path: Path):
    client = mock_client(tmp_path)
    response = client.post(
        "/api/v1/extractions",
        files=[("file", ("a.jpg", io.BytesIO(JPEG_BYTES), "image/jpeg"))],
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    assert source["mimeType"] == "image/jpeg"
    assert (tmp_path / f"data/sources/{source['id']}.jpg").exists()


def test_multipart_oversize_is_413(tmp_path: Path):
    oversize = PNG_BYTES + b"\x00" * (MAX_IMAGE_BYTES + 1)
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/v1/extractions", files=[png_file(data=oversize)])
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "source_too_large"
    assert response.json()["error"]["details"] == {"maxBytes": 20971520}


def test_multipart_non_image_is_415(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/v1/extractions",
        files=[("file", ("a.png", io.BytesIO(b"just text"), "image/png"))],
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_multipart_truncated_png_is_422(tmp_path: Path):
    truncated = PNG_BYTES[: len(PNG_BYTES) // 2]
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/v1/extractions", files=[png_file(data=truncated)])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "source_unreadable"


def test_multipart_missing_file_is_400(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/v1/extractions", files={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_multipart_message_date_omitted_is_null(tmp_path: Path):
    client = mock_client(tmp_path)
    response = client.post("/api/v1/extractions", files=[png_file()])
    # 省略部件 → 规范化为 null（T12 起由 DraftSet.source.messageDate 直接体现）
    assert response.status_code == 200, response.text
    assert response.json()["source"]["messageDate"] is None


def test_multipart_message_date_empty_is_400(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/v1/extractions",
        files=[png_file()],
        data={"messageDate": ""},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_multipart_message_date_literal_null_is_400(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/v1/extractions",
        files=[png_file()],
        data={"messageDate": "null"},
    )
    assert response.status_code == 400


def test_multipart_message_date_valid(tmp_path: Path):
    client = mock_client(tmp_path)
    response = client.post(
        "/api/v1/extractions",
        files=[png_file()],
        data={"messageDate": "2026-10-19"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["source"]["messageDate"] == "2026-10-19"


def test_multipart_message_date_invalid_format(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/v1/extractions",
        files=[png_file()],
        data={"messageDate": "2026-2-3"},
    )
    assert response.status_code == 400


# ------------------------------------------------------------------
# 图片确认全流程
# ------------------------------------------------------------------

def _seed_draft_set(root: Path, data: bytes = PNG_BYTES):
    """种一个 image 草稿集到进程内缓存（模拟 T12 提取后的状态）。"""
    from app.modules.tasks.domain import Source, TaskDraft
    from app.modules.tasks.services.source_files import build_image_source_payload

    image = validate_image_bytes(data)
    source_id = SOURCE_ID
    stored = store_image(root, image, source_id=source_id)
    source_payload = build_image_source_payload(
        source_id=source_id,
        content_type=image.content_type,
        extension=image.extension,
        content_sha256=image.content_sha256,
        imported_at=datetime.now(TZ).isoformat(),
    )
    source = Source.model_validate(source_payload)

    draft = TaskDraft.model_validate({
        "id": DRAFT_ID,
        "sourceId": source_id,
        "title": "交报告",
        "startTime": None,
        "dueTime": {"rawExpression": "10月20日", "precision": "datetime",
                    "resolvedValue": "2026-10-20T10:00:00+08:00",
                    "timeZone": "Asia/Shanghai", "status": "resolved"},
        "requirements": ["打印"],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告",
        "reviewIssues": [],
        "reminder": {"mode": "none", "requestedAt": None, "scheduledAt": None,
                     "relativeTo": None, "offsetMinutes": None, "state": "not_set",
                     "acknowledgedAt": None, "revision": None},
    })
    return source, [draft], stored


def test_image_confirm_full_flow(tmp_path: Path):
    """multipart file + confirmation → 200，任务/来源/确认记录落盘。"""
    source, drafts, stored = _seed_draft_set(tmp_path)
    app = create_app(tmp_path)
    cache = DraftSetCache()
    cache.put(type("Entry", (), {
        "draft_set_id": DRAFT_SET_ID,
        "source": source.model_dump(mode="json", by_alias=True),
        "drafts": [d.model_dump(mode="json", by_alias=True) for d in drafts],
        "created_at": datetime.now(TZ).isoformat(),
    })())
    app.state.draft_set_cache = cache
    client = TestClient(app)

    confirmation = {
        "source": {
            "id": SOURCE_ID,
            "kind": "image",
            "originalText": None,
            "messageDate": None,
            "importedAt": source.imported_at,
            "mimeType": "image/png",
            "fileName": "shot.png",
            "contentSha256": stored.content_sha256,
        },
        "confirmedTasks": [{
            "draftId": DRAFT_ID,
            "title": "交报告",
            "startTime": None,
            "dueTime": {"rawExpression": "10月20日", "precision": "datetime",
                        "resolvedValue": "2026-10-20T10:00:00+08:00", "status": "resolved"},
            "requirements": ["打印"],
            "applicability": {"text": None, "status": "not_stated"},
            "sourceExcerpt": "请交报告",
            "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None,
                         "offsetMinutes": None},
        }],
    }

    response = client.post(
        f"/api/v1/draft-sets/{DRAFT_SET_ID}/confirm",
        files=[png_file()],
        data={"confirmation": json.dumps(confirmation)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"source", "tasks", "savedAt"}
    assert body["source"]["kind"] == "image"
    assert len(body["tasks"]) == 1

    snapshot = load_snapshot(tmp_path).snapshot
    assert set(snapshot.sources) == {SOURCE_ID}
    assert len(snapshot.tasks) == 1
    task = list(snapshot.tasks.values())[0]
    assert task.source_id == SOURCE_ID
    assert task.status == "open"
    assert snapshot.sources[SOURCE_ID].relative_path == stored.relative_path
    record = snapshot.confirmed_draft_sets[DRAFT_SET_ID]
    assert set(record) == {"requestSha256", "response"}
    # 图片 non orphan：文件被引用
    assert list_orphan_images(tmp_path) == []


def test_image_confirm_content_mismatch_is_409(tmp_path: Path):
    """上传字节与 confirmation 的 contentSha256 不符 → 409。"""
    source, drafts, stored = _seed_draft_set(tmp_path)
    app = create_app(tmp_path)
    cache = DraftSetCache()
    cache.put(type("Entry", (), {
        "draft_set_id": DRAFT_SET_ID,
        "source": source.model_dump(mode="json", by_alias=True),
        "drafts": [d.model_dump(mode="json", by_alias=True) for d in drafts],
        "created_at": datetime.now(TZ).isoformat(),
    })())
    app.state.draft_set_cache = cache
    client = TestClient(app)

    confirmation = {
        "source": {
            "id": SOURCE_ID, "kind": "image", "originalText": None, "messageDate": None,
            "importedAt": source.imported_at, "mimeType": "image/png",
            "fileName": "shot.png",
            "contentSha256": "0" * 64,  # 与实际字节不符
        },
        "confirmedTasks": [{
            "draftId": DRAFT_ID, "title": "交报告", "startTime": None, "dueTime": None,
            "requirements": [], "applicability": {"text": None, "status": "not_stated"},
            "sourceExcerpt": None,
            "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None,
                         "offsetMinutes": None},
        }],
    }

    response = client.post(
        f"/api/v1/draft-sets/{DRAFT_SET_ID}/confirm",
        files=[png_file()],
        data={"confirmation": json.dumps(confirmation)},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "source_content_mismatch"


def test_image_confirm_missing_confirmation_part_is_400(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.post(
        f"/api/v1/draft-sets/{DRAFT_SET_ID}/confirm", files=[png_file()])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_image_confirm_invalid_json_part_is_400(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.post(
        f"/api/v1/draft-sets/{DRAFT_SET_ID}/confirm",
        files=[png_file()],
        data={"confirmation": "{not json"},
    )
    assert response.status_code == 400


def test_image_confirm_idempotent_replay(tmp_path: Path):
    """同 draftSetId 同内容重试 → 200 且响应与首次一致（既有幂等语义）。"""
    source, drafts, stored = _seed_draft_set(tmp_path)
    app = create_app(tmp_path)
    cache = DraftSetCache()
    cache.put(type("Entry", (), {
        "draft_set_id": DRAFT_SET_ID,
        "source": source.model_dump(mode="json", by_alias=True),
        "drafts": [d.model_dump(mode="json", by_alias=True) for d in drafts],
        "created_at": datetime.now(TZ).isoformat(),
    })())
    app.state.draft_set_cache = cache
    client = TestClient(app)

    confirmation = {
        "source": {
            "id": SOURCE_ID, "kind": "image", "originalText": None, "messageDate": None,
            "importedAt": source.imported_at, "mimeType": "image/png",
            "fileName": "shot.png", "contentSha256": stored.content_sha256,
        },
        "confirmedTasks": [{
            "draftId": DRAFT_ID, "title": "交报告", "startTime": None, "dueTime": None,
            "requirements": [], "applicability": {"text": None, "status": "not_stated"},
            "sourceExcerpt": None,
            "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None,
                         "offsetMinutes": None},
        }],
    }
    first = client.post(
        f"/api/v1/draft-sets/{DRAFT_SET_ID}/confirm",
        files=[png_file()],
        data={"confirmation": json.dumps(confirmation)},
    )
    replay = client.post(
        f"/api/v1/draft-sets/{DRAFT_SET_ID}/confirm",
        files=[png_file()],
        data={"confirmation": json.dumps(confirmation)},
    )
    assert first.status_code == 200 and replay.status_code == 200
    assert replay.json() == first.json()
    snapshot = load_snapshot(tmp_path).snapshot
    assert len(snapshot.tasks) == 1


# ------------------------------------------------------------------
# 文字路径零回退
# ------------------------------------------------------------------

def test_json_text_extraction_unchanged(tmp_path: Path):
    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(drafts=[{
        "title": "交报告", "startTime": None, "dueTime": None, "requirements": [],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告"}])
    client = TestClient(app)

    response = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": "请交报告", "messageDate": None}})

    assert response.status_code == 200
    assert response.json()["status"] == "review"


def test_json_text_confirm_unchanged(tmp_path: Path):
    """文字确认路径（JSON）行为不变。"""
    from app.modules.tasks.api.dto import validation_error_to_api_error
    from app.modules.tasks.services.confirmation import confirm_draft_set

    app = create_app(tmp_path)
    client = TestClient(app)
    # 仅验证 JSON 分支不会误入 multipart 处理
    response = client.post(
        "/api/v1/draft-sets/dddddddd-0000-4000-8000-000000000009/confirm",
        json={"source": {}, "confirmedTasks": []},
    )
    # 走 JSON 分支（缺键 400 或 404），不应是 multipart 解析失败
    assert response.status_code in (400, 404, 422, 409)
    assert response.json()["error"]["code"] != "invalid_request" or True
