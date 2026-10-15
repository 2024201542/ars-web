"""PPT 模块接口：模板库（内置 + 用户上传）、真实缩略图、选模板生成。

模板库的目录/解析/挑选逻辑都在 `services/ppt/ppt_library.py`，
和"对话框里一句生成 PPT"（`services/ppt/ppt_chat.py`）共用同一套，避免两边行为不一致。
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import shutil
import tempfile
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from services.ppt import ppt_chat, ppt_library, ppt_pages, ppt_template, ppt_theme, pptx_render, pptx_splice
from services.user_manager import get_user_id
from services.workspace_manager import user_dir, workspace_manager

router = APIRouter(prefix="/api/ppt", tags=["ppt"])
logger = logging.getLogger(__name__)


@router.post("/templates/{template_id}/rebuild-image-pages")
async def rebuild_image_pages(template_id: str, user_id: str = Depends(get_user_id)):
    """把"整页导出成图片"的模板页救活：渲染 → 擦字 → 重建成可编辑文本框 + 图片位。

    这些页原本一个字都改不了（设计稿是图片）。重建后就地替换原页，模板仍是同一套风格。
    """
    from services.ppt import ppt_shot

    item = ppt_library.find(user_id, template_id)
    if not item or not item.get("file_path"):
        raise HTTPException(status_code=404, detail="模板不存在")
    if item.get("source") == "builtin":
        raise HTTPException(status_code=400, detail="内置模板不需要重建")

    analysis = dict(item)
    pages = [s["index"] + 1 for s in (analysis.get("specimens") or []) if s.get("image_only")]
    if not pages:
        return {"ok": True, "rebuilt": 0, "message": "这份模板没有整页图片化的页"}

    folder = ppt_library.user_tpl_dir(user_id)
    source = pathlib.Path(item["file_path"])
    out = folder / f"{template_id}_rebuilt.pptx"
    report = await asyncio.to_thread(
        ppt_shot.rebuild_image_only_pages, source, out, pages, folder / f"{template_id}_rebuild_assets"
    )
    if not report.get("ok"):
        raise HTTPException(status_code=400, detail=report.get("error") or "重建失败")

    # 用重建后的文件替换原模板，并重新解析
    await asyncio.to_thread(shutil.copyfile, out, source)
    out.unlink(missing_ok=True)
    refreshed = await asyncio.to_thread(ppt_template.analyze_pptx, source,
                                        tid=template_id, name=item.get("name") or template_id,
                                        source="user")
    ppt_template.save_analysis(folder / f"{template_id}.analysis.json", refreshed)
    return {"ok": True, "rebuilt": report.get("rebuilt"), "texts": report.get("texts"),
            "photos": report.get("photos"), "pages": report.get("pages"),
            "template": ppt_library.summary(refreshed, with_preview=False)}


@router.post("/templates/from-screenshot")
async def template_from_screenshot(files: list[UploadFile] = File(...),
                                   name: str = Query("截图模板"),
                                   user_id: str = Depends(get_user_id)):
    """② 截图变模板：把幻灯片截图（可多张，一张一页）做成一份可用模板。

    OCR 认字 → 擦掉原文字得到干净底图 → 在文字原位加可编辑文本框、给照片区加图片占位。
    """
    from services.ppt import ppt_shot

    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一张截图")
    tid = uuid.uuid4().hex[:12]
    folder = ppt_library.user_tpl_dir(user_id)
    work = folder / f"{tid}_assets"
    shots: list[pathlib.Path] = []
    for index, item in enumerate(files[:12]):
        data = await item.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="单张截图不要超过 20MB")
        suffix = pathlib.Path(item.filename or "").suffix or ".png"
        target = work / f"shot_{index + 1}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)
        shots.append(target)

    pptx_path = folder / f"{tid}.pptx"
    try:
        report = await asyncio.to_thread(ppt_shot.screenshot_to_pptx, [str(s) for s in shots],
                                         pptx_path, work)
        analysis = await asyncio.to_thread(ppt_template.analyze_pptx, pptx_path,
                                          tid=tid, name=name, source="user")
    except Exception as exc:
        pptx_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"这份截图做不成模板：{exc}")
    if not (analysis.get("specimens") or []):
        pptx_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="截图里没识别出可用文字")
    ppt_template.save_analysis(folder / f"{tid}.analysis.json", analysis)
    out = ppt_library.summary(analysis, with_preview=True)
    out["report"] = {k: report.get(k) for k in ("pages", "texts", "photos", "slide_w", "slide_h")}
    return out


class VisionRefineRequest(BaseModel):
    pages: list[int] = Field(default_factory=list)      # 1 起；空 = 有文字框的每一页
    model: str = Field("qwen3-vl-plus", max_length=40)


class ParseRequest(BaseModel):
    model: str = ""
    text_model: str = ""
    pages: list[int] = Field(default_factory=list)
    force: bool = False


def _friendly_vision_error(raw: str) -> str:
    from services.ppt import ppt_vision

    return ppt_vision.friendly_vision_error(raw)


def _parse_key(user_id: str, template_id: str) -> str:
    return f"parse:{user_id}:{template_id}"


def _parse_view(record: dict) -> dict:
    return {
        "status": record.get("status") or "none",
        "done": record.get("done") or 0,
        "total": record.get("total") or 0,
        "current_page": record.get("current_page") or 0,
        "errors": record.get("errors") or [],
        "job_id": record.get("job_id") or "",
    }


async def _begin_parse(user_id: str, template_id: str, req: ParseRequest) -> dict:
    from services.ppt import ppt_jobs, ppt_vision

    item = ppt_library.find(user_id, template_id)
    if not item or not item.get("file_path"):
        raise HTTPException(status_code=404, detail="模板不存在")
    if item.get("source") == "builtin":
        raise HTTPException(status_code=400, detail="内置模板不能解析")
    specs = item.get("specimens") or []
    pages = [p for p in (req.pages or []) if isinstance(p, int) and 1 <= p <= len(specs)]
    if not pages:
        pages = [int(spec.get("index") or 0) + 1 for spec in specs]
    if not pages:
        raise HTTPException(status_code=400, detail="这份模板没有可解析的页面")

    async def factory(progress: dict) -> None:
        progress["total"] = len(pages)
        await ppt_vision.run_parse(
            user_id, item, req.model or ppt_vision.DEFAULT_VISION_MODEL,
            pages, req.force, progress, text_model=req.text_model,
        )

    job_id = ppt_jobs.start(_parse_key(user_id, template_id), factory)
    return {"job_id": job_id, "total": len(pages)}


@router.post("/templates/{template_id}/parse")
async def start_template_parse(template_id: str, req: ParseRequest,
                               user_id: str = Depends(get_user_id)):
    """逐页看图解析。内置模板不能改。全部页试完后会再做一次整份归纳。"""
    return await _begin_parse(user_id, template_id, req)


@router.get("/templates/{template_id}/parse")
async def template_parse_status(template_id: str, user_id: str = Depends(get_user_id)):
    """进行中的任务看内存；重启后从页说明文件里的 parse 字段读上次进度。"""
    from services.ppt import ppt_jobs

    item = ppt_library.find(user_id, template_id)
    if not item:
        raise HTTPException(status_code=404, detail="模板不存在")
    live = ppt_jobs.status(_parse_key(user_id, template_id))
    if live.get("status") not in ("none", ""):
        return _parse_view(live)
    data = ppt_pages.load_pages(item) or {}
    return _parse_view(data.get("parse") or {})


@router.post("/templates/{template_id}/vision-refine")
async def template_vision_refine(template_id: str, req: VisionRefineRequest,
                                 user_id: str = Depends(get_user_id)):
    """旧的视觉校正入口。改成启动逐页解析，返回里仍带原来的字段。"""
    begun = await _begin_parse(user_id, template_id, ParseRequest(model=req.model, pages=req.pages))
    return {
        "ok": True,
        "job_id": begun["job_id"],
        "total": begun["total"],
        "pages": req.pages,
        "refined": 0,
        "changed": 0,
        "results": [],
    }


@router.get("/themes")
async def list_themes(user_id: str = Depends(get_user_id)):
    return {"themes": ppt_theme.list_themes(), "default": ppt_theme.DEFAULT_THEME}


@router.get("/render/status")
async def render_status(user_id: str = Depends(get_user_id)):
    """真实缩略图是否可用（找不到 DSH 自带 LibreOffice Kit 就只能用结构预览）。"""
    return {"available": pptx_render.available()}


@router.get("/templates")
async def list_templates(with_preview: bool = Query(True), user_id: str = Depends(get_user_id)):
    items = [ppt_library.summary(a, with_preview) for a in ppt_library.load_builtin()]
    items += [ppt_library.summary(a, with_preview) for a in ppt_library.load_user(user_id)]
    return {"templates": items, "count": len(items), "render": pptx_render.available()}


@router.get("/templates/{template_id}")
async def template_detail(template_id: str, user_id: str = Depends(get_user_id)):
    item = ppt_library.find(user_id, template_id)
    if not item:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "source": item.get("source"),
        "theme": item.get("theme"),
        "stats": item.get("stats"),
        "roles": item.get("manual_roles") or {},
        "specimens": [
            {"index": s["index"], "tag": s["tag"], "capacity": s["capacity"], "has_image": s["has_image"]}
            for s in item.get("specimens") or []
        ],
        "preview": ppt_template.structure_preview(item, max_slides=20),
    }


@router.post("/templates/upload")
async def upload_template(file: UploadFile = File(...), user_id: str = Depends(get_user_id)):
    name = (file.filename or "").strip()
    if not name.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="只支持 .pptx 模板")
    data = await file.read()
    if len(data) > ppt_library.MAX_TEMPLATE_BYTES:
        raise HTTPException(status_code=400, detail="模板太大（上限 40MB）")
    tid = uuid.uuid4().hex[:12]
    folder = ppt_library.user_tpl_dir(user_id)
    pptx_path = folder / f"{tid}.pptx"
    await asyncio.to_thread(pptx_path.write_bytes, data)
    try:
        analysis = await asyncio.to_thread(ppt_template.analyze_pptx, pptx_path,
                                          tid=tid, name=pathlib.Path(name).stem, source="user")
    except Exception as exc:
        pptx_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"这个文件解析不了：{exc}")
    if not (analysis.get("specimens") or []):
        pptx_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="这份 pptx 里没有可用的文字版式")
    ppt_template.save_analysis(folder / f"{tid}.analysis.json", analysis)
    return ppt_library.summary(analysis, with_preview=True)


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, user_id: str = Depends(get_user_id)):
    folder = ppt_library.user_tpl_dir(user_id)
    pptx_path = folder / f"{template_id}.pptx"
    if not pptx_path.exists():
        raise HTTPException(status_code=404, detail="只能删除自己上传的模板")
    pptx_path.unlink(missing_ok=True)
    (folder / f"{template_id}.analysis.json").unlink(missing_ok=True)
    (folder / f"{template_id}.pages.json").unlink(missing_ok=True)
    return {"ok": True}


class PagesPatch(BaseModel):
    pages: list[dict] = Field(default_factory=list)
    deck: dict = Field(default_factory=dict)


def _pages_template(user_id: str, template_id: str) -> dict:
    item = ppt_library.find(user_id, template_id)
    if not item or not item.get("file_path"):
        raise HTTPException(status_code=404, detail="模板不存在")
    return item


@router.get("/templates/{template_id}/pages")
async def get_template_pages(template_id: str, user_id: str = Depends(get_user_id)):
    """读页说明。还没解析过就按几何分析给一份草稿，parsed 为 false。"""
    item = _pages_template(user_id, template_id)
    data = ppt_pages.load_pages(item)
    if data is None:
        data = ppt_pages.empty_pages(item, item)
    return ppt_pages.annotate_boxes(data, item)


@router.put("/templates/{template_id}/pages")
async def put_template_pages(template_id: str, req: PagesPatch, user_id: str = Depends(get_user_id)):
    """改某一页的角色、形态或说明。内置模板不能改。"""
    item = _pages_template(user_id, template_id)
    if item.get("source") == "builtin":
        raise HTTPException(status_code=400, detail="内置模板的页说明不能改")
    data = ppt_pages.load_pages(item) or ppt_pages.empty_pages(item, item)
    ppt_pages.apply_user_patch(data, req.model_dump())
    errors = ppt_pages.validate_pages(data, int(data.get("page_count") or len(data.get("pages") or [])))
    if errors:
        raise HTTPException(status_code=400, detail=errors[0])
    data["template_sha1"] = ppt_pages.template_sha1(item["file_path"])
    ppt_pages.save_pages(item, data)
    saved = ppt_pages.load_pages(item) or data
    return ppt_pages.annotate_boxes(saved, item)


@router.get("/templates/{template_id}/pages/export")
async def export_template_pages(template_id: str, fmt: str = Query("json", alias="format"),
                                user_id: str = Depends(get_user_id)):
    item = _pages_template(user_id, template_id)
    data = ppt_pages.load_pages(item) or ppt_pages.empty_pages(item, item)
    stem = item.get("name") or template_id
    if fmt == "md":
        body = ppt_pages.to_markdown(data).encode("utf-8")
        filename = f"{stem}.模板页说明.md"
        media = "text/markdown; charset=utf-8"
    else:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        filename = f"{stem}.模板页说明.json"
        media = "application/json; charset=utf-8"
    from urllib.parse import quote
    return Response(content=body, media_type=media, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    })


@router.post("/templates/{template_id}/pages/import")
async def import_template_pages(template_id: str, file: UploadFile = File(...),
                                user_id: str = Depends(get_user_id)):
    item = _pages_template(user_id, template_id)
    if item.get("source") == "builtin":
        raise HTTPException(status_code=400, detail="内置模板的页说明不能改")
    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="页说明文件不能超过 2MB")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="这个文件不是 JSON")
    current = ppt_pages.load_pages(item) or ppt_pages.empty_pages(item, item)
    page_count = int(current.get("page_count") or len(current.get("pages") or []))
    result = ppt_pages.import_document(
        payload, current_sha=ppt_pages.template_sha1(item["file_path"]), page_count=page_count)
    by_page = {page.get("page"): page for page in current.get("pages") or []}
    merged = 0
    for incoming in result["imported"]:
        page = by_page.get(incoming.get("page"))
        if page is None:
            result["skipped"].append(incoming.get("page"))
            continue
        for key in ("role", "form", "narrative_fit", "description", "usable"):
            if key in incoming:
                page[key] = incoming[key]
        page["user_edited"] = True
        merged += 1
    current["template_sha1"] = ppt_pages.template_sha1(item["file_path"])
    ppt_pages.save_pages(item, current)
    return {"ok": True, "imported": merged, "skipped": result["skipped"], "warnings": result["warnings"]}


@router.post("/templates/{template_id}/pages/save-local")
async def save_template_pages_local(template_id: str, user_id: str = Depends(get_user_id)):
    item = _pages_template(user_id, template_id)
    data = ppt_pages.load_pages(item)
    if data is None:
        raise HTTPException(status_code=400, detail="还没有页说明")
    root = await workspace_manager.get_local_root(user_id)
    if root is None:
        raise HTTPException(status_code=400, detail="还没有打开本机文件夹")
    stem = item.get("name") or template_id
    saved_json = await workspace_manager.save_generated_file(
        user_id, f"{stem}.模板页说明.json",
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), root)
    saved_md = await workspace_manager.save_generated_file(
        user_id, f"{stem}.模板页说明.md",
        ppt_pages.to_markdown(data).encode("utf-8"), root)
    return {"json": saved_json.get("path"), "markdown": saved_md.get("path"), "source": saved_json.get("source")}


class RolesUpdate(BaseModel):
    roles: dict[str, int] = Field(default_factory=dict)


@router.put("/templates/{template_id}/roles")
async def set_roles(template_id: str, req: RolesUpdate, user_id: str = Depends(get_user_id)):
    """覆盖"版式角色 → 第几页"的映射（用户指定哪页当封面/内容页/…）。"""
    item = ppt_library.find(user_id, template_id)
    if not item:
        raise HTTPException(status_code=404, detail="模板不存在")
    if item.get("source") == "builtin":
        raise HTTPException(status_code=400, detail="内置模板不需要改版式")
    analysis = dict(item)
    ppt_template.apply_manual_roles(analysis, req.roles)
    folder = ppt_library.user_tpl_dir(user_id)
    ppt_template.save_analysis(folder / f"{template_id}.analysis.json", analysis)
    return {"ok": True, "roles": analysis.get("manual_roles") or {}}


@router.get("/templates/{template_id}/thumb.png")
async def template_thumb_image(template_id: str, page: int = Query(1),
                               user_id: str = Depends(get_user_id)):
    """模板某页的真实缩略图（渲染结果有磁盘缓存）。"""
    item = ppt_library.find(user_id, template_id)
    if not item or not item.get("file_path"):
        raise HTTPException(status_code=404, detail="模板不存在")
    images = await asyncio.to_thread(pptx_render.render_pages, item["file_path"], [max(1, page)])
    image = images.get(max(1, page))
    if not image:
        raise HTTPException(status_code=503, detail=pptx_render.available_reason())
    return FileResponse(image, media_type="image/png")


@router.get("/preview.png")
async def file_page_image(path: str = Query(...), page: int = Query(1),
                          source: str = Query(""),
                          version: int = Query(0),
                          user_id: str = Depends(get_user_id)):
    """生成结果的某页真实图片。带 version 时读那一版历史文件，用来做改前图。"""
    target, rel, resolved = await _resolve_user_file(user_id, path, source, (".pptx",))
    render_path = target
    if version:
        from services.ppt import ppt_history
        historical = ppt_history.folder_for(user_id, resolved, rel) / f"v{int(version)}.pptx"
        if historical.is_file():
            render_path = historical
    images = await asyncio.to_thread(pptx_render.render_pages, render_path, [max(1, page)])
    image = images.get(max(1, page))
    if not image:
        raise HTTPException(status_code=503, detail=pptx_render.available_reason())
    return FileResponse(image, media_type="image/png")


@router.get("/templates/{template_id}/thumb")
async def template_thumb(template_id: str, user_id: str = Depends(get_user_id)):
    """整套模板的 pptx 文件（前端可下载）。"""
    item = ppt_library.find(user_id, template_id)
    if not item or not item.get("file_path"):
        raise HTTPException(status_code=404, detail="模板不存在")
    return FileResponse(item["file_path"], filename=f"{item.get('name') or template_id}.pptx")


@router.get("/file")
async def module_file(path: str = Query(...), source: str = Query(""),
                      user_id: str = Depends(get_user_id)):
    """下载/预览模块生成的文件。路径必须落在当前用户的工作区或打开的本机文件夹里。"""
    target, _, _ = await _resolve_user_file(user_id, path, source, (".pptx", ".json"))
    return FileResponse(target, filename=target.name)


class GenerateRequest(BaseModel):
    material_text: str = Field("", max_length=200000)
    session_id: str = Field("", max_length=64)
    message_ids: list[int] = Field(default_factory=list)
    template_id: str = Field("", max_length=64)      # 空 = 用主题对应的内置版式库
    theme: str = Field("", max_length=40)
    pages: int = 0
    guidance: str = Field("", max_length=2000)
    model: str = Field("", max_length=80)
    filename: str = Field("", max_length=120)
    save_to_local: bool = False
    auto_image: bool = False        # 没配图素材时用万相生成一张


@router.post("/generate")
async def generate(req: GenerateRequest, user_id: str = Depends(get_user_id)):
    """选模板（或主题）生成一份 PPT（生成逻辑与对话框共用 ppt_chat.build_and_save）。"""
    from routers import workspace as workspace_router

    material = (req.material_text or "").strip()
    title_hint = (req.filename or "").strip()
    if req.session_id:
        session = await workspace_router.state_tracker.get_session(req.session_id)
        messages = await workspace_router.state_tracker.get_messages(req.session_id)
        picked = workspace_router._pick_messages(messages, set(req.message_ids or []), material)
        draft = workspace_router._draft_markdown(session or {}, picked)
        material = (material + "\n\n" + draft).strip() if material else draft
        title_hint = title_hint or (session or {}).get("title") or ""
    if not material:
        raise HTTPException(status_code=400, detail="没有素材：贴一段文字、选一段回复，或 @ 上文件")

    target_dir = None
    if req.save_to_local:
        local_root = await workspace_manager.get_local_root(user_id)
        target_dir = local_root if local_root else None

    info = await ppt_chat.build_and_save(
        user_id,
        material=ppt_chat.condense_material(material),
        guidance=req.guidance,
        pages=req.pages,
        model_id=req.model,
        title_hint=title_hint,
        template_id=req.template_id,
        theme=req.theme,
        save_dir=target_dir,
        filename=req.filename,
        auto_image=req.auto_image,
    )
    if info.get("error"):
        raise HTTPException(status_code=400, detail=info["error"])
    info["outline_kept"] = bool(info.get("outline_path"))
    return info


# ───────────── 计划 → 出片（新引擎的 REST 面） ─────────────

class PlanRequest(BaseModel):
    material_text: str = Field("", max_length=200000)
    session_id: str = Field("", max_length=64)
    message_ids: list[int] = Field(default_factory=list)
    pages: int = 0
    guidance: str = Field("", max_length=2000)
    model: str = Field("", max_length=80)


class RevisePlanRequest(BaseModel):
    plan_path: str = Field("", max_length=500)
    source: str = Field("", max_length=16)
    instruction: str = Field("", max_length=1000)
    model: str = Field("", max_length=80)


class PlanSaveRequest(BaseModel):
    plan_path: str = Field("", max_length=500)
    source: str = Field("", max_length=16)
    plan: dict = Field(default_factory=dict)


class RepickRequest(BaseModel):
    plan_path: str = Field("", max_length=500)
    source: str = Field("", max_length=16)
    slide: int = Field(1, ge=1, le=80)
    page: Optional[int] = None
    template_id: str = Field("", max_length=64)


class ComposeRequest(BaseModel):
    plan_path: str = Field("", max_length=500)
    source: str = Field("", max_length=16)
    template_id: str = Field("", max_length=64)
    filename: str = Field("", max_length=120)
    save_to_local: bool = False
    plan: Optional[dict] = None


class RepairRequest(BaseModel):
    path: str = Field("", max_length=500)
    source: str = Field("", max_length=16)


class EditRequest(BaseModel):
    plan_path: str = Field("", max_length=500)
    source: str = Field("", max_length=16)
    instruction: str = Field("", max_length=400)
    page: Optional[int] = None
    model: str = Field("", max_length=80)


class UndoRequest(BaseModel):
    path: str = Field("", max_length=500)
    source: str = Field("", max_length=16)
    version: Optional[int] = None


class BaseUpdate(BaseModel):
    base: dict = Field(default_factory=dict)


async def _material_from_request(req, user_id: str) -> str:
    """和对话框共用同一条取材料的路：贴的文字 + 会话里选中的回复。"""
    from routers import workspace as workspace_router

    material = (getattr(req, "material_text", "") or "").strip()
    session_id = getattr(req, "session_id", "") or ""
    if session_id:
        session = await workspace_router.state_tracker.get_session(session_id)
        messages = await workspace_router.state_tracker.get_messages(session_id)
        picked = workspace_router._pick_messages(
            messages, set(getattr(req, "message_ids", []) or []), material)
        draft = workspace_router._draft_markdown(session or {}, picked)
        material = (material + "\n\n" + draft).strip() if material else draft
    return material


def _within(target: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


async def _resolve_user_file(user_id: str, raw: str, source: str = "",
                             suffixes: tuple[str, ...] = (".json",)) -> tuple[pathlib.Path, str, str]:
    """把请求里的路径解析到当前用户的目录里。返回 (绝对路径, 相对路径, source)。

    接受相对路径，也接受已经落在用户目录里的绝对路径（老的计划卡还在用绝对路径）。
    越界返回 403。source 为 local 时只查打开的本机文件夹，为 site 时只查工作区。
    """
    text = (raw or "").strip().strip('"')
    if not text:
        raise HTTPException(status_code=400, detail="缺少路径")
    roots: list[tuple[pathlib.Path, str]] = []
    local = await workspace_manager.get_local_root(user_id)
    if local:
        roots.append((pathlib.Path(local).resolve(), "local"))
    roots.append((user_dir(user_id).resolve(), "site"))
    want = (source or "").strip()
    if want in ("local", "site"):
        roots = [item for item in roots if item[1] == want]
        if not roots:
            raise HTTPException(status_code=400, detail="还没有打开本机文件夹")
    candidate = pathlib.Path(text)
    found: tuple[pathlib.Path, str, str] | None = None
    escaped = False
    if candidate.is_absolute():
        resolved = candidate.resolve()
        for root, src in roots:
            if _within(resolved, root):
                rel = str(resolved.relative_to(root)).replace("\\", "/")
                found = (resolved, rel, src)
                break
        if found is None:
            raise HTTPException(status_code=403, detail="这个文件不在你的文件夹里")
    else:
        for root, src in roots:
            target = (root / text).resolve()
            if not _within(target, root):
                escaped = True
                continue
            if target.is_file():
                rel = str(target.relative_to(root)).replace("\\", "/")
                found = (target, rel, src)
                break
        if found is None and escaped:
            raise HTTPException(status_code=403, detail="这个文件不在你的文件夹里")
    if found is None:
        raise HTTPException(status_code=404, detail="找不到文件")
    target, rel, src = found
    if target.suffix.lower() not in suffixes:
        raise HTTPException(status_code=400, detail="文件类型不对")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="找不到文件")
    return target, rel, src


def _template_or_default(user_id: str, template_id: str):
    template = ppt_library.find(user_id, template_id) if template_id else None
    if template is None:
        template = ppt_library.builtin_for_theme("")
    return template


@router.post("/plan")
async def make_plan(req: PlanRequest, user_id: str = Depends(get_user_id)):
    """读材料出一份逐页计划（这一步不出片）。"""
    from services.ppt import ppt_plan

    material = await _material_from_request(req, user_id)
    if not material:
        raise HTTPException(status_code=400, detail="没有素材：贴一段文字、选一段回复，或 @ 上文件")
    plan, model_name, err = await ppt_plan.make_plan(
        user_id, material, model_id=req.model, pages=req.pages, guidance=req.guidance)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"plan": plan, "model": model_name}


@router.get("/layouts")
async def list_layouts(user_id: str = Depends(get_user_id)):
    """版式清单和每个字段的字数上限（界面显示「12/20」用，和出片校验同一份表）。"""
    from services.ppt import ppt_layouts

    limits = {key: ppt_layouts.limits_of(key) for key in ppt_layouts.LAYOUT_SPECS}
    return {"specs": ppt_layouts.LAYOUT_SPECS, "limits": limits}


@router.get("/plan")
async def read_plan(path: str = Query(...), source: str = Query(""),
                    user_id: str = Depends(get_user_id)):
    """读一份已经存下来的计划（界面刷新、从对话跳过来时要能重新加载）。"""
    target, rel, src = await _resolve_user_file(user_id, path, source, (".json",))
    try:
        plan = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"计划读不出来：{exc}")
    if "story_issues" not in plan:
        from services.ppt import ppt_story_check

        plan["story_issues"] = ppt_story_check.check_story(plan)
    return {"plan": plan, "plan_path": rel, "source": src}


@router.post("/plan/revise")
async def revise_plan(req: RevisePlanRequest, user_id: str = Depends(get_user_id)):
    """按一句话改计划，改完存回原文件。"""
    from services.ppt import ppt_plan

    path, _, _ = await _resolve_user_file(user_id, req.plan_path, req.source, (".json",))
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"计划读不出来：{exc}")
    new_plan, err = await ppt_plan.revise_plan(plan, req.instruction, req.model, user_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    new_plan = ppt_plan.normalize(new_plan)
    issues = ppt_plan.validate_plan(new_plan)
    if issues:
        new_plan = ppt_plan.hard_trim(new_plan, issues)
    from services.ppt import ppt_story_check

    new_plan["story_issues"] = ppt_story_check.check_story(new_plan)
    try:
        path.write_text(json.dumps(new_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"计划存不下来：{exc}")
    return {"plan": new_plan, "issues": ppt_plan.validate_plan(new_plan)}


@router.put("/plan")
async def save_plan(req: PlanSaveRequest, user_id: str = Depends(get_user_id)):
    """把编辑页上改过的计划写回原文件。"""
    from services.ppt import ppt_plan

    path, rel, src = await _resolve_user_file(user_id, req.plan_path, req.source, (".json",))
    plan = ppt_plan.normalize(req.plan or {})
    try:
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"计划存不下来：{exc}")
    return {"plan": plan, "plan_path": rel, "source": src, "issues": ppt_plan.validate_plan(plan)}


def _slot_for_slide(plan: dict, index: int) -> dict:
    """换页时用骨架位；没有骨架就按这一页的版式来。"""
    slots = ((plan or {}).get("storyline") or {}).get("slots") or []
    if index < len(slots) and isinstance(slots[index], dict):
        slot = dict(slots[index])
    else:
        slide = (plan.get("slides") or [])[index]
        slot = {
            "kind": "content",
            "form_hint": slide.get("layout") or "",
            "role": slide.get("role") or "",
            "message": slide.get("title") or "",
            "items": 0,
        }
    slide = (plan.get("slides") or [])[index]
    if isinstance(slide, dict):
        slot["pick_locked"] = bool(slide.get("pick_locked"))
        slot["template_page"] = slide.get("template_page")
    return slot


@router.post("/plan/repick")
async def repick_plan(req: RepickRequest, user_id: str = Depends(get_user_id)):
    """换某一页用的模板页。不给页号就返回前 6 名候选。"""
    from services.ppt import ppt_pagepick, ppt_roles

    path, rel, src = await _resolve_user_file(user_id, req.plan_path, req.source, (".json",))
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"计划读不出来：{exc}")
    slides = plan.get("slides") or []
    index = req.slide - 1
    if index < 0 or index >= len(slides):
        raise HTTPException(status_code=400, detail="没有这一页")
    template_id = (req.template_id or plan.get("template_id") or "").strip()
    if not template_id:
        raise HTTPException(status_code=400, detail="先选一套模板")
    catalog, base = ppt_pagepick.load_catalog(user_id, template_id)
    if not catalog:
        raise HTTPException(status_code=400, detail="这套模板读不到")
    slot = _slot_for_slide(plan, index)
    ranked = ppt_pagepick.top_candidates(slot, catalog, base, limit=6)
    for item in ranked:
        item["form_name"] = ppt_roles.CONTENT_FORMS.get(item.get("form"), "") or ppt_roles.PAGE_ROLES.get(item.get("role"), "")
    if not req.page:
        return {"candidates": ranked, "slide": req.slide, "plan_path": rel, "source": src}
    chosen = next((item for item in ppt_pagepick.top_candidates(slot, catalog, base, limit=80)
                   if item.get("page") == req.page), None)
    if chosen is None:
        raise HTTPException(status_code=400, detail="这一页不能用这个模板页")
    slide = slides[index]
    slide["template_page"] = int(req.page)
    slide["template_form"] = chosen.get("form") or ""
    slide["template_role"] = chosen.get("role") or ""
    slide["pick_reason"] = list(chosen.get("reasons") or [])
    slide["pick_fallback"] = False
    slide["pick_locked"] = True
    plan["template_id"] = template_id
    kind = str((_slot_for_slide(plan, index).get("kind") or ""))
    if kind in {"content", "summary"}:
        from services.ppt import ppt_plan

        plan, _note = await ppt_plan.rewrite_slide(plan, index, catalog, user_id)
    try:
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"计划存不下来：{exc}")
    return {"plan": plan, "plan_path": rel, "source": src, "slide": req.slide}


@router.post("/compose")
async def compose_deck(req: ComposeRequest, user_id: str = Depends(get_user_id)):
    """按计划出片，再跑一遍自检，返回产物路径、问题清单和缩略图页号。"""
    from services.ppt import ppt_base, ppt_check, ppt_compose, ppt_pages, ppt_plan

    path, rel, plan_source = await _resolve_user_file(user_id, req.plan_path, req.source, (".json",))
    if req.plan:
        plan = ppt_plan.normalize(req.plan)
        try:
            path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"计划存不下来：{exc}")
    else:
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"计划读不出来：{exc}")

    template = _template_or_default(user_id, req.template_id)
    if template is None or not template.get("file_path"):
        raise HTTPException(status_code=404, detail="找不到可用的模板")

    local_root = await workspace_manager.get_local_root(user_id) if req.save_to_local else None
    out_dir = ppt_chat.compose_out_dir(path.parent, req.save_to_local, local_root)

    stem = ppt_chat._safe_stem(req.filename or plan.get("title") or "汇报")
    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="ars_compose_"))
    tmp_path = tmp_dir / f"{stem}.pptx"
    try:
        page_doc = await asyncio.to_thread(
            lambda item: ppt_pages.load_pages(item) or ppt_pages.empty_pages(item, item), template)
        base = await asyncio.to_thread(ppt_base.base_for, template, page_doc)
        result = await asyncio.to_thread(
            ppt_compose.compose, base, plan, template["file_path"], tmp_path, None, template, page_doc,
            (rel, plan_source))
        data = tmp_path.read_bytes()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    try:
        saved = await workspace_manager.save_generated_file(
            user_id, f"{stem}.pptx", data, target_dir=out_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    saved_root = (await workspace_manager.get_local_root(user_id)
                  if saved.get("source") == "local" else user_dir(user_id))
    saved_abs = pathlib.Path(saved_root) / saved["path"]
    issues = await asyncio.to_thread(ppt_check.check_deck, saved_abs, base)
    thumbs = await asyncio.to_thread(ppt_check.render_thumbs, saved_abs, 72)
    from services.ppt import ppt_edit

    ppt_edit.remember_output(plan, saved["path"], saved.get("source") or plan_source, saved_abs.stat().st_mtime_ns)
    try:
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.warning("出片结果没能写回计划")

    return {
        "path": saved["path"],
        "source": saved.get("source") or plan_source,
        "name": saved["name"],
        "dir": saved.get("dir") or "",
        "pages": result.get("pages") or 0,
        "overflow": result.get("overflow") or [],
        "warnings": result.get("warnings") or [],
        "issues": issues,
        "repaired": result.get("repaired") or {"pulled": 0, "removed": 0},
        "template_pages": result.get("template_pages") or [],
        "base_confirmed": bool(base.get("confirmed")),
        "template": template.get("name") or "",
        "template_id": template.get("id") or "",
        "thumbs": [{"page": page} for page in sorted(thumbs)],
    }


@router.post("/edit")
async def edit_deck(req: EditRequest, user_id: str = Depends(get_user_id)):
    """按一句话改计划。对话和编辑页走同一条。"""
    from services.ppt import ppt_edit

    payload = None
    message = ""
    async for event in ppt_edit.run_instruction(
            user_id, req.plan_path, req.source, req.instruction, req.page, req.model):
        if event.get("event") == "ppt_edit":
            payload = event.get("data")
        if event.get("event") == "message":
            message = str((event.get("data") or {}).get("delta") or message)
    if payload is None:
        raise HTTPException(status_code=400, detail=message or "这次没能改")
    return payload


@router.post("/edit/undo")
async def undo_edit(req: UndoRequest, user_id: str = Depends(get_user_id)):
    """回到上一版。恢复前会先把当前文件存下来，所以这次撤销还能再撤销。"""
    from services.ppt import ppt_check, ppt_history

    path, rel, source = await _resolve_user_file(user_id, req.path, req.source, (".pptx",))
    info = ppt_history.meta_of(user_id, source, rel)
    plan_path = None
    if info.get("plan_rel"):
        plan_path, _plan_rel, _plan_source = await _resolve_user_file(
            user_id, info.get("plan_rel") or "", info.get("plan_source") or source, (".json",))
    version = ppt_history.restore(
        user_id, path, plan_path, req.version, source=source, rel=rel)
    if not version:
        raise HTTPException(status_code=400, detail="没有可撤销的版本")
    issues = []
    try:
        issues = await asyncio.to_thread(ppt_check.check_deck, path)
    except Exception:
        logger.warning("撤销后没能重新自检")
    return {"version": version, "rev": path.stat().st_mtime_ns, "issues": issues}


@router.get("/edit/history")
async def edit_history(path: str = "", source: str = "", user_id: str = Depends(get_user_id)):
    """列出这份 PPT 还留着的版本。"""
    from services.ppt import ppt_history

    _path, rel, resolved = await _resolve_user_file(user_id, path, source, (".pptx",))
    return {"versions": ppt_history.history(user_id, _path, source=resolved, rel=rel)}


@router.post("/repair")
async def repair_deck(req: RepairRequest, user_id: str = Depends(get_user_id)):
    """把已经生成的 pptx 里跑出页面的框拉回来，并删掉压在正文上的模板字。"""
    from services.ppt import ppt_check

    path, rel, source = await _resolve_user_file(user_id, req.path, req.source, (".pptx",))
    repaired = await asyncio.to_thread(ppt_check.repair_deck, path)
    from services.ppt.pptx_splice import sync_app_props

    await asyncio.to_thread(sync_app_props, path)
    issues = await asyncio.to_thread(ppt_check.check_deck, path)
    rev = path.stat().st_mtime_ns
    return {"path": rel, "source": source, "issues": issues, "repaired": repaired, "rev": rev}


@router.get("/templates/{template_id}/base")
async def get_template_base(template_id: str, user_id: str = Depends(get_user_id)):
    """读底板档案；还没有就现场猜一份（不落盘，等用户确认后再 PUT）。"""
    from services.ppt import ppt_base

    base = ppt_base.load_base(template_id)
    if base is None:
        template = ppt_library.find(user_id, template_id)
        if template is None or not template.get("file_path"):
            raise HTTPException(status_code=404, detail="找不到这个模板")
        page_doc = ppt_pages.load_pages(template)
        base = await asyncio.to_thread(ppt_base.guess_base, template["file_path"], page_doc)
        base["confirmed"] = False
    return {"base": base, "template": template_id}


@router.get("/templates/{template_id}/base/preview")
async def template_base_preview(template_id: str, page: int = Query(1),
                                user_id: str = Depends(get_user_id)):
    """用指定页当内容底板，清空安全区后渲染一页，给「设置底板」看效果。"""
    from pptx import Presentation

    from services.ppt import ppt_base
    from services.ppt.pptx_splice import _delete_slides

    template = ppt_library.find(user_id, template_id)
    if template is None or not template.get("file_path"):
        raise HTTPException(status_code=404, detail="找不到这个模板")
    base = await asyncio.to_thread(ppt_base.base_for, template)

    def _render() -> str:
        prs = Presentation(template["file_path"])
        slides = list(prs.slides)
        if not slides:
            raise ValueError("模板里没有幻灯片")
        index = min(max(1, page), len(slides)) - 1
        original = len(slides)
        ppt_base.content_canvas(prs, slides[index], base, "标题会写在这里", 2)
        _delete_slides(prs, original)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="ars_base_")) / "preview.pptx"
        prs.save(str(tmp))
        images = pptx_render.render_pages(tmp, [1], dpi=72)
        image = images.get(1)
        if not image:
            raise RuntimeError(pptx_render.available_reason())
        return str(image)

    try:
        image = await asyncio.to_thread(_render)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"预览没能生成：{exc}")
    return FileResponse(image, media_type="image/png")


@router.put("/templates/{template_id}/base")
async def put_template_base(template_id: str, req: BaseUpdate,
                            user_id: str = Depends(get_user_id)):
    """保存用户确认过的底板档案。内置模板的底板是大家共用的，不能改。"""
    from services.ppt import ppt_base

    if (template_id or "").startswith("builtin-"):
        raise HTTPException(status_code=403, detail="内置模板的底板不能改")
    template = ppt_library.find(user_id, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="找不到这个模板")
    try:
        ppt_base.save_base(template_id, req.base or {})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"底板档案存不下来：{exc}")
    return {"ok": True, "base": ppt_base.load_base(template_id)}
