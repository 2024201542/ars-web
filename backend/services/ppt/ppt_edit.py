"""把一句修改意见拆成操作，并按页改计划。文字类只动点名的页。"""

from __future__ import annotations

import copy
import io
import json
import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_OPS = (
    "rewrite", "shorten", "expand", "add_bridge", "rewrite_notes", "fix_layout",
    "add_page", "delete_page", "move_page", "merge_pages", "split_page",
    "change_form", "swap_page", "resize_deck", "apply_all",
)
_TEXT_OPS = {"rewrite", "shorten", "expand", "add_bridge", "rewrite_notes", "apply_all", "fix_layout"}
_STRUCT_OPS = {
    "add_page", "delete_page", "move_page", "merge_pages", "split_page",
    "change_form", "swap_page", "resize_deck",
}

EDIT_PLAN_SYSTEM = """你在把用户对 PPT 的修改意见拆成操作。只输出 JSON，不要解释。
可用操作：{ops}
PPT 当前结构（页号、角色、模板页形态、标题、承接句）：
{outline}
规则：
1. 只拆用户说到的问题，不顺手改别的。
2. 用户说「太挤、字太多」用 shorten；「接不上、跳」用 add_bridge，接不上的原因是缺内容时用 add_page；
   「压住、重叠、跑出去」用 fix_layout；「加背景、先讲背景」用 add_page（role=background，after=目录页或封面）。
3. 用户没说页号但说了「这页」，用 {current_page}。
4. 页号按当前结构，不要按操作后的结构。
输出：{"ops": [{"op": "shorten", "page": 3}], "reply": "一句话说明打算怎么改"}"""


def _slides(plan: dict) -> list:
    return [slide for slide in (plan.get("slides") or []) if isinstance(slide, dict)]


def _tag(plan: dict) -> None:
    for index, slide in enumerate(_slides(plan), 1):
        slide["_edit_id"] = index


def _untag(plan: dict) -> None:
    for slide in _slides(plan):
        slide.pop("_edit_id", None)


def _find(plan: dict, page: int) -> dict | None:
    for slide in _slides(plan):
        if slide.get("_edit_id") == page:
            return slide
    slides = _slides(plan)
    if 1 <= page <= len(slides):
        return slides[page - 1]
    return None


def _index_of(plan: dict, page: int) -> int:
    slides = _slides(plan)
    for index, slide in enumerate(slides):
        if slide.get("_edit_id") == page:
            return index
    if 1 <= page <= len(slides):
        return page - 1
    return -1


def outline_for_edit(plan: dict) -> str:
    lines = []
    for index, slide in enumerate(_slides(plan), 1):
        lines.append(
            f"{index} {slide.get('role') or slide.get('layout') or ''} "
            f"{slide.get('template_form') or ''} {slide.get('title') or ''} "
            f"{slide.get('lead') or ''}"
        )
    return "\n".join(lines)[:3000]


def _page_numbers(text: str) -> list[int]:
    from services.ppt.ppt_edit_intent import page_numbers
    return page_numbers(text)


def fallback_ops(instruction: str, current_page: int | None = None) -> dict:
    """模型没给出可用 JSON 时，按问题词选一个操作。"""
    text = (instruction or "").strip()
    pages = _page_numbers(text)
    page = pages[-1] if pages else (int(current_page) if current_page else 0)
    if any(word in text for word in ("挤", "太多", "太长")):
        targets = pages or ([page] if page else [])
        ops = [{"op": "shorten", "page": item} for item in targets]
        reply = "缩短点到的页"
    elif ("所有" in text or "每页" in text or "每一页" in text) and any(
            word in text for word in ("讲稿", "过渡", "备注")):
        ops = [{"op": "rewrite_notes", "page": 0, "instruction": text}]
        reply = "给每一页讲稿加上过渡"
    elif any(word in text for word in ("接不上", "衔接", "突兀")) or ("跳" in text and "页" in text):
        ops = [{"op": "add_bridge", "page": page}] if page else []
        reply = "补上这一页的承接"
    elif any(word in text for word in ("压住", "重叠", "跑出去", "出界", "挡住")):
        ops = [{"op": "fix_layout", "page": page}] if page else []
        reply = "先整理这一页的版面"
    elif "背景" in text and any(word in text for word in ("加", "前面", "先讲")):
        ops = [{"op": "add_page", "after": 2, "role": "background", "instruction": text}]
        reply = "在前面加一页背景"
    else:
        ops = [{"op": "rewrite", "page": page, "instruction": text}] if page else []
        reply = "按这句话改点到的页"
    return {"ops": ops, "reply": reply}


