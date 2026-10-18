"""T11 图片来源文件服务测试（字节校验、落盘、回读、orphan）。

用真实最小 PNG/JPEG 字节构造样本；不依赖 multipart。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.modules.tasks.services.source_files import (
    MAX_IMAGE_BYTES,
    SourceFileError,
    build_image_source_payload,
    build_relative_path,
    detect_image_format,
    list_orphan_images,
    read_image,
    sanitize_file_name,
    sources_dir,
    store_image,
    validate_image_bytes,
)


# 最小合法 PNG：签名 + IHDR + IEND（结构校验所需的最简形式）
def make_png() -> bytes:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1 RGB
    raw = b"\x00\xff\x00\x00"  # filter + 1 pixel
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


# 最小合法 JPEG：SOI + APP0 + EOI
def make_jpeg() -> bytes:
    return (
        b"\xff\xd8\xff"
        + b"\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


PNG_BYTES = make_png()
JPEG_BYTES = make_jpeg()


# ------------------------------------------------------------------
# 1. 字节校验矩阵
# ------------------------------------------------------------------

def test_valid_png_passes():
    image = validate_image_bytes(PNG_BYTES)
    assert image.content_type == "image/png"
    assert image.extension == "png"
    assert image.content_sha256 == hashlib.sha256(PNG_BYTES).hexdigest()


def test_valid_jpeg_passes():
    image = validate_image_bytes(JPEG_BYTES)
    assert image.content_type == "image/jpeg"
    assert image.extension == "jpg"
    assert image.content_sha256 == hashlib.sha256(JPEG_BYTES).hexdigest()


def test_oversize_is_413_with_max_bytes():
    oversize = PNG_BYTES + b"\x00" * (MAX_IMAGE_BYTES + 1)
    with pytest.raises(SourceFileError) as exc:
        validate_image_bytes(oversize)
    assert exc.value.status == 413
    assert exc.value.code == "source_too_large"
    assert exc.value.details == {"maxBytes": 20971520}


def test_non_image_magic_is_415():
    with pytest.raises(SourceFileError) as exc:
        validate_image_bytes(b"this is plain text, not an image")
    assert exc.value.status == 415
    assert exc.value.code == "unsupported_media_type"


def test_truncated_png_is_422():
    truncated = PNG_BYTES[: len(PNG_BYTES) // 2]
    with pytest.raises(SourceFileError) as exc:
        validate_image_bytes(truncated)
    assert exc.value.status == 422
    assert exc.value.code == "source_unreadable"


def test_truncated_jpeg_is_422():
    truncated = JPEG_BYTES[:5]  # 有 SOI 但无 EOI
    with pytest.raises(SourceFileError) as exc:
        validate_image_bytes(truncated)
    assert exc.value.status == 422
    assert exc.value.code == "source_unreadable"


def test_extension_disguise_rejected_by_magic():
    """.png 实为文本 → 按魔数拒绝（不信任扩展名）。"""
    disguised = b"not a real png at all"
    with pytest.raises(SourceFileError) as exc:
        validate_image_bytes(disguised)
    assert exc.value.status == 415


def test_detect_format_returns_none_for_unknown():
    assert detect_image_format(b"") is None
    assert detect_image_format(b"abc") is None


def test_empty_bytes_is_415():
    with pytest.raises(SourceFileError) as exc:
        validate_image_bytes(b"")
    assert exc.value.status == 415


# ------------------------------------------------------------------
# 2. 落盘协议
# ------------------------------------------------------------------

def test_store_image_creates_file_and_no_tmp_leftover(tmp_path: Path):
    image = validate_image_bytes(PNG_BYTES)
    stored = store_image(tmp_path, image)

    assert stored.absolute_path.exists()
    assert stored.absolute_path.name.endswith(".png")
    assert stored.relative_path == f"data/sources/{stored.source_id}.png"
    # 无临时文件残留
    assert not (sources_dir(tmp_path) / f"{stored.source_id}.tmp").exists()
    assert list(sources_dir(tmp_path).glob("*.tmp")) == []


def test_store_image_jpeg_extension(tmp_path: Path):
    image = validate_image_bytes(JPEG_BYTES)
    stored = store_image(tmp_path, image)
    assert stored.absolute_path.name.endswith(".jpg")
    assert stored.content_type == "image/jpeg"


def test_stored_bytes_match_upload_exactly(tmp_path: Path):
    image = validate_image_bytes(PNG_BYTES)
    stored = store_image(tmp_path, image)
    assert stored.absolute_path.read_bytes() == PNG_BYTES
    assert read_image(tmp_path, stored.relative_path) == PNG_BYTES


def test_store_image_with_explicit_source_id(tmp_path: Path):
    image = validate_image_bytes(PNG_BYTES)
    stored = store_image(tmp_path, image, source_id="11111111-1111-4111-8111-111111111111")
    assert stored.source_id == "11111111-1111-4111-8111-111111111111"
    assert stored.relative_path == "data/sources/11111111-1111-4111-8111-111111111111.png"


def test_read_image_missing_file_is_410(tmp_path: Path):
    with pytest.raises(SourceFileError) as exc:
        read_image(tmp_path, "data/sources/does-not-exist.png")
    assert exc.value.status == 410
    assert exc.value.code == "source_content_missing"


# ------------------------------------------------------------------
# 3. orphan 识别（不做自动删除）
# ------------------------------------------------------------------

def test_list_orphan_images_when_no_snapshot(tmp_path: Path):
    image = validate_image_bytes(PNG_BYTES)
    store_image(tmp_path, image)
    orphans = list_orphan_images(tmp_path)
    assert len(orphans) == 1
    assert orphans[0].startswith("data/sources/")


def test_list_orphan_images_empty_dir(tmp_path: Path):
    assert list_orphan_images(tmp_path) == []


def test_list_orphan_excludes_referenced(tmp_path: Path):
    from app.modules.tasks.domain import Source
    from app.modules.tasks.services.source_files import build_image_source_payload
    from app.modules.tasks.storage import commit

    image = validate_image_bytes(PNG_BYTES)
    stored = store_image(tmp_path, image)
    payload = build_image_source_payload(
        source_id=stored.source_id,
        content_type=image.content_type,
        extension=image.extension,
        content_sha256=image.content_sha256,
        imported_at="2026-10-17T08:00:00+08:00",
    )
    commit(tmp_path, lambda snap: snap.add_source(Source.model_validate(payload)))

    assert list_orphan_images(tmp_path) == []


# ------------------------------------------------------------------
# 4. 元数据辅助
# ------------------------------------------------------------------

def test_sanitize_file_name():
    assert sanitize_file_name("note.png") == "note.png"
    assert sanitize_file_name("a/b\\c.png") == "a_b_c.png"
    # ".." → "_"（各 2 字符），"/" → "_"（2 个）→ 共 4 个下划线
    assert sanitize_file_name("../../etc/passwd") == "____etc_passwd"
    assert "/" not in sanitize_file_name("../../etc/passwd")
    assert ".." not in sanitize_file_name("../../etc/passwd")
    assert sanitize_file_name("") is None
    assert sanitize_file_name(None) is None
    assert sanitize_file_name("   ") is None


def test_build_relative_path_is_posix():
    assert build_relative_path("abc", "png") == "data/sources/abc.png"
    assert "\\" not in build_relative_path("abc", "jpg")


def test_build_image_source_payload_shape():
    payload = build_image_source_payload(
        source_id="11111111-1111-4111-8111-111111111111",
        content_type="image/png",
        extension="png",
        content_sha256="a" * 64,
        imported_at="2026-10-17T08:00:00+08:00",
        message_date=None,
        file_name="shot.png",
    )
    assert set(payload) == {
        "id", "kind", "originalText", "relativePath", "mimeType",
        "fileName", "messageDate", "importedAt", "contentSha256",
    }
    assert payload["kind"] == "image"
    assert payload["originalText"] is None
    assert payload["relativePath"] == "data/sources/11111111-1111-4111-8111-111111111111.png"


def test_image_source_payload_validates_as_domain_source():
    from app.modules.tasks.domain import Source

    payload = build_image_source_payload(
        source_id="11111111-1111-4111-8111-111111111111",
        content_type="image/jpeg",
        extension="jpg",
        content_sha256="b" * 64,
        imported_at="2026-10-17T08:00:00+08:00",
        file_name="x.jpg",
    )
    source = Source.model_validate(payload)
    assert source.kind == "image"
    assert source.mime_type == "image/jpeg"
    assert source.relative_path.endswith(".jpg")


def test_image_source_requires_matching_extension():
    """MIME 与扩展名不一致时领域模型应拒绝（保证落盘路径与 MIME 对应）。"""
    from app.modules.tasks.domain import Source

    payload = build_image_source_payload(
        source_id="11111111-1111-4111-8111-111111111111",
        content_type="image/png",
        extension="png",
        content_sha256="c" * 64,
        imported_at="2026-10-17T08:00:00+08:00",
    )
    payload["relativePath"] = "data/sources/11111111-1111-4111-8111-111111111111.jpg"
    with pytest.raises(Exception):
        Source.model_validate(payload)
