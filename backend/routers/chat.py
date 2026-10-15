"""对话/流式输出 API —— 全模型走 Claude Code CLI 引擎"""

import asyncio
import json
import pathlib

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
logger = get_logger(__name__)
BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]


class DebateHintBody(BaseModel):
    text: str = Field("", max_length=1000)


async def _static_reply(text: str):
    yield {"event": "message", "data": {"delta": text}}
    yield {"event": "done", "data": {"message": "完成"}}


def _plan_from_message(message: dict) -> dict | None:
    meta = message.get("metadata")
    if isinstance(meta, str) and meta:
        try:
            meta = json.loads(meta)
        except Exception:
            return None
    if not isinstance(meta, dict):
        return None
    plan = meta.get("ppt_plan")
    if isinstance(plan, dict) and plan.get("plan_path"):
        return plan
    return None


async def _store_plan(user_id: str, save_dir, plan: dict) -> dict:
    """把计划写进用户自己的目录，返回相对路径和 source。"""
    from services.ppt import ppt_chat
    from services.workspace_manager import user_dir, workspace_manager

    if save_dir is None:
        folder = user_dir(user_id) / "generated"
    else:
        folder = pathlib.Path(save_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stem = ppt_chat._safe_stem((plan or {}).get("title") or "汇报")
    path = folder / f"{stem}.ppt计划.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    local = await workspace_manager.get_local_root(user_id)
    if local and workspace_manager._is_inside(path, pathlib.Path(local)):
        root, source = pathlib.Path(local).resolve(), "local"
    else:
        root, source = user_dir(user_id).resolve(), "site"
    rel = str(path.resolve().relative_to(root)).replace("\\", "/")
    return {"plan_path": rel, "source": source}


async def _store_draft(user_id: str, save_dir, title: str, text: str) -> dict:
    """内容稿和计划放在同一个文件夹。"""
    from services.ppt import ppt_chat
    from services.workspace_manager import user_dir, workspace_manager

    if save_dir is None:
        folder = user_dir(user_id) / "generated"
    else:
        folder = pathlib.Path(save_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stem = ppt_chat._safe_stem(title or "内容稿")
    path = folder / f"{stem}.内容稿.md"
    path.write_text(text, encoding="utf-8")
    local = await workspace_manager.get_local_root(user_id)
    if local and workspace_manager._is_inside(path, pathlib.Path(local)):
        root, source = pathlib.Path(local).resolve(), "local"
    else:
        root, source = user_dir(user_id).resolve(), "site"
    rel = str(path.resolve().relative_to(root)).replace("\\", "/")
    return {"draft_path": rel, "source": source}


async def _read_saved_draft(session_id: str, user_id: str, messages: list[dict]) -> tuple[str, str]:
    """最近一份计划旁边的内容稿。返回 (相对路径, 正文)。没有就是空。"""
    from services.workspace_manager import workspace_manager

    for message in reversed(messages or []):
        found = _plan_from_message(message)
        if not found or not found.get("draft_path"):
            continue
        source = found.get("source") or "local"
        text = await workspace_manager.get_content(
            session_id, found["draft_path"], user_id, source)
        return found["draft_path"], (text or "").strip()
    return "", ""


def _changed_pages(before: dict, after: dict) -> list[int]:
    old = list((before or {}).get("slides") or [])
    new = list((after or {}).get("slides") or [])
    changed = []
    for index in range(max(len(old), len(new))):
        left = old[index] if index < len(old) else None
        right = new[index] if index < len(new) else None
        if left != right:
            changed.append(index + 1)
    return changed


async def _ppt_edit_reply(user_id: str, req, plan_meta: dict):
    """一句修改意见拆成操作，只改点到的页。"""
    from services.ppt import ppt_edit

    instruction = (getattr(req, "user_text", "") or "").strip() or (req.message or "").strip()
    page = getattr(req, "current_page", None)
    async for event in ppt_edit.run_instruction(
            user_id, plan_meta.get("plan_path") or "", plan_meta.get("source") or "",
            instruction, page, getattr(req, "model", "") or ""):
        yield event


async def _ppt_revise_reply(user_id: str, req, plan_meta: dict):
    """上一条是 PPT 计划时，把这句话交给改计划，而不是普通聊天。"""
    from routers.template_library import _resolve_user_file
    from services.ppt import ppt_layouts, ppt_plan

    instruction = (getattr(req, "user_text", "") or "").strip() or (req.message or "").strip()
    try:
        path, rel, source = await _resolve_user_file(
            user_id, plan_meta.get("plan_path") or "", plan_meta.get("source") or "", (".json",))
        plan = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        yield {"event": "message", "data": {"delta": f"这次没能读到计划：{detail}"}}
        yield {"event": "done", "data": {"message": "完成"}}
        return
    yield {"event": "phase_start", "data": {"phase": "tool", "description": "正在按你的要求改计划"}}
    new_plan, err = await ppt_plan.revise_plan(plan, instruction, req.model or "", user_id)
    if err and ppt_plan.parse_layout_change(instruction) is None:
        yield {"event": "message", "data": {"delta": f"这次没能改计划：{err}"}}
        yield {"event": "done", "data": {"message": "完成"}}
        return
    if err:
        new_plan = plan
    new_plan = ppt_plan.pin_other_pages(plan, new_plan, instruction)
    new_plan = ppt_plan.normalize(new_plan)
    new_plan = ppt_plan.force_layout_change(new_plan, instruction)
    new_plan = ppt_plan.normalize(new_plan)
    issues = ppt_plan.validate_plan(new_plan)
    if issues:
        new_plan = ppt_plan.hard_trim(new_plan, issues)
    from services.ppt import ppt_story_check

    new_plan["story_issues"] = ppt_story_check.check_story(new_plan)
    path.write_text(json.dumps(new_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    changed = _changed_pages(plan, new_plan)
    parsed = ppt_plan.parse_layout_change(instruction)
    if parsed:
        page, layout = parsed
        name = ppt_layouts.LAYOUT_SPECS[layout]["name"]
        where = f"第 {page} 页已改成{name}"
        if 2 in changed and page != 2:
            where += "，目录也按章节改了一下"
    else:
        where = "、".join(f"第 {n} 页" for n in changed[:6]) or "没有改动页"
    yield {"event": "ppt_plan", "data": {
        "plan_path": rel,
        "source": source,
        "plan": new_plan,
        "model": req.model or "",
        "template_id": plan_meta.get("template_id") or "",
        "revised": True,
        "changed_pages": changed,
        "story_issue_count": len(new_plan.get("story_issues") or []),
    }}
    yield {"event": "message", "data": {"delta": f"已按你的要求改了计划（{where}）。确认后点「生成 PPT」。"}}
    yield {"event": "done", "data": {"message": "完成"}}


async def _ppt_reply(session_id: str, user_id: str, req, messages: list[dict]):
    """对话框里说一句要 PPT，就直接生成 .pptx 并放到附件所在文件夹。"""
    from services.ppt import ppt_chat
    from services.workspace_manager import workspace_manager

    async def workspace_manager_resolve(uid: str, rel: str, source: str):
        return await workspace_manager.resolve_file(uid, rel, source or "site")

    parts: list[str] = []
    message = (req.message or "").strip()
    if message:
        parts.append(message)
    # 文件夹和来源要先定下来，材料才知道该读哪、该不该用对话。
    paths = list(getattr(req, "attach_paths", None) or [])
    if (req.open_path or "").strip():
        paths.append(req.open_path.strip())
    instruction = (getattr(req, "user_text", "") or "").strip()
    if not instruction:
        marker = "用户问题:"
        raw = req.message or ""
        instruction = raw.rsplit(marker, 1)[-1].strip() if marker in raw else raw
    folder_text = instruction + "\n" + (req.message or "")
    save_dir, asked_folder = await ppt_chat.named_save_dir(user_id, folder_text)
    if save_dir is None:
        save_dir = await ppt_chat.resolve_save_dir(user_id, paths, getattr(req, "attach_source", "") or "")
    if save_dir is None:
        # 没带附件时，直接写进用户当前打开的那个本机文件夹——
        # 否则文件落在工作区 generated/，而左侧文件树显示的是本机文件夹，用户会"看不到文件"。
        save_dir = await workspace_manager.get_local_root(user_id)

    named_hit = bool(asked_folder) and save_dir is not None and save_dir.name == asked_folder
    attached = ppt_chat.attached_names(message)
    folder_names: list[str] = []
    folder_empty = False
    if named_hit:
        folder_body, folder_names = await ppt_chat.load_folder_material(
            user_id, session_id, save_dir, skip_names=set(attached))
        if folder_body:
            parts.append(folder_body)
        elif not attached:
            folder_empty = True
    # 没带文件、文件夹里也没有文稿时，才用最近的讨论。状态句（已列出计划、已出片）不当材料。
    used_discussion = False
    if not attached and not folder_names:
        discussion = ppt_chat.recent_discussion(messages)
        if discussion:
            parts.extend(discussion)
            used_discussion = True
    material = ppt_chat.condense_material("\n\n".join(parts))
    material_from = ppt_chat.source_label(folder_names or attached, used_discussion)
    draft_rel = ""
    rebuild = ppt_chat.wants_rebuild_from_draft(instruction)
    if rebuild:
        draft_rel, draft_text = await _read_saved_draft(session_id, user_id, messages)
        if not draft_text:
            yield {"event": "message", "data": {"delta": "没有找到内容稿。先让它生成一份，改完再说「按内容稿重出计划」。"}}
            yield {"event": "done", "data": {"message": "完成"}}
            return
        material = draft_text
        material_from = pathlib.Path(draft_rel).name

    # 配图素材：附件里"是图片"的当配图；附了 PDF 就顺手把里面的图表抽出来当配图候选
    from services.ppt import ppt_image

    image_paths: list[str] = []
    for raw in paths:
        try:
            resolved = await workspace_manager_resolve(user_id, raw, getattr(req, "attach_source", "") or "")
        except Exception:
            resolved = None
        if not resolved:
            continue
        if ppt_image.is_image(resolved):
            image_paths.append(str(resolved))
        elif str(resolved).lower().endswith(".pdf"):
            from services.workspace_manager import user_dir

            out_dir = (save_dir or (user_dir(user_id) / "generated")) / "_ppt_images"
            extracted = await asyncio.to_thread(
                ppt_image.extract_from_pdf, str(resolved), str(out_dir), 200, 6
            )
            image_paths.extend(a["path"] for a in extracted)
            if extracted:
                logger.info("从 PDF 抽出 %d 张图当配图", len(extracted))

    if ppt_chat.current_engine() != "splice":
        # 新路：只列计划，不直接出片。用户看过计划、确认以后再调 /api/ppt/compose。
        from services.ppt import ppt_plan

        if not rebuild and ppt_plan.needs_content_draft(material):
            yield {"event": "phase_start",
                   "data": {"phase": "tool", "description": "正在写内容稿（约 20–40 秒）"}}
            draft, _, draft_err = await ppt_plan.write_content_draft(
                user_id, material, req.model or "")
            if draft_err or not (draft or "").strip():
                logger.warning("内容稿没写成，按题目列计划：%s", draft_err)
            else:
                try:
                    stored_draft = await _store_draft(
                        user_id, save_dir, ppt_plan.draft_title(draft), draft)
                except Exception as exc:
                    logger.warning("内容稿没能存下来：%s", exc)
                    stored_draft = {}
                if stored_draft.get("draft_path"):
                    draft_rel = stored_draft["draft_path"]
                    material = draft
                    material_from = pathlib.Path(draft_rel).name
        yield {"event": "phase_start",
               "data": {"phase": "tool", "description": "正在读材料、列 PPT 计划（约 20–60 秒）"}}
        plan, used_model, err = await ppt_plan.make_plan(
            user_id, material, model_id=req.model or "",
            pages=int(getattr(req, "ppt_pages", 0) or 0), guidance=instruction,
            template_id=(getattr(req, "ppt_template_id", "") or "").strip())
        if err:
            yield {"event": "message", "data": {"delta": f"这次没能列出 PPT 计划：{err}"}}
            yield {"event": "done", "data": {"message": "完成"}}
            return
        try:
            stored = await _store_plan(user_id, save_dir, plan)
        except Exception as exc:
            yield {"event": "message", "data": {"delta": f"计划没能存下来：{exc}"}}
            yield {"event": "done", "data": {"message": "完成"}}
            return
        story_issues = plan.get("story_issues") or []
        yield {"event": "ppt_plan", "data": {
            "plan_path": stored["plan_path"],
            "source": stored["source"],
            "plan": plan,
            "model": used_model,
            "template_id": (getattr(req, "ppt_template_id", "") or "").strip(),
            "material_from": material_from,
            "draft_path": draft_rel,
            "deck_type": (plan.get("storyline") or {}).get("deck_type") or "",
            "story_issue_count": len(story_issues),
        }}
        place = save_dir.name if save_dir is not None else "工作区"
        missing = ""
        if asked_folder and (save_dir is None or save_dir.name != asked_folder):
            missing = f"左侧没有叫「{asked_folder}」的文件夹，所以没有放进去。"
        empty_line = "这个文件夹里没有可读的文稿，按题目来写。\n" if folder_empty else ""
        quality = plan.get("quality") or {}
        thin_line = ""
        if quality.get("thin_before"):
            thin_line = (f"内容偏薄 {quality.get('thin_before')} 页，"
                         f"已自动充实 {quality.get('enriched') or 0} 页。\n")
        draft_line = ""
        if draft_rel:
            draft_name = pathlib.Path(draft_rel).name
            if rebuild:
                draft_line = f"已按内容稿「{draft_name}」重出。\n"
            else:
                draft_line = f"内容稿已放在旁边：{draft_name}。改完可以说「按内容稿重出计划」。\n"
        from services.ppt import ppt_story, ppt_story_check

        story = plan.get("storyline") or {}
        if story.get("sections"):
            structure_line = "结构：" + ppt_story.structure_line(story) + "。\n"
        elif plan.get("story_note"):
            structure_line = str(plan["story_note"]) + "。\n"
        else:
            structure_line = ""
        write_line = (str(plan["write_note"]) + "。\n") if plan.get("write_note") else ""
        story_issues = plan.get("story_issues") or []
        check_line = f"讲法检查：{len(story_issues)} 个问题。\n" if story_issues else "讲法检查：没有问题。\n"
        sentence = ppt_story_check.review_sentence(plan)
        score_line = ""
        if sentence:
            score_line = sentence + ("\n" if sentence.endswith("。") else "。\n")
        yield {"event": "message", "data": {"delta": (
            f"已列出 {len(plan.get('slides') or [])} 页计划，放在「{place}」。确认后点「生成 PPT」。\n"
            f"材料来自：{material_from}。\n"
            + structure_line
            + write_line
            + check_line
            + score_line
            + draft_line
            + thin_line
            + missing
            + empty_line
            + "想改就直接说，比如「第 6 页改成时间轴」「整体压到 10 页」。")}}
        yield {"event": "done", "data": {"message": "完成"}}
        return

    yield {"event": "phase_start",
           "data": {"phase": "tool", "description": "正在整理大纲并生成 PPT（约 15–60 秒）"}}
    info = await ppt_chat.build_and_save(
        user_id,
        material=material,
        guidance="",
        pages=int(getattr(req, "ppt_pages", 0) or 0),
        model_id=req.model or "",
        title_hint="",
        template_id=(getattr(req, "ppt_template_id", "") or "").strip(),
        save_dir=save_dir,
        images=image_paths,
        auto_image=bool(getattr(req, "ppt_auto_image", False)),
    )
    if info.get("error"):
        yield {"event": "message", "data": {"delta": f"这次没能生成 PPT：{info['error']}"}}
        yield {"event": "done", "data": {"message": "完成"}}
        return
    where = info.get("dir") or ""
    if info.get("source") == "local":
        where = f"你打开的文件夹{f'（{where}）' if where else ''}"
    else:
        where = where or "工作区 generated"
    yield {"event": "ppt_created", "data": info}
    sections = "、".join([s for s in (info.get("sections") or []) if s][:6])
    template_line = f"用了模板：{info['template']}\n" if info.get("template") else ""
    yield {
        "event": "message",
        "data": {"delta": (
            f"已生成 PPT：**{info['name']}**（{info['pages']} 页，{info['model']}）\n"
            + template_line
            + f"保存位置：{where}\n"
            + (f"页面顺序：{sections}\n" if sections else "")
            + "可以在中间预览区直接改文字后写回，也可以在左侧文件栏下载。"
        )},
    }
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
    # 让模型知道界面能出真正的 pptx（否则它会答"生成不了二进制文档"，误导用户）
    from services.entry_prompt import CAPABILITY_LINE
    prompt = f"{prompt}\n\n{CAPABILITY_LINE}"
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
    # 对话框里说"根据这个写个 ppt" → 直接生成文件，不再走模型闲谈
    ppt_job = False
    ppt_revise = None
    ppt_info: dict | None = None
    ppt_plan_meta = None
    ppt_edit_meta = None
    if not lit_text and skill_name not in {"idea-debate", "academic-pipeline"}:
        from services.ppt.ppt_chat import wants_plan_revise, wants_ppt, wants_rebuild_from_draft

        check_text = (getattr(req, "user_text", "") or "").strip()
        if not check_text:
            # 前端没单独传时，从注入的正文里把"用户问题"那段抽出来
            marker = "用户问题:"
            check_text = req.message.rsplit(marker, 1)[-1] if marker in req.message else req.message
        ppt_job = wants_ppt(check_text) or wants_rebuild_from_draft(check_text)
        if not ppt_job:
            from services.ppt import ppt_edit_intent

            found_plan = None
            for message in reversed(stored_messages):
                if message.get("role") != "assistant":
                    continue
                found = _plan_from_message(message)
                if found:
                    found_plan = found
                    break
            if found_plan:
                plan_doc = None
                if ppt_edit_intent.quick_classify(check_text) == "unsure":
                    try:
                        from routers.template_library import _resolve_user_file

                        path, _rel, _source = await _resolve_user_file(
                            user_id, found_plan.get("plan_path") or "",
                            found_plan.get("source") or "", (".json",))
                        plan_doc = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:
                        plan_doc = None
                decision = await ppt_edit_intent.classify(
                    check_text, plan_doc, req.model or "", user_id)
                if decision.get("kind") == "edit":
                    ppt_revise = found_plan
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
        nonlocal ppt_info, ppt_plan_meta, ppt_edit_meta
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
            if ppt_revise:
                source = _ppt_edit_reply(user_id, req, ppt_revise)
            elif ppt_job:
                source = _ppt_reply(session_id, user_id, req, stored_messages)
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
                elif evt_type == "ppt_created":
                    ppt_info = data
                elif evt_type == "ppt_plan":
                    ppt_plan_meta = data
                elif evt_type == "ppt_edit":
                    ppt_edit_meta = data
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
            if ppt_info:
                assistant_meta_obj["ppt"] = ppt_info
            if ppt_plan_meta:
                assistant_meta_obj["ppt_plan"] = ppt_plan_meta
            if ppt_edit_meta:
                assistant_meta_obj["ppt_edit"] = ppt_edit_meta
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
