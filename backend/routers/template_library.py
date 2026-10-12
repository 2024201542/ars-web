"""PPT 模块接口：模板库（内置 + 用户上传）、真实缩略图、选模板生成。

模板库的目录/解析/挑选逻辑都在 `services/ppt_library.py`，
和"对话框里一句生成 PPT"（`services/ppt_chat.py`）共用同一套，避免两边行为不一致。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from services import ppt_chat, ppt_library, ppt_template, ppt_theme, pptx_render, pptx_splice
from services.user_manager import get_user_id
from services.workspace_manager import user_dir, workspace_manager

router = APIRouter(prefix="/api/ppt", tags=["ppt"])


@router.post("/templates/{template_id}/rebuild-image-pages")
async def rebuild_image_pages(template_id: str, user_id: str = Depends(get_user_id)):
    """把"整页导出成图片"的模板页救活：渲染 → 擦字 → 重建成可编辑文本框 + 图片位。

    这些页原本一个字都改不了（设计稿是图片）。重建后就地替换原页，模板仍是同一套风格。
    """
    from services import ppt_shot

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
    from services import ppt_shot

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
    pages: list[int] = Field(default_factory=list)      # 1 起；空 = 自动挑 6 页
    model: str = Field("qwen-vl-max", max_length=40)


@router.post("/templates/{template_id}/vision-refine")
async def template_vision_refine(template_id: str, req: VisionRefineRequest,
                                 user_id: str = Depends(get_user_id)):
    """③ 用视觉模型（qwen-vl）校正模板的"标题/正文/配图位"，让填字落到对的位置。

    只对用户模板生效（内置模板本来就是按同一套规则生成的，不需要）。
    """
    from services import ppt_vision

    item = ppt_library.find(user_id, template_id)
    if not item or not item.get("file_path"):
        raise HTTPException(status_code=404, detail="模板不存在")
    if item.get("source") == "builtin":
        raise HTTPException(status_code=400, detail="内置模板不需要视觉校正")

    analysis = dict(item)
    specs = analysis.get("specimens") or []
    pages = [p for p in (req.pages or []) if 1 <= p <= len(specs)]
    if not pages:
        # 自动挑：文本框中等的正文页（最多 6 页），避开封面/目录/结尾
        auto = [s["index"] + 1 for s in specs
                if s.get("tag") not in ("cover", "toc", "end") and len(s.get("frames") or []) >= 3]
        pages = auto[:6]
    if not pages:
        raise HTTPException(status_code=400, detail="这份模板没有可校正的页面")

    results = []
    for page in pages:
        try:
            results.append(await ppt_vision.refine_page(user_id, analysis, item["file_path"], page,
                                                        req.model))
        except Exception as exc:
            results.append({"ok": False, "page": page, "error": f"{type(exc).__name__}: {exc}"})

    folder = ppt_library.user_tpl_dir(user_id)
    analysis.pop("file_path", None)
    ppt_template.save_analysis(folder / f"{template_id}.analysis.json", analysis)
    ok = sum(1 for r in results if r.get("ok"))
    changed = sum(1 for r in results if r.get("changed"))
    return {"ok": True, "pages": pages, "refined": ok, "changed": changed, "results": results}


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
    return {"ok": True}


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
                          user_id: str = Depends(get_user_id)):
    """生成结果的某页真实图片（供结果面板展示）。"""
    root = user_dir(user_id).resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    images = await asyncio.to_thread(pptx_render.render_pages, target, [max(1, page)])
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
async def module_file(path: str = Query(...), user_id: str = Depends(get_user_id)):
    """下载/预览模块生成的文件（限定在用户工作区内，防目录穿越）。"""
    root = user_dir(user_id).resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
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
