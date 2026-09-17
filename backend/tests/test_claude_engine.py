"""测试 claude_engine.py — Claude CLI 事件解析"""

import pytest


def _test_import():
    import sys
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from services.claude_engine import ClaudeEngine
    return ClaudeEngine()


_engine = _test_import()


class TestParseEvent:
    """测试 _parse_event — Claude CLI stream-json 事件解析。"""

    def test_content_block_delta_text(self):
        evt = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello, World!"},
            },
        }
        result = _engine._parse_event(evt)
        assert result is not None
        assert result["event"] == "message"
        assert result["data"]["delta"] == "Hello, World!"

    def test_content_block_delta_empty_skipped(self):
        evt = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": ""},
            },
        }
        result = _engine._parse_event(evt)
        assert result is None

    def test_content_block_start_skipped(self):
        evt = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        }
        assert _engine._parse_event(evt) is None

    def test_content_block_stop_skipped(self):
        evt = {
            "type": "stream_event",
            "event": {"type": "content_block_stop", "index": 0},
        }
        assert _engine._parse_event(evt) is None

    def test_tool_use_event(self):
        evt = {
            "type": "stream_event",
            "event": {
                "type": "tool_use",
                "name": "WebSearch",
                "input": {"query": "climate change papers 2025"},
            },
        }
        result = _engine._parse_event(evt)
        assert result is not None
        assert result["event"] == "phase_start"
        assert result["data"]["phase"] == "tool"
        assert "WebSearch" in result["data"]["description"]
        assert "climate change" in result["data"]["description"]

    def test_tool_use_non_dict_input(self):
        evt = {
            "type": "stream_event",
            "event": {
                "type": "tool_use",
                "name": "Read",
                "input": "some_file.txt",
            },
        }
        result = _engine._parse_event(evt)
        assert result is not None
        assert result["event"] == "phase_start"

    def test_tool_result_event(self):
        evt = {
            "type": "stream_event",
            "event": {
                "type": "tool_result",
                "content": "Search results: 42 papers found.",
            },
        }
        result = _engine._parse_event(evt)
        assert result is not None
        assert result["event"] == "message"
        assert "工具输出" in result["data"]["delta"]
        assert "42 papers found" in result["data"]["delta"]

    def test_tool_result_list_content(self):
        evt = {
            "type": "stream_event",
            "event": {
                "type": "tool_result",
                "content": [
                    {"type": "text", "text": "Part A."},
                    {"type": "text", "text": "Part B."},
                ],
            },
        }
        result = _engine._parse_event(evt)
        assert result is not None
        assert "Part A." in result["data"]["delta"]
        assert "Part B." in result["data"]["delta"]

    def test_tool_result_empty_content(self):
        evt = {
            "type": "stream_event",
            "event": {"type": "tool_result", "content": ""},
        }
        assert _engine._parse_event(evt) is None

    def test_system_thinking_tokens(self):
        evt = {
            "type": "system",
            "subtype": "thinking_tokens",
            "estimated_tokens": 1500,
        }
        result = _engine._parse_event(evt)
        assert result is not None
        assert result["event"] == "progress"
        assert result["data"]["tokens"] == 1500
        assert result["data"]["phase"] == "thinking"

    def test_system_init(self):
        evt = {"type": "system", "subtype": "init"}
        result = _engine._parse_event(evt)
        assert result is not None
        assert result["event"] == "progress"
        assert result["data"]["phase"] == "init"

    def test_system_unknown_subtype_skipped(self):
        evt = {"type": "system", "subtype": "unknown_subtype"}
        assert _engine._parse_event(evt) is None

    def test_error_result(self):
        evt = {
            "type": "result",
            "is_error": True,
            "result": "API key is invalid",
        }
        result = _engine._parse_event(evt)
        assert result is not None
        assert result["event"] == "error"
        assert result["data"]["code"] == "CLI_ERROR"
        assert "API key is invalid" in result["data"]["message"]

    def test_assistant_message(self):
        evt = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Full response text."},
                ],
            },
        }
        result = _engine._parse_event(evt)
        assert result is not None
        assert result["event"] == "message"
        assert result["data"]["delta"] == "Full response text."

    def test_assistant_message_multiple_text_blocks(self):
        evt = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "First paragraph. "},
                    {"type": "text", "text": "Second paragraph."},
                ],
            },
        }
        result = _engine._parse_event(evt)
        assert result is not None
        assert result["data"]["delta"] == "First paragraph. Second paragraph."

    def test_assistant_message_empty_skipped(self):
        evt = {
            "type": "assistant",
            "message": {"role": "assistant", "content": ""},
        }
        assert _engine._parse_event(evt) is None

    def test_unknown_event_type_skipped(self):
        evt = {"type": "unknown_xyz", "event": {"type": "irrelevant"}}
        assert _engine._parse_event(evt) is None

    def test_no_event_key(self):
        evt = {"type": "stream_event"}
        result = _engine._parse_event(evt)
        assert result is None
