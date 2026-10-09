"""消息数据模型"""

from pydantic import BaseModel, Field
from typing import Optional


class DebateSeat(BaseModel):
    model: str = Field(..., max_length=80)
    provider: str = Field("", max_length=40)
    name: str = Field("", max_length=40)
    stance: str = Field("", max_length=2000)


class DebateMaterial(BaseModel):
    name: str = Field(..., max_length=200)
    path: str = Field(..., max_length=400)
    source: str = Field("", max_length=10)


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=50000)
    model: Optional[str] = None
    open_path: Optional[str] = Field(None, max_length=240)
    pipeline_action: Optional[str] = Field("", max_length=20)
    debate_models: list[str] = Field(default_factory=list, max_length=6)
    debate_seats: list[DebateSeat] = Field(default_factory=list, max_length=6)
    debate_action: str = Field("", max_length=20)
    summarize_model: str = Field("", max_length=80)
    summarize_scope: str = Field("", max_length=20)
    summarize_pair: list[str] = Field(default_factory=list, max_length=2)
    summarize_rounds: list[int] = Field(default_factory=list, max_length=8)
    debate_rounds: int = Field(2, ge=1, le=4)
    debate_materials: list[DebateMaterial] = Field(default_factory=list, max_length=4)


class Message(BaseModel):
    id: int
    session_id: str
    role: str
    content: Optional[str] = None
    agent_name: Optional[str] = None
    phase_name: Optional[str] = None
    metadata: Optional[str] = None
    created_at: str
