"""会话数据模型"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SessionCreate(BaseModel):
    skill_name: str
    mode_name: str
    title: Optional[str] = None


class SessionSummary(BaseModel):
    id: str
    skill_name: str
    mode_name: str
    title: Optional[str] = None
    status: str = "active"
    created_at: str
    updated_at: str


class Session(SessionSummary):
    passport: Optional[str] = None


class SessionDetail(BaseModel):
    session: Session
    messages: list = []
    artifacts: list = []
