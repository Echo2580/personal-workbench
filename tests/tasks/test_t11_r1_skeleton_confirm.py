"""图片确认全流程（T11-R1 建立，T12 适配）。

T12 起 `/extractions` 返回真实 DraftSet（原 501 骨架已回收），因此本文件的"真实路径"
= multipart 提取（注入的 mock 视觉模型产出草稿）→ 仅凭提取响应构造 §4.2 确认输入 →
multipart 确认。**不向 app.state.draft_set_cache 注入条目**（QA-P11 O-01 教训）。
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from tasks_test_app import create_app
from app.modules.tasks.services.model_adapter import MockExtractionModel
from app.modules.tasks.services.source_files import list_orphan_images

TZ = timezone(timedelta(hours=8))
SID = "11111111-1111-4111-8111-111111111111"  # 仅用于“来源 id 不符”负例
OTHER_DRAFT_ID = "eeeeeeee-0000-4000-8000-000000000002"


def make_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


PNG_BYTES = make_png()

DRAFT_ONE = {
    "title": "交报告",
    "startTime": None,
    "dueTime": None,
    "requirements": [],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "请交报告",
}


def png_file(name: str = "shot.png"):
    return ("file", (name, io.BytesIO(PNG_BYTES), "image/png"))


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path)
    # 注入 mock 视觉模型：本文件只验证 HTTP 契约，不做真实调用
    app.state.extraction_model = MockExtractionModel(image_drafts=[DRAFT_ONE])
    return TestClient(app)


def extract(client: TestClient) -> dict:
    """真实路径第一步：multipart 提取 → 200 DraftSet。"""
    response = client.post("/api/v1/extractions", files=[png_file()])
    assert response.status_code == 200, response.text
    return response.json()


def confirmation_for(draft_set: dict, *, title: str | None = None,
                     draft_id: str | None = None, source_id: str | None = None,
                     sha: str | None = None, duplicate: bool = False) -> dict:
    """仅凭提取响应构造 §4.2 完整确认输入（客户端唯一元数据来源）。"""
    source = draft_set["source"]
    tasks = []
    for index, draft in enumerate(draft_set["drafts"]):
        tasks.append({
            "draftId": draft_id if draft_id is not None and index == 0 else draft["id"],
            "title": title if title is not None and index == 0 else draft["title"],
            "startTime": None,
            "dueTime": None,
            "requirements": draft["requirements"],
            "applicability": draft["applicability"],
            "sourceExcerpt": draft["sourceExcerpt"],
            "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None,
                         "offsetMinutes": None},
        })
    if duplicate and tasks:
        tasks.append(dict(tasks[0]))
    return {
        "source": {
            "id": source_id or source["id"],
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


def confirm(client: TestClient, draft_set_id: str, confirmation: dict):
    return client.post(
        f"/api/v1/draft-sets/{draft_set_id}/confirm",
        files=[png_file()],
        data={"confirmation": json.dumps(confirmation)},
    )


# --------------------------------------------------------------------- #
# 1. 提取响应必须自带确认所需的服务端生成元数据
# --------------------------------------------------------------------- #


def test_extraction_response_exposes_draft_set_id(tmp_path: Path):
    body = extract(make_client(tmp_path))
    assert "draftSetId" in body
    draft_set_id = body["draftSetId"]
    assert isinstance(draft_set_id, str)
    assert str(uuid.UUID(draft_set_id)) == draft_set_id


def test_extraction_response_exposes_imported_at(tmp_path: Path):
    """确认时的来源元数据核对需要提取时刻：客户端无法自行猜测。"""
    body = extract(make_client(tmp_path))
    assert "importedAt" in body["source"], body["source"]
    parsed = datetime.fromisoformat(body["source"]["importedAt"])
    assert parsed.utcoffset() == timedelta(hours=8)


# --------------------------------------------------------------------- #
# 2. 图片确认全流程（真实路径，零缓存注入）
# --------------------------------------------------------------------- #


def test_image_confirm_full_flow_is_200(tmp_path: Path):
    client = make_client(tmp_path)
    draft_set = extract(client)

    response = confirm(client, draft_set["draftSetId"], confirmation_for(draft_set))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"source", "tasks", "savedAt"}
    # 契约 §4.2：响应 source 是 SourceMetadata（七键投影，不含 relativePath/originalText）
    assert set(body["source"]) == {
        "id", "kind", "mimeType", "fileName", "messageDate", "importedAt", "contentSha256",
    }
    assert body["source"]["id"] == draft_set["source"]["id"]
    assert body["source"]["kind"] == "image"
    assert body["source"]["mimeType"] == draft_set["source"]["mimeType"]
    assert body["source"]["contentSha256"] == draft_set["source"]["contentSha256"]
    assert body["source"]["importedAt"] == draft_set["source"]["importedAt"]
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["title"] == "交报告"
    assert body["tasks"][0]["draftId"] == draft_set["drafts"][0]["id"]
    assert body["tasks"][0]["status"] == "open"


def test_image_confirm_persists_three_partitions(tmp_path: Path):
    from app.modules.tasks.storage import load_snapshot

    client = make_client(tmp_path)
    draft_set = extract(client)
    assert confirm(client, draft_set["draftSetId"],
                   confirmation_for(draft_set)).status_code == 200

    snapshot = load_snapshot(tmp_path).snapshot
    assert set(snapshot.sources) == {draft_set["source"]["id"]}
    assert len(snapshot.tasks) == 1
    assert set(snapshot.confirmed_draft_sets) == {draft_set["draftSetId"]}
    record = snapshot.confirmed_draft_sets[draft_set["draftSetId"]]
    assert set(record) == {"requestSha256", "response"}
    saved_source = snapshot.sources[draft_set["source"]["id"]]
    assert saved_source.relative_path == f"data/sources/{draft_set['source']['id']}.png"
    assert saved_source.kind == "image"
    assert list(snapshot.tasks.values())[0].source_id == draft_set["source"]["id"]
    # 文件被引用后不再是无引用图片
    assert list_orphan_images(tmp_path) == []
    # 磁盘文件字节不变
    assert (tmp_path / saved_source.relative_path).read_bytes() == PNG_BYTES


def test_image_confirm_content_endpoint_returns_original(tmp_path: Path):
    client = make_client(tmp_path)
    draft_set = extract(client)
    assert confirm(client, draft_set["draftSetId"],
                   confirmation_for(draft_set)).status_code == 200

    response = client.get(f"/api/v1/sources/{draft_set['source']['id']}/content")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("image/png")
    assert response.content == PNG_BYTES


def test_image_confirm_idempotent_replay(tmp_path: Path):
    client = make_client(tmp_path)
    draft_set = extract(client)
    payload = confirmation_for(draft_set)

    first = confirm(client, draft_set["draftSetId"], payload)
    replay = confirm(client, draft_set["draftSetId"], payload)

    assert first.status_code == 200 and replay.status_code == 200, (first.text, replay.text)
    assert replay.json() == first.json()
    from app.modules.tasks.storage import load_snapshot
    assert len(load_snapshot(tmp_path).snapshot.tasks) == 1


def test_image_confirm_changed_content_conflicts(tmp_path: Path):
    client = make_client(tmp_path)
    draft_set = extract(client)
    assert confirm(client, draft_set["draftSetId"],
                   confirmation_for(draft_set)).status_code == 200

    changed = confirmation_for(draft_set, title="换了标题")
    response = confirm(client, draft_set["draftSetId"], changed)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "idempotency_conflict"


# --------------------------------------------------------------------- #
# 3. 负例与边界
# --------------------------------------------------------------------- #


def test_image_confirm_byte_mismatch_is_409(tmp_path: Path):
    client = make_client(tmp_path)
    draft_set = extract(client)

    response = confirm(
        client, draft_set["draftSetId"],
        confirmation_for(draft_set, sha=hashlib.sha256(b"x").hexdigest()),
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "source_content_mismatch"


def test_image_confirm_source_id_mismatch_is_409(tmp_path: Path):
    client = make_client(tmp_path)
    draft_set = extract(client)

    response = confirm(client, draft_set["draftSetId"],
                       confirmation_for(draft_set, source_id=SID))

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "source_content_mismatch"


def test_image_confirm_unknown_draft_set_is_404(tmp_path: Path):
    """未登记的 draftSetId 仍 404（缓存只在提取后登记）。"""
    client = make_client(tmp_path)
    draft_set = extract(client)

    response = confirm(client, str(uuid.uuid4()), confirmation_for(draft_set))

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "draft_set_not_found"


def test_image_confirm_empty_tasks_is_422(tmp_path: Path):
    client = make_client(tmp_path)
    draft_set = extract(client)
    payload = confirmation_for(draft_set)
    payload["confirmedTasks"] = []

    response = confirm(client, draft_set["draftSetId"], payload)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "empty_confirmation"


def test_image_confirm_duplicate_draft_ids_is_422(tmp_path: Path):
    client = make_client(tmp_path)
    draft_set = extract(client)
    payload = confirmation_for(draft_set, duplicate=True)

    response = confirm(client, draft_set["draftSetId"], payload)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "task_validation_failed"
    errors = response.json()["error"]["details"]["fieldErrors"]
    assert any(item["code"] == "duplicate" for item in errors), errors


def test_confirm_does_not_rewrite_shared_cache(tmp_path: Path):
    """确认成功后共享缓存条目仍是提取时的草稿内容（不被确认请求改写）。"""
    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(image_drafts=[DRAFT_ONE])
    client = TestClient(app)
    draft_set = extract(client)
    assert confirm(client, draft_set["draftSetId"],
                   confirmation_for(draft_set)).status_code == 200

    entry = app.state.draft_set_cache.get(draft_set["draftSetId"])
    assert entry is not None
    assert [d["id"] for d in entry.drafts] == [draft_set["drafts"][0]["id"]]
    assert len(app.state.draft_set_cache) == 1


# --------------------------------------------------------------------- #
# 4. 对照：draftId 归属校验（T12 起图片条目自带草稿，走真实成员校验）
# --------------------------------------------------------------------- #


def test_image_confirm_foreign_draft_id_is_rejected(tmp_path: Path):
    client = make_client(tmp_path)
    draft_set = extract(client)

    response = confirm(client, draft_set["draftSetId"],
                       confirmation_for(draft_set, draft_id=OTHER_DRAFT_ID))

    assert response.status_code == 422, response.text
    errors = response.json()["error"]["details"]["fieldErrors"]
    assert any(item["code"] == "not_in_batch" for item in errors), errors


def test_text_confirm_draft_id_membership_still_enforced(tmp_path: Path):
    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(drafts=[{
        "title": "交报告", "startTime": None, "dueTime": None, "requirements": [],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告"}])
    client = TestClient(app)

    extracted = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": "请交报告", "messageDate": None}})
    assert extracted.status_code == 200, extracted.text
    draft_set = extracted.json()

    payload = {
        "source": {
            "id": draft_set["source"]["id"], "kind": "text",
            "originalText": "请交报告", "messageDate": None,
            "importedAt": draft_set["source"]["importedAt"],
            "mimeType": draft_set["source"]["mimeType"], "fileName": None,
            "contentSha256": draft_set["source"]["contentSha256"],
        },
        "confirmedTasks": [{
            "draftId": OTHER_DRAFT_ID, "title": "交报告", "startTime": None, "dueTime": None,
            "requirements": [], "applicability": {"text": None, "status": "not_stated"},
            "sourceExcerpt": None,
            "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None,
                         "offsetMinutes": None},
        }],
    }
    response = client.post(f"/api/v1/draft-sets/{draft_set['draftSetId']}/confirm", json=payload)

    assert response.status_code == 422, response.text
    errors = response.json()["error"]["details"]["fieldErrors"]
    assert any(item["code"] == "not_in_batch" for item in errors), errors
