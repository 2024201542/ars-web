"""多人协作（类 GitHub 异步交接）API

流程：
1. 主稿方「发给对方继续」→ 生成邀请链接（只用于第一次认人）
2. 对方登录后接受 → 克隆会话，并出现在主稿方协作列表
3. 对方「交回审阅」→ 主稿方待处理
4. 主稿方「采纳进主稿」或「退回再改」
5. 采纳后对方副本刷新成最新主稿；主稿方可再点「请 TA 继续」（不必新链接）
6. 同一主稿同一时间只允许一人 editing / 一份 review_pending
"""

from __future__ import annotations

import difflib
import json
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deps import limiter
from services.state_tracker import tracker as state_tracker
from services.user_manager import get_user_id
from services.workspace_manager import session_dir

router = APIRouter(tags=["collab"])

# status: invite_pending | editing | review_pending | idle | rejected | revoked | merged(历史，视同 idle)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _normalize_status(status: Optional[str]) -> str:
    if status == "merged":
        return "idle"
    return status or ""


async def _ensure_tables():
    await state_tracker._ensure_initialized()
    await state_tracker._execute(
        """
        CREATE TABLE IF NOT EXISTS collab_handoffs (
            id TEXT PRIMARY KEY,
            token TEXT UNIQUE,
            root_session_id TEXT NOT NULL,
            parent_session_id TEXT NOT NULL,
            fork_session_id TEXT,
            from_user_id TEXT NOT NULL,
            to_user_id TEXT,
            status TEXT NOT NULL,
            note TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await state_tracker._execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_token ON collab_handoffs(token)"
    )
    await state_tracker._execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_root ON collab_handoffs(root_session_id)"
    )
    await state_tracker._execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_fork ON collab_handoffs(fork_session_id)"
    )
    await state_tracker._execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_to ON collab_handoffs(to_user_id, status)"
    )
    await state_tracker._execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_from ON collab_handoffs(from_user_id, status)"
    )
    # 基线快照：接续人开始本轮修改时的主稿消息（类 Git 的 branch point）
    cols = await state_tracker._fetchall("PRAGMA table_info(collab_handoffs)")
    col_names = {dict(c).get("name") for c in cols}
    if "baseline_json" not in col_names:
        await state_tracker._execute(
            "ALTER TABLE collab_handoffs ADD COLUMN baseline_json TEXT"
        )
    await state_tracker._execute(
        """
        CREATE TABLE IF NOT EXISTS collab_stashes (
            id TEXT PRIMARY KEY,
            handoff_id TEXT NOT NULL,
            root_session_id TEXT NOT NULL,
            partner_user_id TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    await state_tracker._execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_stash_h ON collab_stashes(handoff_id)"
    )
    await state_tracker._commit()


async def _get_handoff_by_token(token: str) -> Optional[dict]:
    rows = await state_tracker._fetchall(
        "SELECT * FROM collab_handoffs WHERE token = ?", (token,)
    )
    return dict(rows[0]) if rows else None


async def _get_handoff(handoff_id: str) -> Optional[dict]:
    rows = await state_tracker._fetchall(
        "SELECT * FROM collab_handoffs WHERE id = ?", (handoff_id,)
    )
    return dict(rows[0]) if rows else None


async def _update_handoff(handoff_id: str, **fields):
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [handoff_id]
    await state_tracker._execute(
        f"UPDATE collab_handoffs SET {cols} WHERE id = ?", vals
    )
    await state_tracker._commit()


async def _username(user_id: Optional[str]) -> str:
    if not user_id:
        return ""
    rows = await state_tracker._fetchall(
        "SELECT username, display_name FROM users WHERE id = ?", (user_id,)
    )
    if not rows:
        return user_id[:8]
    r = dict(rows[0])
    return r.get("display_name") or r.get("username") or user_id[:8]


def _author_metadata(existing, role: str, fallback: str) -> str:
    """保证消息 metadata 里有 author，便于预览和主稿区分是谁说的。"""
    parsed: dict = {}
    if isinstance(existing, str) and existing.strip():
        try:
            loaded = json.loads(existing)
            if isinstance(loaded, dict):
                parsed = loaded
        except Exception:
            parsed = {}
    elif isinstance(existing, dict):
        parsed = dict(existing)
    if not parsed.get("author"):
        parsed["author"] = fallback if role == "user" else "助手"
    return json.dumps(parsed, ensure_ascii=False)


async def _clear_session_content(session_id: str):
    await state_tracker._execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    await state_tracker._execute("DELETE FROM artifacts WHERE session_id = ?", (session_id,))
    await state_tracker._commit()


def _clear_claude_jsonl(session_id: str):
    """删除 Claude CLI 会话文件，避免刷新副本后误 resume 旧上下文。"""
    projects = Path.home() / ".claude" / "projects"
    if not projects.is_dir():
        return
    for cand in projects.glob(f"**/{session_id}.jsonl"):
        try:
            cand.unlink(missing_ok=True)
        except Exception:
            pass


async def _copy_content_into_session(source_id: str, dest_id: str, owner_name: str):
    """把源会话的消息/产出物/工作区写入目标会话（不新建会话）。"""
    messages = await state_tracker.get_messages(source_id)
    for m in messages:
        content = m.get("content") or ""
        if not str(content).strip():
            continue
        role = m.get("role") or "assistant"
        await state_tracker.add_message(
            dest_id,
            role,
            content,
            agent_name=m.get("agent_name"),
            phase_name=m.get("phase_name"),
            metadata=_author_metadata(m.get("metadata"), role, owner_name),
        )

    artifacts = await state_tracker.get_artifacts(source_id)
    for a in artifacts:
        await state_tracker.add_artifact(
            dest_id,
            a.get("artifact_type") or "markdown",
            a.get("content") or "",
            fmt=a.get("format") or "markdown",
        )

    try:
        src_dir = session_dir(source_id)
        dst_dir = session_dir(dest_id)
        if src_dir.exists() and src_dir.is_dir():
            if dst_dir.exists():
                shutil.rmtree(dst_dir, ignore_errors=True)
            shutil.copytree(src_dir, dst_dir)
    except Exception:
        pass

    await state_tracker._execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (_now(), dest_id),
    )
    await state_tracker._commit()


