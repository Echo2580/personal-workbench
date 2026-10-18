"""T11 图片来源端点测试：/content 图片回看 + 410 缺失 + 文字路径零回退。

multipart 提取/确认骨架因环境缺 python-multipart（任务单禁止新增依赖）无法实测，
已实现但待经理授权安装依赖后验证——见交付报告"阻塞与请示"。
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.modules.tasks.domain import Source
from tasks_test_app import create_app
from app.modules.tasks.services.source_files import (
    build_image_source_payload,
    store_image,
    validate_image_bytes,
)
from app.modules.tasks.storage import commit

SOURCE_ID = "11111111-1111-4111-8111-111111111111"
TZ = timezone(timedelta(hours=8))


def make_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
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


def seed_image_source(root: Path, data: bytes, source_id: str = SOURCE_ID) -> str:
    image = validate_image_bytes(data)
    stored = store_image(root, image, source_id=source_id)
    payload = build_image_source_payload(
        source_id=source_id,
        content_type=image.content_type,
        extension=image.extension,
        content_sha256=image.content_sha256,
        imported_at=datetime.now(TZ).isoformat(),
        file_name=f"shot.{image.extension}",
    )
    commit(root, lambda snap: snap.add_source(Source.model_validate(payload)))
    return stored.relative_path


def test_content_returns_png_bytes_and_content_type(tmp_path: Path):
    relative = seed_image_source(tmp_path, PNG_BYTES)
    assert relative.endswith(".png")
    client = TestClient(create_app(tmp_path))

    response = client.get(f"/api/v1/sources/{SOURCE_ID}/content")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == PNG_BYTES
    assert hashlib.sha256(response.content).hexdigest() == hashlib.sha256(PNG_BYTES).hexdigest()


def test_content_returns_jpeg_bytes_and_content_type(tmp_path: Path):
    seed_image_source(tmp_path, JPEG_BYTES)
    client = TestClient(create_app(tmp_path))

    response = client.get(f"/api/v1/sources/{SOURCE_ID}/content")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == JPEG_BYTES


def test_content_missing_file_is_410(tmp_path: Path):
    """元数据在但源文件缺失 → 410 source_content_missing（回收 T06 的 501）。"""
    seed_image_source(tmp_path, PNG_BYTES)
    # 删除实际文件，保留 JSON 中的来源
    (tmp_path / "data" / "sources" / f"{SOURCE_ID}.png").unlink()
    client = TestClient(create_app(tmp_path))

    response = client.get(f"/api/v1/sources/{SOURCE_ID}/content")

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "source_content_missing"
    # 不再是 501
    assert response.status_code != 501


def test_content_unknown_source_is_404(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.get("/api/v1/sources/99999999-9999-4999-8999-999999999999/content")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "source_not_found"


def test_image_source_metadata_has_seven_keys_and_no_internal(tmp_path: Path):
    seed_image_source(tmp_path, PNG_BYTES)
    client = TestClient(create_app(tmp_path))

    response = client.get(f"/api/v1/sources/{SOURCE_ID}")

    assert response.status_code == 200
    meta = response.json()["source"]
    assert set(meta) == {
        "id", "kind", "mimeType", "fileName",
        "messageDate", "importedAt", "contentSha256",
    }
    assert meta["kind"] == "image"
    assert meta["mimeType"] == "image/png"
    assert "relativePath" not in meta
    assert "originalText" not in meta


# ------------------------------------------------------------------
# 文字路径零回退（硬护栏）
# ------------------------------------------------------------------

def test_text_content_still_returns_plain_text(tmp_path: Path):
    """文字源 /content 行为不变：text/plain + 原样字节。"""
    now = datetime.now(TZ)
    source = {
        "id": SOURCE_ID, "kind": "text", "originalText": "  请交报告\n",
        "relativePath": None, "mimeType": "text/plain; charset=utf-8",
        "fileName": None, "messageDate": None, "importedAt": now.isoformat(),
        "contentSha256": "a" * 64,
    }
    commit(tmp_path, lambda snap: snap.add_source_meta(source))
    client = TestClient(create_app(tmp_path))

    response = client.get(f"/api/v1/sources/{SOURCE_ID}/content")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.content.decode("utf-8") == "  请交报告\n"


def test_text_extraction_path_unchanged(tmp_path: Path):
    """文字提取 JSON 路径行为不变（无模型注入时走真实适配器，此处只验证非图片分支不受影响）。"""
    from app.modules.tasks.services.model_adapter import MockExtractionModel

    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(drafts=[{
        "title": "交报告", "startTime": None, "dueTime": None, "requirements": [],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告"}])
    client = TestClient(app)

    response = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": "请交报告", "messageDate": None}})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "review"
    assert len(body["drafts"]) == 1


def test_image_kind_in_json_extraction_is_415(tmp_path: Path):
    """JSON 路径仍不接受 kind=image（415），与 T06/T07 一致。"""
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/v1/extractions", json={
        "source": {"kind": "image", "originalText": None}})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
