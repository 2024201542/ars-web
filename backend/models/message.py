"""消息数据模型"""

from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=50000)
    model: Optional[str] = None


class Message(BaseModel):
    id: int
    session_id: str
    role: str
    content: Optional[str] = None
    agent_name: Optional[str] = None
    phase_name: Optional[str] = None
    metadata: Optional[str] = None
    created_at: str
