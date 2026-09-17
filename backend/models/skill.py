"""技能数据模型"""

from pydantic import BaseModel
from typing import Optional


class SkillInfo(BaseModel):
    name: str
    display_name: str
    description: str
    modes: list[str]
    icon: Optional[str] = None


class ModeInfo(BaseModel):
    name: str
    display_name: str
    description: str
    phases: list[str]
    estimated_time: str
    paper_types: list[str] = []


class SkillConfig(BaseModel):
    paper_types: list[dict] = []
    citation_formats: list[dict] = []
    output_formats: list[str] = ["markdown", "docx", "pdf", "latex"]
