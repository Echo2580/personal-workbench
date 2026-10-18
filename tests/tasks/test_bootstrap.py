from fastapi.testclient import TestClient

from tasks_test_app import create_app


def test_health_without_model_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_local_assets_from_other_cwd(monkeypatch, tmp_path):
    other = tmp_path / "启动 测试"
    other.mkdir()
    monkeypatch.chdir(other)
    client = TestClient(create_app())

    page = client.get("/")

    assert page.status_code == 200
    assert "Snap2Todo" in page.text
    assert "/static/styles.css" in page.text
    assert client.get("/static/styles.css").status_code == 200


def test_static_files_cannot_escape_web():
    client = TestClient(create_app())

    assert client.get("/static/%2e%2e/README.md").status_code == 404