async def _clone_session(source_id: str, new_owner_id: str, title_suffix: str) -> dict:
    src = await state_tracker.get_session(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="源会话不存在")

    title = (src.get("title") or "学术研究会话").strip()
    if title_suffix and title_suffix not in title:
        title = f"{title} · {title_suffix}"

    new_session = await state_tracker.create_session(
        skill_name=src["skill_name"],
        mode_name=src["mode_name"],
        title=title[:120],
        user_id=new_owner_id,
    )
    new_id = new_session["id"]
    owner_name = await _username(src.get("user_id")) or "主稿方"
    await _copy_content_into_session(source_id, new_id, owner_name)
    return await state_tracker.get_session(new_id) or new_session


async def _refresh_fork_from_root(root_id: str, fork_id: str):
    """用最新主稿覆盖接续副本（会话 id 不变）。"""
    root = await state_tracker.get_session(root_id)
    if not root:
        raise HTTPException(status_code=404, detail="主稿不存在")
    fork = await state_tracker.get_session(fork_id)
    if not fork:
        raise HTTPException(status_code=404, detail="副本不存在")

    owner_name = await _username(root.get("user_id")) or "主稿方"
    await _clear_session_content(fork_id)
    _clear_claude_jsonl(fork_id)
    await _copy_content_into_session(root_id, fork_id, owner_name)


async def _merge_fork_into_root(root_id: str, fork_id: str, from_name: str):
    """将副本内容合并进主稿：追加分隔说明 + 副本消息，并用副本产出物覆盖主稿产出物。"""
    fork_messages = await state_tracker.get_messages(fork_id)
    await state_tracker.add_message(
        root_id,
        "assistant",
        f"——\n**【已采纳】** 已合并来自「{from_name}」交回的修改（{_now()}）。\n——",
        agent_name="collab",
        phase_name="merge",
    )
    for m in fork_messages:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        role = m.get("role") or "assistant"
        await state_tracker.add_message(
            root_id,
            role,
            content,
            agent_name=m.get("agent_name"),
            phase_name=m.get("phase_name"),
            metadata=_author_metadata(m.get("metadata"), role, from_name or "协作者"),
        )

    for a in await state_tracker.get_artifacts(fork_id):
        content = a.get("content") or ""
        if not str(content).strip():
            continue
        await state_tracker.add_artifact(
            root_id,
            a.get("artifact_type") or "markdown",
            content,
            fmt=a.get("format") or "markdown",
        )

    try:
        src_dir = session_dir(fork_id)
        dst_dir = session_dir(root_id)
        if src_dir.exists() and src_dir.is_dir():
            dst_dir.mkdir(parents=True, exist_ok=True)
            for item in src_dir.iterdir():
                target = dst_dir / item.name
                if item.is_dir():
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
    except Exception:
        pass

    await state_tracker._execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (_now(), root_id),
    )
    await state_tracker._commit()


async def _resolve_root_id(session_id: str) -> str:
    rows = await state_tracker._fetchall(
        "SELECT root_session_id FROM collab_handoffs WHERE fork_session_id = ? ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    )
    if rows:
        return dict(rows[0])["root_session_id"] or session_id
    return session_id


async def _find_partner_handoff(root_id: str, partner_user_id: str) -> Optional[dict]:
    """同一主稿 + 同一接续人：取最新一条已有副本的交接。"""
    rows = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE root_session_id = ? AND to_user_id = ?
          AND fork_session_id IS NOT NULL
          AND status != 'revoked'
        ORDER BY updated_at DESC LIMIT 1
        """,
        (root_id, partner_user_id),
    )
    return dict(rows[0]) if rows else None


async def _root_busy_handoff(root_id: str, exclude_id: Optional[str] = None) -> Optional[dict]:
    # rejected 表示退回后对方仍可改，同样占轮次
    rows = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE root_session_id = ?
          AND status IN ('editing', 'review_pending', 'rejected')
        ORDER BY updated_at DESC
        """,
        (root_id,),
    )
    for r in rows:
        d = dict(r)
        if exclude_id and d["id"] == exclude_id:
            continue
        return d
    return None


def _status_label(status: str) -> str:
    return {
        "editing": "正在修改",
        "review_pending": "已交回待审阅",
        "rejected": "已退回，对方可再改",
        "idle": "空闲（可请继续）",
        "merged": "空闲（可请继续）",
        "invite_pending": "待接受",
        "revoked": "已撤销",
    }.get(status, status or "未知")


def _extract_author(meta_raw, role: str, user_fallback: str) -> str:
    author = ""
    if isinstance(meta_raw, str) and meta_raw.strip():
        try:
            loaded = json.loads(meta_raw)
            if isinstance(loaded, dict):
                author = loaded.get("author") or ""
        except Exception:
            author = ""
    if not author:
        author = user_fallback if role == "user" else "助手"
    return author


def _line_diff(old: str, new: str) -> list[dict]:
    """段落/行级 diff，类似代码改动的红绿标记。"""
    old_lines = (old or "").splitlines() or [""]
    new_lines = (new or "").splitlines() or [""]
    # 过长时截断，避免预览爆炸
    if len(old_lines) > 80:
        old_lines = old_lines[:80] + ["…（主稿原文过长，已截断）"]
    if len(new_lines) > 80:
        new_lines = new_lines[:80] + ["…（副本原文过长，已截断）"]
    out: list[dict] = []
    for line in difflib.ndiff(old_lines, new_lines):
        if line.startswith("  "):
            out.append({"type": "same", "text": line[2:]})
        elif line.startswith("+ "):
            out.append({"type": "add", "text": line[2:]})
        elif line.startswith("- "):
            out.append({"type": "del", "text": line[2:]})
        # 忽略 ? 提示行
    return out[:200]


