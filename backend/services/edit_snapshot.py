"""一轮对话开始前记下文稿，结束后对比，用来撤销这一轮的修改。"""

import json
import uuid
from pathlib import Path

from config import DB_PATH
from services.workspace_manager import SKIP_DIRS, TEXT_EDIT_EXTS, workspace_manager

BACKUP_ROOT = DB_PATH.parent / "edit_backups"
MAX_FILES = 400
MAX_FILE_BYTES = 512 * 1024
MAX_DOCX_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024


def snapshot_tree(root: Path) -> dict[str, bytes]:
    """记下目录里的文稿。只含 .md .txt .bib .tex。"""
    base = root.resolve()
    found: dict[str, bytes] = {}
    total = 0
    if not base.is_dir():
        return found
    for path in base.rglob("*"):
        if len(found) >= MAX_FILES or total >= MAX_TOTAL_BYTES:
            break
        try:
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(base)
        except (OSError, ValueError):
            continue
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel.parts):
            continue
        ext = path.suffix.lower()
        if ext not in TEXT_EDIT_EXTS and ext != ".docx":
            continue
        try:
            size = path.stat().st_size
            limit = MAX_DOCX_BYTES if ext == ".docx" else MAX_FILE_BYTES
            if size > limit or total + size > MAX_TOTAL_BYTES:
                continue
            found[rel.as_posix()] = path.read_bytes()
            total += size
        except OSError:
            continue
    return found


def diff_trees(before: dict[str, bytes], after: dict[str, bytes]) -> list[dict]:
    changes: list[dict] = []
    for rel, old in before.items():
        new = after.get(rel)
        if new is None:
            action = "deleted"
        elif new != old:
            action = "modified"
        else:
            continue
        changes.append({"path": rel, "name": Path(rel).name, "action": action})
    for rel in after:
        if rel not in before:
            changes.append({"path": rel, "name": Path(rel).name, "action": "created"})
    return changes


def store_backup(user_id: str, root: Path, before: dict[str, bytes], changes: list[dict], backup_root: Path | None = None) -> str:
    backup_id = uuid.uuid4().hex
    dest = (backup_root or BACKUP_ROOT) / backup_id
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for index, change in enumerate(changes):
        item = {"path": change["path"], "name": change["name"], "action": change["action"]}
        if change["action"] != "created":
            blob_name = f"{index}.bin"
            (dest / blob_name).write_bytes(before[change["path"]])
            item["blob"] = blob_name
        files.append(item)
    manifest = {
        "user_id": user_id,
        "root": str(root.resolve()),
        "restored": False,
        "files": files,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return backup_id


def commit_changes(user_id: str, root: Path, before: dict[str, bytes]) -> dict | None:
    changes = diff_trees(before, snapshot_tree(root))
    if not changes:
        return None
    backup_id = store_backup(user_id, root, before, changes)
    return {
        "backup_id": backup_id,
        "files": [{"path": item["path"], "name": item["name"], "action": item["action"]} for item in changes],
    }


def restore_backup(backup_id: str, user_id: str, current_root: Path) -> list[dict]:
    if not backup_id or len(backup_id) != 32 or any(ch not in "0123456789abcdef" for ch in backup_id):
        raise ValueError("没有这次修改的记录")
    dest = BACKUP_ROOT / backup_id
    manifest_path = dest / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("没有这次修改的记录")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("user_id") != user_id:
        raise ValueError("没有这次修改的记录")
    if manifest.get("restored"):
        raise ValueError("这次修改已经撤销过了")
    saved_root = Path(str(manifest.get("root") or "")).resolve()
    if saved_root != current_root.resolve():
        raise ValueError("文件夹已经换过，不能撤销这次修改")

    restored: list[dict] = []
    for item in manifest.get("files") or []:
        rel = str(item.get("path") or "")
        action = item.get("action")
        target = workspace_manager._resolve_inside(saved_root, rel, must_exist=False)
        if target is None:
            continue
        if action == "created":
            if target.is_file() and not target.is_symlink():
                target.unlink()
            restored.append({"path": rel, "action": action})
            continue
        blob_name = str(item.get("blob") or "")
        blob = (dest / blob_name).resolve()
        if not blob_name or not blob.is_file() or dest.resolve() not in blob.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob.read_bytes())
        restored.append({"path": rel, "action": action})

    manifest["restored"] = True
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return restored
