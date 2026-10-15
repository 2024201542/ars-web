"""模板页说明：每一页适合讲什么、有哪些格子、每格能写几个字。

文件跟模板放在一起：`<模板.pptx 同名>.pages.json`。
内置模板的这份文件随代码提供，不能改。用户模板由「解析模板」生成，也可以导入。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Optional

from services.ppt import ppt_roles

_USER_FIELDS = ("role", "form", "narrative_fit", "description", "usable")
_TOC_INDEX = re.compile(r"^-\d{2}-$")


def pages_path(template: dict) -> pathlib.Path:
    file_path = str((template or {}).get("file_path") or "")
    if not file_path:
        raise ValueError("模板没有文件路径")
    return pathlib.Path(file_path).with_suffix(".pages.json")


def template_sha1(path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def slot_capacity(frame: Optional[dict], font_pt: Optional[int] = None) -> tuple[int, int]:
    """按框的宽高和字号估算能写多少字。返回 (字数, 行数)。

    行数 = floor(框高 × 72 / (字号 × 1.35))，至少 1。
    每行字数 = floor(框宽 × 72 / 字号)。字数再乘 0.85。没有字号按 18pt。
    标题类格子的 0.9 和最多 2 行在写入格子时再收，不放在这里。
    """
    frame = frame or {}
    raw = frame.get("size") if font_pt in (None, "") else font_pt
    try:
        pt = int(raw or 18)
    except (TypeError, ValueError):
        pt = 18
    if pt <= 0:
        pt = 18
    width = float(frame.get("w") or 2)
    height = float(frame.get("h") or 0.4)
    lines = max(1, int((height * 72) / (pt * 1.35)))
    per_line = max(1, int((width * 72) / pt))
    chars = max(1, int(lines * per_line * 0.85))
    return chars, lines


def _slot_capacity(frame: Optional[dict]) -> tuple[int, int, int]:
    """按框的宽高和字号估算能写多少字。返回 (字数, 行数, 字号)。"""
    frame = frame or {}
    try:
        pt = int(frame.get("size") or 18) or 18
    except (TypeError, ValueError):
        pt = 18
    chars, lines = slot_capacity(frame, pt)
    return chars, lines, pt


def _guess_page(spec: dict) -> tuple[str, str, int, str]:
    """用现成的几何标签先猜一版。看图解析会覆盖。返回 role, form, repeat, kind。"""
    tag = str(spec.get("tag") or "")
    if tag == "cover":
        return "cover", "none", 0, "functional"
    if tag == "toc":
        return "toc", "none", 0, "functional"
    if tag == "section":
        return "section", "none", 0, "functional"
    if tag == "end":
        return "end", "none", 0, "functional"
    if tag == "image+text":
        return "content", "image_text", 0, "content"
    if tag == "big-number":
        return "content", "bignum", 0, "content"
    if tag == "cards-3":
        return "content", "cards", 3, "content"
    if tag == "timeline":
        return "content", "timeline", 0, "content"
    if tag == "two-col":
        return "content", "compare", 2, "content"
    if tag == "quote":
        return "content", "quote", 0, "content"
    if tag.startswith("bullets-"):
        try:
            repeat = int(tag.split("-", 1)[1])
        except ValueError:
            repeat = 0
        return "content", "bullets", repeat, "content"
    return "content", "text", 0, "content"


def _frame_map(spec: dict) -> dict[int, dict]:
    return {int(frame["i"]): frame for frame in (spec.get("frames") or []) if "i" in frame}


def _title_like(name: str) -> bool:
    text = str(name or "")
    return text in ("title", "section_title") or text.endswith(".head")


def _same_box(a: dict, b: dict) -> bool:
    try:
        return all(
            abs(float(a.get(key) or 0) - float(b.get(key) or 0)) <= 0.03
            for key in ("x", "y", "w", "h")
        )
    except (TypeError, ValueError):
        return False


def closing_title(sample: str) -> str:
    """结尾标题用模板原文。原文超过 6 个字就改成「谢谢」，避免伸进右侧的图。"""
    from services.ppt import ppt_layouts

    text = str(sample or "").strip()
    if text and 0 < ppt_layouts.text_len(text) <= 6:
        return text
    return "谢谢"


def free_row_width(frame: Optional[dict], boxes: list, slide_width: float,
                   safe_right: Optional[float] = None, clip_graphics: bool = False) -> float:
    """标题这一行从框的左边能用到多宽（英寸）。

    往右碰到同一行、纵向有重叠的下一个形状就停，并留 0.08 英寸空隙。
    没有下一个形状时停在安全边距；没给安全边距就用页宽减 0.5 英寸。
    算出来比原框窄时保持原框宽度。满幅底图不当成右边的障碍。
    """
    frame = frame or {}
    left = float(frame.get("x") or 0)
    top = float(frame.get("y") or 0)
    bottom = top + float(frame.get("h") or 0)
    original = max(0.0, float(frame.get("w") or 0))
    try:
        page_w = float(slide_width)
    except (TypeError, ValueError):
        page_w = 13.333
    if page_w <= 0:
        page_w = 13.333
    if safe_right is None:
        limit = page_w - 0.5
    else:
        try:
            limit = float(safe_right)
        except (TypeError, ValueError):
            limit = page_w - 0.5
    limit = max(left + original, min(limit, page_w))
    own_i = frame.get("i")
    hit_shape = False
    for box in boxes or []:
        if not isinstance(box, dict) or box is frame or _same_box(box, frame):
            continue
        if own_i is not None and box.get("i") is not None and box.get("i") == own_i:
            continue
        width = float(box.get("w") or 0)
        if width <= 0 or width >= page_w * 0.85:
            continue
        ox = float(box.get("x") or 0)
        oy = float(box.get("y") or 0)
        oh = float(box.get("h") or 0)
        if min(bottom, oy + oh) - max(top, oy) <= 0:
            continue
        if ox <= left + 0.05:
            continue
        if ox < limit:
            limit = ox
            hit_shape = True
    gap = 0.08 if hit_shape else 0.0
    width = max(original, limit - left - gap)
    if not clip_graphics:
        return width
    cut = None
    for box in boxes or []:
        if not isinstance(box, dict) or not box.get("graphic"):
            continue
        if box is frame or _same_box(box, frame):
            continue
        box_w = float(box.get("w") or 0)
        if box_w <= 0 or box_w >= page_w * 0.85:
            continue
        ox = float(box.get("x") or 0)
        oy = float(box.get("y") or 0)
        oh = float(box.get("h") or 0)
        if min(bottom, oy + oh) - max(top, oy) <= 0:
            continue
        if ox <= left + 0.05 or ox >= left + original:
            continue
        cut = ox if cut is None else min(cut, ox)
    if cut is None:
        return width
    return max(0.8, min(width, cut - left - 0.08))


def _capped_title_chars(frame: Optional[dict], pt: int) -> tuple[int, int]:
    """标题最多两行。字数按这个行数重算，不再用超出两行的容量。"""
    _chars, lines = slot_capacity(frame, pt)
    lines = min(max(1, lines), 2)
    width = float((frame or {}).get("w") or 2)
    per_line = max(1, int((width * 72) / max(pt, 1)))
    chars = max(1, int(lines * per_line * 0.85 * 0.9))
    return chars, lines


def _title_capacity(frame: Optional[dict]) -> tuple[int, int]:
    """标题按模板字号算。字号很大、框又已经写满时，允许降到 20pt、最多两行，尽量给到 12 字。

    出片仍从模板字号往下缩，这里只放宽写给模型的上限。
    """
    try:
        pt = int((frame or {}).get("size") or 18) or 18
    except (TypeError, ValueError):
        pt = 18
    if pt <= 0:
        pt = 18
    chars, lines = _capped_title_chars(frame, pt)
    if chars >= 12 or pt <= 20:
        return chars, lines
    best = (chars, lines)
    for smaller in range(pt - 2, 19, -2):
        got, got_lines = _capped_title_chars(frame, smaller)
        if got > best[0]:
            best = (got, got_lines)
        if got >= 12:
            return got, got_lines
    return best


def _make_slot(name: str, frame_i, frame: Optional[dict], required: bool,
               boxes: Optional[list] = None, slide_width: Optional[float] = None,
               safe_right: Optional[float] = None, clip_graphics: bool = False) -> dict:
    use = frame
    grow_w = None
    clipped = False
    if frame and _title_like(name) and slide_width:
        width = free_row_width(frame, boxes or [], slide_width, safe_right, clip_graphics)
        original = float(frame.get("w") or 0)
        if clip_graphics and width < original - 0.05:
            use = dict(frame)
            use["w"] = width
            clipped = True
        elif width > original + 0.15:
            use = dict(frame)
            use["w"] = width
            grow_w = round(width, 2)
    if name in ("title", "section_title"):
        if clipped:
            try:
                pt_now = int((frame or {}).get("size") or 18) or 18
            except (TypeError, ValueError):
                pt_now = 18
            chars, lines = _capped_title_chars(use, pt_now if pt_now > 0 else 18)
        else:
            chars, lines = _title_capacity(use)
        _chars, _lines, pt = _slot_capacity(use)
    else:
        chars, lines, pt = _slot_capacity(use)
    slot = {
        "name": name,
        "frame": frame_i,
        "shape_id": (frame or {}).get("shape_id"),
        "max_chars": chars,
        "max_lines": lines,
        "font_pt": pt,
        "required": required,
    }
    if grow_w is not None:
        slot["grow_w"] = grow_w
    return slot


def _slide_width(analysis: Optional[dict]) -> Optional[float]:
    try:
        width = float((analysis or {}).get("slide_width") or 0)
    except (TypeError, ValueError):
        return None
    return width or None


def recalc_capacities(pages: dict, analysis: dict,
                       obstacles_by_page: Optional[dict] = None) -> dict:
    """只重算字数上限、行数和 grow_w。角色、说明、user_edited 不动。"""
    specs = {}
    for spec in (analysis or {}).get("specimens") or []:
        try:
            specs[int(spec.get("index"))] = spec
        except (TypeError, ValueError):
            continue
    slide_w = _slide_width(analysis)
    extra = obstacles_by_page or {}
    for page in (pages or {}).get("pages") or []:
        if not isinstance(page, dict):
            continue
        try:
            number = int(page.get("page") or 0)
        except (TypeError, ValueError):
            continue
        spec = specs.get(number - 1) or {}
        frames = _frame_map(spec)
        boxes = list(frames.values()) + list(extra.get(number) or [])
        for slot in page.get("slots") or []:
            if not isinstance(slot, dict):
                continue
            frame = frames.get(slot.get("frame"))
            if not frame:
                continue
            clip = str(page.get("role") or "") in {"cover", "end"} and str(slot.get("name") or "") == "title"
            fresh = _make_slot(
                str(slot.get("name") or ""), slot.get("frame"), frame,
                bool(slot.get("required")), boxes, slide_w, clip_graphics=clip,
            )
            slot["max_chars"] = fresh["max_chars"]
            slot["max_lines"] = fresh["max_lines"]
            if "grow_w" in fresh:
                slot["grow_w"] = fresh["grow_w"]
            else:
                slot.pop("grow_w", None)
    return pages


def empty_pages(template: dict, analysis: dict) -> dict:
    """按几何分析生成一份还没看过图的页说明。"""
    specs = (analysis or {}).get("specimens") or []
    slide_w = _slide_width(analysis)
    pages = []
    for spec in specs:
        role, form, repeat, kind = _guess_page(spec)
        frames = _frame_map(spec)
        boxes = list(frames.values())
        slots = []
        title_i = spec.get("title_i")
        if title_i is not None:
            slots.append(_make_slot("title", title_i, frames.get(title_i), True, boxes, slide_w))
        bodies = [i for i in (spec.get("bodies_i") or []) if i is not None and i != title_i]
        if not bodies and spec.get("body_i") is not None and spec.get("body_i") != title_i:
            bodies = [spec["body_i"]]
        for offset, frame_i in enumerate(bodies, 1):
            name = "body" if len(bodies) == 1 else f"item{offset}.body"
            slots.append(_make_slot(name, frame_i, frames.get(frame_i), True, boxes, slide_w))
        pages.append({
            "page": int(spec.get("index") or 0) + 1,
            "kind": kind,
            "role": role,
            "form": form,
            "narrative_fit": [],
            "description": "",
            "sample_heading": "",
            "repeat": repeat,
            "slots": slots,
            "decor": [],
            "images": [],
            "variant_group": 0,
            "usable": not bool(spec.get("image_only")),
            "unusable_reason": "整页是图片，没有可写的文字框" if spec.get("image_only") else "",
            "vision_ok": False,
            "user_edited": False,
            "parse_warnings": [],
        })
    width = (analysis or {}).get("slide_width")
    height = (analysis or {}).get("slide_height")
    return {
        "version": 1,
        "template_id": (template or {}).get("id") or (analysis or {}).get("id") or "",
        "template_name": (template or {}).get("name") or (analysis or {}).get("name") or "",
        "template_sha1": "",
        "analysis_version": (analysis or {}).get("version") or 0,
        "slide_size": [width, height],
        "page_count": len(pages),
        "parsed_at": "",
        "models": {},
        "prompt_version": 1,
        "parse": {"status": "none", "done": 0, "total": len(pages), "errors": []},
        "deck": {
            "summary": "",
            "template_storyline": [],
            "functional": {},
            "variant_groups": [],
            "suggested_base": {},
        },
        "pages": pages,
        "parsed": False,
    }


def load_pages(template: dict) -> Optional[dict]:
    path = pages_path(template)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("version", 1)
    data.setdefault("pages", [])
    data.setdefault("deck", {})
    data.setdefault("parse", {"status": "done", "done": 0, "total": 0, "errors": []})
    data["parsed"] = True
    file_path = (template or {}).get("file_path")
    if file_path and pathlib.Path(file_path).is_file():
        current = template_sha1(file_path)
        recorded = str(data.get("template_sha1") or "")
        data["stale"] = bool(recorded and recorded != current)
    else:
        data["stale"] = False
    return data


def dedupe_slot_names(page: dict) -> list[str]:
    """同一页格子名重复时，第二个起改成 name_2、name_3，并写进 parse_warnings。"""
    if not isinstance(page, dict):
        return []
    used: list[str] = []
    added: list[str] = []
    for slot in page.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        name = str(slot.get("name") or "")
        if not name or name not in used:
            if name:
                used.append(name)
            continue
        number = 2
        candidate = f"{name}_{number}"
        while candidate in used:
            number += 1
            candidate = f"{name}_{number}"
        slot["name"] = candidate
        used.append(candidate)
        added.append(f"格子名 {name} 重复，已改成 {candidate}")
    if added:
        current = [str(item) for item in (page.get("parse_warnings") or [])]
        for item in added:
            if item not in current:
                current.append(item)
        page["parse_warnings"] = current
    return added


def save_pages(template: dict, data: dict) -> None:
    if (template or {}).get("source") == "builtin":
        raise PermissionError("内置模板的页说明不能改")
    path = pages_path(template)
    path.parent.mkdir(parents=True, exist_ok=True)
    for page in (data or {}).get("pages") or []:
        if isinstance(page, dict):
            dedupe_slot_names(page)
    payload = dict(data)
    payload.pop("stale", None)
    payload.pop("parsed", None)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def pages_status(template: dict) -> str:
    path = pages_path(template) if (template or {}).get("file_path") else None
    if path is None or not path.is_file():
        return "none"
    data = load_pages(template)
    if not data:
        return "none"
    if data.get("stale"):
        return "stale"
    parse = data.get("parse") or {}
    status = str(parse.get("status") or "")
    if status == "running":
        return "running"
    if status in ("failed", "partial") or parse.get("errors"):
        return "partial"
    if data.get("pages"):
        return "done"
    return "none"


def validate_pages(data: dict, page_count: int) -> list[str]:
    errors = []
    for page in (data or {}).get("pages") or []:
        number = page.get("page")
        if not isinstance(number, int) or number < 1 or number > page_count:
            errors.append(f"页号 {number} 超出 1 到 {page_count}")
            continue
        role = page.get("role")
        if role not in ppt_roles.PAGE_ROLES:
            errors.append(f"第 {number} 页的角色 {role} 不在词表里")
        form = page.get("form")
        if form not in ppt_roles.CONTENT_FORMS:
            errors.append(f"第 {number} 页的形态 {form} 不在词表里")
        for role_name in page.get("narrative_fit") or []:
            if role_name not in ppt_roles.NARRATIVE_ROLES:
                errors.append(f"第 {number} 页的叙事角色 {role_name} 不在词表里")
        for slot in page.get("slots") or []:
            name = slot.get("name")
            if not ppt_roles.slot_pattern_ok(name):
                errors.append(f"第 {number} 页的格子名 {name} 不合法")
    return errors


def merge_user_edits(old: dict, new: dict) -> dict:
    """重新解析时，用户改过的页保留角色、形态、说明和格子名。"""
    kept = {page.get("page"): page for page in (old or {}).get("pages") or []
            if page.get("user_edited")}
    for page in (new or {}).get("pages") or []:
        prev = kept.get(page.get("page"))
        if not prev:
            continue
        for key in _USER_FIELDS:
            if key in prev:
                page[key] = prev[key]
        names = {slot.get("frame"): slot.get("name") for slot in prev.get("slots") or []}
        for slot in page.get("slots") or []:
            name = names.get(slot.get("frame"))
            if name:
                slot["name"] = name
        page["user_edited"] = True
    if (old or {}).get("deck", {}).get("summary") and (old.get("deck") or {}).get("user_summary"):
        new.setdefault("deck", {})["summary"] = old["deck"]["summary"]
        new["deck"]["user_summary"] = True
    return new


def write_deck(pages_data: dict, facts: dict, story: dict) -> dict:
    """把整份归纳写进 deck。用户改过的简介保留。"""
    pages_data = pages_data if isinstance(pages_data, dict) else {}
    deck = pages_data.setdefault("deck", {})
    keep_summary = deck.get("summary") if deck.get("user_summary") else None
    deck["functional"] = dict((facts or {}).get("functional") or {})
    deck["variant_groups"] = list((facts or {}).get("variant_groups") or [])
    deck["suggested_base"] = dict((facts or {}).get("suggested_base") or {})
    deck["summary"] = keep_summary if keep_summary else str((story or {}).get("summary") or "")
    deck["deck_type_hint"] = str((story or {}).get("deck_type_hint") or "")
    deck["template_storyline"] = list((story or {}).get("template_storyline") or [])
    if keep_summary:
        deck["user_summary"] = True
    return pages_data


def apply_user_patch(data: dict, patch: dict) -> dict:
    by_page = {page.get("page"): page for page in data.get("pages") or []}
    for item in (patch or {}).get("pages") or []:
        page = by_page.get(item.get("page"))
        if page is None:
            continue
        for key in _USER_FIELDS:
            if key in item:
                page[key] = item[key]
        if "slots" in item:
            names = {slot.get("frame"): slot.get("name") for slot in item.get("slots") or []}
            for slot in page.get("slots") or []:
                if slot.get("frame") in names and names[slot.get("frame")]:
                    slot["name"] = names[slot.get("frame")]
        page["user_edited"] = True
    deck = (patch or {}).get("deck")
    if isinstance(deck, dict) and "summary" in deck:
        data.setdefault("deck", {})["summary"] = deck["summary"]
        data["deck"]["user_summary"] = True
    return data


def annotate_boxes(data: dict, analysis: dict) -> dict:
    """给格子补上框的位置，只用于界面画框，不写回文件。"""
    specs = {int(spec.get("index") or 0): spec for spec in (analysis or {}).get("specimens") or []}
    for page in (data or {}).get("pages") or []:
        spec = specs.get(int(page.get("page") or 1) - 1) or {}
        frames = {int(frame["i"]): frame for frame in spec.get("frames") or [] if "i" in frame}
        for slot in page.get("slots") or []:
            frame = frames.get(slot.get("frame"))
            if not frame:
                continue
            slot["box"] = [
                round(float(frame.get("x") or 0), 2),
                round(float(frame.get("y") or 0), 2),
                round(float(frame.get("w") or 0), 2),
                round(float(frame.get("h") or 0), 2),
            ]
    return data


def import_document(payload: dict, *, current_sha: str, page_count: int) -> dict:
    warnings = []
    recorded = str((payload or {}).get("template_sha1") or "")
    if recorded and current_sha and recorded != current_sha:
        warnings.append("这份说明是另一份模板的，页号对不上的部分不会导入")
    imported = []
    skipped = []
    for page in (payload or {}).get("pages") or []:
        number = page.get("page")
        if not isinstance(number, int) or number < 1 or number > page_count:
            skipped.append(number)
            continue
        imported.append(page)
    return {"imported": imported, "skipped": skipped, "warnings": warnings}


def to_markdown(data: dict) -> str:
    lines = [f"# {(data or {}).get('template_name') or '模板'} 页说明", ""]
    summary = ((data or {}).get("deck") or {}).get("summary") or ""
    if summary:
        lines.append(summary)
        lines.append("")
    for page in (data or {}).get("pages") or []:
        role = ppt_roles.PAGE_ROLES.get(page.get("role"), page.get("role"))
        form = ppt_roles.CONTENT_FORMS.get(page.get("form"), page.get("form"))
        fits = "、".join(ppt_roles.NARRATIVE_ROLES.get(name, name)
                        for name in (page.get("narrative_fit") or []))
        fit_text = f"｜适合：{fits}" if fits else ""
        desc = page.get("description") or ""
        slot_bits = []
        for slot in page.get("slots") or []:
            slot_bits.append(f"{slot.get('name')} {slot.get('max_chars')} 字")
        slots = "｜格子：" + "、".join(slot_bits) if slot_bits else ""
        lines.append(f"第 {page.get('page')} 页｜{role}｜{form}{fit_text}｜{desc}{slots}")
    return "\n".join(lines).rstrip() + "\n"


def apply_page_parse(pages_data: dict, analysis: dict, page: int, result: dict) -> dict:
    """把一页的看图结果写进页说明，并回写该页的 title_i / bodies_i。

    不在词表里的取值丢掉，回落到几何推测。decor_keep / decor_clear 进 decor，不进 slots。
    missing 只记一条警告，不建框。用户改过的页保留角色、形态、说明和格子名。
    """
    pages_data = pages_data if isinstance(pages_data, dict) else {}
    pages = pages_data.setdefault("pages", [])
    current = next((item for item in pages if item.get("page") == page), None)
    spec = next((item for item in (analysis or {}).get("specimens") or []
                 if item.get("index") == page - 1), None)
    fallback_role, fallback_form, fallback_repeat, kind = _guess_page(spec or {})
    warnings: list[str] = []
    payload = result or {}

    role = payload.get("role")
    if role not in ppt_roles.PAGE_ROLES:
        warnings.append(f"角色 {role} 不在词表里，沿用推测")
        role = fallback_role
    form = payload.get("form")
    if form not in ppt_roles.CONTENT_FORMS:
        warnings.append(f"形态 {form} 不在词表里，沿用推测")
        form = fallback_form

    fits = []
    for name in payload.get("narrative_fit") or []:
        if name in ppt_roles.NARRATIVE_ROLES:
            fits.append(name)
        else:
            warnings.append(f"叙事角色 {name} 不在词表里")
    if len(fits) > 4:
        warnings.append("叙事角色超过 4 个，只保留前 4 个")
        fits = fits[:4]

    frames = _frame_map(spec or {})
    slots = []
    decor = []
    title_i = None
    bodies: list[int] = []
    for item in payload.get("frames") or []:
        fid = str(item.get("id") or "")
        if len(fid) < 2 or fid[0] not in ("F", "f"):
            warnings.append(f"框编号 {fid} 无法对应")
            continue
        try:
            frame_i = int(fid[1:])
        except ValueError:
            warnings.append(f"框编号 {fid} 无法对应")
            continue
        slot_name = str(item.get("slot") or "")
        frame = frames.get(frame_i)
        if frame is None:
            warnings.append(f"框编号 {fid} 无法对应")
            continue
        if _TOC_INDEX.match(str(frame.get("text") or "").strip()):
            decor.append(_decor_entry(frame_i, frame, "keep"))
            continue
        if slot_name == "decor_keep":
            decor.append(_decor_entry(frame_i, frame, "keep"))
            continue
        if slot_name == "decor_clear":
            decor.append(_decor_entry(frame_i, frame, "clear"))
            continue
        if not ppt_roles.slot_pattern_ok(slot_name):
            warnings.append(f"格子名 {slot_name} 不合法")
            continue
        required = slot_name in ("title", "section_title", "body") or slot_name.endswith((".body", ".head"))
        slots.append(_make_slot(
            slot_name, frame_i, frame, required, list(frames.values()), _slide_width(analysis),
        ))
        if slot_name == "title" and title_i is None:
            title_i = frame_i
        if slot_name == "body" or (slot_name.startswith("item") and slot_name.endswith(".body")):
            bodies.append(frame_i)

    if payload.get("missing"):
        warnings.append("这页有看得到但没法写的字，可能是图片上的字")
    names = {slot.get("name") for slot in slots}
    if role == "section" and "section_title" not in names and "title" not in names:
        warnings.append("没有可写的章节名，角色改为内容页")
        role = "content"

    try:
        repeat = int(payload.get("repeat") if payload.get("repeat") is not None else fallback_repeat)
    except (TypeError, ValueError):
        repeat = fallback_repeat
    usable = True if "usable" not in payload else bool(payload.get("usable"))
    fresh = {
        "page": page,
        "kind": (current or {}).get("kind") or kind,
        "role": role,
        "form": form,
        "narrative_fit": fits,
        "description": str(payload.get("description") or "")[:60],
        "sample_heading": str(payload.get("sample_heading") or ""),
        "repeat": repeat,
        "slots": slots,
        "decor": decor,
        "images": list((current or {}).get("images") or []),
        "variant_group": (current or {}).get("variant_group") or 0,
        "usable": usable,
        "unusable_reason": str(payload.get("unusable_reason") or ""),
        "vision_ok": True,
        "user_edited": False,
        "parse_warnings": warnings,
    }
    if current and current.get("user_edited"):
        merged = merge_user_edits({"pages": [dict(current)]}, {"pages": [fresh]})
        fresh = merged["pages"][0]
        fresh["vision_ok"] = True
        fresh["parse_warnings"] = warnings
    else:
        _write_parse_indexes(spec, title_i, bodies, payload, analysis)
    dedupe_slot_names(fresh)

    if current is None:
        pages.append(fresh)
    else:
        current.clear()
        current.update(fresh)
    return pages_data


def _decor_entry(frame_i: int, frame: Optional[dict], action: str) -> dict:
    return {
        "frame": frame_i,
        "shape_id": (frame or {}).get("shape_id"),
        "action": action,
        "text": (frame or {}).get("text") or "",
    }


def _write_parse_indexes(spec, title_i, bodies: list[int], payload: dict, analysis: dict) -> None:
    if spec is None:
        return
    if title_i is not None:
        spec["title_i"] = title_i
    if bodies:
        spec["bodies_i"] = bodies
        spec["body_i"] = bodies[0]
        spec["capacity"] = max(1, len(bodies))
    photo_boxes = payload.get("photo_boxes") or []
    if photo_boxes and (spec.get("images") or []):
        from services.ppt import ppt_vision

        slide_w = (analysis or {}).get("slide_width") or 13.333
        slide_h = (analysis or {}).get("slide_height") or 7.5
        ppt_vision._apply_regions(spec, {"photo_boxes": photo_boxes}, slide_w, slide_h)


def catalog_for_prompt(data: dict, limit_chars: int = 3000) -> str:
    lines = []
    for page in (data or {}).get("pages") or []:
        if page.get("usable") is False:
            continue
        role = ppt_roles.PAGE_ROLES.get(page.get("role"), "")
        form = ppt_roles.CONTENT_FORMS.get(page.get("form"), "")
        desc = page.get("description") or ""
        lines.append(f"第{page.get('page')}页 {role} {form} {desc}".strip())
    text = "\n".join(lines)
    if len(text) <= limit_chars:
        return text
    return text[:limit_chars].rsplit("\n", 1)[0]
