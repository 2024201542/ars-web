"""认证 API"""

from fastapi import APIRouter, HTTPException, Depends, Request
from models.user import LoginRequest
from services.user_manager import user_manager, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(req: LoginRequest):
    """登录。"""
    try:
        return await user_manager.login(req.username, req.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """获取当前用户信息。"""
    return {"user": user}


@router.post("/logout")
async def logout(request: Request):
    """登出。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        await user_manager.logout(auth[7:])
    return {"ok": True}