def _pack_msg(m: dict, change: str, partner_name: str, lines: Optional[list] = None) -> dict:
    content = (m.get("content") or "").strip()
    role = m.get("role") or "assistant"
    return {
        "role": role,
        "author": _extract_author(m.get("metadata"), role, partner_name),
        "content": content[:3000],
        "created_at": m.get("created_at"),
        "change": change,  # same | added | removed | changed
        "lines": lines,
    }


def _diff_fork_against_root(root_msgs: list[dict], fork_msgs: list[dict], partner_name: str) -> list[dict]:
    """对比主稿与副本消息，标出新增 / 删除 / 修改（含行级红绿）。"""
    root_clean = [m for m in root_msgs if (m.get("content") or "").strip()]
    fork_clean = [m for m in fork_msgs if (m.get("content") or "").strip()]
    a = [(m.get("role") or "", (m.get("content") or "").strip()) for m in root_clean]
    b = [(m.get("role") or "", (m.get("content") or "").strip()) for m in fork_clean]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    out: list[dict] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for m in fork_clean[j1:j2]:
                out.append(_pack_msg(m, "same", partner_name))
        elif tag == "insert":
            for m in fork_clean[j1:j2]:
                out.append(_pack_msg(m, "added", partner_name))
        elif tag == "delete":
            for m in root_clean[i1:i2]:
                # 主稿有、副本没有：用主稿内容展示为删除
                packed = _pack_msg(m, "removed", partner_name)
                packed["author"] = _extract_author(m.get("metadata"), m.get("role") or "assistant", "主稿")
                out.append(packed)
        elif tag == "replace":
            root_slice = root_clean[i1:i2]
            fork_slice = fork_clean[j1:j2]
            # 一一对应时做行级 diff；否则分别标删除/新增
            pairs = min(len(root_slice), len(fork_slice))
            for k in range(pairs):
                old_c = (root_slice[k].get("content") or "").strip()
                new_c = (fork_slice[k].get("content") or "").strip()
                if old_c == new_c and (root_slice[k].get("role") == fork_slice[k].get("role")):
                    out.append(_pack_msg(fork_slice[k], "same", partner_name))
                else:
                    out.append(
                        _pack_msg(
                            fork_slice[k],
                            "changed",
                            partner_name,
                            lines=_line_diff(old_c, new_c),
                        )
                    )
            for m in root_slice[pairs:]:
                packed = _pack_msg(m, "removed", partner_name)
                packed["author"] = _extract_author(m.get("metadata"), m.get("role") or "assistant", "主稿")
                out.append(packed)
            for m in fork_slice[pairs:]:
                out.append(_pack_msg(m, "added", partner_name))

    # 预览窗口只留尾部，但优先保留有改动的条目
    if len(out) <= 50:
        return out
    changed = [x for x in out if x.get("change") != "same"]
    same_tail = [x for x in out if x.get("change") == "same"][-10:]
    merged = same_tail + changed
    return merged[-60:]


def _normalize_msg_list(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        out.append({"role": m.get("role") or "assistant", "content": content})
    return out


def _parse_baseline(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, list):
        return _normalize_msg_list(raw)
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, list):
            return _normalize_msg_list(loaded)
    except Exception:
        pass
    return []


def _msgs_fingerprint(msgs: list[dict]) -> list[tuple]:
    return [(m.get("role") or "", m.get("content") or "") for m in msgs]


def _delta_messages(base: list[dict], newer: list[dict]) -> list[dict]:
    """相对基线，newer 里新增或替换出来的消息（对方的「提交」）。"""
    a = _msgs_fingerprint(base)
    b = _msgs_fingerprint(newer)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    delta: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            delta.extend(newer[j1:j2])
    return delta


def _analyze_three_way(base: list[dict], ours: list[dict], theirs: list[dict]) -> dict:
    """类 Git 三方：base=开改时主稿，ours=当前主稿，theirs=交回副本。"""
    base_n = _normalize_msg_list(base)
    ours_n = _normalize_msg_list(ours)
    theirs_n = _normalize_msg_list(theirs)
    root_diverged = _msgs_fingerprint(ours_n) != _msgs_fingerprint(base_n)
    ours_delta = _delta_messages(base_n, ours_n)
    theirs_delta = _delta_messages(base_n, theirs_n)
    has_conflict = bool(root_diverged and ours_delta and theirs_delta)
    return {
        "root_diverged": root_diverged,
        "has_conflict": has_conflict,
        "ours_delta_count": len(ours_delta),
        "theirs_delta_count": len(theirs_delta),
        "ours_delta": [
            {"role": m["role"], "content": m["content"][:1500]} for m in ours_delta[-12:]
        ],
        "theirs_delta": [
            {"role": m["role"], "content": m["content"][:1500]} for m in theirs_delta[-12:]
        ],
        "theirs_delta_full": theirs_delta,
        "hint": (
            "主稿在对方修改期间也有变动，采纳前请选择如何处理对方改动"
            if has_conflict
            else (
                "主稿在对方修改期间有变动，但可安全并入对方新增内容"
                if root_diverged and theirs_delta
                else "主稿未在对方修改期间改动，将只并入对方相对基线的改动"
            )
        ),
    }


async def _snapshot_session_messages(session_id: str) -> list[dict]:
    msgs = await state_tracker.get_messages(session_id)
    return _normalize_msg_list(msgs)


async def _save_baseline_from_root(handoff_id: str, root_id: str):
    snap = await _snapshot_session_messages(root_id)
    await _update_handoff(
        handoff_id,
        baseline_json=json.dumps(snap, ensure_ascii=False),
    )


async def _fork_has_local_changes(h: dict) -> bool:
    """副本相对基线是否有未交回的本地改动。"""
    fork_id = h.get("fork_session_id")
    if not fork_id:
        return False
    baseline = _parse_baseline(h.get("baseline_json"))
    fork_msgs = await _snapshot_session_messages(fork_id)
    if not baseline:
        # 无基线时：与当前主稿比，不同则视为有本地内容
        root_msgs = await _snapshot_session_messages(h["root_session_id"])
        return _msgs_fingerprint(fork_msgs) != _msgs_fingerprint(root_msgs)
    return _msgs_fingerprint(fork_msgs) != _msgs_fingerprint(baseline)


