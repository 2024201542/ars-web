"""设置管理 API"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from config import DEFAULT_MODEL
from providers import PROVIDERS, list_models, list_providers
from services.state_tracker import inspect_secret, tracker as state_tracker
from services.user_manager import get_user_id

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    moonshot_api_key: Optional[str] = None
    zhipu_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    qwen_api_key: Optional[str] = None
    s2_api_key: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    moonshot_base_url: Optional[str] = None
    zhipu_base_url: Optional[str] = None
    deepseek_base_url: Optional[str] = None
    qwen_base_url: Optional[str] = None


@router.get("")
async def get_settings(user_id: str = Depends(get_user_id)):
    """获取当前用户设置。"""
    settings = await state_tracker.get_settings(user_id)
    model = settings.get("model", DEFAULT_MODEL)

    providers_status = []
    for pid, p in PROVIDERS.items():
        key_val = settings.get(p["key_setting"], "") or ""
        usable, broken = inspect_secret(p["key_setting"], key_val)
        providers_status.append({
            "id": pid,
            "display_name": p["display_name"],
            "protocol": p["protocol"],
            "default_base_url": p["default_base_url"],
            "key_configured": usable,
            "key_unreadable": broken,
            "base_url": settings.get(p["base_url_setting"]) or "",
        })

    return {
        "model": model,
        "providers": providers_status,
        "anthropic_key_configured": inspect_secret(
            "anthropic_api_key", settings.get("anthropic_api_key", "") or ""
        )[0],
    }


@router.put("")
async def update_settings(req: SettingsUpdate, user_id: str = Depends(get_user_id)):
    """更新当前用户设置。"""
    data = req.model_dump(exclude_none=True)
    if data:
        await state_tracker.set_settings_batch(data, user_id)
    return {"ok": True, "message": "设置已更新"}


@router.get("/models")
async def get_models():
    """返回所有可选模型，公开接口。"""
    return {"data": list_models()}


@router.get("/providers")
async def get_providers():
    """返回 provider 列表（公开接口，不区分配置状态）。"""
    return {"data": list_providers()}
