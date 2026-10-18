"""首页偏好（城市 + 自定义快速入口 + 首页大字 + 个人资料）持久化回归。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.home import preferences


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    return TestClient(app, base_url="http://127.0.0.1:17843")


def headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/bootstrap").json()["token"]
    return {"X-Workbench-Token": token, "Origin": "http://127.0.0.1:17843"}


def put_preferences(client, payload):
    return client.put(
        "/api/v1/preferences",
        headers={**headers(client), "Content-Type": "application/json"},
        json=payload,
    )


def make_client(root):
    app = create_app(root)
    return TestClient(app, base_url="http://127.0.0.1:17843")


def write_raw_preferences(data_dir, payload):
    path = data_dir / "home" / "preferences.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_defaults(client):
    body = client.get("/api/v1/preferences", headers=headers(client)).json()
    assert body["city"] == "南京"
    assert body["quickEntries"] == []
    assert body["heroHeadline"] == ""
    assert body["profile"] == {"displayName": "林同学", "signature": "个人版"}


def test_city_roundtrip_and_persist_across_restart(tmp_path):
    root = tmp_path / "data"
    client = make_client(root)

    saved = put_preferences(client, {"city": "成都"})
    assert saved.status_code == 200
    assert saved.json()["city"] == "成都"

    second = make_client(root)
    assert second.get("/api/v1/preferences", headers=headers(second)).json()["city"] == "成都"


def test_quick_entries_add_update_and_persist(tmp_path):
    root = tmp_path / "data"
    client = make_client(root)

    saved = put_preferences(
        client,
        {"quickEntries": [{"label": "Google", "url": "https://google.com"}, {"label": "B站", "url": "https://bilibili.com"}]},
    )
    assert saved.status_code == 200
    entries = saved.json()["quickEntries"]
    assert [entry["label"] for entry in entries] == ["Google", "B站"]
    assert all(entry["id"] for entry in entries)
    # 城市未传时保持不变
    assert saved.json()["city"] == "南京"

    # 部分更新：只改城市，不影响入口
    put_preferences(client, {"city": "杭州"})
    second = make_client(root)
    body = second.get("/api/v1/preferences", headers=headers(second)).json()
    assert body["city"] == "杭州"
    assert [entry["label"] for entry in body["quickEntries"]] == ["Google", "B站"]


def test_quick_entries_validation(client):
    assert put_preferences(client, {"quickEntries": "x"}).status_code == 422
    assert put_preferences(client, {"quickEntries": [{"label": "", "url": "https://a.com"}]}).status_code == 422
    assert put_preferences(client, {"quickEntries": [{"label": "A", "url": "ftp://a.com"}]}).status_code == 422
    assert put_preferences(client, {"quickEntries": [{"label": "A", "url": "https://a.com"}] * 9}).status_code == 422


@pytest.mark.parametrize("payload", [{"city": ""}, {"city": "   "}, {"city": 123}, {}, {"city": "成都", "foo": 1}])
def test_invalid_city_rejected(client, payload):
    assert put_preferences(client, payload).status_code in (400, 422)


def test_preferences_requires_token(client):
    assert client.get("/api/v1/preferences").status_code == 403


def test_city_length_capped(tmp_path):
    payload = preferences.write_preferences(tmp_path, {"city": "长" * 40})
    assert len(payload["city"]) == preferences.MAX_CITY_LENGTH


# --------------------------------------------------------------------------- #
# heroHeadline
# --------------------------------------------------------------------------- #


def test_headline_roundtrip_and_persist_across_restart(tmp_path):
    root = tmp_path / "data"
    client = make_client(root)

    saved = put_preferences(client, {"heroHeadline": "今天只做一件事"})
    assert saved.status_code == 200
    assert saved.json()["heroHeadline"] == "今天只做一件事"

    second = make_client(root)
    assert second.get("/api/v1/preferences", headers=headers(second)).json()["heroHeadline"] == "今天只做一件事"


def test_headline_empty_string_restores_default(client):
    assert put_preferences(client, {"heroHeadline": "自定义大字"}).status_code == 200
    cleared = put_preferences(client, {"heroHeadline": ""})
    assert cleared.status_code == 200
    assert cleared.json()["heroHeadline"] == ""
    assert client.get("/api/v1/preferences", headers=headers(client)).json()["heroHeadline"] == ""


def test_headline_trims_outer_whitespace_and_keeps_other_fields(client):
    put_preferences(client, {"city": "苏州", "heroHeadline": "慢慢来"})
    saved = put_preferences(client, {"heroHeadline": "  专注今天  "})
    assert saved.status_code == 200
    assert saved.json()["heroHeadline"] == "专注今天"
    assert saved.json()["city"] == "苏州"


def test_headline_max_length(client):
    accepted = put_preferences(client, {"heroHeadline": "字" * preferences.MAX_HEADLINE_LENGTH})
    assert accepted.status_code == 200
    rejected = put_preferences(client, {"heroHeadline": "字" * (preferences.MAX_HEADLINE_LENGTH + 1)})
    assert rejected.status_code == 422


@pytest.mark.parametrize("value", ["第一行\n第二行", "带\t制表符", 123, None, ["数组"]])
def test_headline_rejects_invalid_values(client, value):
    assert put_preferences(client, {"heroHeadline": value}).status_code == 422


# --------------------------------------------------------------------------- #
# profile
# --------------------------------------------------------------------------- #


def test_profile_partial_updates_merge(client):
    saved = put_preferences(client, {"profile": {"displayName": "阿林"}})
    assert saved.status_code == 200
    assert saved.json()["profile"] == {"displayName": "阿林", "signature": "个人版"}

    saved = put_preferences(client, {"profile": {"signature": "今天也要好好生活"}})
    assert saved.status_code == 200
    assert saved.json()["profile"] == {"displayName": "阿林", "signature": "今天也要好好生活"}


def test_profile_persists_across_restart_and_trims(tmp_path):
    root = tmp_path / "data"
    client = make_client(root)
    saved = put_preferences(client, {"profile": {"displayName": "  小林  ", "signature": "  个人版·改  "}})
    assert saved.status_code == 200
    assert saved.json()["profile"] == {"displayName": "小林", "signature": "个人版·改"}

    second = make_client(root)
    assert second.get("/api/v1/preferences", headers=headers(second)).json()["profile"] == {
        "displayName": "小林",
        "signature": "个人版·改",
    }


def test_profile_signature_may_be_empty(client):
    saved = put_preferences(client, {"profile": {"signature": ""}})
    assert saved.status_code == 200
    assert saved.json()["profile"] == {"displayName": "林同学", "signature": ""}


@pytest.mark.parametrize(
    "profile",
    [
        "not-an-object",
        [],
        {"displayName": ""},
        {"displayName": "   "},
        {"displayName": "名" * (preferences.MAX_DISPLAY_NAME_LENGTH + 1)},
        {"displayName": 42},
        {"displayName": "带\n换行"},
        {"signature": "签" * (preferences.MAX_SIGNATURE_LENGTH + 1)},
        {"signature": 42},
        {"signature": "带\n换行"},
        {"displayName": "阿林", "nickname": "未知字段"},
        {"displayName": "名" * (preferences.MAX_DISPLAY_NAME_LENGTH + 1), "signature": "合法"},
    ],
)
def test_profile_rejects_invalid_values(client, profile):
    assert put_preferences(client, {"profile": profile}).status_code == 422


def test_profile_boundary_lengths(client):
    saved = put_preferences(
        client,
        {
            "profile": {
                "displayName": "名" * preferences.MAX_DISPLAY_NAME_LENGTH,
                "signature": "签" * preferences.MAX_SIGNATURE_LENGTH,
            }
        },
    )
    assert saved.status_code == 200
    assert len(saved.json()["profile"]["displayName"]) == preferences.MAX_DISPLAY_NAME_LENGTH
    assert len(saved.json()["profile"]["signature"]) == preferences.MAX_SIGNATURE_LENGTH


# --------------------------------------------------------------------------- #
# 兼容与容错
# --------------------------------------------------------------------------- #


def test_old_preferences_file_without_new_fields(tmp_path):
    data_dir = tmp_path / "data"
    write_raw_preferences(data_dir, {"city": "成都", "quickEntries": [{"id": "abc", "label": "A", "url": "https://a.com"}]})

    assert preferences.read_preferences(data_dir) == {
        "city": "成都",
        "quickEntries": [{"id": "abc", "label": "A", "url": "https://a.com"}],
        "heroHeadline": "",
        "profile": {"displayName": "林同学", "signature": "个人版"},
    }

    client = make_client(data_dir)
    body = client.get("/api/v1/preferences", headers=headers(client)).json()
    assert body["city"] == "成都"
    assert body["heroHeadline"] == ""
    assert body["profile"] == {"displayName": "林同学", "signature": "个人版"}


def test_old_file_fields_can_still_be_partially_updated(tmp_path):
    data_dir = tmp_path / "data"
    write_raw_preferences(data_dir, {"city": "成都"})
    client = make_client(data_dir)

    saved = put_preferences(client, {"heroHeadline": "新大字"})
    assert saved.status_code == 200
    assert saved.json()["city"] == "成都"
    assert saved.json()["heroHeadline"] == "新大字"


@pytest.mark.parametrize(
    "stored,expected_headline,expected_profile",
    [
        ({"heroHeadline": 123}, "", {"displayName": "林同学", "signature": "个人版"}),
        ({"heroHeadline": "字" * 31}, "", {"displayName": "林同学", "signature": "个人版"}),
        ({"heroHeadline": "带\n换行"}, "", {"displayName": "林同学", "signature": "个人版"}),
        ({"profile": "坏数据"}, "", {"displayName": "林同学", "signature": "个人版"}),
        ({"profile": {"displayName": "  ", "signature": "签" * 41}}, "", {"displayName": "林同学", "signature": "个人版"}),
        ({"profile": {"displayName": 7, "signature": 8}}, "", {"displayName": "林同学", "signature": "个人版"}),
        ({"profile": {"displayName": "阿林", "signature": ""}}, "", {"displayName": "阿林", "signature": ""}),
    ],
)
def test_invalid_stored_values_fall_back_to_defaults(tmp_path, stored, expected_headline, expected_profile):
    data_dir = tmp_path / "data"
    write_raw_preferences(data_dir, {"city": "南京", **stored})
    payload = preferences.read_preferences(data_dir)
    assert payload["heroHeadline"] == expected_headline
    assert payload["profile"] == expected_profile
    # 非法存量数据不应阻挡后续合法写入
    fixed = preferences.write_preferences(data_dir, {"heroHeadline": "修好了"})
    assert fixed["heroHeadline"] == "修好了"


def test_corrupt_json_file_falls_back_to_defaults(tmp_path):
    data_dir = tmp_path / "data"
    path = data_dir / "home" / "preferences.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    payload = preferences.read_preferences(data_dir)
    assert payload["city"] == "南京"
    assert payload["heroHeadline"] == ""
    assert payload["profile"] == {"displayName": "林同学", "signature": "个人版"}


# --------------------------------------------------------------------------- #
# 未知字段
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("payload", [{"heroheadline": "大小写未知"}, {"unknown": 1}, {"city": "南京", "extra": True}])
def test_unknown_top_level_fields_rejected_without_writing(client, payload):
    before = client.get("/api/v1/preferences", headers=headers(client)).json()
    response = put_preferences(client, payload)
    assert response.status_code in (400, 422)
    after = client.get("/api/v1/preferences", headers=headers(client)).json()
    assert after == before


def test_unknown_profile_fields_rejected_without_writing(client):
    before = client.get("/api/v1/preferences", headers=headers(client)).json()
    response = put_preferences(client, {"profile": {"displayName": "阿林", "avatar": "x"}})
    assert response.status_code in (400, 422)
    after = client.get("/api/v1/preferences", headers=headers(client)).json()
    assert after == before
