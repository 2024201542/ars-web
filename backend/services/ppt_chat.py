"""PPT 生成的服务入口：供 REST 接口与"对话框一句话生成"共用。

把它独立出来，是为了让两处走完全同一条路径（同一套大纲提示词、同一个生成器、
同一套落盘规则），避免两边行为不一致。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import tempfile
import uuid
from typing import Optional

from services import ppt_template, ppt_theme
from services.workspace_manager import workspace_manager


async def resolve_save_dir(user_id: str, paths: list[str], source: str = "") -> Optional[pathlib.Path]:
    """由"附件/正在预览的文件"推断保存目录：取第一个能解析到的文件的所在目录。

    解析不到就返回 None（调用方回落到 generated/）。
    """
    from services import workspace_manager as _wm

    for raw in paths:
        rel = (raw or "").strip()
        if not rel:
            continue
        try:
            fp = await _wm.workspace_manager.resolve_file(user_id, rel, source or "site")
        except Exception:
            fp = None
        if not fp:
            continue
        parent = pathlib.Path(fp).parent
        if parent and str(parent) not in ("", "."):
            return parent
    return None


async def build_and_save(
    user_id: str,
    *,
    material: str,
    guidance: str = "",
    pages: int = 0,
    model_id: str = "",
    title_hint: str = "",
    template_path: str = "",
    template_id: str = "",
    theme: str = "",
    save_dir: Optional[pathlib.Path] = None,
    filename: str = "",
    save_outline: bool = True,
    images: Optional[list[str]] = None,
    auto_image: bool = False,
) -> dict:
    """生成大纲 → 出 .pptx → 落盘（可选同时存 outline.json）。失败返回 {"error": ...}。

    出片有两条路：
    - 给了模板（`template_id` 或 `template_path`）→ **拼接**：克隆模板版式页、替换文字，保住模板观感；
    - 没给 → 用所选主题对应的内置模板当版式库（同样走拼接），再不行才退回老 builder。
    """
    from services import ppt_library, pptx_builder, pptx_outline, pptx_splice

    material = (material or "").strip()
    if not material:
        return {"error": "没有可用的材料：请先选中一段回复，或 @ 上要参考的文件"}

    template = ppt_library.find(user_id, template_id) if template_id else None
    legacy_template: Optional[pathlib.Path] = None
    if template is None and template_path:
        candidate = pathlib.Path(template_path)
        if not candidate.is_file():
            resolved = await workspace_manager.get_user_file_path(user_id, template_path)
            if resolved:
                candidate = pathlib.Path(resolved)
        if candidate.is_file() and candidate.suffix.lower() == ".pptx":
            analysis = ppt_template.load_analysis(candidate.with_suffix(".analysis.json"))
            if analysis:
                template = {**analysis, "file_path": str(candidate)}
            else:
                legacy_template = candidate        # 老行为：直接把这个 pptx 当模板套版式
    theme_template = False
    if template is None and legacy_template is None:
        template = ppt_library.builtin_for_theme(theme or "")
        theme_template = template is not None

    guidance = "\n".join(x for x in [(guidance or "").strip(), ppt_library.LAYOUT_HINT] if x)
    # 有配图时告诉模型有哪几张、什么形状，它才能把图排到合适的页
    if images:
        from services import ppt_image

        assets = ppt_image.collect(images)
        if assets:
            lines = [f"图{i + 1}：{a['name']}（{a['orient']}，{a['width']}x{a['height']}）" for i, a in enumerate(assets)]
            guidance += (
                "\n\n这次有配图素材，可以给页面加 image 字段指定用第几张图（1 起）：\n"
                + "\n".join(lines)
                + "\n把图放在需要说明的页面上；竖图适合两栏/图文页，横图适合整页图或图文页。"
            )
            pages_with_images = True
    outline, used_model, err = await pptx_outline.generate_outline(
        user_id, material, model_id, guidance, pages, title_hint
    )
    if err:
        return {"error": err}
    if not outline or not outline.get("slides"):
        return {"error": "模型没有给出可用的大纲"}

    outline.setdefault("theme", {})
    if not outline.get("theme", {}).get("accent"):
        outline["theme"] = ppt_theme.outline_theme(theme)

    stem = _safe_stem(filename or outline.get("title") or title_hint or "汇报")
    warnings: list[str] = []
    used_tags: list[str] = []
    generated_image = ""

    # 没配图素材、用户又要"自动配图" → 用万相按标题生成一张
    if auto_image and not images:
        from services import ppt_genimage

        title_for_image = str(outline.get("title") or (outline.get("slides") or [{}])[0].get("title") or "")
        made, err = await ppt_genimage.generate_image(user_id, title_for_image or stem)
        if made:
            images = [str(made)]
            generated_image = made.name
        elif err:
            warnings.append(f"自动配图没成功：{err}")

    try:
        if template and template.get("file_path"):
            out_tmp = pathlib.Path(tempfile.gettempdir()) / f"ppt_splice_{uuid.uuid4().hex[:8]}.pptx"
            stats = await asyncio.to_thread(
                pptx_splice.splice, template, outline, template["file_path"], out_tmp, images
            )
            data = await asyncio.to_thread(out_tmp.read_bytes)
            out_tmp.unlink(missing_ok=True)
            used_tags = stats.get("used_tags") or []
            warnings = stats.get("warnings") or []
        else:
            data = await asyncio.to_thread(pptx_builder.build_pptx, outline, legacy_template)
    except Exception as exc:
        return {"error": f"生成 PPT 失败：{exc}"}

    outline_path = ""
    if save_outline:
        try:
            saved_outline = await workspace_manager.save_generated_file(
                user_id, f"{stem}.outline.json",
                json.dumps(outline, ensure_ascii=False, indent=2).encode("utf-8"),
                target_dir=save_dir,
            )
            outline_path = saved_outline.get("path") or ""
        except Exception:
            outline_path = ""

    try:
        info = await workspace_manager.save_generated_file(
            user_id, f"{stem}.pptx", data, target_dir=save_dir
        )
    except Exception as exc:
        return {"error": f"保存 PPT 失败：{exc}"}

    info.update({
        "format": "pptx",
        "pages": len(outline.get("slides") or []),
        "outline_path": outline_path,
        "model": used_model,
        "fallback": bool(outline.get("fallback")),
        "template": template.get("name") if template else "",
        "theme_template": theme_template,
        "used_tags": used_tags,
        "warnings": warnings,
        "images_used": (stats.get("images_used") if isinstance(stats, dict) else []) or [],
        "generated_image": generated_image,
        "images_available": (stats.get("images_available") if isinstance(stats, dict) else 0) or 0,
        "template_hint": (template_path or "").strip() if not template else "",
        "sections": [str(s.get("title") or "") for s in (outline.get("slides") or [])][:8],
    })
    return info


def _safe_stem(name: str) -> str:
    raw = "".join(c for c in str(name or "汇报") if c.isalnum() or c in "._- （）()【】")[:60]
    return raw.strip(" .") or "汇报"


def condense_material(text: str, head: int = 18000, tail: int = 8000) -> str:
    """材料过长时保头保尾：论文的摘要/引言在开头，结论在结尾，中间略去。

    一份 50 页扫描件 OCR 后可达 5–6 万字，整段塞进大纲提示词既贵又容易超上下文。
    """
    raw = (text or "").strip()
    if len(raw) <= head + tail:
        return raw
    omitted = len(raw) - head - tail
    return (
        raw[:head]
        + f"\n\n……（中间省略 {omitted} 字，为保证 PPT 覆盖首尾重点）……\n\n"
        + raw[-tail:]
    )


def wants_ppt(message: str) -> bool:
    """判断这句话是不是在要 PPT。宁可少判，不要误触发。"""
    import re

    text = (message or "").strip()
    if not text or len(text) > 400:
        return False
    verb = r"(生成|做|写|出|整个|帮我做|帮我写|来一?份|做一个|做一个|弄一个|搞一个)"
    noun = r"(ppt|PPT|幻灯片|演示文稿|课件|汇报材料)"
    if re.search(verb + r".{0,8}" + noun, text):
        return True
    if re.search(noun + r".{0,8}" + verb, text):
        return True
    return False