async def plan_ops(instruction: str, plan: dict, current_page: int | None = None,
                   model: str = "", user_id: str = "") -> dict:
    """让模型把一句话拆成操作。JSON 不可用时走规则。"""
    from services.ppt.ppt_plan import _ask_text
    from services.ppt.pptx_outline import _extract_json

    system = (EDIT_PLAN_SYSTEM
              .replace("{ops}", "、".join(_OPS))
              .replace("{outline}", outline_for_edit(plan))
              .replace("{current_page}", str(current_page or "")))
    text, _name, err = await _ask_text(user_id, system, instruction or "", model or "", max_tokens=800)
    data = _extract_json(text) if text and not err else None
    if not isinstance(data, dict) or not isinstance(data.get("ops"), list) or not data.get("ops"):
        return fallback_ops(instruction, current_page)
    ops = []
    for item in data["ops"]:
        if isinstance(item, dict) and item.get("op") in _OPS:
            ops.append(item)
    if not ops:
        return fallback_ops(instruction, current_page)
    reply = str(data.get("reply") or "").strip() or "按这句话改"
    return {"ops": ops, "reply": reply}


def _cut(text: str, ratio: float = 0.6) -> str:
    raw = str(text or "")
    if len(raw) <= 4:
        return raw
    keep = max(1, int(len(raw) * ratio))
    return raw[:keep]


def _locked(slide: dict) -> set[str]:
    return {str(item) for item in (slide.get("locked_slots") or []) if item}


def _explicit_slots(op: dict) -> dict[str, str]:
    """用户点名改某个格子时才返回新文字。没点名的锁定格子不能从这里解开。"""
    instruction = str(op.get("instruction") or "")
    found: dict[str, str] = {}
    for label, slot in (("标题", "title"), ("承接", "lead"), ("正文", "body")):
        match = re.search(rf"{label}(?:改成|改为|换成|变成)\s*[「\"']?(.+?)[」\"']?\s*$", instruction)
        if match:
            found[slot] = match.group(1).strip()
    text = str(op.get("text") or "").strip()
    named = op.get("slots") if isinstance(op.get("slots"), list) else []
    if text:
        for name in named:
            found.setdefault(str(name), text)
    return found


def _write_named_slots(slide: dict, values: dict[str, str]) -> None:
    slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else {}
    for name, value in values.items():
        slots[name] = value
        if name == "title":
            slide["title"] = value
        elif name == "lead":
            slide["lead"] = value
    if slots:
        slide["slots"] = slots
    locked = [item for item in (slide.get("locked_slots") or []) if item not in values]
    slide["locked_slots"] = locked


def _shorten_slide(slide: dict, names: list | None = None) -> None:
    locked = _locked(slide)
    slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else None
    if slots:
        chosen = list(names or [name for name in slots if name != "title"])
        for name in chosen:
            if name in slots and name not in locked:
                slots[name] = _cut(slots[name])
        slide["slots"] = slots
        return
    points = slide.get("points")
    if isinstance(points, list) and points:
        slide["points"] = [_cut(item) if isinstance(item, str) else item for item in points]
        return
    if slide.get("notes"):
        slide["notes"] = _cut(str(slide.get("notes")))


def _expand_slide(slide: dict) -> None:
    slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else None
    extra = "例如：再补一个具体例子。"
    if slots:
        locked = _locked(slide)
        name = next((key for key in slots if key not in {"title", "lead"} and key not in locked), "")
        if name:
            slots[name] = str(slots.get(name) or "") + extra
            slide["slots"] = slots
            return
    notes = str(slide.get("notes") or "")
    slide["notes"] = notes + extra


def _rewrite_slide_text(slide: dict, instruction: str) -> None:
    note = (instruction or "").strip()
    if slide.get("notes") is not None:
        slide["notes"] = (str(slide.get("notes") or "") + " " + note).strip()
    slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else None
    if slots and "body" in slots and "body" not in _locked(slide):
        slots["body"] = _cut(str(slots.get("body") or "") + note, 1)


def _split_first(notes: str) -> tuple[str, str]:
    raw = notes or ""
    for sep in ("。", "！", "？", "\n"):
        if sep in raw:
            index = raw.index(sep)
            return raw[:index + 1], raw[index + 1:]
    return raw, ""


def _add_bridge(slide: dict) -> None:
    if "lead" not in _locked(slide):
        lead = str(slide.get("lead") or "")
        slide["lead"] = lead if lead.startswith("接着") else ("接着上一页，" + lead).strip("，")
        slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else None
        if slots and "lead" in slots:
            slots["lead"] = slide["lead"]
            slide["slots"] = slots
    first, rest = _split_first(str(slide.get("notes") or ""))
    if not first.startswith("接着上一页"):
        slide["notes"] = "接着上一页。" + rest