async def _stash_fork_content(h: dict, note: str = "") -> str:
    fork_id = h.get("fork_session_id")
    snap = await _snapshot_session_messages(fork_id)
    stash_id = secrets.token_hex(12)
    await state_tracker._execute(
        """
        INSERT INTO collab_stashes
        (id, handoff_id, root_session_id, partner_user_id, snapshot_json, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stash_id,
            h["id"],
            h["root_session_id"],
            h.get("to_user_id"),
            json.dumps(snap, ensure_ascii=False),
            (note or "请继续前自动保存的未交回草稿")[:200],
            _now(),
        ),
    )
    await state_tracker._commit()
    return stash_id


async def _append_messages_to_root(root_id: str, messages: list[dict], from_name: str, mode_label: str):
    await state_tracker.add_message(
        root_id,
        "assistant",
        f"——\n**【已采纳 · {mode_label}】** 已合并来自「{from_name}」的改动（{_now()}）。\n——",
        agent_name="collab",
        phase_name="merge",
    )
    for m in messages:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        role = m.get("role") or "assistant"
        await state_tracker.add_message(
            root_id,
            role,
            content,
            agent_name=m.get("agent_name"),
            phase_name=m.get("phase_name"),
            metadata=_author_metadata(m.get("metadata"), role, from_name or "协作者"),
        )
    await state_tracker._execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (_now(), root_id),
    )
    await state_tracker._commit()


async def _copy_fork_artifacts_and_files(root_id: str, fork_id: str):
    for a in await state_tracker.get_artifacts(fork_id):
        content = a.get("content") or ""
        if not str(content).strip():
            continue
        await state_tracker.add_artifact(
            root_id,
            a.get("artifact_type") or "markdown",
            content,
            fmt=a.get("format") or "markdown",
        )
    try:
        src_dir = session_dir(fork_id)
        dst_dir = session_dir(root_id)
        if src_dir.exists() and src_dir.is_dir():
            dst_dir.mkdir(parents=True, exist_ok=True)
            for item in src_dir.iterdir():
                target = dst_dir / item.name
                if item.is_dir():
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
    except Exception:
        pass


async def _list_partners(root_id: str) -> list[dict]:
    """主稿方界面：已接受的人（每人一条，最新交接）。"""
    rows = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE root_session_id = ?
          AND to_user_id IS NOT NULL
          AND fork_session_id IS NOT NULL
          AND status != 'revoked'
        ORDER BY updated_at DESC
        """,
        (root_id,),
    )
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        uid = d.get("to_user_id")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        st = d.get("status") or ""
        norm = _normalize_status(st)
        dirty = False
        if norm == "idle":
            try:
                dirty = await _fork_has_local_changes(d)
            except Exception:
                dirty = False
        out.append(
            {
                "handoff_id": d["id"],
                "partner_user_id": uid,
                "partner_name": await _username(uid),
                "fork_session_id": d.get("fork_session_id"),
                "status": st,
                "status_norm": norm,
                "status_label": _status_label(st),
                "note": d.get("note") or "",
                "can_request_continue": norm == "idle",
                "has_local_changes": dirty,
                "updated_at": d.get("updated_at"),
            }
        )
    return out


class InviteCreateRequest(BaseModel):
    expires_days: int = Field(default=7, ge=1, le=90)


class NoteRequest(BaseModel):
    note: str = ""


class RequestEditRequest(BaseModel):
    force: bool = False


class MergeRequest(BaseModel):
    # append_theirs: 保留主稿并并入对方相对基线的改动（默认/冲突时的「两边都要」）
    # keep_ours_only: 不并入对方文字改动（仍可拷贝产出物可选——这里不拷贝消息）
    # full_fork: 旧行为，整份副本消息追加（兼容）
    mode: str = Field(default="append_theirs")


@router.post("/api/sessions/{session_id}/collab/invite")
@limiter.limit("30/hour")
async def create_invite(
    request: Request,
    session_id: str,
    req: InviteCreateRequest,
    user_id: str = Depends(get_user_id),
):
    await _ensure_tables()
    session = await state_tracker.get_session(session_id)
    if not session or session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = await state_tracker.get_messages(session_id)
    if not any((m.get("content") or "").strip() for m in messages):
        raise HTTPException(status_code=400, detail="会话暂无内容，无法发给对方")

    root_id = await _resolve_root_id(session_id)

    token = secrets.token_urlsafe(24)
    handoff_id = secrets.token_hex(16)
    now = _now()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=req.expires_days)).isoformat()

    await state_tracker._execute(
        """
        INSERT INTO collab_handoffs
        (id, token, root_session_id, parent_session_id, fork_session_id, from_user_id, to_user_id,
         status, note, expires_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, NULL, ?, NULL, 'invite_pending', NULL, ?, ?, ?)
        """,
        (handoff_id, token, root_id, session_id, user_id, expires_at, now, now),
    )
    await state_tracker._commit()

    return {
        "id": handoff_id,
        "token": token,
        "url_path": f"/#/collab/{token}",
        "expires_at": expires_at,
        "title": session.get("title") or "学术研究会话",
        "root_session_id": root_id,
    }


