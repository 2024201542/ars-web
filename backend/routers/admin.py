"""管理员 API"""

from fastapi import APIRouter, HTTPException, Depends
from models.user import UserCreate
from pydantic import BaseModel
from services.user_manager import user_manager, get_admin_user
from services.state_tracker import tracker as state_tracker

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminCreateUser(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "user"


@router.get("/users")
async def list_users(page: int = 1, limit: int = 50, admin: dict = Depends(get_admin_user)):
    all_users = await user_manager.list_users()
    total = len(all_users)
    start = (page - 1) * limit
    return {"data": all_users[start:start+limit], "total": total, "page": page}


@router.post("/users")
async def create_user(req: AdminCreateUser, admin: dict = Depends(get_admin_user)):
    try:
        user = await user_manager.create_user(req.username, req.password, req.display_name or req.username, req.role)
        return user
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(get_admin_user)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    await user_manager.delete_user(user_id)
    return {"ok": True}


@router.get("/users/{user_id}/sessions")
async def get_user_sessions(user_id: str, admin: dict = Depends(get_admin_user)):
    sessions = await user_manager.get_user_sessions(user_id)
    return {"data": sessions}


@router.get("/stats")
async def get_stats(admin: dict = Depends(get_admin_user)):
    return await user_manager.get_stats()
