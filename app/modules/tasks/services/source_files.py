"""图片来源字节校验、落盘、回读与无引用清理辅助（T11）。

契约 §1.5（单张 PNG/JPEG、20 MiB）、§3.1（image 字段与 relativePath）、§2（临时文件
→ 哈希校验 → 原子移动 → 锁内 JSON 提交，orphan 规则）。

锁内外切分（§2.1）：字节写入、重读校验、哈希比对、原子移动均在**存储锁外**完成
（长 IO 不进锁）；JSON 快照提交必须**锁内**（由调用方用 commit 完成）。
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.modules.tasks.storage import load_snapshot


MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MiB，契约 §1.5
MAX_BYTES_DETAIL = 20971520

PNG_MAGIC = b"\x89PNG"
JPEG_MAGIC = b"\xff\xd8\xff"

# PNG 必需块：签名 + IHDR + IDAT... + IEND；这里做最小结构校验
PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"


class SourceFileError(Exception):
    """图片字节/落盘错误，携带契约错误码与 details。"""

    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class ImageBytes:
    """校验通过的原始图片字节与其规范元数据。"""

    data: bytes
    content_type: str  # image/png 或 image/jpeg
    extension: str  # png 或 jpg
    content_sha256: str


def detect_image_format(data: bytes) -> str | None:
    """按魔数判定格式，返回 "png" / "jpeg"；无法识别返回 None。不信任扩展名。"""
    if data.startswith(PNG_MAGIC):
        return "png"
    if data.startswith(JPEG_MAGIC):
        return "jpeg"
    return None


def _looks_like_valid_png(data: bytes) -> bool:
    """最小 PNG 结构校验：签名 + IHDR 在前 + 结尾 IEND。"""
    if len(data) < 8 + 25:  # 签名 + IHDR(25) 至少
        return False
    if not data.startswith(PNG_MAGIC):
        return False
    if b"IHDR" not in data[:33]:
        return False
    return data.rstrip().endswith(PNG_IEND) or PNG_IEND in data[-16:]


def _looks_like_valid_jpeg(data: bytes) -> bool:
    """最小 JPEG 结构校验：SOI + 结尾 EOI(FFD9)。"""
    if not data.startswith(JPEG_MAGIC):
        return False
    if len(data) < 4:
        return False
    return data.rstrip().endswith(b"\xff\xd9")


def validate_image_bytes(data: bytes) -> ImageBytes:
    """字节级校验：大小 → 魔数 → 结构。失败抛 SourceFileError。

    - 超 20 MiB → 413 source_too_large（details.maxBytes）
    - 魔数非 PNG/JPEG → 415 unsupported_media_type
    - 魔数合法但结构损坏 → 422 source_unreadable
    """
    if len(data) > MAX_IMAGE_BYTES:
        raise SourceFileError(
            413,
            "source_too_large",
            "图片超过 20 MiB 上限。",
            {"maxBytes": MAX_BYTES_DETAIL},
        )

    fmt = detect_image_format(data)
    if fmt is None:
        raise SourceFileError(
            415,
            "unsupported_media_type",
            "只接受 PNG 或 JPEG 图片。",
        )

    if fmt == "png" and not _looks_like_valid_png(data):
        raise SourceFileError(
            422,
            "source_unreadable",
            "PNG 内容损坏或截断，无法读取。",
        )
    if fmt == "jpeg" and not _looks_like_valid_jpeg(data):
        raise SourceFileError(
            422,
            "source_unreadable",
            "JPEG 内容损坏或截断，无法读取。",
        )

    if fmt == "png":
        content_type, extension = "image/png", "png"
    else:
        content_type, extension = "image/jpeg", "jpg"

    return ImageBytes(
        data=data,
        content_type=content_type,
        extension=extension,
        content_sha256=hashlib.sha256(data).hexdigest(),
    )


def sanitize_file_name(name: str | None) -> str | None:
    """清理仅用于展示的文件名：去掉路径分隔符与 ..，空值返回 None。不参与路径。"""
    if not name:
        return None
    cleaned = str(name).replace("\\", "_").replace("/", "_").replace("..", "_").strip()
    return cleaned or None


def sources_dir(root: Path) -> Path:
    return Path(root) / "data" / "sources"


def build_relative_path(source_id: str, extension: str) -> str:
    """契约/D-013：data/sources/<id>.png|.jpg，POSIX 分隔符。"""
    return f"data/sources/{source_id}.{extension}"


@dataclass
class StoredImage:
    source_id: str
    relative_path: str
    absolute_path: Path
    content_type: str
    content_sha256: str


def store_image(root: Path, image: ImageBytes, source_id: str | None = None) -> StoredImage:
    """落盘协议（锁外）：临时文件 → 重读校验字节与哈希 → 原子移至最终路径。

    失败时回滚本次新建的临时/最终文件，不留下半成品。
    """
    source_id = source_id or str(uuid.uuid4())
    directory = sources_dir(root)
    directory.mkdir(parents=True, exist_ok=True)

    tmp_path = directory / f"{source_id}.tmp"
    final_path = directory / f"{source_id}.{image.extension}"

    # 1. 写临时文件
    tmp_path.write_bytes(image.data)

    try:
        # 2. 重读校验：字节逐字节一致 + 哈希一致
        reread = tmp_path.read_bytes()
        if reread != image.data:
            raise SourceFileError(422, "source_unreadable", "回读字节与上传内容不一致。")
        if hashlib.sha256(reread).hexdigest() != image.content_sha256:
            raise SourceFileError(422, "source_unreadable", "回读哈希与上传内容不一致。")

        # 3. 原子移动至最终路径
        os.replace(tmp_path, final_path)
    except Exception:
        # 回滚本次新建文件
        for leftover in (tmp_path, final_path):
            try:
                if leftover.exists():
                    leftover.unlink()
            except OSError:
                pass
        raise

    return StoredImage(
        source_id=source_id,
        relative_path=build_relative_path(source_id, image.extension),
        absolute_path=final_path,
        content_type=image.content_type,
        content_sha256=image.content_sha256,
    )


def read_image(root: Path, relative_path: str) -> bytes:
    """按 relativePath 回读原图字节；文件缺失抛 410 source_content_missing。"""
    path = Path(root) / relative_path
    if not path.exists():
        raise SourceFileError(410, "source_content_missing", "原图文件缺失，无法回看。")
    return path.read_bytes()


def list_orphan_images(root: Path) -> list[str]:
    """列出 data/sources/ 中未被当前快照 relativePath 引用的文件（相对路径形式）。

    仅识别，**不做自动删除**（契约 §2：清理只能针对未被当前有效快照引用的文件，
    且自动清理不属本轮）。
    """
    directory = sources_dir(root)
    if not directory.exists():
        return []

    loaded = load_snapshot(root)
    referenced: set[str] = set()
    if loaded.snapshot is not None:
        for source in loaded.snapshot.sources.values():
            rel = getattr(source, "relative_path", None)
            if rel:
                referenced.add(str(rel))

    orphans: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        rel = f"data/sources/{path.name}"
        if rel not in referenced:
            orphans.append(rel)
    return orphans


def build_image_source_payload(
    *,
    source_id: str,
    content_type: str,
    extension: str,
    content_sha256: str,
    imported_at: str,
    message_date: str | None = None,
    file_name: str | None = None,
) -> dict[str, Any]:
    """构造 image 源的完整 Source 载荷（契约 §3.1 九键）。"""
    return {
        "id": source_id,
        "kind": "image",
        "originalText": None,
        "relativePath": build_relative_path(source_id, extension),
        "mimeType": content_type,
        "fileName": sanitize_file_name(file_name),
        "messageDate": message_date,
        "importedAt": imported_at,
        "contentSha256": content_sha256,
    }