@router.get("/api/collab/invites/{token}")
async def preview_invite(token: str, user_id: str = Depends(get_user_id)):
    """登录后预览邀请（接受前）。"""
    await _ensure_tables()
    h = await _get_handoff_by_token(token)
    if not h:
        raise HTTPException(status_code=404, detail="邀请不存在或链接无效")
    if h.get("status") == "revoked":
        raise HTTPException(status_code=410, detail="邀请已撤销")
    exp = _parse_iso(h.get("expires_at"))
    if exp and exp < datetime.now(timezone.utc) and h.get("status") == "invite_pending":
        raise HTTPException(status_code=410, detail="邀请已过期")

    parent = await state_tracker.get_session(h["parent_session_id"])
    messages = await state_tracker.get_messages(h["parent_session_id"]) if parent else []
    preview = []
    for m in messages[-6:]:
        c = (m.get("content") or "").strip()
        if c:
            preview.append({"role": m.get("role"), "content": c[:500]})

    existing = None
    if h.get("root_session_id"):
        existing = await _find_partner_handoff(h["root_session_id"], user_id)

    return {
        "id": h["id"],
        "status": h["status"],
        "expires_at": h.get("expires_at"),
        "from_user": await _username(h["from_user_id"]),
        "title": (parent or {}).get("title") or "学术研究会话",
        "skill_name": (parent or {}).get("skill_name"),
        "mode_name": (parent or {}).get("mode_name"),
        "message_count": len(messages),
        "preview_messages": preview,
        "fork_session_id": (existing or h).get("fork_session_id") if existing else h.get("fork_session_id"),
        "already_accepted_by_me": bool(existing) or (
            h.get("to_user_id") == user_id and bool(h.get("fork_session_id"))
        ),
        "is_own_invite": h.get("from_user_id") == user_id,
    }


@router.post("/api/collab/invites/{token}/accept")
@limiter.limit("30/hour")
async def accept_invite(request: Request, token: str, user_id: str = Depends(get_user_id)):
    await _ensure_tables()
    h = await _get_handoff_by_token(token)
    if not h:
        raise HTTPException(status_code=404, detail="邀请不存在或链接无效")
    if h.get("from_user_id") == user_id:
        raise HTTPException(status_code=400, detail="不能接受自己发出的邀请，请用另一个账号打开")
    if h.get("status") == "revoked":
        raise HTTPException(status_code=410, detail="邀请已撤销")
    exp = _parse_iso(h.get("expires_at"))
    if exp and exp < datetime.now(timezone.utc) and h.get("status") == "invite_pending":
        raise HTTPException(status_code=410, detail="邀请已过期")

    root_id = h["root_session_id"]

    # 同一主稿已接受过：直接打开已有副本（不必新 fork）
    existing = await _find_partner_handoff(root_id, user_id)
    if existing:
        if h["id"] != existing["id"] and h.get("status") == "invite_pending":
            await _update_handoff(h["id"], status="revoked", token=None)
        fork = await state_tracker.get_session(existing["fork_session_id"])
        return {
            "handoff_id": existing["id"],
            "session_id": existing["fork_session_id"],
            "skill_name": (fork or {}).get("skill_name"),
            "already": True,
            "status": existing.get("status"),
            "message": "你已是这篇主稿的接续人，已打开原有副本",
        }

    if h.get("fork_session_id") and h.get("to_user_id") == user_id:
        fork = await state_tracker.get_session(h["fork_session_id"])
        return {
            "handoff_id": h["id"],
            "session_id": h["fork_session_id"],
            "skill_name": (fork or {}).get("skill_name"),
            "already": True,
            "status": h.get("status"),
        }

    if h.get("status") != "invite_pending":
        if h.get("to_user_id") == user_id and h.get("fork_session_id"):
            fork = await state_tracker.get_session(h["fork_session_id"])
            return {
                "handoff_id": h["id"],
                "session_id": h["fork_session_id"],
                "skill_name": (fork or {}).get("skill_name"),
                "already": True,
                "status": h.get("status"),
            }
        raise HTTPException(status_code=409, detail="该邀请已被他人接受或已结束")

    busy = await _root_busy_handoff(root_id)
    initial_status = "idle" if busy else "editing"

    fork = await _clone_session(h["parent_session_id"], user_id, "接续")
    await _update_handoff(
        h["id"],
        fork_session_id=fork["id"],
        to_user_id=user_id,
        status=initial_status,
    )
    # 记下开改基线（相对 parent/root 当时内容），供之后三方合并
    baseline_src = h.get("parent_session_id") or root_id
    await _save_baseline_from_root(h["id"], baseline_src)

    msg = "已接受，可以开始修改"
    if busy:
        who = await _username(busy.get("to_user_id")) or "其他人"
        msg = f"已加入主稿方的协作列表；当前轮到「{who}」，请等待主稿方请你继续"

    return {
        "handoff_id": h["id"],
        "session_id": fork["id"],
        "skill_name": fork.get("skill_name"),
        "already": False,
        "status": initial_status,
        "message": msg,
    }


@router.post("/api/sessions/{session_id}/collab/submit")
async def submit_for_review(
    session_id: str,
    req: NoteRequest,
    user_id: str = Depends(get_user_id),
):
    await _ensure_tables()
    session = await state_tracker.get_session(session_id)
    if not session or session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    rows = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE fork_session_id = ? AND to_user_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (session_id, user_id),
    )
    if not rows:
        raise HTTPException(status_code=400, detail="当前会话不是协作副本，无法交回")
    h = dict(rows[0])
    if h["status"] not in ("editing", "rejected"):
        raise HTTPException(status_code=409, detail=f"当前状态不可交回（{_status_label(h['status'])}）")

    await _update_handoff(h["id"], status="review_pending", note=(req.note or "").strip()[:500] or None)
    return {"ok": True, "handoff_id": h["id"], "message": "已交回，等待对方审阅"}


@router.get("/api/collab/handoffs/{handoff_id}/preview")
async def preview_handoff(handoff_id: str, user_id: str = Depends(get_user_id)):
    """主稿方在采纳前预览：双边 diff + 三方（基线/主稿/副本）冲突提示。"""
    await _ensure_tables()
    h = await _get_handoff(handoff_id)
    if not h:
        raise HTTPException(status_code=404, detail="交接不存在")
    root = await state_tracker.get_session(h["root_session_id"])
    if not root or root.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="只有主稿方可以预览交回内容")
    fork_id = h.get("fork_session_id")
    if not fork_id:
        raise HTTPException(status_code=400, detail="还没有可预览的副本")

    partner_name = await _username(h.get("to_user_id")) or "协作者"
    root_messages = await state_tracker.get_messages(h["root_session_id"])
    fork_messages = await state_tracker.get_messages(fork_id)
    preview = _diff_fork_against_root(root_messages, fork_messages, partner_name)
    counts = {"same": 0, "added": 0, "removed": 0, "changed": 0}
    for m in preview:
        k = m.get("change") or "same"
        if k in counts:
            counts[k] += 1

    baseline = _parse_baseline(h.get("baseline_json"))
    if not baseline:
        # 旧交接无基线：用副本与主稿的公共前缀近似
        baseline = _normalize_msg_list(root_messages)
    three_way = _analyze_three_way(baseline, root_messages, fork_messages)
    # 不把完整 delta 返回给前端（太大）
    three_way_out = {k: v for k, v in three_way.items() if k != "theirs_delta_full"}

    return {
        "handoff_id": h["id"],
        "status": h["status"],
        "note": h.get("note") or "",
        "from_user": partner_name,
        "fork_title": (await state_tracker.get_session(fork_id) or {}).get("title") or "副本",
        "messages": preview,
        "diff_summary": counts,
        "three_way": three_way_out,
    }


