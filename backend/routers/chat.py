"""对话/流式输出 API —— 全模型走 Claude Code CLI 引擎"""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse

from config import PROXY_BASE_URL
from deps import limiter
from providers import get_provider_for_model
from models.message import ChatRequest
from services.state_tracker import tracker as state_tracker
from services.user_manager import get_user_id
from logging_config import get_logger
from services.claude_engine import claude_session_exists, engine as claude

router = APIRouter(prefix="/api/sessions", tags=["chat"])

_active_generations: dict[str, asyncio.Event] = {}


@router.post("/{session_id}/chat")
@limiter.limit("30/minute")
async def chat(request: Request, session_id: str, req: ChatRequest, user_id: str = Depends(get_user_id)):
    session = await state_tracker.get_session(session_id)
    if not session or session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    model = req.model or await state_tracker.get_setting("model", user_id) or "deepseek-chat"
    provider = get_provider_for_model(model)

    api_key = await state_tracker.get_setting(provider["key_setting"], user_id)
    if not api_key:
        raise HTTPException(status_code=400, detail=f"尚未配置 {provider['display_name']} 的 API Key")

    _log = get_logger(__name__)
    _log.info("CHAT session=%s model=%s user=%s", session_id, model, user_id)

    effective_base_url = ""
    if provider["protocol"] != "anthropic":
        effective_base_url = PROXY_BASE_URL

    stored_messages = await state_tracker.get_messages(session_id)
    # 数据库里有克隆来的旧消息，不代表 Claude CLI 已经有这个会话
    is_first = not claude_session_exists(session_id)
    prompt = req.message
    if is_first and stored_messages:
        lines = []
        for m in stored_messages[-8:]:
            text = (m.get("content") or "").strip()
            if not text:
                continue
            who = "用户" if m.get("role") == "user" else "助手"
            lines.append(f"{who}：{text[:800]}")
        if lines:
            prompt = (
                "以下是这份文稿已有的对话，请据此继续，不要重复整段历史。\n\n"
                + "\n\n".join(lines)
                + "\n\n---\n当前要处理的新消息：\n"
                + req.message
            )
    author_name = user_id[:8]
    try:
        rows = await state_tracker._fetchall(
            "SELECT username, display_name FROM users WHERE id = ?", (user_id,)
        )
        if rows:
            r = dict(rows[0])
            author_name = r.get("display_name") or r.get("username") or author_name
    except Exception:
        pass
    user_meta = json.dumps({"author": author_name, "author_id": user_id}, ensure_ascii=False)
    assistant_meta = json.dumps({"author": "助手", "author_id": user_id}, ensure_ascii=False)
    await state_tracker.add_message(session_id, "user", req.message, metadata=user_meta)

    cancel_event = asyncio.Event()
    _active_generations[session_id] = cancel_event

    async def event_stream():
        assistant_parts: list[str] = []
        saw_error = False
        try:
            async for evt in claude.chat(
                session_id=session_id,
                message=prompt,
                cancel_event=cancel_event,
                skill_name=session.get("skill_name", ""),
                api_key=api_key,
                base_url=effective_base_url,
                model=model,
                is_first=is_first,
            ):
                evt_type = evt.get("event", "")
                data = evt.get("data", {}) or {}
                if evt_type == "message" and data.get("delta"):
                    assistant_parts.append(str(data["delta"]))
                elif evt_type == "error":
                    saw_error = True
                if evt_type == "heartbeat":
                    yield f": heartbeat\n\n"
                else:
                    yield f"event: {evt_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as e:
            saw_error = True
            _log.exception("chat stream failed session=%s", session_id)
            msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            yield (
                "event: error\ndata: "
                + json.dumps({"code": "INTERNAL_ERROR", "message": msg}, ensure_ascii=False)
                + "\n\n"
            )
        finally:
            full = "".join(assistant_parts).strip()
            try:
                if full:
                    await state_tracker.add_message(session_id, "assistant", full, metadata=assistant_meta)
                    if not saw_error:
                        await state_tracker.update_session_status(session_id, "completed")
                elif saw_error:
                    await state_tracker.update_session_status(session_id, "error")
            except Exception as persist_err:
                _log.exception("persist assistant message failed: %s", persist_err)
            cancel_event.set()
            _active_generations.pop(session_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/{session_id}/chat/stop")
async def stop_chat(session_id: str):
    evt = _active_generations.get(session_id)
    if not evt:
        return {"ok": False, "message": "没有正在进行的生成任务"}
    evt.set()
    return {"ok": True, "message": "已停止生成"}
