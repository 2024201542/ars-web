"""Anthropic API 客户端封装"""

from typing import AsyncGenerator, Optional

from anthropic import AsyncAnthropic, APIError, RateLimitError

from config import DEFAULT_MODEL


class AnthropicClient:
    """Anthropic Messages API 异步客户端。"""

    def __init__(self, api_key: str, model: Optional[str] = None, base_url: Optional[str] = None):
        self.client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        self.model = model or DEFAULT_MODEL

    async def stream_message(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 8192,
    ) -> AsyncGenerator[str, None]:
        """流式调用 Anthropic Messages API，逐 token 返回文本。"""
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except RateLimitError as e:
            raise RuntimeError(f"API 请求频率超限: {e}") from e
        except APIError as e:
            raise RuntimeError(f"Anthropic API 错误: {e}") from e

    async def stream_message_with_tool_use(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
    ) -> AsyncGenerator[dict, None]:
        """带工具调用的流式请求。"""
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
                tools=tools,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            yield {"type": "text", "content": event.delta.text}
                    elif event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            yield {"type": "tool_use_start", "name": event.content_block.name}
                    elif event.type == "content_block_stop":
                        yield {"type": "block_stop"}
        except RateLimitError as e:
            raise RuntimeError(f"API 请求频率超限: {e}") from e
        except APIError as e:
            raise RuntimeError(f"Anthropic API 错误: {e}") from e
