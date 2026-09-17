"""测试 state_tracker.py —— 会话与消息持久化"""

import pytest
from services.state_tracker import StateTracker


@pytest.fixture
async def tracker(tmp_path):
    """使用临时数据库的 StateTracker。"""
    db_path = str(tmp_path / "test.db")
    t = StateTracker(db_path=db_path)
    yield t
    # 清理连接池
    if hasattr(t, '_pool'):
        await t._pool.close()


class TestSessions:
    """会话管理测试"""

    async def test_create_session(self, tracker):
        s = await tracker.create_session("deep-research", "full", "Test session")
        assert s["id"]
        assert s["skill_name"] == "deep-research"
        assert s["mode_name"] == "full"
        assert s["status"] == "active"

    async def test_list_sessions_empty(self, tracker):
        result = await tracker.list_sessions()
        assert result["data"] == []
        assert result["meta"]["total"] == 0

    async def test_list_sessions_with_data(self, tracker):
        await tracker.create_session("deep-research", "full")
        await tracker.create_session("academic-paper", "plan")
        result = await tracker.list_sessions()
        assert len(result["data"]) == 2
        assert result["meta"]["total"] == 2

    async def test_get_session_not_found(self, tracker):
        s = await tracker.get_session("nonexistent-id")
        assert s is None

    async def test_get_session_found(self, tracker):
        created = await tracker.create_session("deep-research", "full")
        found = await tracker.get_session(created["id"])
        assert found is not None
        assert found["skill_name"] == "deep-research"

    async def test_delete_session(self, tracker):
        s = await tracker.create_session("deep-research", "full")
        await tracker.delete_session(s["id"])
        assert await tracker.get_session(s["id"]) is None

    async def test_update_session_status(self, tracker):
        s = await tracker.create_session("deep-research", "full")
        await tracker.update_session_status(s["id"], "completed")
        updated = await tracker.get_session(s["id"])
        assert updated["status"] == "completed"


class TestMessages:
    """消息管理测试"""

    async def test_add_and_get_messages(self, tracker):
        s = await tracker.create_session("deep-research", "full")
        await tracker.add_message(s["id"], "user", "Hello")
        await tracker.add_message(s["id"], "assistant", "Hi there", agent_name="test_agent")
        msgs = await tracker.get_messages(s["id"])
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["agent_name"] == "test_agent"

    async def test_messages_ordered_by_id(self, tracker):
        s = await tracker.create_session("deep-research", "full")
        await tracker.add_message(s["id"], "user", "First")
        await tracker.add_message(s["id"], "assistant", "Second")
        msgs = await tracker.get_messages(s["id"])
        assert msgs[0]["content"] == "First"
        assert msgs[1]["content"] == "Second"


class TestArtifacts:
    """产出物管理测试"""

    async def test_add_and_get_artifacts(self, tracker):
        s = await tracker.create_session("deep-research", "full")
        await tracker.add_artifact(s["id"], "draft", "# Draft Content")
        artifacts = await tracker.get_artifacts(s["id"])
        assert len(artifacts) == 1
        assert artifacts[0]["artifact_type"] == "draft"
        assert artifacts[0]["format"] == "markdown"


class TestSettings:
    """设置管理测试"""

    async def test_set_and_get_setting(self, tracker):
        await tracker.set_setting("model", "claude-sonnet-4-6")
        val = await tracker.get_setting("model")
        assert val == "claude-sonnet-4-6"

    async def test_get_setting_not_found(self, tracker):
        val = await tracker.get_setting("nonexistent")
        assert val is None

    async def test_encrypted_settings(self, tracker):
        """敏感 key（如 anthropic_api_key）应加密存储，读取时解密。"""
        await tracker.set_setting("anthropic_api_key", "sk-ant-secret-key-123")
        # 直接读 raw value（不经过 get_setting 解密）
        raw = await tracker.get_settings()
        stored = raw.get("anthropic_api_key", "")
        # 加密后的值不应等于原始值
        assert stored != "sk-ant-secret-key-123"
        # 通过 get_setting 应得到原始值
        val = await tracker.get_setting("anthropic_api_key")
        assert val == "sk-ant-secret-key-123"

    async def test_get_settings_returns_dict(self, tracker):
        await tracker.set_setting("model", "test-model")
        settings = await tracker.get_settings()
        assert isinstance(settings, dict)
        assert settings["model"] == "test-model"


class TestSessionDetail:
    """会话详情测试"""

    async def test_get_session_detail(self, tracker):
        s = await tracker.create_session("deep-research", "full")
        await tracker.add_message(s["id"], "user", "Hello")
        await tracker.add_artifact(s["id"], "report", "content")
        detail = await tracker.get_session_detail(s["id"])
        assert detail is not None
        assert "session" in detail
        assert len(detail["messages"]) == 1
        assert len(detail["artifacts"]) == 1
