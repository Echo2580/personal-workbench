"""构造样本测试 T06 来源接口。

所有数据均为接口测试的构造样本，不代表真实提取或保存结果。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tasks_test_app import create_app
from app.modules.tasks.storage import commit


SOURCE_TEXT = "11111111-1111-4111-8111-111111111111"
SOURCE_IMAGE = "22222222-2222-4222-8222-222222222222"
STAMP = "2026-10-20T08:00:00+08:00"

TEXT_BODY = "  请交报告\n第二行  "


def text_source_payload(
    source_id: str = SOURCE_TEXT, text: str = TEXT_BODY
) -> dict[str, Any]:
    return {
        "id": source_id,
        "kind": "text",
        "originalText": text,
        "relativePath": None,
        "mimeType": "text/plain; charset=utf-8",
        "fileName": None,
        "messageDate": None,
        "importedAt": STAMP,
        "contentSha256": "a" * 64,
    }


def image_source_payload(source_id: str = SOURCE_IMAGE) -> dict[str, Any]:
    return {
        "id": source_id,
        "kind": "image",
        "originalText": None,
        "relativePath": f"data/sources/{source_id}.png",
        "mimeType": "image/png",
        "fileName": "通知.png",
        "messageDate": None,
        "importedAt": STAMP,
        "contentSha256": "b" * 64,
    }


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def client(data_root: Path) -> TestClient:
    seed = commit(
        data_root,
        lambda snap: snap.add_source_meta(text_source_payload())
        .add_source_meta(image_source_payload()),
    )
    assert seed.error is None, seed.error
    return TestClient(create_app(data_root))


def test_source_metadata_has_exactly_seven_keys(client: TestClient):
    response = client.get(f"/api/v1/sources/{SOURCE_TEXT}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"source"}
    assert set(body["source"]) == {
        "id",
        "kind",
        "mimeType",
        "fileName",
        "messageDate",
        "importedAt",
        "contentSha256",
    }
    assert body["source"]["id"] == SOURCE_TEXT
    assert body["source"]["kind"] == "text"
    assert body["source"]["fileName"] is None
    assert body["source"]["messageDate"] is None
    # 内部字段不得泄露
    assert "relativePath" not in body["source"]
    assert "originalText" not in body["source"]


def test_source_metadata_image_hides_internal_fields(client: TestClient):
    response = client.get(f"/api/v1/sources/{SOURCE_IMAGE}")

    assert response.status_code == 200
    source = response.json()["source"]
    assert source["kind"] == "image"
    assert source["fileName"] == "通知.png"
    assert source["mimeType"] == "image/png"
    assert "relativePath" not in source
    assert "originalText" not in source


def test_source_not_found(client: TestClient):
    response = client.get("/api/v1/sources/99999999-9999-4999-8999-999999999999")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "source_not_found"
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["details"] == {}


def test_content_text_returns_original_bytes(client: TestClient):
    response = client.get(f"/api/v1/sources/{SOURCE_TEXT}/content")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    # 原样字节：含首尾空白与换行，不做清洗
    assert response.content.decode("utf-8") == TEXT_BODY


def test_content_text_preserves_untouched_source(client: TestClient):
    client.get(f"/api/v1/sources/{SOURCE_TEXT}/content")

    meta = client.get(f"/api/v1/sources/{SOURCE_TEXT}").json()["source"]
    assert meta["contentSha256"] == "a" * 64


def test_content_image_missing_file_is_410(client: TestClient):
    """T11：图片 /content 已实现；元数据在但源文件缺失 → 410 source_content_missing
    （回收 T06 的 501 not_implemented）。"""
    response = client.get(f"/api/v1/sources/{SOURCE_IMAGE}/content")

    assert response.status_code == 410
    body = response.json()
    assert body["error"]["code"] == "source_content_missing"


def test_content_source_not_found(client: TestClient):
    response = client.get(
        "/api/v1/sources/99999999-9999-4999-8999-999999999999/content"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "source_not_found"


def test_corrupt_state_returns_storage_read_failed(data_root: Path):
    (data_root / "state.json").write_text(
        '{"schemaVersion":1,"sources":{', encoding="utf-8"
    )
    client = TestClient(create_app(data_root))

    detail = client.get(f"/api/v1/sources/{SOURCE_TEXT}")
    listing = client.get("/api/v1/tasks")

    for response in (detail, listing):
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "storage_read_failed"


def test_unknown_schema_version_returns_storage_version_unsupported(
    data_root: Path,
):
    (data_root / "state.json").write_text(
        '{"schemaVersion":4,"sources":{},"tasks":{},"confirmedDraftSets":{}}',
        encoding="utf-8",
    )
    client = TestClient(create_app(data_root))

    response = client.get(f"/api/v1/sources/{SOURCE_TEXT}")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "storage_version_unsupported"


def test_health_and_home_still_work(client: TestClient):
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Snap2Todo" in page.text
