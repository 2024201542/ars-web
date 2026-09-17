"""大模型 Provider 注册表。

集中描述每个 Provider 走什么协议、默认 base_url、读哪个 Key 设置项，
以及每个可选模型属于哪个 Provider。模型选择据此自动路由到正确的客户端。

国产厂商的 base_url 与模型名为常见默认值，用户可在设置页覆盖
（settings 中的 <provider>_base_url）。
"""

from typing import Optional

# 协议常量
PROTOCOL_ANTHROPIC = "anthropic"
PROTOCOL_OPENAI = "openai"


# provider_id -> 配置
PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "display_name": "Anthropic",
        "protocol": PROTOCOL_ANTHROPIC,
        "default_base_url": None,  # 官方默认端点
        "key_setting": "anthropic_api_key",
        "base_url_setting": "anthropic_base_url",
    },
    "moonshot": {
        "display_name": "Kimi / 月之暗面",
        "protocol": PROTOCOL_OPENAI,
        "default_base_url": "https://api.moonshot.cn/v1",
        "key_setting": "moonshot_api_key",
        "base_url_setting": "moonshot_base_url",
    },
    "zhipu": {
        "display_name": "智谱 GLM",
        "protocol": PROTOCOL_OPENAI,
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "key_setting": "zhipu_api_key",
        "base_url_setting": "zhipu_base_url",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "protocol": PROTOCOL_OPENAI,
        "default_base_url": "https://api.deepseek.com",
        "key_setting": "deepseek_api_key",
        "base_url_setting": "deepseek_base_url",
    },
    "qwen": {
        "display_name": "通义千问 Qwen",
        "protocol": PROTOCOL_OPENAI,
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_setting": "qwen_api_key",
        "base_url_setting": "qwen_base_url",
    },
}


# 可选模型清单。id 为实际传给 API 的模型名，用户可在设置页改 base_url 但模型名固定。
MODELS: list[dict] = [
    # Anthropic 官方
    {"id": "claude-sonnet-4-6", "name": "Claude Sonnet", "provider": "anthropic",
     "desc": "速度与智能的最佳平衡，适合大部分研究任务"},
    {"id": "claude-opus-4-8", "name": "Claude Opus", "provider": "anthropic",
     "desc": "最强推理能力，适合复杂分析与长流程任务"},
    {"id": "claude-haiku-4-5", "name": "Claude Haiku", "provider": "anthropic",
     "desc": "最快、最经济，适合简单任务"},
    # Kimi / 月之暗面（Anthropic 兼容）
    {"id": "kimi-k2-0905-preview", "name": "Kimi K2", "provider": "moonshot",
     "desc": "月之暗面 Kimi，超长上下文，中文表现优秀"},
    # 智谱 GLM（Anthropic 兼容）
    {"id": "glm-4.6", "name": "GLM-4.6", "provider": "zhipu",
     "desc": "智谱 GLM 旗舰模型，综合能力强"},
    # DeepSeek（OpenAI 兼容）
    {"id": "deepseek-chat", "name": "DeepSeek Chat", "provider": "deepseek",
     "desc": "DeepSeek-V3 通用对话模型"},
    {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "provider": "deepseek",
     "desc": "DeepSeek-R1 推理模型，擅长复杂推理"},
    # 通义千问 Qwen（OpenAI 兼容）
    {"id": "qwen-max", "name": "通义千问 Max", "provider": "qwen",
     "desc": "阿里 Qwen 旗舰模型，能力最强"},
    {"id": "qwen-plus", "name": "通义千问 Plus", "provider": "qwen",
     "desc": "阿里 Qwen 均衡模型，性价比高"},
]


_MODEL_INDEX = {m["id"]: m for m in MODELS}


def get_provider_id_for_model(model_id: str) -> str:
    """返回模型所属的 provider_id；未知模型回退到 anthropic。"""
    m = _MODEL_INDEX.get(model_id)
    return m["provider"] if m else "anthropic"


def get_provider_for_model(model_id: str) -> dict:
    """返回模型所属 provider 的配置 dict。"""
    return PROVIDERS[get_provider_id_for_model(model_id)]


def list_models() -> list[dict]:
    """返回所有可选模型（含 provider 与 provider 显示名），供前端渲染。"""
    result = []
    for m in MODELS:
        prov = PROVIDERS[m["provider"]]
        result.append({
            **m,
            "provider_display_name": prov["display_name"],
            "protocol": prov["protocol"],
        })
    return result


def list_providers() -> list[dict]:
    """返回所有 provider 元信息（含默认 base_url、key 设置项名），供前端渲染配置项。"""
    return [
        {
            "id": pid,
            "display_name": p["display_name"],
            "protocol": p["protocol"],
            "default_base_url": p["default_base_url"],
            "key_setting": p["key_setting"],
            "base_url_setting": p["base_url_setting"],
        }
        for pid, p in PROVIDERS.items()
    ]