def _rewrite_notes(slide: dict, instruction: str) -> None:
    slide["notes"] = (instruction or "把这一页讲清楚。").strip()


def _sync_toc(plan: dict) -> None:
    slides = _slides(plan)
    toc = next((slide for slide in slides if slide.get("layout") == "toc"), None)
    if not toc:
        return
    labels = []
    for slide in slides:
        if slide is toc:
            continue
        if slide.get("layout") == "section" or slide.get("role") in {"background", "section"}:
            section_slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else {}
            labels.append(str(section_slots.get("section_title") or slide.get("title") or slide.get("role") or "内容"))
    if labels:
        toc["items"] = [{"label": name} for name in labels]
        slots = toc.get("slots") if isinstance(toc.get("slots"), dict) else None
        if slots:
            limits = toc.get("slot_limits") if isinstance(toc.get("slot_limits"), dict) else {}
            warnings = list(toc.get("slot_warnings") or [])
            from services.ppt import ppt_layouts

            for index, name in enumerate(labels, 1):
                key = f"item{index}.head"
                if key not in slots and key not in limits:
                    continue
                text = name
                limit = int(limits.get(key) or 0)
                if limit > 0 and ppt_layouts.text_len(text) > limit:
                    note = f"{key} 超过 {limit} 字，已截断"
                    if note not in warnings:
                        warnings.append(note)
                    text = ppt_layouts.truncate(text, limit, ellipsis="")
                slots[key] = text
                toc["items"][index - 1]["label"] = text
            toc["slots"] = slots
            if warnings:
                toc["slot_warnings"] = warnings


def _blank_page(role: str, instruction: str) -> tuple[dict, dict]:
    title = "背景介绍" if role == "background" else (instruction or "补充")[:20]
    slide = {
        "layout": "bullets",
        "role": role or "finding",
        "title": title,
        "lead": "",
        "notes": "",
        "points": [],
        "slots": {"title": title, "body": ""},
        "_edit_id": 0,
    }
    slot = {"kind": "content", "role": role or "finding", "message": title}
    return slide, slot


def _assign_template(slide: dict, slot: dict, catalog: dict | None) -> None:
    if not catalog:
        return
    from services.ppt import ppt_pagepick

    try:
        picks = ppt_pagepick.pick_pages([slot], catalog, None)
    except Exception:
        picks = []
    page_no = (picks[0] or {}).get("page") if picks else None
    if not page_no:
        for card in catalog.get("pages") or []:
            if isinstance(card, dict) and card.get("page"):
                page_no = card["page"]
                break
    if page_no:
        slide["template_page"] = int(page_no)


def _insert_page(plan: dict, after: int, role: str, instruction: str, catalog: dict | None) -> int:
    slides = _slides(plan)
    slide, slot = _blank_page(role, instruction)
    _assign_template(slide, slot, catalog)
    index = min(max(after, 0), len(slides))
    slides.insert(index, slide)
    plan["slides"] = slides
    story = plan.get("storyline")
    if isinstance(story, dict) and isinstance(story.get("slots"), list):
        slots = story["slots"]
        if len(slots) + 1 == len(slides):
            slots.insert(index, slot)
            for number, item in enumerate(slots, 1):
                if isinstance(item, dict):
                    item["no"] = number
    _sync_toc(plan)
    return index + 1


def _delete_page(plan: dict, page: int) -> str:
    slides = _slides(plan)
    index = _index_of(plan, page)
    if index < 0:
        return ""
    slides.pop(index)
    plan["slides"] = slides
    story = plan.get("storyline")
    if isinstance(story, dict) and isinstance(story.get("slots"), list):
        slots = story["slots"]
        if index < len(slots):
            slots.pop(index)
    note = ""
    content_run = 0
    for slide in slides:
        if slide.get("layout") == "section":
            if 0 < content_run < 2:
                note = "有一章不足 2 页，已并进相邻章"
            content_run = 0
        elif slide.get("layout") not in {"cover", "toc", "end"}:
            content_run += 1
    _sync_toc(plan)
    return note


def _move_page(plan: dict, page: int, to: int) -> None:
    slides = _slides(plan)
    index = _index_of(plan, page)
    if index < 0:
        return
    slide = slides.pop(index)
    dest = min(max(to - 1, 0), len(slides))
    slides.insert(dest, slide)
    plan["slides"] = slides
    _add_bridge(slide)


def _append_note(slide: dict, sentence: str) -> None:
    extra = (sentence or "").strip() or "接着上一页。"
    notes = str(slide.get("notes") or "").strip()
    if extra in notes:
        return
    slide["notes"] = f"{notes}{extra}" if not notes or notes.endswith(("。", "！", "？")) else f"{notes}。{extra}"


