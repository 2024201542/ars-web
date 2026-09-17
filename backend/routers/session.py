"""会话管理 API"""

from fastapi import APIRouter, HTTPException, Depends
from models.session import SessionCreate
from pydantic import BaseModel
from services.state_tracker import tracker as state_tracker
from services.user_manager import get_user_id

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", status_code=201)
async def create_session(req: SessionCreate, user_id: str = Depends(get_user_id)):
    """创建新会话。"""
    session = await state_tracker.create_session(
        skill_name=req.skill_name,
        mode_name=req.mode_name,
        title=req.title,
        user_id=user_id,
    )
    return session


@router.get("")
async def list_sessions(page: int = 1, limit: int = 50, skill: str = "", user_id: str = Depends(get_user_id)):
    """获取会话列表，可按技能筛选。"""
    return await state_tracker.list_sessions(page, limit, skill, user_id)


@router.get("/{session_id}")
async def get_session(session_id: str, user_id: str = Depends(get_user_id)):
    """获取会话详情（含消息历史）。"""
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    detail = await state_tracker.get_session_detail(session_id)
    return detail


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, user_id: str = Depends(get_user_id)):
    """删除会话。"""
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    await state_tracker.delete_session(session_id)


class SessionUpdate(BaseModel):
    title: str


@router.patch("/{session_id}")
async def update_session(session_id: str, req: SessionUpdate, user_id: str = Depends(get_user_id)):
    """重命名 / 保存会话标题。"""
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    await state_tracker.update_session_title(session_id, title)
    s = await state_tracker.get_session(session_id)
    return s