@router.post("/api/collab/handoffs/{handoff_id}/merge")
async def merge_handoff(
    handoff_id: str,
    req: MergeRequest = MergeRequest(),
    user_id: str = Depends(get_user_id),
):
    await _ensure_tables()
    h = await _get_handoff(handoff_id)
    if not h:
        raise HTTPException(status_code=404, detail="交接不存在")
    root = await state_tracker.get_session(h["root_session_id"])
    if not root or root.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="只有主稿方可以采纳")
    if h["status"] != "review_pending":
        raise HTTPException(status_code=409, detail="当前没有待审阅的交回")
    if not h.get("fork_session_id"):
        raise HTTPException(status_code=400, detail="缺少副本会话")

    mode = (req.mode or "append_theirs").strip()
    if mode not in ("append_theirs", "keep_ours_only", "full_fork"):
        raise HTTPException(status_code=400, detail="无效的合并方式")

    from_name = await _username(h.get("to_user_id")) or "协作者"
    root_id = h["root_session_id"]
    fork_id = h["fork_session_id"]
    root_messages = await state_tracker.get_messages(root_id)
    fork_messages = await state_tracker.get_messages(fork_id)
    baseline = _parse_baseline(h.get("baseline_json"))
    if not baseline:
        baseline = _normalize_msg_list(root_messages)

    three_way = _analyze_three_way(baseline, root_messages, fork_messages)

    if mode == "full_fork":
        await _merge_fork_into_root(root_id, fork_id, from_name)
        label = "整份副本"
    elif mode == "keep_ours_only":
        await state_tracker.add_message(
            root_id,
            "assistant",
            f"——\n**【已审阅 · 仅保留主稿】** 「{from_name}」的交回未并入正文（{_now()}）。\n——",
            agent_name="collab",
            phase_name="merge",
        )
        label = "仅保留主稿"
    else:
        # append_theirs：只并入相对基线的对方改动（类 Git merge 保留双方）
        delta = three_way.get("theirs_delta_full") or []
        if not delta:
            # 无纯增量时退回整份追加，避免「采纳了但什么都没发生」
            await _merge_fork_into_root(root_id, fork_id, from_name)
            label = "整份副本（无增量基线）"
        else:
            label = "并入对方改动" if three_way.get("has_conflict") or three_way.get("root_diverged") else "增量合并"
            await _append_messages_to_root(root_id, delta, from_name, label)
            await _copy_fork_artifacts_and_files(root_id, fork_id)

    await _refresh_fork_from_root(root_id, fork_id)
    await _update_handoff(h["id"], status="idle", note=None, baseline_json=None)
    return {
        "ok": True,
        "root_session_id": root_id,
        "skill_name": root.get("skill_name"),
        "mode": mode,
        "three_way": {k: v for k, v in three_way.items() if k != "theirs_delta_full"},
        "message": f"已处理交回（{label}），对方副本已刷新为最新主稿",
    }


@router.post("/api/collab/handoffs/{handoff_id}/reject")
async def reject_handoff(
    handoff_id: str,
    req: NoteRequest,
    user_id: str = Depends(get_user_id),
):
    await _ensure_tables()
    h = await _get_handoff(handoff_id)
    if not h:
        raise HTTPException(status_code=404, detail="交接不存在")
    root = await state_tracker.get_session(h["root_session_id"])
    if not root or root.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="只有主稿方可以退回")
    if h["status"] != "review_pending":
        raise HTTPException(status_code=409, detail="当前没有待审阅的交回")

    note = (req.note or "").strip()[:500]
    await _update_handoff(h["id"], status="rejected", note=note or h.get("note"))
    return {"ok": True, "message": "已退回，对方可继续修改后再交回"}


@router.post("/api/collab/handoffs/{handoff_id}/request-edit")
async def request_partner_edit(
    handoff_id: str,
    req: RequestEditRequest = RequestEditRequest(),
    user_id: str = Depends(get_user_id),
):
    """主稿方请已记住的接续人继续改。若对方副本有未交回改动，需 force 才会先存草稿再覆盖同步。"""
    await _ensure_tables()
    h = await _get_handoff(handoff_id)
    if not h:
        raise HTTPException(status_code=404, detail="交接不存在")
    root = await state_tracker.get_session(h["root_session_id"])
    if not root or root.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="只有主稿方可以请对方继续")
    if not h.get("to_user_id") or not h.get("fork_session_id"):
        raise HTTPException(status_code=400, detail="对方尚未接受，无法请继续")

    st = _normalize_status(h.get("status"))
    if st != "idle":
        raise HTTPException(
            status_code=409,
            detail=f"当前状态不可请继续（{_status_label(h.get('status'))}）",
        )

    busy = await _root_busy_handoff(h["root_session_id"], exclude_id=h["id"])
    if busy:
        who = await _username(busy.get("to_user_id")) or "其他人"
        raise HTTPException(
            status_code=409,
            detail=f"当前轮到「{who}」（{_status_label(busy.get('status'))}），请等其交回或审阅完成后再请下一位",
        )

    dirty = await _fork_has_local_changes(h)
    name = await _username(h.get("to_user_id"))
    if dirty and not req.force:
        return {
            "ok": False,
            "needs_confirm": True,
            "has_local_changes": True,
            "partner_name": name,
            "handoff_id": h["id"],
            "message": f"「{name}」的副本里还有未交回的修改。若继续，会先存成草稿再同步最新主稿（未交回内容不会进主稿，但可找回草稿）。",
        }

    stashed = None
    if dirty and req.force:
        stashed = await _stash_fork_content(h, note="请继续前自动保存")

    await _refresh_fork_from_root(h["root_session_id"], h["fork_session_id"])
    await _save_baseline_from_root(h["id"], h["root_session_id"])
    await _update_handoff(h["id"], status="editing", note=None)
    msg = f"已请「{name}」继续修改（已同步最新主稿）"
    if stashed:
        msg += "；其未交回内容已存为草稿"
    return {
        "ok": True,
        "handoff_id": h["id"],
        "partner_name": name,
        "fork_session_id": h["fork_session_id"],
        "stashed": bool(stashed),
        "stash_id": stashed,
        "message": msg,
    }