def _apply_text(slide: dict, op: dict) -> str:
    explicit = _explicit_slots(op)
    if explicit:
        _write_named_slots(slide, explicit)
        return "改了点名的格子"
    name = str(op.get("op") or "")
    if name == "shorten":
        _shorten_slide(slide, op.get("slots") if isinstance(op.get("slots"), list) else None)
        return "缩短了这一页的文字"
    if name == "expand":
        _expand_slide(slide)
        return "补了一个具体例子"
    if name == "add_bridge":
        _add_bridge(slide)
        return "补了承接句和讲稿第一句"
    if name == "rewrite_notes":
        _rewrite_notes(slide, str(op.get("instruction") or ""))
        return "改了讲稿"
    if name == "rewrite":
        _rewrite_slide_text(slide, str(op.get("instruction") or ""))
        return "改了这一页的文字"
    return ""


def _layout_still_bad(pptx_path, page: int) -> bool:
    if not pptx_path:
        return True
    from pathlib import Path
    path = Path(pptx_path)
    if not path.is_file():
        return True
    from services.ppt import ppt_check
    ppt_check.repair_deck(path)
    issues = ppt_check.check_deck(path)
    return any(item.get("page") == page and item.get("kind") in {"offslide", "overlap"} for item in issues)


async def apply_ops(plan: dict, ops: list, *, catalog: dict | None = None,
                    pptx_path=None) -> tuple[dict, list[dict]]:
    """先按页号从大到小做结构操作，再按原来的页号做文字操作。"""
    out = copy.deepcopy(plan or {})
    out["slides"] = _slides(out)
    _tag(out)
    changes: list[dict] = []
    structural = [op for op in ops if isinstance(op, dict) and op.get("op") in _STRUCT_OPS]
    textual = [op for op in ops if isinstance(op, dict) and op.get("op") in _TEXT_OPS]
    structural.sort(key=lambda op: int(op.get("page") or op.get("after") or 0), reverse=True)
    for op in structural:
        name = op.get("op")
        if name == "add_page":
            after = int(op.get("after") or 1)
            page_no = _insert_page(out, after, str(op.get("role") or "finding"),
                                   str(op.get("instruction") or ""), catalog)
            changes.append({"page": page_no, "what": f"新增第 {page_no} 页"})
        elif name == "delete_page":
            page = int(op.get("page") or 0)
            note = _delete_page(out, page)
            what = f"删了第 {page} 页"
            if note:
                what += "。" + note
            changes.append({"page": page, "what": what})
        elif name == "move_page":
            page = int(op.get("page") or 0)
            _move_page(out, page, int(op.get("to") or page))
            changes.append({"page": page, "what": f"把第 {page} 页移到第 {op.get('to')} 页"})
        elif name == "merge_pages":
            pages = [int(item) for item in (op.get("pages") or []) if str(item).isdigit() or isinstance(item, int)]
            if len(pages) >= 2:
                _delete_page(out, max(pages))
                changes.append({"page": min(pages), "what": "合并了点到的页"})
        elif name == "split_page":
            page = int(op.get("page") or 0)
            page_no = _insert_page(out, _index_of(out, page) + 1, "finding", "拆出来的后半", catalog)
            changes.append({"page": page_no, "what": f"把第 {page} 页拆成两页"})
        elif name == "change_form":
            slide = _find(out, int(op.get("page") or 0))
            if slide is not None:
                slide["template_form"] = str(op.get("form") or "")
                slide.pop("template_page", None)
                _assign_template(slide, {"kind": "content", "form_hint": slide["template_form"]}, catalog)
                changes.append({"page": int(op.get("page") or 0), "what": "换了这一页的形态并重新选页"})
        elif name == "swap_page":
            slide = _find(out, int(op.get("page") or 0))
            if slide is not None:
                chosen = op.get("template_page")
                if not chosen and catalog:
                    _assign_template(slide, {"kind": "content"}, catalog)
                elif chosen:
                    slide["template_page"] = int(chosen)
                changes.append({"page": int(op.get("page") or 0), "what": "换了模板页"})
        elif name == "resize_deck":
            from services.ppt import ppt_story
            story = out.get("storyline") if isinstance(out.get("storyline"), dict) else {"slots": []}
            out["storyline"] = ppt_story.normalize_storyline(story, int(op.get("pages") or len(_slides(out))))
            changes.append({"page": 0, "what": f"页数改到 {op.get('pages')}"})
    for op in textual:
        name = op.get("op")
        if name == "apply_all":
            content = [slide for slide in _slides(out) if slide.get("layout") not in {"cover", "toc", "section", "end"}]
            for offset in range(0, len(content), 4):
                for slide in content[offset:offset + 4]:
                    _shorten_slide(slide)
            changes.append({"page": 0, "what": "所有内容页按同一句改了"})
            continue
        if name == "rewrite_notes" and int(op.get("page") or 0) == 0:
            for slide in _slides(out):
                if slide.get("layout") in {"cover", "toc", "end"}:
                    continue
                _append_note(slide, "接着上一页。")
            changes.append({"page": 0, "what": "所有页讲稿加上了过渡句"})
            continue
        page = int(op.get("page") or 0)
        slide = _find(out, page)
        if slide is None:
            continue
        if name == "fix_layout":
            changes.append({"page": page, "what": "先整理这一页的出界和叠字"})
            if _layout_still_bad(pptx_path, page):
                _shorten_slide(slide)
                changes.append({"page": page, "what": "缩短了这一页的文字"})
            continue
        what = _apply_text(slide, op)
        if what:
            changes.append({"page": page, "what": what})
    _untag(out)
    return out, changes


