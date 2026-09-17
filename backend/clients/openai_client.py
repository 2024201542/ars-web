"""OpenAI 兼容 API 客户端封装。

对外暴露与 AnthropicClient 相同的 stream_message 接口，便于 AgentRunner
通过鸭子类型无差别调用。用于 DeepSeek / 通义千问等仅提供 OpenAI 兼容接口的厂商。
"""

from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI, APIError, RateLimitError


class OpenAIClient:
    """OpenAI Chat Completions 兼容的异步流式客户端。"""

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def stream_message(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 8192,
    ) -> AsyncGenerator[str, None]:
        """流式调用 Chat Completions，逐 token 返回文本。

        OpenAI 协议没有独立的 system 参数，需把 system_prompt 作为
        role=system 的首条消息注入。
        """
        full_messages = [{"role": "system", "content": system_prompt}, *messages]
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=full_messages,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except RateLimitError as e:
            raise RuntimeError(f"API 请求频率超限: {e}") from e
        except APIError as e:
            raise RuntimeError(f"OpenAI 兼容 API 错误: {e}") from e
