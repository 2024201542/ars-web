"""每次改 PPT 之前存一版。撤销时先把当前状态存下来，再回到上一版。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

_KEEP = 20


def history_root() -> Path:
    override = os.environ.get("ARS_PPT_HISTORY_DIR", "")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data" / "ppt_history"


def folder_for(user_id: str, source: str, rel: str) -> Path:
    safe_user = re.sub(r"[^A-Za-z0-9_-]", "_", user_id or "user")[:80] or "user"
    key = hashlib.sha1(f"{source or ''}{rel or ''}".encode("utf-8")).hexdigest()[:12]
    return history_root() / safe_user / key


def _log_path(folder: Path) -> Path:
    return folder / "log.json"


def _read_log(folder: Path) -> list[dict]:
    path = _log_path(folder)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _write_log(folder: Path, rows: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    _log_path(folder).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _cursor(folder: Path) -> int:
    path = folder / "cursor.json"
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    try:
        return int((data or {}).get("current") or 0)
    except (TypeError, ValueError):
        return 0


def _set_cursor(folder: Path, version: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cursor.json").write_text(
        json.dumps({"current": int(version)}, ensure_ascii=False), encoding="utf-8")


def _previous(rows: list[dict], version: int) -> int | None:
    earlier = []
    for row in rows:
        try:
            number = int(row.get("version") or 0)
        except (TypeError, ValueError):
            continue
        if number < version:
            earlier.append(number)
    return max(earlier) if earlier else None


def _prune(folder: Path, rows: list[dict]) -> list[dict]:
    while len(rows) > _KEEP:
        old = rows.pop(0)
        try:
            number = int(old.get("version") or 0)
        except (TypeError, ValueError):
            number = 0
        for name in (f"v{number}.pptx", f"v{number}.plan.json"):
            target = folder / name
            if target.is_file():
                target.unlink()
    if rows and _cursor(folder) not in {int(row.get("version") or 0) for row in rows}:
        _set_cursor(folder, int(rows[0].get("version") or 0))
    return rows


def snapshot(user_id: str, pptx_path, plan_path, note: dict, *,
             source: str = "", rel: str = "", plan_source: str = "", plan_rel: str = "") -> int:
    """把当前 pptx 和计划原样复制成一个版本。返回版本号。"""
    folder = folder_for(user_id, source, rel or str(plan_path))
    folder.mkdir(parents=True, exist_ok=True)
    rows = _read_log(folder)
    version = 1 + max((int(row.get("version") or 0) for row in rows), default=0)
    deck = Path(pptx_path) if pptx_path else None
    plan = Path(plan_path) if plan_path else None
    if deck is not None and deck.is_file():
        shutil.copyfile(deck, folder / f"v{version}.pptx")
    if plan is not None and plan.is_file():
        shutil.copyfile(plan, folder / f"v{version}.plan.json")
    payload = note if isinstance(note, dict) else {}
    rows.append({
        "version": version,
        "at": datetime.now(timezone.utc).isoformat(),
        "instruction": str(payload.get("instruction") or ""),
        "ops": payload.get("ops") if isinstance(payload.get("ops"), list) else [],
        "changed_pages": payload.get("changed_pages") if isinstance(payload.get("changed_pages"), list) else [],
    })
    rows = _prune(folder, rows)
    _write_log(folder, rows)
    _set_cursor(folder, version)
    existing = {}
    meta_path = folder / "meta.json"
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    meta = {
        "source": source or existing.get("source") or "",
        "rel": rel or existing.get("rel") or "",
        "plan_source": plan_source or existing.get("plan_source") or source,
        "plan_rel": plan_rel or existing.get("plan_rel") or "",
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return version


def annotate(user_id: str, source: str, rel: str, version: int, changed_pages: list) -> None:
    folder = folder_for(user_id, source, rel)
    rows = _read_log(folder)
    for row in rows:
        if int(row.get("version") or 0) == int(version):
            row["changed_pages"] = list(changed_pages or [])
    _write_log(folder, rows)


def history(user_id: str, pptx_path=None, *, source: str = "", rel: str = "") -> list[dict]:
    folder = folder_for(user_id, source, rel or str(pptx_path or ""))
    return _read_log(folder)


def meta_of(user_id: str, source: str, rel: str) -> dict:
    folder = folder_for(user_id, source, rel)
    path = folder / "meta.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def restore(user_id: str, pptx_path, plan_path, version: int | None = None, *,
            source: str = "", rel: str = "") -> int:
    """先把当前文件存成一版，再把指定版本复制回去。不带版本号就回到上一版。"""
    folder = folder_for(user_id, source, rel or str(plan_path))
    rows = _read_log(folder)
    if not rows:
        return 0
    cursor = _cursor(folder)
    target = int(version) if version else cursor
    deck_src = folder / f"v{target}.pptx"
    plan_src = folder / f"v{target}.plan.json"
    if not deck_src.is_file() and not plan_src.is_file():
        return 0
    snapshot(user_id, pptx_path, plan_path,
             {"instruction": "撤销前的当前状态", "ops": [], "changed_pages": []},
             source=source, rel=rel or str(plan_path))
    if deck_src.is_file() and pptx_path:
        shutil.copyfile(deck_src, pptx_path)
    if plan_src.is_file() and plan_path:
        shutil.copyfile(plan_src, plan_path)
    rows = _read_log(folder)
    _set_cursor(folder, _previous(rows, target) or target)
    return target
