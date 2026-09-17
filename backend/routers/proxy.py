"""Anthropic → OpenAI 格式翻译代理

Claude CLI 只支持 Anthropic 格式（/v1/messages）。
当用户选择非 Anthropic 模型（DeepSeek/Kimi/GLM/Qwen）时，
本代理将 Anthropic 格式请求翻译为 OpenAI 格式，转发到实际 Provider。

Claude CLI 配置:
  ANTHROPIC_BASE_URL = http://localhost:8000/v1/proxy
  ANTHROPIC_API_KEY  = 实际 Provider 的 Key（DeepSeek 等）
"""

import asyncio
import json
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from logging_config import get_logger

router = APIRouter(prefix="/v1/proxy", tags=["proxy"])


# ---------- Anthropic 请求模型 ----------

class AnthropicTextContent(BaseModel):
    type: str = "text"
    text: str

class AnthropicImageContent(BaseModel):
    type: str = "image"
    source: dict

class AnthropicMessage(BaseModel):
    role: str
    content: str | list

class AnthropicMessagesRequest(BaseModel):
    model: str
    messages: list[AnthropicMessage]
    system: Optional[str | list] = None  # Anthropic 支持 string 或 content block 数组
    max_tokens: int = 4096
    stream: bool = False
    temperature: float = 1.0
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[list[str]] = None


# ---------- 翻译逻辑 ----------

def _anthropic_to_openai(req: AnthropicMessagesRequest) -> dict:
    """将 Anthropic Messages 请求翻译为 OpenAI Chat Completions 请求。"""
    openai_messages = []

    if req.system:
        if isinstance(req.system, list):
            # 从 content block 数组中提取文本
            system_text = "\n".join(
                block.get("text", "") for block in req.system
                if isinstance(block, dict) and block.get("type") == "text"
            )
        else:
            system_text = req.system
        if system_text:
            openai_messages.append({"role": "system", "content": system_text})

    for msg in req.messages:
        role = msg.role
        if isinstance(msg.content, str):
            content = msg.content
        elif isinstance(msg.content, list):
            # 多模态 content 数组
            text_parts = []
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = "\n".join(text_parts)
        else:
            content = ""
        openai_messages.append({"role": role, "content": content})

    return {
        "model": req.model,
        "messages": openai_messages,
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
        "top_p": req.top_p or 1.0,
        "stream": req.stream,
        "stop": req.stop_sequences or None,
    }


def _openai_chunk_to_anthropic_sse(chunk: dict) -> Optional[dict]:
    """将 OpenAI SSE chunk 翻译为 Anthropic SSE 格式。"""
    choices = chunk.get("choices", [])
    if not choices:
        return None

    choice = choices[0]
    delta = choice.get("delta", {})

    # 结束标志 —— 必须在最前面检查，避免被初始空 chunk 逻辑误杀
    finish_reason = choice.get("finish_reason")
    if finish_reason:
        return {"type": "content_block_stop", "index": 0}

    # 初始空 chunk 跳过（role: assistant，无内容，无 finish_reason）
    if chunk.get("object") == "chat.completion.chunk" and choice.get("index", 0) == 0 and not delta.get("content"):
        return None

    # 内容增量
    if delta.get("content"):
        return {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": delta["content"]},
        }

    return None


# ---------- 端点 ----------

@router.post("/v1/messages")
async def proxy_messages(request: Request):
    """代理 Anthropic /v1/messages → OpenAI /v1/chat/completions。"""
    # 读取请求体
    body = await request.body()
    try:
        req_data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    anthropic_req = AnthropicMessagesRequest(**req_data)
    openai_body = _anthropic_to_openai(anthropic_req)

    # 提取 API Key（Claude CLI 通过环境变量传入后放在 x-api-key header 中）
    api_key = request.headers.get("x-api-key", "")

    # 确定目标 URL：优先从 x-base-url header 读取，其次从 model 推断
    provider_base_url = request.headers.get("x-base-url", "")
    if not provider_base_url:
        from providers import get_provider_for_model
        model = anthropic_req.model
        provider = get_provider_for_model(model)
        provider_base_url = provider.get("default_base_url", "")

    if not api_key:
        raise HTTPException(status_code=401, detail="未提供 API Key")

    target_url = f"{provider_base_url.rstrip('/')}/v1/chat/completions"
    _final_key = api_key

    _proxy_log = get_logger(__name__)
    _proxy_log.info("PROXY model=%s target=%s stream=%s", model, target_url, anthropic_req.stream)

    async with httpx.AsyncClient(timeout=300.0) as client:
        headers = {
            "Authorization": f"Bearer {_final_key}",
            "Content-Type": "application/json",
        }

        if not anthropic_req.stream:
            # 非流式
            resp = await client.post(target_url, json=openai_body, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            data = resp.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage = data.get("usage", {})
            return JSONResponse({
                "id": f"msg_{int(time.time()*1000)}",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": content}],
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                },
            })

        # 流式 —— 在生成器内部管理 httpx 客户端生命周期，
        # 以免 client 在 StreamingResponse 开始迭代前被关闭。
        async def stream_translate():
            _headers = {
                "Authorization": f"Bearer {_final_key}",
                "Content-Type": "application/json",
            }
            try:
                async with httpx.AsyncClient(timeout=300.0) as _client:
                    async with _client.stream("POST", target_url, json=openai_body, headers=_headers) as resp:
                        if resp.status_code != 200:
                            body_text = await resp.aread()
                            yield json.dumps({
                                "type": "error",
                                "error": {"type": "api_error", "message": f"Provider error: {body_text.decode()}"}
                            }).encode() + b"\n"
                            return

                        # 发送 content_block_start
                        yield json.dumps({
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""}
                        }).encode() + b"\n"

                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            d = line[6:]  # 去掉 "data: " 前缀
                            if d == "[DONE]":
                                break
                            try:
                                chunk = json.loads(d)
                                translated = _openai_chunk_to_anthropic_sse(chunk)
                                if translated:
                                    yield json.dumps(translated).encode() + b"\n"
                            except json.JSONDecodeError:
                                continue

                        # 发送 content_block_stop
                        yield json.dumps({"type": "content_block_stop", "index": 0}).encode() + b"\n"

                        # 发送 message delta
                        yield json.dumps({
                            "type": "message_delta",
                            "delta": {"stop_reason": "end_turn"},
                            "usage": {"output_tokens": 0}
                        }).encode() + b"\n"

            except Exception as e:
                yield json.dumps({
                    "type": "error",
                    "error": {"type": "api_error", "message": str(e)}
                }).encode() + b"\n"

        return StreamingResponse(
            stream_translate(),
            media_type="text/event-stream",
        )


@router.get("/v1/models")
async def proxy_list_models():
    """返回模型列表（Claude CLI 校验用）。

    与 providers.py MODELS 保持同步，避免 Claude CLI 校验失败。
    """
    from providers import MODELS as PROVIDER_MODELS
    return JSONResponse({
        "data": [{"id": m["id"], "type": "model"} for m in PROVIDER_MODELS]
    })