@router.post("/api/collab/handoffs/{handoff_id}/revoke")
async def revoke_invite(handoff_id: str, user_id: str = Depends(get_user_id)):
    await _ensure_tables()
    h = await _get_handoff(handoff_id)
    if not h:
        raise HTTPException(status_code=404, detail="交接不存在")
    if h.get("from_user_id") != user_id:
        # 主稿方也可撤销未接受邀请
        root = await state_tracker.get_session(h["root_session_id"])
        if not root or root.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="只能撤销自己发出的邀请")
    if h["status"] != "invite_pending":
        raise HTTPException(status_code=409, detail="仅未接受的邀请可撤销")
    await _update_handoff(h["id"], status="revoked", token=None)
    return {"ok": True}


@router.get("/api/collab/inbox")
async def collab_inbox(user_id: str = Depends(get_user_id)):
    """待我处理：别人交回给我审阅的 + 我被退回可再改的 + 主稿方请我继续。"""
    await _ensure_tables()
    review_rows = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE status = 'review_pending'
          AND root_session_id IN (SELECT id FROM sessions WHERE user_id = ?)
        ORDER BY updated_at DESC
        """,
        (user_id,),
    )
    rejected_rows = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE status = 'rejected' AND to_user_id = ?
        ORDER BY updated_at DESC
        """,
        (user_id,),
    )
    turn_rows = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE status = 'editing' AND to_user_id = ?
        ORDER BY updated_at DESC
        """,
        (user_id,),
    )

    async def _pack(rows, kind: str):
        out = []
        for r in rows:
            d = dict(r)
            root = await state_tracker.get_session(d["root_session_id"])
            fork = await state_tracker.get_session(d["fork_session_id"]) if d.get("fork_session_id") else None
            out.append(
                {
                    "id": d["id"],
                    "kind": kind,
                    "status": d["status"],
                    "note": d.get("note"),
                    "updated_at": d.get("updated_at"),
                    "root_session_id": d["root_session_id"],
                    "fork_session_id": d.get("fork_session_id"),
                    "root_title": (root or {}).get("title") or "主稿",
                    "fork_title": (fork or {}).get("title") or "副本",
                    "skill_name": (root or fork or {}).get("skill_name"),
                    "from_user": await _username(
                        d.get("to_user_id") if kind == "review" else d.get("from_user_id")
                    ),
                    "to_user": await _username(
                        d.get("from_user_id") if kind == "review" else d.get("to_user_id")
                    ),
                }
            )
        return out

    reviews = await _pack(review_rows, "review")
    rejected = await _pack(rejected_rows, "rejected")
    turns = await _pack(turn_rows, "your_turn")

    # 空闲接续人：若主稿正被他人占用，给出等待提醒
    idle_rows = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE status IN ('idle', 'merged') AND to_user_id = ?
          AND fork_session_id IS NOT NULL
        ORDER BY updated_at DESC
        """,
        (user_id,),
    )
    waiting = []
    seen_roots: set[str] = set()
    for r in idle_rows:
        d = dict(r)
        rid = d["root_session_id"]
        if rid in seen_roots:
            continue
        seen_roots.add(rid)
        busy = await _root_busy_handoff(rid)
        if not busy or busy.get("to_user_id") == user_id:
            continue
        root = await state_tracker.get_session(rid)
        fork = await state_tracker.get_session(d["fork_session_id"]) if d.get("fork_session_id") else None
        waiting.append(
            {
                "id": d["id"] + ":wait",
                "kind": "waiting",
                "status": d["status"],
                "note": None,
                "updated_at": busy.get("updated_at") or d.get("updated_at"),
                "root_session_id": rid,
                "fork_session_id": d.get("fork_session_id"),
                "root_title": (root or {}).get("title") or "主稿",
                "fork_title": (fork or {}).get("title") or "副本",
                "skill_name": (root or fork or {}).get("skill_name"),
                "from_user": await _username(busy.get("to_user_id")),
                "to_user": await _username(user_id),
                "busy_status_label": _status_label(busy.get("status")),
            }
        )

    # 我已交回、等主稿方审阅
    my_submitted = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE status = 'review_pending' AND to_user_id = ?
        ORDER BY updated_at DESC
        """,
        (user_id,),
    )
    submitted = await _pack(my_submitted, "submitted")

    return {
        "data": reviews + turns + rejected + waiting + submitted,
        "review_count": len(reviews),
        "rejected_count": len(rejected),
        "turn_count": len(turns),
        "waiting_count": len(waiting),
        "submitted_count": len(submitted),
        "alert_count": len(reviews) + len(turns) + len(rejected) + len(waiting),
    }


@router.get("/api/sessions/{session_id}/collab")
async def session_collab_state(session_id: str, user_id: str = Depends(get_user_id)):
    """当前会话的协作状态（用于按钮显隐与搭档列表）。"""
    await _ensure_tables()
    session = await state_tracker.get_session(session_id)
    if not session or session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    as_fork = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs WHERE fork_session_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (session_id,),
    )
    fork_h = dict(as_fork[0]) if as_fork else None
    root_id = fork_h["root_session_id"] if fork_h else session_id

    # 主稿会话：列出已接受的接续人
    is_root_owner = (not fork_h) and session.get("user_id") == user_id
    partners = await _list_partners(root_id) if is_root_owner else []

    as_root_pending = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE root_session_id = ? AND status = 'review_pending'
        ORDER BY updated_at DESC LIMIT 5
        """,
        (root_id if is_root_owner else session_id,),
    ) if is_root_owner else []

    my_invites = await state_tracker._fetchall(
        """
        SELECT id, token, status, expires_at, created_at FROM collab_handoffs
        WHERE parent_session_id = ? AND from_user_id = ? AND status = 'invite_pending'
        ORDER BY created_at DESC LIMIT 5
        """,
        (session_id, user_id),
    ) if is_root_owner else []

    busy = await _root_busy_handoff(root_id)
    active_editor = None
    if busy and busy.get("to_user_id"):
        active_editor = {
            "handoff_id": busy["id"],
            "partner_user_id": busy["to_user_id"],
            "partner_name": await _username(busy["to_user_id"]),
            "status": busy["status"],
            "status_label": _status_label(busy["status"]),
            "is_me": busy.get("to_user_id") == user_id,
        }

    fork_status = fork_h["status"] if fork_h else None
    can_submit = bool(fork_h and fork_h["status"] in ("editing", "rejected"))
    wait_reason = ""
    banner = ""
    banner_kind = ""  # your_turn | waiting_slot | submitted | rejected | idle
    if fork_h:
        if fork_h["status"] in ("editing",):
            banner_kind = "your_turn"
            banner = "主稿方已请你继续修改。改完后可先预览差异，再交回主稿方审阅。"
        elif fork_h["status"] == "rejected":
            banner_kind = "rejected"
            banner = "主稿方已退回，请按说明继续修改后再交回。"
            if fork_h.get("note"):
                banner += f"（说明：{fork_h['note']}）"
        elif fork_h["status"] == "review_pending":
            banner_kind = "submitted"
            banner = "已交回，等待主稿方预览并决定是否并入主稿。"
        elif _normalize_status(fork_status) == "idle":
            if active_editor and not active_editor.get("is_me"):
                banner_kind = "waiting_slot"
                banner = f"稿子正由「{active_editor['partner_name']}」修改（{active_editor['status_label']}），请等待轮到你。"
                wait_reason = banner
            else:
                banner_kind = "idle"
                banner = "等待主稿方再次请你继续修改。"
                wait_reason = banner
        if not wait_reason and not can_submit:
            wait_reason = banner or f"当前不可交回（{_status_label(fork_status)}）"

    return {
        "is_fork": bool(fork_h),
        "is_root_owner": is_root_owner,
        "can_invite": is_root_owner,
        "can_submit": can_submit,
        "wait_reason": wait_reason,
        "banner": banner,
        "banner_kind": banner_kind,
        "fork_status": fork_status,
        "fork_status_label": _status_label(fork_status) if fork_status else None,
        "handoff_id": fork_h["id"] if fork_h else None,
        "root_session_id": root_id,
        "partners": partners,
        "active_editor": active_editor,
        "pending_reviews": [
            {
                "id": dict(r)["id"],
                "from_user": await _username(dict(r).get("to_user_id")),
                "note": dict(r).get("note"),
                "fork_session_id": dict(r).get("fork_session_id"),
                "updated_at": dict(r).get("updated_at"),
            }
            for r in as_root_pending
        ],
        "open_invites": [
            {
                "id": dict(r)["id"],
                "token": dict(r).get("token"),
                "url_path": f"/#/collab/{dict(r)['token']}" if dict(r).get("token") else None,
                "expires_at": dict(r).get("expires_at"),
            }
            for r in my_invites
            if dict(r).get("token")
        ],
    }


