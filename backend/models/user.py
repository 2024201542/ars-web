"""用户模型"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=4, max_length=128)
    display_name: Optional[str] = None
    invite_code: Optional[str] = None  # 可选的邀请码（用于注册限制）


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: str
    username: str
    display_name: Optional[str] = None
    role: Literal["user", "admin"]
    created_at: str


class AuthResponse(BaseModel):
    token: str
    user: UserInfo
