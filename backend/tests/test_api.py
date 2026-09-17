"""测试 API 端点（会话 / 技能 / 设置）"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(tmp_path / "test_api.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(tmp_path / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(tmp_path / "workspaces"))

    # 重置 state_tracker 单例以指向测试数据库（直接从环境变量读取，
    # 避免 config.DB_PATH 模块缓存导致指向非测试路径）
    import os
    from services.state_tracker import tracker
    test_db_path = os.environ["ARS_WEB_DB_PATH"]
    tracker._reset_for_test(test_db_path)

    from main import app
    with TestClient(app) as c:
        # Register via user_manager directly (public register is disabled)
        import asyncio
        from services.user_manager import user_manager
        loop = asyncio.new_event_loop()
        loop.run_until_complete(user_manager.register("tester", "test1234", "tester"))
        loop.close()
        yield c


@pytest.fixture
def auth(client):
    r = client.post("/api/auth/login", json={"username": "tester", "password": "test1234"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestHealthCheck:
    def test_health_returns_ok(self, client):
        assert client.get("/api/health").status_code == 200


class TestSessionsAPI:
    def test_crud(self, client, auth):
        # Create
        r = client.post("/api/sessions", json={"skill_name": "deep-research", "mode_name": "full"}, headers=auth)
        assert r.status_code == 201
        sid = r.json()["id"]
        # List
        r = client.get("/api/sessions", headers=auth)
        assert r.status_code == 200
        # Get
        r = client.get(f"/api/sessions/{sid}", headers=auth)
        assert r.status_code == 200
        # Delete
        assert client.delete(f"/api/sessions/{sid}", headers=auth).status_code == 204
        assert client.get(f"/api/sessions/{sid}", headers=auth).status_code == 404

    def test_not_found(self, client, auth):
        assert client.get("/api/sessions/not-an-id", headers=auth).status_code == 404


class TestSettingsAPI:
    def test_crud(self, client, auth):
        r = client.get("/api/settings", headers=auth)
        assert r.status_code == 200
        client.put("/api/settings", json={"model": "claude-opus-4-8"}, headers=auth)
        assert client.get("/api/settings", headers=auth).json()["model"] == "claude-opus-4-8"


class TestModelsAPI:
    def test_list_models(self, client):
        r = client.get("/api/settings/models")
        assert r.status_code == 200 and len(r.json()["data"]) >= 4

    def test_list_providers(self, client):
        r = client.get("/api/settings/providers")
        assert r.status_code == 200 and len(r.json()["data"]) >= 4
