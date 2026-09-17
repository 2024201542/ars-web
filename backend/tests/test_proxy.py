"""测试 proxy.py — Anthropic ↔ OpenAI 协议翻译"""

import json
import pytest


# ── 直接导入纯函数以测试 ──
def _test_import_proxy():
    """安全导入 proxy 模块中的函数。"""
    import sys
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from routers.proxy import _anthropic_to_openai, _openai_chunk_to_anthropic_sse, AnthropicMessagesRequest
    return _anthropic_to_openai, _openai_chunk_to_anthropic_sse, AnthropicMessagesRequest


_anthropic_to_openai, _openai_chunk_to_anthropic_sse, AnthropicMessagesRequest = _test_import_proxy()


class TestAnthropicToOpenAI:
    """测试 Anthropic → OpenAI 请求格式翻译。"""

    def test_basic_message(self):
        req = AnthropicMessagesRequest(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
        )
        result = _anthropic_to_openai(req)
        assert result["model"] == "claude-sonnet-4-6"
        assert result["max_tokens"] == 100
        assert result["stream"] is False
        assert result["temperature"] == 1.0
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "Hello"

    def test_adds_system_message(self):
        req = AnthropicMessagesRequest(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "Hi"}],
            system="You are a helpful assistant.",
            max_tokens=100,
        )
        result = _anthropic_to_openai(req)
        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][0]["content"] == "You are a helpful assistant."
        assert result["messages"][1]["role"] == "user"

    def test_system_as_content_blocks(self):
        req = AnthropicMessagesRequest(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            system=[
                {"type": "text", "text": "First instruction."},
                {"type": "text", "text": "Second instruction."},
            ],
            max_tokens=100,
        )
        result = _anthropic_to_openai(req)
        assert result["messages"][0]["role"] == "system"
        assert "First instruction.\nSecond instruction." == result["messages"][0]["content"]

    def test_stream_flag(self):
        req = AnthropicMessagesRequest(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "Hi"}],
            stream=True,
            max_tokens=100,
        )
        result = _anthropic_to_openai(req)
        assert result["stream"] is True

    def test_stop_sequences(self):
        req = AnthropicMessagesRequest(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "Hi"}],
            stop_sequences=["STOP", "END"],
            max_tokens=100,
        )
        result = _anthropic_to_openai(req)
        assert result["stop"] == ["STOP", "END"]

    def test_multimodal_content_strips_non_text(self):
        req = AnthropicMessagesRequest(
            model="claude-sonnet-4-6",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {"type": "image", "source": {"type": "base64", "data": "xxx"}},
                ],
            }],
            max_tokens=100,
        )
        result = _anthropic_to_openai(req)
        assert "What is in this image?" == result["messages"][0]["content"]

    def test_multiple_messages(self):
        req = AnthropicMessagesRequest(
            model="deepseek-reasoner",
            messages=[
                {"role": "user", "content": "Question 1"},
                {"role": "assistant", "content": "Answer 1"},
                {"role": "user", "content": "Question 2"},
            ],
            max_tokens=500,
        )
        result = _anthropic_to_openai(req)
        assert len(result["messages"]) == 3
        assert result["messages"][0]["content"] == "Question 1"
        assert result["messages"][1]["content"] == "Answer 1"


class TestOpenAIToAnthropicSSE:
    """测试 OpenAI SSE chunk → Anthropic SSE 反向翻译。"""

    def test_content_delta(self):
        chunk = {
            "object": "chat.completion.chunk",
            "choices": [
                {"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}
            ],
        }
        result = _openai_chunk_to_anthropic_sse(chunk)
        assert result is not None
        assert result["type"] == "content_block_delta"
        assert result["delta"]["type"] == "text_delta"
        assert result["delta"]["text"] == "Hello"

    def test_skip_empty_first_chunk(self):
        chunk = {
            "object": "chat.completion.chunk",
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": None}
            ],
        }
        result = _openai_chunk_to_anthropic_sse(chunk)
        assert result is None

    def test_finish_reason(self):
        chunk = {
            "object": "chat.completion.chunk",
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"}
            ],
        }
        result = _openai_chunk_to_anthropic_sse(chunk)
        assert result == {"type": "content_block_stop", "index": 0}

    def test_no_choices(self):
        chunk = {"object": "chat.completion.chunk", "choices": []}
        result = _openai_chunk_to_anthropic_sse(chunk)
        assert result is None

    def test_multiple_choices_takes_first(self):
        chunk = {
            "object": "chat.completion.chunk",
            "choices": [
                {"index": 0, "delta": {"content": "Alpha"}, "finish_reason": None},
                {"index": 1, "delta": {"content": "Beta"}, "finish_reason": None},
            ],
        }
        result = _openai_chunk_to_anthropic_sse(chunk)
        assert result["delta"]["text"] == "Alpha"

    def test_content_block_start_is_handled_separately(self):
        # 首个 chunk 不含 content 但 object 匹配 —— 跳过
        chunk = {
            "object": "chat.completion.chunk",
            "choices": [
                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
            ],
        }
        result = _openai_chunk_to_anthropic_sse(chunk)
        assert result is None
