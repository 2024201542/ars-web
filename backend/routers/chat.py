"""对话/流式输出 API —— 全模型走 Claude Code CLI 引擎"""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse

from deps import limiter
from providers import get_provider_for_model, get_provider_id_for_model
from services.entry_prompt import mode_instruction, resolve_chat_route
from models.message import ChatRequest
from services.state_tracker import inspect_secret, tracker as state_tracker
from services.user_manager import get_user_id
from logging_config import get_logger
from services.claude_engine import claude_session_exists, engine as claude

router = APIRouter(prefix="/api/sessions", tags=["chat"])


class DebateHintBody(BaseModel):
    text: str = Field("", max_length=1000)


async def _static_reply(text: str):
    yield {"event": "message", "data": {"delta": text}}
    yield {"event": "done", "data": {"message": "完成"}}


async def _debate_ready(user_id: str):
    from providers import PROVIDERS
    from services.idea_debate import model_catalog

    ready: list[dict] = []
    keys: dict[str, str] = {}
    bases: dict[str, str] = {}
    missing: set[str] = set()
    for row in model_catalog():
        provider_id = row["provider"]
        if provider_id not in keys and provider_id not in missing:
            provider = PROVIDERS[provider_id]
            key = await state_tracker.get_setting(provider["key_setting"], user_id)
            if not key:
                missing.add(provider_id)
            else:
                custom = (await state_tracker.get_setting(provider["base_url_setting"], user_id) or "").strip()
                keys[provider_id] = key
                bases[provider_id] = custom or (provider.get("default_base_url") or "")
        if provider_id in keys:
            ready.append(row)
    return ready, keys, bases


def _debate_seats(req: ChatRequest, ready: list[dict]) -> list[dict]:
    if req.debate_seats:
        return [item.model_dump() for item in req.debate_seats]
    by_id = {item.get("id"): item for item in ready}
    seats = []
    for model_id in req.debate_models or []:
        known = by_id.get(model_id)
        if not known:
            continue
        seats.append({
            "model": model_id,
            "provider": known["provider"],
            "name": known["name"],
            "stance": "",
        })
    return seats


def _seat_by_model(model_id: str, seats: list[dict], ready: list[dict]) -> dict | None:
    wanted = (model_id or "").strip()
    if wanted:
        for seat in seats:
            if seat.get("model") == wanted:
                return seat
        known = next((item for item in ready if item.get("id") == wanted), None)
        if not known:
            return None
        return {"model": wanted, "provider": known["provider"], "name": known["name"], "stance": ""}
    return seats[0] if seats else None


def _open_file_hint(path: str = "") -> str:
    raw = (path or "").replace("\n", " ").replace("\r", " ").strip()
    if not raw or ".." in raw or raw.startswith(("/", "\\")) or (len(raw) >= 2 and raw[1] == ":"):
        return ""
    word = ""
    if raw.lower().endswith(".docx"):
        word = "这是 Word。正文在同目录的「" + raw + ".txt」里，一段一行。要改就改那份 txt，不要直接改 .docx。"
    return (
        "（界面提示，不要复述给用户：中间正在预览的文件是 "
        f"「{raw}」。只有用户明确要求修改这篇或点名的文稿时，才直接改左侧对应文件并保存。"
        f"{word}）"
    )

_active_generations: dict[str, asyncio.Event] = {}


