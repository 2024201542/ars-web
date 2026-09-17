"""只读分享链接 API (L0)"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deps import limiter
from services.state_tracker import tracker as state_tracker
from services.user_manager import get_user_id

router = APIRouter(tags=["share"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


class ShareCreateRequest(BaseModel):
    expires_days: int = Field(default=7, ge=1, le=90)
    include_files: bool = False


class ShareCreateResponse(BaseModel):
    token: str
    url_path: str
    expires_at: str
    title: str
    message_count: int


async def _ensure_share_table():
    await state_tracker._ensure_initialized()
    await state_tracker._execute(
        """
        CREATE TABLE IF NOT EXISTS shares (
            id TEXT PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            session_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            title TEXT,
            snapshot TEXT NOT NULL,
            include_files INTEGER DEFAULT 0,
            expires_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    await state_tracker._execute(
        "CREATE INDEX IF NOT EXISTS idx_shares_token ON shares(token)"
    )
    await state_tracker._execute(
        "CREATE INDEX IF NOT EXISTS idx_shares_session ON shares(session_id)"
    )
    await state_tracker._commit()


def _build_snapshot(session: dict, messages: list, include_files: bool) -> dict:
    cleaned = []
    for m in messages:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        cleaned.append(
            {
                "role": m.get("role"),
                "content": content,
                "created_at": m.get("created_at"),
            }
        )
    return {
        "title": session.get("title") or "学术研究会话",
        "skill_name": session.get("skill_name"),
        "mode_name": session.get("mode_name"),
        "session_created_at": session.get("created_at"),
        "shared_at": _now(),
        "include_files": bool(include_files),
        "messages": cleaned,
        # L0：不附带文件正文，仅保留对话；include_files 预留给后续扩展
        "files": [],
    }


@router.post("/api/sessions/{session_id}/share", response_model=ShareCreateResponse)
@limiter.limit("20/hour")
async def create_share(
    request: Request,
    session_id: str,
    req: ShareCreateRequest,
    user_id: str = Depends(get_user_id),
):
    await _ensure_share_table()
    session = await state_tracker.get_session(session_id)
    if not session or session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = await state_tracker.get_messages(session_id)
    snapshot = _build_snapshot(session, messages, req.include_files)
    if not snapshot["messages"]:
        raise HTTPException(status_code=400, detail="会话暂无内容，无法分享")

    token = secrets.token_urlsafe(24)
    share_id = secrets.token_hex(16)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=req.expires_days)).isoformat()
    created_at = _now()

    await state_tracker._execute(
        """
        INSERT INTO shares (id, token, session_id, owner_id, title, snapshot, include_files, expires_at, revoked_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            share_id,
            token,
            session_id,
            user_id,
            snapshot["title"],
            json.dumps(snapshot, ensure_ascii=False),
            1 if req.include_files else 0,
            expires_at,
            created_at,
        ),
    )
    await state_tracker._commit()

    return ShareCreateResponse(
        token=token,
        url_path=f"/#/share/{token}",
        expires_at=expires_at,
        title=snapshot["title"],
        message_count=len(snapshot["messages"]),
    )


@router.get("/api/sessions/{session_id}/shares")
async def list_shares(session_id: str, user_id: str = Depends(get_user_id)):
    await _ensure_share_table()
    session = await state_tracker.get_session(session_id)
    if not session or session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    rows = await state_tracker._fetchall(
        """
        SELECT token, title, expires_at, revoked_at, created_at, include_files
        FROM shares WHERE session_id = ? AND owner_id = ?
        ORDER BY created_at DESC
        """,
        (session_id, user_id),
    )
    now = datetime.now(timezone.utc)
    data = []
    for r in rows:
        d = dict(r)
        exp = _parse_iso(d.get("expires_at"))
        revoked = bool(d.get("revoked_at"))
        expired = bool(exp and exp < now)
        d["active"] = (not revoked) and (not expired)
        d["url_path"] = f"/#/share/{d['token']}"
        data.append(d)
    return {"data": data}


@router.delete("/api/shares/{token}")
async def revoke_share(token: str, user_id: str = Depends(get_user_id)):
    await _ensure_share_table()
    rows = await state_tracker._fetchall(
        "SELECT id, owner_id, revoked_at FROM shares WHERE token = ?",
        (token,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="分享不存在")
    row = dict(rows[0])
    if row.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="只能撤销自己的分享")
    if row.get("revoked_at"):
        return {"ok": True, "message": "已撤销"}
    await state_tracker._execute(
        "UPDATE shares SET revoked_at = ? WHERE token = ?",
        (_now(), token),
    )
    await state_tracker._commit()
    return {"ok": True, "message": "已撤销分享链接"}


@router.get("/api/public/shares/{token}")
@limiter.limit("60/minute")
async def get_public_share(request: Request, token: str):
    """公开只读：无需登录。"""
    await _ensure_share_table()
    rows = await state_tracker._fetchall(
        "SELECT title, snapshot, expires_at, revoked_at, created_at FROM shares WHERE token = ?",
        (token,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="分享不存在或链接无效")
    row = dict(rows[0])
    if row.get("revoked_at"):
        raise HTTPException(status_code=410, detail="分享链接已撤销")
    exp = _parse_iso(row.get("expires_at"))
    if exp and exp < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="分享链接已过期")

    try:
        snapshot = json.loads(row["snapshot"])
    except Exception:
        raise HTTPException(status_code=500, detail="分享数据损坏")

    return {
        "title": row.get("title") or snapshot.get("title"),
        "expires_at": row.get("expires_at"),
        "created_at": row.get("created_at"),
        "readonly": True,
        "snapshot": snapshot,
    }
