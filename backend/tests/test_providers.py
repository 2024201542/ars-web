"""测试 providers.py —— 模型路由与 Provider 注册"""

import pytest
from providers import (
    PROVIDERS,
    MODELS,
    get_provider_id_for_model,
    get_provider_for_model,
    list_models,
    list_providers,
    PROTOCOL_ANTHROPIC,
    PROTOCOL_OPENAI,
)


class TestProviders:
    """Provider 注册表测试"""

    def test_all_models_have_valid_provider(self):
        """每个模型必须引用一个已注册的 provider。"""
        for m in MODELS:
            assert m["provider"] in PROVIDERS, (
                f"模型 {m['id']} 的 provider '{m['provider']}' 未在 PROVIDERS 中注册"
            )

    def test_get_provider_id_for_model_known(self):
        """已知模型应返回正确的 provider_id。"""
        assert get_provider_id_for_model("claude-sonnet-4-6") == "anthropic"
        assert get_provider_id_for_model("deepseek-chat") == "deepseek"
        assert get_provider_id_for_model("kimi-k2-0905-preview") == "moonshot"

    def test_get_provider_id_for_model_unknown_fallback(self):
        """未知模型应回退到 anthropic。"""
        assert get_provider_id_for_model("nonexistent-model") == "anthropic"

    def test_get_provider_for_model_returns_config(self):
        """get_provider_for_model 应返回完整配置 dict。"""
        cfg = get_provider_for_model("claude-sonnet-4-6")
        assert cfg["protocol"] == PROTOCOL_ANTHROPIC
        assert cfg["display_name"] == "Anthropic"

    def test_list_models_includes_provider_info(self):
        """list_models 每个条目应包含 provider_display_name。"""
        result = list_models()
        assert len(result) == len(MODELS)
        for r in result:
            assert "provider_display_name" in r
            assert "protocol" in r

    def test_list_providers_includes_all(self):
        """list_providers 应返回所有注册的 provider。"""
        result = list_providers()
        assert len(result) == len(PROVIDERS)
        provider_ids = {p["id"] for p in result}
        assert provider_ids == set(PROVIDERS.keys())

    def test_provider_configs_have_required_fields(self):
        """每个 provider 必须包含必要字段。"""
        required = {"display_name", "protocol", "default_base_url", "key_setting", "base_url_setting"}
        for pid, cfg in PROVIDERS.items():
            missing = required - set(cfg.keys())
            assert not missing, f"Provider '{pid}' 缺少字段: {missing}"