def _slide_body(slide: dict | None) -> str:
    if not isinstance(slide, dict):
        return ""
    data = {key: value for key, value in slide.items() if key != "_edit_id"}
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def changed_pages_of(before: dict, after: dict, changes: list[dict]) -> list[int]:
    pages = []
    for item in changes:
        try:
            page = int(item.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
        if page and page not in pages:
            pages.append(page)
    old = [_slide_body(slide) for slide in _slides(before)]
    new = _slides(after)
    for index, slide in enumerate(new):
        body = _slide_body(slide)
        same = old[index] if index < len(old) else None
        if body == same or body in old:
            continue
        if (index + 1) not in pages:
            pages.append(index + 1)
    return pages


def nearby_issues(plan: dict, pages: list[int]) -> list[dict]:
    from services.ppt import ppt_story_check
    wanted = set()
    for page in pages:
        wanted.update({page - 1, page, page + 1})
    return [item for item in ppt_story_check.check_story(plan) if item.get("page") in wanted]


def result_reply(plan: dict, reply: str, changes: list[dict]) -> str:
    text = (reply or "").strip() or "已按这句话改了计划"
    bits = [str(item.get("what") or "") for item in changes if item.get("what")]
    if bits:
        text = text.rstrip("。") + "。" + "；".join(bits)
    output = plan.get("output") if isinstance(plan.get("output"), dict) else {}
    if not output.get("path"):
        text = text.rstrip("。") + "。还没出过片，改好的计划点生成 PPT 才会变成文件。"
    return text


_CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
_VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CUSTOM_TYPE = "application/vnd.openxmlformats-officedocument.custom-properties+xml"
_CUSTOM_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
_SLOT_NAME = re.compile(r"^ars:s(\d+):(.+)$")


def _zip_replace(path: Path, files: dict[str, bytes]) -> None:
    blob = path.read_bytes()
    source = zipfile.ZipFile(io.BytesIO(blob))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dest:
        seen = set()
        for info in source.infolist():
            payload = files.get(info.filename, source.read(info.filename))
            cloned = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
            cloned.compress_type = info.compress_type
            cloned.external_attr = info.external_attr
            dest.writestr(cloned, payload)
            seen.add(info.filename)
        for name, payload in files.items():
            if name not in seen:
                dest.writestr(name, payload)
    source.close()
    path.write_bytes(out.getvalue())


def _custom_xml(value: str, existing: bytes | None = None) -> bytes:
    ET.register_namespace("", _CUSTOM_NS)
    ET.register_namespace("vt", _VT_NS)
    if existing:
        root = ET.fromstring(existing)
    else:
        root = ET.Element(f"{{{_CUSTOM_NS}}}Properties")
    prop = None
    for item in root:
        if item.attrib.get("name") == "ars_plan":
            prop = item
            break
    if prop is None:
        pids = [int(item.attrib.get("pid") or 1) for item in root]
        prop = ET.SubElement(root, f"{{{_CUSTOM_NS}}}property")
        prop.set("fmtid", "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}")
        prop.set("pid", str(max(pids or [1]) + 1))
        prop.set("name", "ars_plan")
    node = prop.find(f"{{{_VT_NS}}}lpwstr")
    if node is None:
        node = ET.SubElement(prop, f"{{{_VT_NS}}}lpwstr")
    node.text = value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _ensure_override(content_types: bytes) -> bytes:
    ET.register_namespace("", _CT_NS)
    root = ET.fromstring(content_types)
    for item in root:
        if item.attrib.get("PartName") == "/docProps/custom.xml":
            return content_types
    node = ET.SubElement(root, f"{{{_CT_NS}}}Override")
    node.set("PartName", "/docProps/custom.xml")
    node.set("ContentType", _CUSTOM_TYPE)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _ensure_custom_rel(rels: bytes) -> bytes:
    ET.register_namespace("", _REL_NS)
    root = ET.fromstring(rels)
    for item in root:
        if item.attrib.get("Type") == _CUSTOM_REL:
            return rels
    ids = {item.attrib.get("Id") or "" for item in root}
    number = 1
    while f"rId{number}" in ids:
        number += 1
    node = ET.SubElement(root, f"{{{_REL_NS}}}Relationship")
    node.set("Id", f"rId{number}")
    node.set("Type", _CUSTOM_REL)
    node.set("Target", "docProps/custom.xml")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def stamp_plan_mark(pptx_path, rel: str, source: str) -> None:
    """在自定义属性 ars_plan 里记下计划的相对路径和来源。"""
    path = Path(pptx_path)
    if not path.is_file() or not rel:
        return
    value = json.dumps({"path": rel, "source": source or ""}, ensure_ascii=False)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        existing = zf.read("docProps/custom.xml") if "docProps/custom.xml" in names else None
        content_types = zf.read("[Content_Types].xml")
        rels = zf.read("_rels/.rels")
    _zip_replace(path, {
        "docProps/custom.xml": _custom_xml(value, existing),
        "[Content_Types].xml": _ensure_override(content_types),
        "_rels/.rels": _ensure_custom_rel(rels),
    })


def read_plan_mark(pptx_path) -> dict:
    path = Path(pptx_path)
    if not path.is_file():
        return {}
    try:
        with zipfile.ZipFile(path) as zf:
            if "docProps/custom.xml" not in zf.namelist():
                return {}
            root = ET.fromstring(zf.read("docProps/custom.xml"))
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return {}
    for item in root:
        if item.attrib.get("name") != "ars_plan":
            continue
        node = item.find(f"{{{_VT_NS}}}lpwstr")
        raw = (node.text or "") if node is not None else ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict) and data.get("path"):
            return {"path": str(data.get("path") or ""), "source": str(data.get("source") or "")}
    return {}


