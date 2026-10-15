"""PPT 生成的服务入口：供 REST 接口与"对话框一句话生成"共用。

把它独立出来，是为了让两处走完全同一条路径（同一套大纲提示词、同一个生成器、
同一套落盘规则），避免两边行为不一致。
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import tempfile
import uuid
from typing import Optional

from services.ppt import ppt_template, ppt_theme
from services.workspace_manager import workspace_manager

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
GENERATED_DIR = BACKEND_DIR / "generated"

_FOLDER_PHRASE = re.compile(
    r"(?:生成在|生成到|放到|放进|存到|写到|在)\s*[「\"']?"
    r"([^「\"'@\s]{1,40}?)"
    r"[」\"']?\s*(?:这个|该)?文件夹"
)
_BRACKET_FOLDER = re.compile(r"\[文件夹:\s*([^\]]+)\]")


def pick_folder(text: str, directories: list[dict]) -> tuple[str, str]:
    """从这句话里找出要写入的文件夹。

    返回 (相对路径, 用户点的名字)。对上了路径非空。
    点了名字但左侧没有这个文件夹时，路径为空、名字留下，方便告诉用户。
    和全流程用的是同一条 @文件夹 规则。
    """
    from services.pipeline_steps import mentioned_folder

    dirs = [item for item in directories or [] if item.get("is_dir") and item.get("path")]
    hit = mentioned_folder(text or "", dirs)
    if hit:
        return hit, hit.split("/")[-1]
    for match in _BRACKET_FOLDER.finditer(text or ""):
        raw = match.group(1).strip().replace("\\", "/")
        for item in dirs:
            path = item.get("path") or ""
            if path == raw:
                return path, path.split("/")[-1]
        for item in dirs:
            path = item.get("path") or ""
            if path.split("/")[-1] == raw.split("/")[-1]:
                return path, path.split("/")[-1]
    phrase = _FOLDER_PHRASE.search(text or "")
    if not phrase:
        return "", ""
    asked = phrase.group(1).strip().strip("「」\"'")
    matches = [item.get("path") or "" for item in dirs if (item.get("path") or "").split("/")[-1] == asked]
    if len(matches) == 1:
        return matches[0], asked
    return "", asked


def compose_out_dir(plan_parent: pathlib.Path, save_to_local: bool,
                    local_root: Optional[pathlib.Path]) -> pathlib.Path:
    """成品跟计划放在同一个文件夹。计划已经在打开的文件夹里时，不再抬到根目录。"""
    parent = pathlib.Path(plan_parent)
    if not save_to_local or local_root is None:
        return parent
    root = pathlib.Path(local_root)
    if workspace_manager._is_inside(parent, root):
        return parent
    return root


# 这些开头是系统自己写进对话的状态句。拿去当 PPT 材料，模型会照着「已列出计划」写正文。
_STATUS_PREFIXES = ("已列出", "已按你的要求", "已出片", "已生成 PPT", "这次没能")
_FILE_TAG = re.compile(r"\[文件:\s*([^\]]+)")
_FOLDER_TEXT_EXTS = {".md", ".txt", ".docx", ".pdf"}
# 一个文件夹里最多打开这么多个文稿。再多就按修改时间只取最新的，避免一次 OCR 几十份 PDF。
_FOLDER_FILE_CAP = 8


def _message_meta(message: dict) -> dict:
    meta = (message or {}).get("metadata")
    if isinstance(meta, str) and meta.strip():
        try:
            meta = json.loads(meta)
        except Exception:
            return {}
    return meta if isinstance(meta, dict) else {}


def is_status_reply(message: dict) -> bool:
    """这条助手回复是 PPT 状态，不能当材料。"""
    if (message or {}).get("role") not in (None, "", "assistant"):
        return False
    meta = _message_meta(message)
    if meta.get("ppt_plan") or meta.get("ppt"):
        return True
    text = ((message or {}).get("content") or "").strip()
    return text.startswith(_STATUS_PREFIXES)


def recent_discussion(messages: list[dict], keep: int = 3) -> list[str]:
    """最近几条真正讨论过内容的助手回复，按时间从旧到新。"""
    picked = []
    for message in messages or []:
        if message.get("role") != "assistant":
            continue
        text = (message.get("content") or "").strip()
        if not text or is_status_reply(message):
            continue
        picked.append(text)
    return picked[-keep:]


def attached_names(message: str) -> list[str]:
    """消息里 `[文件: 名字]` 的文件名。读失败时括号里的说明不算进名字。"""
    names = []
    for match in _FILE_TAG.finditer(message or ""):
        raw = match.group(1).strip()
        name = raw.split("（", 1)[0].strip()
        if name and name not in names:
            names.append(name)
    return names


def source_label(file_names: list[str], used_discussion: bool) -> str:
    """计划卡片上「材料来自」后面的那半句。"""
    names = [name for name in file_names if name]
    if names:
        return "、".join(names)
    if used_discussion:
        return "最近的对话"
    return "只有题目"


def select_folder_files(folder: pathlib.Path, limit: int = _FOLDER_FILE_CAP) -> list[pathlib.Path]:
    """这个文件夹直属的文稿，新的在前。

    读 md / txt / docx / pdf。图片说明、计划 json、pptx 这类生成物跳过。
    `*.内容稿.md` 是给用户改的底稿，要读。
    """
    if not folder or not pathlib.Path(folder).is_dir():
        return []
    found = []
    try:
        entries = list(pathlib.Path(folder).iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_file() or entry.name.startswith("."):
            continue
        if entry.name.startswith("图片说明"):
            continue
        if entry.name.endswith(".ppt计划.json"):
            continue
        if entry.suffix.lower() not in _FOLDER_TEXT_EXTS:
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        found.append((mtime, entry))
    found.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in found[:limit]]


def pack_folder_texts(items: list[tuple[str, str]], limit: Optional[int] = None) -> tuple[str, list[str]]:
    """把 (文件名, 正文) 收成一段材料。正文合计不超过 limit 字，后面的文件截断后不再继续。"""
    if limit is None:
        from services.ppt.ppt_plan import DIGEST_LIMIT
        limit = DIGEST_LIMIT
    chunks = []
    names = []
    used = 0
    for name, text in items:
        body = (text or "").strip()
        if not body:
            continue
        room = limit - used
        if room <= 0:
            break
        if len(body) > room:
            body = body[:room]
        chunks.append(f"【{name}】\n{body}")
        names.append(name)
        used += len(body)
    return "\n\n".join(chunks), names


async def load_folder_material(
    user_id: str,
    session_id: str,
    folder: pathlib.Path,
    skip_names: Optional[set[str]] = None,
) -> tuple[str, list[str]]:
    """读文件夹里的文稿。路径必须落在用户打开的目录或他自己的工作区里。"""
    from services.ppt.ppt_plan import DIGEST_LIMIT
    from services.workspace_manager import user_dir

    skip = skip_names or set()
    files = [path for path in select_folder_files(folder) if path.name not in skip]
    root = await workspace_manager.get_local_root(user_id)
    site = user_dir(user_id)
    items: list[tuple[str, str]] = []
    for path in files:
        resolved = path.resolve()
        text = None
        if root and workspace_manager._is_inside(resolved, pathlib.Path(root)):
            rel = str(resolved.relative_to(pathlib.Path(root).resolve())).replace("\\", "/")
            text = await workspace_manager.get_content(session_id, rel, user_id, "local")
        elif workspace_manager._is_inside(resolved, site.resolve()):
            rel = str(resolved.relative_to(site.resolve())).replace("\\", "/")
            text = await workspace_manager.get_content(session_id, rel, user_id, "site")
        if (text or "").strip():
            items.append((path.name, text.strip()))
    return pack_folder_texts(items, DIGEST_LIMIT)


async def named_save_dir(user_id: str, text: str) -> tuple[Optional[pathlib.Path], str]:
    """用户点了左侧某个文件夹时，返回那个目录。没点到就 (None, 点的名字或空)。"""
    listed = await workspace_manager.list_active(user_id)
    directories = [item for item in (listed.get("data") or []) if item.get("is_dir")]
    rel, asked = pick_folder(text, directories)
    if not rel:
        return None, asked
    root = await workspace_manager.get_local_root(user_id)
    if root is None:
        from services.workspace_manager import user_dir
        root = user_dir(user_id)
    found = workspace_manager._resolve_inside(pathlib.Path(root), rel, must_exist=True)
    if found and found.is_dir():
        return found, asked or found.name
    return None, asked


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


def current_engine() -> str:
    """当前出片引擎：`canvas`（默认）或 `splice`（老路）。"""
    return (os.environ.get("ARS_PPT_ENGINE") or "canvas").strip().lower()


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
    engine: str = "",
) -> dict:
    """出片入口：按引擎分派。失败返回 {"error": ...}。

    - `canvas`（默认；环境变量 `ARS_PPT_ENGINE` 也认这个）→ 新路：先出逐页计划，
      再用版式库按底板档案画进模板；
    - `splice` → 老路：把文字填进模板原有的版式页。

    参数留空就看环境变量，所以原有的调用方一行都不用改。
    """
    chosen = engine.strip().lower() if engine else current_engine()
    options = dict(material=material, guidance=guidance, pages=pages, model_id=model_id,
                   title_hint=title_hint, template_path=template_path, template_id=template_id,
                   theme=theme, save_dir=save_dir, filename=filename, save_outline=save_outline,
                   images=images, auto_image=auto_image)
    if chosen == "splice":
        return await _build_splice(user_id, **options)
    return await _build_canvas(user_id, **options)


async def _build_splice(
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
    """老路：生成大纲 → 出 .pptx → 落盘（可选同时存 outline.json）。失败返回 {"error": ...}。

    出片有两条路：
    - 给了模板（`template_id` 或 `template_path`）→ **拼接**：克隆模板版式页、替换文字，保住模板观感；
    - 没给 → 用所选主题对应的内置模板当版式库（同样走拼接），再不行才退回老 builder。
    """
    from services.ppt import ppt_library, pptx_builder, pptx_outline, pptx_splice

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
        from services.ppt import ppt_image

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
        from services.ppt import ppt_genimage

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


async def _build_canvas(
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
    """新路：先出逐页计划，再用版式库按底板档案把内容画进模板。

    和 `_build_splice` 的区别：老路把文字填进模板原有的设计页，新路只借模板的
    底板（页眉、校徽、页码）和配色，内容由 `ppt_layouts` 按安全区画。
    """
    from services.ppt import ppt_base, ppt_check, ppt_compose, ppt_library, ppt_pages, ppt_plan

    material = (material or "").strip()
    if not material:
        return {"error": "没有可用的材料：请先选中一段回复，或 @ 上要参考的文件"}

    plan, used_model, err = await ppt_plan.make_plan(
        user_id, material, model_id=model_id, pages=pages, guidance=guidance or "")
    if err:
        return {"error": err}
    if not (plan or {}).get("slides"):
        return {"error": "模型没有给出可用的计划"}

    template = ppt_library.find(user_id, template_id) if template_id else None
    if template is None:
        template = ppt_library.builtin_for_theme(theme or "")
    if template is None or not template.get("file_path"):
        return {"error": "找不到可用的模板：请先在模板库里选一套"}

    base = await asyncio.to_thread(ppt_base.base_for, template)

    warnings: list[str] = []
    generated_image = ""
    if auto_image and not images:
        from services.ppt import ppt_genimage

        title_for_image = str(plan.get("title") or (plan.get("slides") or [{}])[0].get("title") or "")
        made, image_err = await ppt_genimage.generate_image(user_id, title_for_image or "汇报")
        if made:
            images = [str(made)]
            generated_image = made.name
        elif image_err:
            warnings.append(f"自动配图没成功：{image_err}")

    stem = _safe_stem(filename or plan.get("title") or title_hint or "汇报")
    tmp_deck = pathlib.Path(tempfile.gettempdir()) / f"ppt_canvas_{uuid.uuid4().hex[:8]}.pptx"
    try:
        page_doc = await asyncio.to_thread(
            lambda item: ppt_pages.load_pages(item) or ppt_pages.empty_pages(item, item), template)
        result = await asyncio.to_thread(
            ppt_compose.compose, base, plan, template["file_path"], tmp_deck, images, template, page_doc)
        issues = await asyncio.to_thread(ppt_check.check_deck, tmp_deck, base)
        data = await asyncio.to_thread(tmp_deck.read_bytes)
    except Exception as exc:
        return {"error": f"生成 PPT 失败：{exc}"}
    finally:
        tmp_deck.unlink(missing_ok=True)

    plan_path = ""
    if save_outline:
        try:
            saved_plan = await workspace_manager.save_generated_file(
                user_id, f"{stem}.ppt计划.json",
                json.dumps(plan, ensure_ascii=False, indent=2).encode("utf-8"),
                target_dir=save_dir,
            )
            plan_path = saved_plan.get("path") or ""
        except Exception:
            plan_path = ""

    try:
        info = await workspace_manager.save_generated_file(
            user_id, f"{stem}.pptx", data, target_dir=save_dir)
    except Exception as exc:
        return {"error": f"保存 PPT 失败：{exc}"}
    if plan_path and info.get("path"):
        from services.ppt import ppt_edit
        from services.workspace_manager import user_dir

        root = await workspace_manager.get_local_root(user_id) if info.get("source") == "local" else user_dir(user_id)
        try:
            ppt_edit.stamp_plan_mark(pathlib.Path(root) / info["path"], plan_path, info.get("source") or "site")
        except Exception:
            warnings.append("计划路径没能写进片子")

    info.update({
        "format": "pptx",
        "engine": "canvas",
        "pages": result.get("pages") or len(plan.get("slides") or []),
        "plan_path": plan_path,
        "model": used_model,
        "fallback": False,
        "template": template.get("name") or "",
        "used_tags": [str(s.get("layout") or "") for s in (plan.get("slides") or [])],
        "warnings": warnings + [str(w.get("detail") or "") for w in (result.get("warnings") or [])],
        "overflow": result.get("overflow") or [],
        "issues": issues,
        "repaired": result.get("repaired") or {},
        "template_pages": result.get("template_pages") or [],
        "images_used": [pathlib.Path(p).name for p in (images or [])],
        "generated_image": generated_image,
        "images_available": len(images or []),
        "sections": [str(s.get("title") or s.get("quote") or "")
                     for s in (plan.get("slides") or [])][:8],
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
    """判断这句话是不是在要 PPT。大小写、口语说法都认，问句不算。"""
    import re

    text = (message or "").strip()
    if not text or len(text) > 400:
        return False
    if re.search(r"为什么|为啥|怎么|如何", text):
        return False
    verb = r"(生成一下|生成|做个|做一个|做|写|出片|出|整个|帮我做|帮我写|来一?份|弄一个|搞一个|按这个出)"
    noun = r"(ppt|幻灯片|演示文稿|课件|汇报材料)"
    if re.search(verb + r".{0,12}" + noun, text, re.IGNORECASE):
        return True
    if re.search(noun + r".{0,12}" + verb, text, re.IGNORECASE):
        return True
    if re.search(r"出片", text):
        return True
    return False


def wants_rebuild_from_draft(message: str) -> bool:
    """「按内容稿重出计划」：用改过的内容稿再出一份计划。问句不算。"""
    text = (message or "").strip()
    if not text or len(text) > 400:
        return False
    if text.endswith("？") or text.endswith("?"):
        return False
    return "内容稿" in text and "重出" in text


def wants_plan_revise(message: str) -> bool:
    """已经有计划时，这句话是不是在改计划。问句不算。

    页码加「太挤、接不上」这类说法在 ppt_edit_intent.quick_classify 里。
    这里仍是它的一条规则：第 N 页加改、换、删，或整体压页数。
    """
    import re

    text = (message or "").strip()
    if not text or len(text) > 400:
        return False
    if re.search(r"^(为什么|为啥|怎么|如何)", text):
        return False
    if text.endswith("？") or text.endswith("?"):
        return False
    if re.search(r"第\s*\d+\s*页", text) and re.search(r"改|换|删|加|合并|拆|时间轴|变成|做成", text):
        return True
    return bool(re.search(r"整体压到|压到\s*\d+\s*页|加一页|删一页|合并", text))

