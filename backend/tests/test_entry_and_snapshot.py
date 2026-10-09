"""对话入口路由，以及改文件后的撤销快照。"""

from pathlib import Path

from services.edit_snapshot import diff_trees, restore_backup, snapshot_tree, store_backup
from services.entry_prompt import mode_instruction, resolve_chat_route
from config import PROXY_BASE_URL


def test_chat_entry_has_no_tools():
    allow, base = resolve_chat_route("deepseek", "", "chat")
    assert allow is False
    assert base == PROXY_BASE_URL


def test_deepseek_agent_uses_anthropic_endpoint():
    allow, base = resolve_chat_route("deepseek", "", "agent")
    assert allow is True
    assert base == "https://api.deepseek.com/anthropic"


def test_deepseek_default_base_still_uses_tool_endpoint():
    allow, base = resolve_chat_route("deepseek", "https://api.deepseek.com", "academic-paper")
    assert allow is True
    assert base == "https://api.deepseek.com/anthropic"


def test_custom_openai_base_stays_on_proxy():
    allow, base = resolve_chat_route("deepseek", "https://example.com/v1", "agent")
    assert allow is False
    assert base == PROXY_BASE_URL


def test_anthropic_chat_disables_tools():
    allow, base = resolve_chat_route("anthropic", "", "chat")
    assert allow is False
    assert base == ""


def test_mode_instruction_is_one_line():
    line = mode_instruction("academic-paper", "plan")
    assert "写作规划" in line
    assert "\n" not in line
    assert mode_instruction("chat", "chat") == ""
    assert mode_instruction("agent", "agent") == ""


def test_structure_map_draws_without_editing():
    line = mode_instruction("academic-paper", "structure-map")
    assert "论文结构图.html" in line
    assert "不要改" in line
    assert "不要用图片" in line
    assert "\n" not in line


def test_snapshot_diff_and_restore(tmp_path, monkeypatch):
    import services.edit_snapshot as snap

    root = tmp_path / "notes"
    root.mkdir()
    target = root / "试改.txt"
    target.write_text("甲\n", encoding="utf-8")
    before = snapshot_tree(root)
    target.write_text("乙\n", encoding="utf-8")
    (root / "新建.txt").write_text("新\n", encoding="utf-8")
    changes = diff_trees(before, snapshot_tree(root))
    actions = {item["path"]: item["action"] for item in changes}
    assert actions["试改.txt"] == "modified"
    assert actions["新建.txt"] == "created"

    backup_root = tmp_path / "backups"
    monkeypatch.setattr(snap, "BACKUP_ROOT", backup_root)
    backup_id = store_backup("user-1", root, before, changes, backup_root=backup_root)
    restored = restore_backup(backup_id, "user-1", root)
    assert target.read_text(encoding="utf-8") == "甲\n"
    assert not (root / "新建.txt").exists()
    assert {item["path"] for item in restored} == {"试改.txt", "新建.txt"}
    try:
        restore_backup(backup_id, "user-1", root)
        assert False, "second undo should fail"
    except ValueError as exc:
        assert "已经撤销" in str(exc)