def find_plan_for_deck(pptx_path) -> dict:
    """先读 ars_plan。没有时，找同目录同名的「.ppt计划.json」。"""
    mark = read_plan_mark(pptx_path)
    if mark.get("path"):
        return {"path": mark["path"], "source": mark.get("source") or "", "absolute": ""}
    path = Path(pptx_path)
    sibling = path.with_name(path.stem + ".ppt计划.json")
    if sibling.is_file():
        return {"path": sibling.name, "source": "", "absolute": str(sibling)}
    return {"path": "", "source": "", "absolute": ""}


def manual_loss_note(plan: dict) -> str:
    pages = [str(index) for index, slide in enumerate(_slides(plan), 1) if slide.get("manual_notes")]
    if not pages:
        return ""
    return "第 " + "、".join(pages) + " 页有手改内容，重新出片会丢失"


def slide_snapshot(pptx_path) -> dict[int, list[str]]:
    """每一页里，没有格子名的文本框文字。用来判断手改动的是不是模板原框。"""
    from pptx import Presentation

    from services.ppt.ppt_compose import _iter_shapes

    path = Path(pptx_path)
    if not path.is_file():
        return {}
    prs = Presentation(str(path))
    found: dict[int, list[str]] = {}
    for index, slide in enumerate(prs.slides, 1):
        texts = []
        for shape in _iter_shapes(slide):
            name = str(getattr(shape, "name", "") or "")
            if _SLOT_NAME.match(name) or not getattr(shape, "has_text_frame", False):
                continue
            value = shape.text_frame.text.strip()
            if value:
                texts.append(value)
        found[index] = texts
    return found


