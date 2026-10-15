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
    # 上限与中间件保持一致：附件正文（扫描件 OCR 后可达 5–6 万字）要能通过
    message: str = Field(..., max_length=200000)
    model: Optional[str] = None
    open_path: Optional[str] = Field(None, max_length=240)
    pipeline_action: Optional[str] = Field("", max_length=20)
    # 本次带的附件（相对路径 + 来源），用于"生成的 PPT 放到附件所在文件夹"
    attach_paths: list[str] = Field(default_factory=list, max_length=8)
    attach_source: str = Field("", max_length=10)
    # 用户敲的那句话（不含附件正文）：意图判断只看它，避免被几万字的附件淹没
    user_text: str = Field("", max_length=2000)
    # PPT 生成：选中的模板与页数（在「PPT 生成」入口里由界面带上）
    ppt_template_id: str = Field("", max_length=64)
    ppt_pages: int = Field(0, ge=0, le=40)
    # 没配图时用万相自动生成一张（要花钱花时间，默认关）
    ppt_auto_image: bool = False
    # 编辑页或对话卡片上最近点过的页。用户说「这页」时用它。
    current_page: Optional[int] = Field(None, ge=0, le=80)
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
