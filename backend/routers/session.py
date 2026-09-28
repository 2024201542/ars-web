"""会话管理 API"""

from fastapi import APIRouter, HTTPException, Depends
from models.session import SessionCreate
from pydantic import BaseModel
from services.skill_loader import skill_loader
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
    title: str | None = None
    skill_name: str | None = None
    mode_name: str | None = None


def _entry_allowed(skill_name: str, mode_name: str) -> bool:
    if (skill_name, mode_name) in {("agent", "agent"), ("chat", "chat")}:
        return True
    modes = skill_loader.MODES.get(skill_name) or []
    return any(item.get("name") == mode_name for item in modes)


@router.patch("/{session_id}")
async def update_session(session_id: str, req: SessionUpdate, user_id: str = Depends(get_user_id)):
    """重命名，或记下对话框当前入口。"""
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    if req.skill_name is not None or req.mode_name is not None:
        skill_name = (req.skill_name or "").strip()
        mode_name = (req.mode_name or "").strip()
        if not _entry_allowed(skill_name, mode_name):
            raise HTTPException(status_code=400, detail="没有这个入口")
        await state_tracker.update_session_entry(session_id, skill_name, mode_name)
    title = (req.title or "").strip()
    if title:
        await state_tracker.update_session_title(session_id, title)
    elif req.skill_name is None and req.mode_name is None:
        raise HTTPException(status_code=400, detail="标题不能为空")
    s = await state_tracker.get_session(session_id)
    return s
