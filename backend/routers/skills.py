"""技能查询 API"""

from fastapi import APIRouter, HTTPException

from services.skill_loader import skill_loader

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
async def list_skills():
    """获取所有可用技能列表。"""
    skills = skill_loader.get_skills()
    return {"data": skills}


@router.get("/{skill_name}/modes")
async def get_skill_modes(skill_name: str):
    """获取某技能的所有模式。"""
    modes = skill_loader.get_skill_modes(skill_name)
    if not modes:
        raise HTTPException(status_code=404, detail=f"技能 {skill_name} 不存在")
    return {"data": modes}


@router.get("/{skill_name}/config")
async def get_skill_config(skill_name: str):
    """获取技能配置项。"""
    config = skill_loader.get_skill_config(skill_name)
    return config
