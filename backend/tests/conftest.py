"""测试配置管理"""

import pytest
import sys
import pathlib

# 将 backend 目录加入 Python 路径
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def reset_config(tmp_path, monkeypatch):
    """每个测试使用独立的临时目录。"""
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(tmp_path / "test_ars.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(tmp_path / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(tmp_path / "workspaces"))
