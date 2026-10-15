"""计划路径只能落在当前用户的目录里，出片同名不覆盖。"""

import pathlib

import pytest
from fastapi import HTTPException

from routers import template_library
from services.workspace_manager import workspace_manager


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    sandbox = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "pytest-env"
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(sandbox / "test_ars.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(sandbox / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(sandbox / "workspaces"))


@pytest.fixture()
def roots(monkeypatch):
    """不用 pytest 的 tmp_path（沙箱里 0o700 会失败），自己建目录。"""
    base = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "ppt_paths"
    user = base / "user"
    local = base / "local"
    outside = base / "outside"
    for folder in (user, local, outside):
        folder.mkdir(parents=True, exist_ok=True)

    async def local_root(_user_id):
        return local

    monkeypatch.setattr(workspace_manager, "get_local_root", local_root)
    monkeypatch.setattr(template_library, "user_dir", lambda _user_id: user)
    return user, local, outside


@pytest.mark.asyncio
async def test_relative_path_inside_user_dir(roots):
    user, _, _ = roots
    target = user / "generated" / "计划.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    found, rel, source = await template_library._resolve_user_file("u", "generated/计划.json", "site")
    assert found == target.resolve()
    assert rel.replace("\\", "/") == "generated/计划.json"
    assert source == "site"


@pytest.mark.asyncio
async def test_absolute_path_outside_is_forbidden(roots):
    _, _, outside = roots
    secret = outside / "secret.json"
    secret.write_text("{}", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        await template_library._resolve_user_file("u", str(secret))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_traversal_is_forbidden(roots):
    user, _, outside = roots
    secret = outside / "secret.json"
    secret.write_text("{}", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        await template_library._resolve_user_file("u", "../outside/secret.json", "site")
    assert exc.value.status_code == 403
    assert user.exists()


@pytest.mark.asyncio
async def test_builtin_base_cannot_be_overwritten():
    with pytest.raises(HTTPException) as exc:
        await template_library.put_template_base(
            "builtin-academic-red", template_library.BaseUpdate(base={"pages": {}}), "stu02")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_same_name_pptx_gets_a_suffix(roots):
    _, local, _ = roots
    first = await workspace_manager.save_generated_file("u", "汇报.pptx", b"one", target_dir=local)
    second = await workspace_manager.save_generated_file("u", "汇报.pptx", b"two", target_dir=local)
    assert first["name"] != second["name"]
    assert (local / first["name"]).read_bytes() == b"one"
    assert (local / second["name"]).read_bytes() == b"two"