def sync_manual_edits(pptx_path, plan: dict, before: dict | None = None) -> bool:
    """命名框里的字和计划不同时写回计划并锁定。没有命名框、而且这次文字变了的页记入手改说明。"""
    from pptx import Presentation

    from services.ppt.ppt_compose import _iter_shapes

    path = Path(pptx_path)
    if not path.is_file():
        return False
    prs = Presentation(str(path))
    slides = _slides(plan)
    changed = False
    for index, slide in enumerate(prs.slides, 1):
        plan_slide = slides[index - 1] if index <= len(slides) else None
        if plan_slide is None:
            continue
        named = False
        for shape in _iter_shapes(slide):
            match = _SLOT_NAME.match(str(getattr(shape, "name", "") or ""))
            if match is None or not getattr(shape, "has_text_frame", False):
                continue
            if int(match.group(1)) != index:
                continue
            named = True
            slot = match.group(2)
            text = shape.text_frame.text.strip()
            slots = plan_slide.get("slots") if isinstance(plan_slide.get("slots"), dict) else {}
            current = str(slots.get(slot) or "")
            if slot == "title" and not current:
                current = str(plan_slide.get("title") or "")
            if text == current.strip():
                continue
            slots = dict(slots)
            slots[slot] = text
            plan_slide["slots"] = slots
            if slot in {"title", "section_title"}:
                plan_slide["title"] = text
            locked = [str(item) for item in (plan_slide.get("locked_slots") or []) if item]
            if slot not in locked:
                locked.append(slot)
            plan_slide["locked_slots"] = locked
            changed = True
        if named or before is None:
            continue
        plain = []
        for shape in _iter_shapes(slide):
            if _SLOT_NAME.match(str(getattr(shape, "name", "") or "")):
                continue
            if not getattr(shape, "has_text_frame", False):
                continue
            value = shape.text_frame.text.strip()
            if value:
                plain.append(value)
        previous = before.get(index) or []
        if sorted(plain) == sorted(previous) or plan_slide.get("manual_notes"):
            continue
        plan_slide["manual_notes"] = "这一页的手改不在命名格子里，重新出片会丢失"
        changed = True
    return changed


def _save_keeping_mark(prs, path: Path) -> None:
    mark = read_plan_mark(path)
    prs.save(str(path))
    if mark.get("path"):
        stamp_plan_mark(path, mark["path"], mark.get("source") or "")


def write_slot_texts(pptx_path, page: int, slots: dict, notes: str | None = None) -> int:
    """按形状名 ars:s{页}:{格子} 把字写回这一页，其它页不改。"""
    from pathlib import Path
    from pptx import Presentation

    from services.ppt.ppt_compose import _iter_shapes
    from services.ppt.pptx_splice import _fill_frame, sync_app_props

    path = Path(pptx_path)
    prs = Presentation(str(path))
    slides = list(prs.slides)
    if page < 1 or page > len(slides):
        return 0
    slide = slides[page - 1]
    prefix = f"ars:s{page}:"
    values = slots if isinstance(slots, dict) else {}
    written = 0
    for shape in _iter_shapes(slide):
        name = str(getattr(shape, "name", "") or "")
        if not name.startswith(prefix):
            continue
        slot = name[len(prefix):]
        if slot not in values or not getattr(shape, "has_text_frame", False):
            continue
        text = str(values.get(slot) or "")
        title_like = slot in {"title", "section_title"} or slot.endswith(".head")
        _fill_frame(shape.text_frame, [(0, text)], keep_bold=True if title_like else False, add_prefix=False)
        from services.ppt.ppt_compose import _apply_point_size, _slot_point_size
        pt = _slot_point_size(shape, text, {})
        _apply_point_size(shape, pt or 10)
        written += 1
    if notes is not None:
        from services.ppt import ppt_base
        ppt_base._notes(slide, notes)
    if written or notes is not None:
        _save_keeping_mark(prs, path)
        try:
            sync_app_props(path)
        except Exception:
            logger.warning("改完这一页后没能刷新文档属性")
    return written


def recompose_deck(user_id: str, plan: dict, pptx_path, plan_mark: tuple[str, str] | None = None) -> str:
    """结构变了就按计划重出到原来的文件。失败时把原因交回调用方。"""
    from services.ppt import ppt_base, ppt_compose, ppt_library, ppt_pages

    template_id = str((plan or {}).get("template_id") or "")
    template = ppt_library.find(user_id, template_id) if template_id else None
    if template is None or not template.get("file_path"):
        return "找不到模板，结构改动还在计划里，点生成 PPT 才会重出"
    page_doc = ppt_pages.load_pages(template) or ppt_pages.empty_pages(template, template)
    base = ppt_base.base_for(template, page_doc)
    ppt_compose.compose(
        base, plan, template["file_path"], pptx_path, None, template, page_doc, plan_mark=plan_mark)
    return manual_loss_note(plan)


