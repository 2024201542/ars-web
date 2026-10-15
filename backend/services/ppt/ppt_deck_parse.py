"""整份模板的讲法：功能页、换色版、底板四页，外加一次文字归纳。

格子签名和底板由代码算。讲法失败时按原标题拼一个简版，不编占位标题。
"""

from __future__ import annotations

import json

from services.ppt import ppt_roles

_DECK_HINTS = {
    "research_talk", "defense", "proposal", "paper_report",
    "lecture", "review", "survey_report",
}
_PLACEHOLDERS = ("标题文字", "点击输入", "请输入", "请在这里", "关键词标题", "添加标题", "在此输入")

STORY_PROMPT = """下面是一套 PPT 模板每一页的说明。请归纳这套模板原本的讲法，只输出 JSON：
{"summary": "一两句话：风格、适合什么场合（答辩、开题、课程讲解……）",
 "deck_type_hint": "取值 research_talk/defense/proposal/paper_report/lecture/review/survey_report，看不出就空",
 "template_storyline": [{"heading": "模板原标题", "role": "叙事角色", "pages": [页号]}]}
template_storyline 按页号顺序，只根据原标题归纳，原标题是「标题文字」「点击输入」这类占位时不要编。
叙事角色取值：__NARRATIVE_ROLES__
"""


def _half(value) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    return round(number * 2) / 2


def _signature(page: dict, spec: dict | None) -> tuple:
    frames = {frame.get("i"): frame for frame in (spec or {}).get("frames") or []}
    parts = []
    for slot in page.get("slots") or []:
        name = str(slot.get("name") or "")
        if not name or name.startswith("decor_"):
            continue
        frame = frames.get(slot.get("frame")) or {}
        pos = (
            _half(frame.get("x")), _half(frame.get("y")),
            _half(frame.get("w")), _half(frame.get("h")),
        )
        parts.append((name, pos))
    parts.sort()
    return tuple(parts)


def _body_count(page: dict) -> int:
    count = 0
    for slot in page.get("slots") or []:
        name = str(slot.get("name") or "")
        if name == "body" or name.endswith(".body"):
            count += 1
    return count


def _has_title(page: dict) -> bool:
    return any(str(slot.get("name") or "") == "title" for slot in page.get("slots") or [])


def deck_facts(pages_data: dict, analysis: dict) -> dict:
    """不调模型。相同格子签名的页归成一组，并选出底板四页。"""
    pages = list((pages_data or {}).get("pages") or [])
    specs = {int(spec.get("index") or 0): spec for spec in (analysis or {}).get("specimens") or []}
    functional: dict[str, list] = {}
    buckets: dict[tuple, list] = {}
    for page in pages:
        role = str(page.get("role") or "")
        if role:
            functional.setdefault(role, []).append(page.get("page"))
        page["variant_group"] = 0
        signature = _signature(page, specs.get(int(page.get("page") or 1) - 1))
        if not signature:
            continue
        buckets.setdefault(signature, []).append(page)

    groups = []
    group_id = 0
    for signature, members in buckets.items():
        if len(members) < 2:
            continue
        group_id += 1
        for page in members:
            page["variant_group"] = group_id
        groups.append({
            "id": group_id,
            "pages": [page.get("page") for page in members],
            "slots": [name for name, _pos in signature],
        })

    cover = next((page.get("page") for page in pages if page.get("role") == "cover"), None)
    section = next((page.get("page") for page in pages if page.get("role") == "section"), None)
    end = next((page.get("page") for page in reversed(pages) if page.get("role") == "end"), None)
    contents = [page for page in pages if page.get("role") == "content" and _has_title(page)]
    content = None
    if contents:
        content = min(contents, key=lambda page: (_body_count(page), len(page.get("decor") or []), page.get("page") or 0))
        content = content.get("page")
    suggested = {}
    if cover:
        suggested["cover"] = cover
    if section:
        suggested["section"] = section
    if content:
        suggested["content"] = content
    if end:
        suggested["end"] = end
    return {
        "functional": functional,
        "variant_groups": groups,
        "suggested_base": suggested,
    }


def _meaningful(text: str) -> bool:
    raw = str(text or "").strip()
    if len(raw) < 2:
        return False
    return not any(word in raw for word in _PLACEHOLDERS)


def fallback_storyline(pages_data: dict) -> list[dict]:
    """模型没给出可用 JSON 时，按原标题和章节页顺序拼一版。"""
    items = []
    for page in (pages_data or {}).get("pages") or []:
        heading = str(page.get("sample_heading") or "").strip()
        if not _meaningful(heading):
            continue
        if page.get("role") not in ("section", "content", "summary", "cover"):
            continue
        role = ""
        for name in page.get("narrative_fit") or []:
            if name in ppt_roles.NARRATIVE_ROLES:
                role = name
                break
        if not role:
            role = "background" if page.get("role") != "cover" else "hook"
        if items and items[-1]["heading"] == heading:
            items[-1]["pages"].append(page.get("page"))
            continue
        items.append({"heading": heading, "role": role, "pages": [page.get("page")]})
    return items


def _roles_text() -> str:
    return "、".join(f"{key} {label}" for key, label in ppt_roles.NARRATIVE_ROLES.items())


def _parse_story(text: str) -> dict | None:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):] if "{" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _clean_story(data: dict, page_count: int) -> dict | None:
    hint = str(data.get("deck_type_hint") or "").strip()
    if hint not in _DECK_HINTS:
        hint = ""
    storyline = []
    for item in data.get("template_storyline") or []:
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading") or "").strip()
        if not _meaningful(heading):
            continue
        role = str(item.get("role") or "")
        if role not in ppt_roles.NARRATIVE_ROLES:
            continue
        pages = []
        for number in item.get("pages") or []:
            try:
                page = int(number)
            except (TypeError, ValueError):
                continue
            if 1 <= page <= max(page_count, 1):
                pages.append(page)
        if not pages:
            continue
        storyline.append({"heading": heading, "role": role, "pages": pages})
    if not storyline and not str(data.get("summary") or "").strip():
        return None
    return {
        "summary": str(data.get("summary") or "")[:200],
        "deck_type_hint": hint,
        "template_storyline": storyline,
    }


async def deck_story(pages_data: dict, text_model: str = "", user_id: str = "") -> dict:
    """一次文字模型调用。失败时简介留空，讲法用简版。"""
    from services.ppt.ppt_plan import _ask_text

    lines = []
    for page in (pages_data or {}).get("pages") or []:
        lines.append(
            f"{page.get('page')}｜{page.get('role') or ''}｜{page.get('form') or ''}"
            f"｜{page.get('sample_heading') or ''}｜{page.get('description') or ''}"
        )
    prompt = STORY_PROMPT.replace("__NARRATIVE_ROLES__", _roles_text())
    text, name, err = "", "", ""
    try:
        text, name, err = await _ask_text(user_id, prompt, "\n".join(lines), text_model or "", max_tokens=1200)
    except Exception as exc:
        err = str(exc)
    parsed = _parse_story(text) if text and not err else None
    page_count = len((pages_data or {}).get("pages") or [])
    cleaned = _clean_story(parsed, page_count) if parsed else None
    if cleaned is None:
        return {
            "summary": "",
            "deck_type_hint": "",
            "template_storyline": fallback_storyline(pages_data),
            "model": name or "",
        }
    cleaned["model"] = name or text_model or ""
    return cleaned
