from typing import Optional

from .anthropic_client import AnthropicClient
from .openai_client import OpenAIClient

from providers import PROTOCOL_ANTHROPIC, PROTOCOL_OPENAI


def make_client(protocol: str, api_key: str, model: str, base_url: Optional[str] = None):
    """根据协议返回对应客户端实例。

    两个客户端都暴露同构的 stream_message(system_prompt, messages, max_tokens) 接口。
    """
    if protocol == PROTOCOL_OPENAI:
        return OpenAIClient(api_key=api_key, model=model, base_url=base_url)
    # 默认 anthropic
    return AnthropicClient(api_key=api_key, model=model, base_url=base_url)


__all__ = ["AnthropicClient", "OpenAIClient", "make_client"]