@router.post("/{session_id}/chat")
@limiter.limit("30/minute")
async def chat(request: Request, session_id: str, req: ChatRequest, user_id: str = Depends(get_user_id)):
    session = await state_tracker.get_session(session_id)
    if not session or session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    model = req.model or await state_tracker.get_setting("model", user_id) or "deepseek-chat"
    provider = get_provider_for_model(model)
    skill_name = session.get("skill_name") or ""
    mode_name = session.get("mode_name") or ""

    api_key = await state_tracker.get_setting(provider["key_setting"], user_id)
    keyword_lookup = (skill_name == "academic-paper" and mode_name == "lit-search") or (
        skill_name == "literature-find" and mode_name in {"search", "files"}
    )
    passage_lookup = skill_name == "literature-find" and mode_name == "passage"
    literature_lookup = keyword_lookup or passage_lookup
    want_files = skill_name == "literature-find" and mode_name == "files"
    if skill_name != "idea-debate" and not keyword_lookup and not api_key:
        raw = await state_tracker.get_settings(user_id)
        _, broken = inspect_secret(provider["key_setting"], raw.get(provider["key_setting"], "") or "")
        if broken:
            raise HTTPException(
                status_code=400,
                detail="之前保存的密钥已经读不出来。请点左下角的模型名，到设置里重新粘贴 API Key 并保存。",
            )
        raise HTTPException(status_code=400, detail=f"尚未配置 {provider['display_name']} 的 API Key")
    custom_base = await state_tracker.get_setting(provider["base_url_setting"], user_id) or ""
    allow_tools, effective_base_url = resolve_chat_route(
        get_provider_id_for_model(model), custom_base, skill_name
    )
    mode_line = mode_instruction(skill_name, mode_name) if allow_tools else ""

    _log = get_logger(__name__)
    _log.info("CHAT session=%s model=%s tools=%s", session_id, model, int(allow_tools))

    stored_messages = await state_tracker.get_messages(session_id)
    pipeline_plan = None
    if skill_name == "academic-pipeline" and allow_tools:
        from services.pipeline_steps import resolve_pipeline
        from services.workspace_manager import workspace_manager
        listed = await workspace_manager.list_active(user_id)
        directories = [item for item in (listed.get("data") or []) if item.get("is_dir")]
        pipeline_plan = resolve_pipeline(stored_messages, req.message, req.pipeline_action or "", directories)
        if pipeline_plan.get("mode_line"):
            mode_line = pipeline_plan["mode_line"]
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
    if pipeline_plan and not pipeline_plan.get("skip_model"):
        if (req.pipeline_action or "") == "continue":
            prompt = pipeline_plan["model_prompt"]
        elif pipeline_plan.get("mode_line"):
            prompt = f"{prompt}\n\n{pipeline_plan['mode_line']}"
    hint = _open_file_hint(req.open_path or "")
    if hint:
        prompt = f"{prompt}\n\n{hint}"
    user_meta = json.dumps({"author": author_name, "author_id": user_id}, ensure_ascii=False)
    await state_tracker.add_message(session_id, "user", req.message, metadata=user_meta)

    lit_text = ""
    lit_payload = None
    debate_job = None
    debate_keys: dict = {}
    debate_bases: dict = {}
    debate_source = ""
    debate_participants: list[dict] = []
    summary_voices: list[dict] = []
    if literature_lookup:
        if passage_lookup:
            from services.literature_search import search_from_passage
            provider_id = get_provider_id_for_model(model)
            base = (custom_base or "").strip() or (provider.get("default_base_url") or "")
            found = await search_from_passage(req.message, model, api_key or "", base, provider_id)
        else:
            from services.literature_search import search_literature
            found = await search_literature(
                req.message,
                "cnki" if mode_name == "lit-search" else "openalex",
                want_files,
            )
        lit_text = found.get("message") or ""
        if found.get("status") != "ok":
            lit_text += "\n\n记下的检索：" + (found.get("query") or "（空）")
        elif want_files:
            lit_payload = {
                "items": [
                    {
                        "doi": item.get("doi") or "",
                        "title": item.get("title") or "",
                        "year": item.get("year") or "",
                        "has_pdf": bool(item.get("pdf_url")),
                    }
                    for item in (found.get("items") or [])
                    if isinstance(item, dict)
                ]
            }
    elif skill_name == "idea-debate":
        from services.idea_debate import clear_debate_hints, latest_speeches, prepare_debate
        clear_debate_hints(session_id)
        ready, debate_keys, debate_bases = await _debate_ready(user_id)
        seats = _debate_seats(req, ready)
        action = (req.debate_action or "").strip()
        if action == "topic":
            if not (req.message or "").strip():
                debate_job = {"ok": False, "text": "先写下你的看法，再生成辩题。", "models": []}
            else:
                analyzer = _seat_by_model(req.summarize_model, seats, ready)
                debate_job = prepare_debate("socratic", ready, [analyzer] if analyzer else [])
                party = prepare_debate("custom", ready, seats)
                debate_participants = party.get("models") or []
            debate_source = "topic"
        elif action == "summarize":
            analyst = _seat_by_model(req.summarize_model, seats, ready)
            if not analyst:
                debate_job = {"ok": False, "text": "先选一个用来总结的模型。", "models": []}
            else:
                debate_job = prepare_debate("socratic", ready, [analyst])
            summary_voices = latest_speeches(stored_messages)
            debate_source = "summary"
        else:
            debate_job = prepare_debate(mode_name, ready, seats)
            debate_source = "debate"

    cancel_event = asyncio.Event()
    _active_generations[session_id] = cancel_event

    async def event_stream():
        assistant_parts: list[str] = []
        saw_error = False
        edits_payload = None
        debate_voices: list[dict] = []
        debate_plan = None
        pipeline_meta = (pipeline_plan or {}).get("pipeline")
        try:
            if pipeline_meta:
                yield f"event: pipeline\ndata: {json.dumps(pipeline_meta, ensure_ascii=False)}\n\n"
            if pipeline_plan and pipeline_plan.get("skip_model"):
                text = pipeline_plan.get("text") or ""
                assistant_parts.append(text)
                yield f"event: message\ndata: {json.dumps({'delta': text}, ensure_ascii=False)}\n\n"
                yield "event: done\ndata: {\"message\": \"完成\"}\n\n"
                return
            if lit_payload:
                yield f"event: literature\ndata: {json.dumps(lit_payload, ensure_ascii=False)}\n\n"
            if lit_text:
                source = _static_reply(lit_text)
            elif debate_job is not None and not debate_job.get("ok"):
                source = _static_reply(debate_job.get("text") or "")
            elif debate_source == "topic" and debate_job is not None:
                from services.idea_debate import stream_topic
                source = stream_topic(
                    (debate_job.get("models") or [{}])[0],
                    req.message,
                    debate_participants,
                    debate_keys,
                    debate_bases,
                )
            elif debate_source == "summary" and debate_job is not None:
                from services.idea_debate import stream_summary
                source = stream_summary(
                    (debate_job.get("models") or [{}])[0],
                    summary_voices,
                    req.summarize_scope or "last",
                    list(req.summarize_pair or []),
                    debate_keys,
                    debate_bases,
                    list(req.summarize_rounds or []),
                )
            elif debate_job is not None:
                from services.idea_debate import stream_debate
                excerpt, total = "", 0
                if (req.open_path or "").strip():
                    from services.idea_debate import clip_open_excerpt
                    from services.workspace_manager import workspace_manager
                    opened = await workspace_manager.get_content(session_id, req.open_path or "", user_id)
                    if opened:
                        excerpt, total = clip_open_excerpt(opened)
                # 辩手带的参考材料：每篇最多 3000 字，合计 9000 字；读取走 get_content，扫描件自动走 OCR 缓存
                materials_text = ""
                if req.debate_materials:
                    from services.workspace_manager import workspace_manager as _wm
                    parts: list[str] = []
                    used = 0
                    for mat in req.debate_materials[:4]:
                        try:
                            body = await _wm.get_content(session_id, mat.path, user_id, mat.source or "site")
                        except Exception:
                            body = None
                        if not body:
                            continue
                        clip = body[: max(0, min(3000, 9000 - used))]
                        if not clip:
                            break
                        used += len(clip)
                        parts.append(f"[文件: {mat.name}]\n{clip}")
                    if parts:
                        materials_text = "\n\n".join(parts)
                from services.idea_debate import recent_socratic_turns
                prior_turns = recent_socratic_turns(stored_messages) if mode_name == "socratic" else ""
                source = stream_debate(
                    mode_name, req.message, debate_job.get("models") or [],
                    debate_keys, debate_bases, cancel_event, session_id, excerpt, total, prior_turns,
                    max_rounds=req.debate_rounds, materials_text=materials_text,
                )
            else:
                source = claude.chat(
                    session_id=session_id,
                    message=prompt,
                    cancel_event=cancel_event,
                    skill_name=skill_name,
                    api_key=api_key,
                    base_url=effective_base_url,
                    model=model,
                    is_first=is_first,
                    user_id=user_id,
                    allow_tools=allow_tools,
                    mode_line=mode_line,
                )
            async for evt in source:
                evt_type = evt.get("event", "")
                data = evt.get("data", {}) or {}
                if evt_type == "message" and data.get("delta"):
                    assistant_parts.append(str(data["delta"]))
                elif evt_type == "files_changed":
                    edits_payload = data
                elif evt_type == "debate_voice":
                    debate_voices.append(data)
                elif evt_type == "debate_topic":
                    debate_plan = data
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
            if not full and edits_payload:
                names = "、".join(
                    str(item.get("name") or item.get("path") or "")
                    for item in (edits_payload.get("files") or [])
                ).strip("、")
                full = f"已改文稿：{names}" if names else "已改文稿。"
            assistant_meta_obj = {"author": "助手", "author_id": user_id}
            if edits_payload:
                assistant_meta_obj["edits"] = edits_payload
            if pipeline_meta and not saw_error:
                assistant_meta_obj["pipeline"] = pipeline_meta
            if debate_voices and not saw_error:
                assistant_meta_obj["debate"] = {"voices": debate_voices}
            if debate_plan and not saw_error:
                assistant_meta_obj["debate_plan"] = debate_plan
            if lit_payload and not saw_error:
                assistant_meta_obj["literature"] = lit_payload
            assistant_meta = json.dumps(assistant_meta_obj, ensure_ascii=False)
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
            if skill_name == "idea-debate":
                from services.idea_debate import clear_debate_hints
                clear_debate_hints(session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/{session_id}/debate-hint")
async def debate_hint(session_id: str, body: DebateHintBody, user_id: str = Depends(get_user_id)):
    session = await state_tracker.get_session(session_id)
    if not session or session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    if (session.get("skill_name") or "") != "idea-debate":
        raise HTTPException(status_code=400, detail="当前入口不是多模型辩论")
    if session_id not in _active_generations:
        raise HTTPException(status_code=400, detail="这一轮还没开始，写好后直接发送")
    from services.idea_debate import release_debate_gate
    if not release_debate_gate(session_id, body.text or ""):
        raise HTTPException(status_code=400, detail="现在没有停在下一位，也没有写下方向")
    return {"ok": True}


@router.post("/{session_id}/chat/stop")
async def stop_chat(session_id: str):
    evt = _active_generations.get(session_id)
    if not evt:
        return {"ok": False, "message": "没有正在进行的生成任务"}
    evt.set()
    return {"ok": True, "message": "已停止生成"}
