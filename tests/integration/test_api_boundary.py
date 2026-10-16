from fastapi.testclient import TestClient
from app.main import create_app


def test_security_and_errors(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:17843") as c:
        health = c.get("/healthz").json()
        assert health["service"] == "personal-workbench"
        assert "token" not in str(health) and str(tmp_path) not in str(health)
        b = c.get("/api/v1/bootstrap").json()
        assert len(b["modules"]) == 3
        assert c.post("/api/v1/projects/scan").status_code == 403
        h = {"X-Workbench-Token": b["token"], "Origin": "http://127.0.0.1:17843"}
        assert c.post("/api/v1/projects/scan", headers=h).status_code == 202
        assert (
            c.get(
                "/api/v1/projects", headers={"X-Workbench-Token": "wrong"}
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/v1/projects/scan", headers={**h, "Origin": "http://evil.test"}
            ).status_code
            == 403
        )
        assert (
            c.get("/api/v1/bootstrap", headers={"Host": "evil.test"}).status_code == 403
        )
        assert (
            c.get(
                "/api/v1/bootstrap", headers={"Origin": "http://evil.test"}
            ).status_code
            == 403
        )
        assert (
            c.get("/api/v1/instance", headers=h).json()["instance_id"]
            == b["instance_id"]
        )


def test_unconfigured_summary_is_not_reported_as_successful_scan(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:17843") as c:
        bootstrap = c.get("/api/v1/bootstrap").json()
        assert bootstrap["modules"][0]["summary"]["availability"] == "尚未配置扫描目录"