@router.get("/api/sessions/{session_id}/collab/diff-preview")
async def fork_diff_preview(session_id: str, user_id: str = Depends(get_user_id)):
    """接续方交回前：预览自己相对基线/当前主稿改了什么。"""
    await _ensure_tables()
    session = await state_tracker.get_session(session_id)
    if not session or session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    rows = await state_tracker._fetchall(
        """
        SELECT * FROM collab_handoffs
        WHERE fork_session_id = ? AND to_user_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (session_id, user_id),
    )
    if not rows:
        raise HTTPException(status_code=400, detail="当前不是协作副本")
    h = dict(rows[0])
    partner_name = await _username(user_id) or "我"
    fork_messages = await state_tracker.get_messages(session_id)
    root_messages = await state_tracker.get_messages(h["root_session_id"])
    baseline = _parse_baseline(h.get("baseline_json"))
    if not baseline:
        baseline = _normalize_msg_list(root_messages)

    # 相对基线的改动（你这轮改了什么）
    vs_baseline = _diff_fork_against_root(
        [{"role": m["role"], "content": m["content"]} for m in baseline],
        fork_messages,
        partner_name,
    )
    # 相对当前主稿（若主稿也动过，交回后可能冲突）
    vs_root = _diff_fork_against_root(root_messages, fork_messages, partner_name)
    three_way = _analyze_three_way(baseline, root_messages, fork_messages)
    three_way_out = {k: v for k, v in three_way.items() if k != "theirs_delta_full"}

    def _counts(items):
        c = {"same": 0, "added": 0, "removed": 0, "changed": 0}
        for m in items:
            k = m.get("change") or "same"
            if k in c:
                c[k] += 1
        return c

    return {
        "handoff_id": h["id"],
        "status": h.get("status"),
        "can_submit": h.get("status") in ("editing", "rejected"),
        "vs_baseline": vs_baseline,
        "vs_baseline_summary": _counts(vs_baseline),
        "vs_root": vs_root,
        "vs_root_summary": _counts(vs_root),
        "three_way": three_way_out,
        "hint": "绿色/琥珀色是你这轮相对开始时的改动；若提示主稿也有变动，交回后主稿方可能看到冲突选项。",
    }