def _apply_to_pptx(user_id: str, before: dict, after: dict, pages: list[int],
                   structural: bool, pptx_path, plan_mark: tuple[str, str] | None = None) -> str:
    """文字类就地改点到的页。结构类重出整份。没有命名框时也按计划重出整份。"""
    if pptx_path is None:
        return ""
    if structural:
        try:
            return recompose_deck(user_id, after, pptx_path, plan_mark)
        except Exception:
            logger.warning("结构改动没能重出片子", exc_info=True)
            return "结构改动还在计划里，点生成 PPT 才会重出"
    old_slides = _slides(before)
    new_slides = _slides(after)
    written = 0
    touched_notes = False
    for page in pages:
        new = new_slides[page - 1] if 0 < page <= len(new_slides) else None
        old = old_slides[page - 1] if 0 < page <= len(old_slides) else None
        if new is None:
            continue
        notes = None
        if old is None or str(new.get("notes") or "") != str(old.get("notes") or ""):
            notes = str(new.get("notes") or "")
            touched_notes = True
        slots = dict(new.get("slots") or {}) if isinstance(new.get("slots"), dict) else {}
        if new.get("lead") and "lead" not in slots:
            slots["lead"] = new.get("lead")
        written += write_slot_texts(pptx_path, page, slots, notes=notes)
    if written == 0 and not touched_notes:
        try:
            note = recompose_deck(user_id, after, pptx_path, plan_mark)
        except Exception:
            logger.warning("没有命名框，按计划重出也失败了", exc_info=True)
            return "这份片子没有按格子命名的框，点生成 PPT 才会重出"
        if note:
            return note
        return "这份片子没有按格子命名的框，已按计划重出整份"
    return ""


def remember_output(plan: dict, path: str, source: str, rev: int) -> dict:
    """出片之后把产物记在计划上，调用方负责写回文件。"""
    plan["output"] = {
        "path": path,
        "source": source,
        "rev": int(rev or 0),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    return plan


async def run_instruction(user_id: str, plan_path: str, source: str, instruction: str,
                          current_page: int | None = None, model: str = "") -> AsyncIterator[dict]:
    """读计划、拆操作、改计划，并按流式事件返回。"""
    from routers.template_library import _resolve_user_file

    try:
        path, rel, src = await _resolve_user_file(user_id, plan_path, source, (".json",))
        plan = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        yield {"event": "message", "data": {"delta": f"这次没能读到计划：{detail}"}}
        yield {"event": "done", "data": {"message": "完成"}}
        return
    yield {"event": "phase_start", "data": {"phase": "tool", "description": "正在按你的要求改这一页"}}
    planned = await plan_ops(instruction, plan, current_page, model, user_id)
    catalog = None
    template_id = str(plan.get("template_id") or "")
    if template_id:
        try:
            from services.ppt import ppt_pagepick
            catalog, _base = ppt_pagepick.load_catalog(user_id, template_id)
        except Exception:
            catalog = None
    pptx_path = None
    output = plan.get("output") if isinstance(plan.get("output"), dict) else {}
    if output.get("path"):
        try:
            pptx_path, _rel, _src = await _resolve_user_file(
                user_id, output.get("path") or "", output.get("source") or src, (".pptx",))
        except Exception:
            pptx_path = None
    from services.ppt import ppt_history

    deck_rel = str(output.get("path") or "")
    deck_source = str(output.get("source") or src)
    version = 0
    try:
        version = ppt_history.snapshot(
            user_id, pptx_path, path,
            {"instruction": instruction, "ops": planned.get("ops") or [], "changed_pages": []},
            source=deck_source if deck_rel else src,
            rel=deck_rel or rel,
            plan_source=src, plan_rel=rel)
    except Exception:
        logger.warning("改之前没能存下这一版", exc_info=True)
    updated, changes = await apply_ops(plan, planned.get("ops") or [], catalog=catalog, pptx_path=pptx_path)
    pages = changed_pages_of(plan, updated, changes)
    if version:
        try:
            ppt_history.annotate(user_id, deck_source if deck_rel else src, deck_rel or rel, version, pages)
        except Exception:
            logger.warning("版本记录里没写上改了哪些页", exc_info=True)
        updated["edit_version"] = version
    updated["story_issues"] = nearby_issues(updated, pages)
    if isinstance(plan.get("output"), dict):
        updated["output"] = plan["output"]
    path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    reply = result_reply(updated, str(planned.get("reply") or ""), changes)
    structural = any(isinstance(op, dict) and op.get("op") in _STRUCT_OPS for op in (planned.get("ops") or []))
    file_note = _apply_to_pptx(user_id, plan, updated, pages, structural, pptx_path, (rel, src))
    if file_note:
        reply = reply.rstrip("。") + "。" + file_note
    rev = int(output.get("rev") or 0)
    if pptx_path is not None and Path(pptx_path).is_file():
        rev = Path(pptx_path).stat().st_mtime_ns
    payload = {
        "plan_path": rel,
        "path": (output.get("path") or ""),
        "source": src,
        "deck_source": deck_source if deck_rel else "",
        "rev": rev,
        "version": int(updated.get("edit_version") or 0),
        "ops": planned.get("ops") or [],
        "changes": changes,
        "changed_pages": pages,
        "issues": updated.get("story_issues") or [],
        "reply": reply,
    }
    yield {"event": "message", "data": {"delta": reply}}
    yield {"event": "ppt_edit", "data": payload}
    yield {"event": "done", "data": {"message": "完成"}}
