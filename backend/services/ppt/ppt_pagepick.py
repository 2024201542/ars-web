"""给叙事骨架的每一页挑一张模板页。同一份输入每次结果相同。"""

from __future__ import annotations

import re

_NEAR = {
    "cards": {"numbered", "bullets"},
    "numbered": {"cards", "bullets"},
    "bullets": {"cards", "numbered"},
    "compare": {"cards"},
    "timeline": {"process"},
    "process": {"timeline"},
    "image_text": {"cards"},
    "bignum": {"cards"},
    "quote": {"text"},
    "text": {"quote"},
}
# compare、image_text、bignum 和 cards 双向相近。上面 cards 没列入它们，这里补上。
_NEAR["cards"] = _NEAR["cards"] | {"compare", "image_text", "bignum"}

_SUMMARY_FORMS = {"numbered", "bullets", "cards"}
_LOW_SCORE = 35


def load_catalog(user_id: str, template_id: str) -> tuple[dict | None, dict | None]:
    """读模板的页说明。还没解析过就用几何推测。返回 (页说明, 底板)。"""
    from services.ppt import ppt_base, ppt_library, ppt_pages

    item = ppt_library.find(user_id, template_id)
    if not item:
        return None, None
    data = ppt_pages.load_pages(item) or ppt_pages.empty_pages(item, item)
    return data, ppt_base.load_base(template_id)


def _usable(catalog: dict) -> list[dict]:
    pages = []
    for page in (catalog or {}).get("pages") or []:
        if isinstance(page, dict) and page.get("usable") is not False:
            pages.append(page)
    return pages


_ITEM_HEAD = re.compile(r"^item\d+\.head$")


def page_has_toc_items(page: dict) -> bool:
    """目录页上有没有 itemN.head。只有标题和正文的目录页填不了章节名。"""
    for slot in (page or {}).get("slots") or []:
        if isinstance(slot, dict) and _ITEM_HEAD.match(str(slot.get("name") or "")):
            return True
    return False


def toc_pages_with_items(catalog: dict) -> list[dict]:
    return [page for page in _usable(catalog) if page.get("role") == "toc" and page_has_toc_items(page)]


def candidates(slot: dict, catalog: dict) -> list[dict]:
    """这一骨架位可以用哪些模板页。不可用的页不进候选。"""
    kind = str((slot or {}).get("kind") or "content")
    pages = _usable(catalog)
    if kind == "cover":
        return [page for page in pages if page.get("role") == "cover"]
    if kind == "toc":
        return [page for page in pages if page.get("role") == "toc" and page_has_toc_items(page)]
    if kind == "section":
        return [page for page in pages if page.get("role") == "section"]
    if kind == "end":
        return [page for page in pages if page.get("role") == "end"]
    if kind == "summary":
        summary = [page for page in pages if page.get("role") == "summary"]
        if summary:
            return summary
        return [page for page in pages
                if page.get("role") == "content" and page.get("form") in _SUMMARY_FORMS]
    return [page for page in pages if page.get("role") == "content"]


def _body_chars(page: dict) -> int:
    total = 0
    for slot in page.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        name = str(slot.get("name") or "")
        if name in {"title", "section_title"}:
            continue
        total += int(slot.get("max_chars") or 0)
    return total


def score(slot: dict, page: dict, prev_page: dict | None, used: dict[int, int]) -> tuple[float, list[str]]:
    """给一张候选页打分，分项写进理由。"""
    points = 0.0
    reasons: list[str] = []
    form = str((slot or {}).get("form_hint") or "")
    page_form = str((page or {}).get("form") or "")
    if form and form == page_form:
        points += 40
        reasons.append("形态一致 +40")
    elif form and page_form in _NEAR.get(form, ()):
        points += 20
        reasons.append("形态相近 +20")

    try:
        items = int((slot or {}).get("items") or 0)
    except (TypeError, ValueError):
        items = 0
    try:
        repeat = int((page or {}).get("repeat") or 0)
    except (TypeError, ValueError):
        repeat = 0
    if repeat == 0 and items <= 1:
        points += 25
        reasons.append("没有并列格子 +25")
    elif items == repeat:
        points += 25
        reasons.append(f"格子组数 {items} 对 {repeat} +25")
    elif abs(items - repeat) == 1:
        points += 12
        reasons.append("格子组数相差 1 +12")

    role = str((slot or {}).get("role") or "")
    fit = (page or {}).get("narrative_fit") or []
    if role and role in fit:
        points += 15
        reasons.append("叙事适配 +15")

    need = len(str((slot or {}).get("message") or "")) + items * 35
    room = _body_chars(page or {})
    if room and need <= room * 0.9:
        points += 10
        reasons.append("容量够 +10")
    elif room and need <= room * 1.2:
        points += 5
        reasons.append("容量勉强 +5")

    page_no = int((page or {}).get("page") or 0)
    times = int((used or {}).get(page_no, 0))
    if times <= 0:
        points += 10
        reasons.append("没用过 +10")
    elif times == 1:
        points += 3
        reasons.append("用过一次 +3")

    if prev_page and int(prev_page.get("page") or 0) == page_no and page_no:
        points -= 40
        reasons.append("与上一页同一张 -40")
    group = int((page or {}).get("variant_group") or 0)
    if (prev_page and group and group == int(prev_page.get("variant_group") or 0)):
        points -= 15
        reasons.append("与上一页同一组 -15")
    if (page or {}).get("vision_ok") is False:
        points -= 5
        reasons.append("还没看过图 -5")
    return points, reasons


def _base_no(base: dict | None, key: str) -> int:
    pages = (base or {}).get("pages") or {}
    try:
        return int(pages.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _by_no(pages: list[dict], number: int) -> dict | None:
    for page in pages:
        if int(page.get("page") or 0) == number:
            return page
    return None


def _blank(no: int, reasons: list[str], score: float = 0) -> dict:
    return {"no": no, "page": None, "score": score, "reasons": reasons, "fallback": True, "form": "", "role": ""}


def _packed(no: int, page: dict | None, value: float, reasons: list[str], fallback: bool) -> dict:
    return {
        "no": no,
        "page": int(page["page"]) if page else None,
        "score": value,
        "reasons": list(reasons),
        "fallback": fallback,
        "form": str((page or {}).get("form") or ""),
        "role": str((page or {}).get("role") or ""),
    }


def _eligible(slot: dict, catalog: dict, base: dict | None) -> list[dict]:
    found = candidates(slot, catalog)
    content_no = _base_no(base, "content")
    kind = str(slot.get("kind") or "content")
    if content_no and kind in {"content", "summary"}:
        found = [page for page in found
                 if int(page.get("page") or 0) != content_no or page.get("role") == "summary"]
    return found


def _best(slot: dict, pages: list[dict], prev: dict | None, used: dict[int, int]) -> tuple[dict | None, float, list[str]]:
    ranked = []
    for page in pages:
        value, reasons = score(slot, page, prev, used)
        ranked.append((value, int(page.get("page") or 0), reasons, page))
    if not ranked:
        return None, 0, ["没有候选页"]
    ranked.sort(key=lambda row: (-row[0], row[1]))
    value, _no, reasons, page = ranked[0]
    return page, value, reasons


def top_candidates(slot: dict, catalog: dict, base: dict | None = None, limit: int = 6) -> list[dict]:
    """某一页的前几名候选，不改计划。"""
    ranked = []
    for page in _eligible(slot, catalog, base):
        value, reasons = score(slot, page, None, {})
        ranked.append(_packed(int(slot.get("no") or 0), page, value, reasons, False))
    ranked.sort(key=lambda item: (-item["score"], item["page"] or 0))
    return ranked[:limit]


def pick_pages(slots: list[dict], catalog: dict, base: dict | None, *,
               reuse_section: bool = True) -> list[dict]:
    """按骨架顺序选页。封面、结尾、目录先定，章节页默认同一张，内容页先挑候选少的。"""
    slots = [slot if isinstance(slot, dict) else {} for slot in (slots or [])]
    result: list[dict | None] = [None] * len(slots)
    used: dict[int, int] = {}

    def slot_no(index: int, slot: dict) -> int:
        try:
            return int(slot.get("no") or index + 1)
        except (TypeError, ValueError):
            return index + 1

    for index, slot in enumerate(slots):
        if slot.get("pick_locked") and slot.get("template_page"):
            try:
                locked = int(slot["template_page"])
            except (TypeError, ValueError):
                locked = 0
            if locked:
                card = _by_no(_usable(catalog), locked)
                result[index] = _packed(
                    slot_no(index, slot), card or {"page": locked, "form": "", "role": ""},
                    0, ["用户指定"], False)
                kind = str(slot.get("kind") or "")
                if kind in {"content", "summary"}:
                    used[locked] = used.get(locked, 0) + 1

    def assign_fixed(index: int, slot: dict, kind: str, base_key: str = "") -> None:
        if result[index] is not None:
            return
        pages = candidates({"kind": kind}, catalog)
        number = slot_no(index, slot)
        if not pages:
            result[index] = _blank(number, ["没有这种模板页"])
            return
        wanted = _base_no(base, base_key) if base_key else 0
        chosen = _by_no(pages, wanted) if wanted else None
        if chosen is None:
            chosen = min(pages, key=lambda page: int(page.get("page") or 0))
        value, reasons = score(slot, chosen, None, {})
        result[index] = _packed(number, chosen, value, reasons, False)

    for index, slot in enumerate(slots):
        kind = str(slot.get("kind") or "content")
        if kind == "cover":
            assign_fixed(index, slot, "cover", "cover")
        elif kind == "end":
            assign_fixed(index, slot, "end", "end")
        elif kind == "toc":
            if result[index] is not None:
                continue
            pages = candidates({"kind": "toc"}, catalog)
            number = slot_no(index, slot)
            if not pages:
                result[index] = _blank(number, ["没有这种模板页"])
                continue
            section_count = sum(1 for item in slots if str(item.get("kind") or "") == "section")
            matched = []
            for page in pages:
                try:
                    repeat = int(page.get("repeat") or 0)
                except (TypeError, ValueError):
                    repeat = 0
                if repeat and repeat == section_count:
                    matched.append(page)
            pool = matched or pages
            wanted = _base_no(base, "toc")
            chosen = _by_no(pool, wanted) if wanted else None
            if chosen is None:
                chosen = min(pool, key=lambda page: int(page.get("page") or 0))
            value, reasons = score(slot, chosen, None, {})
            if matched:
                reasons = list(reasons) + [f"目录条数等于章节数 {section_count}"]
            result[index] = _packed(number, chosen, value, reasons, False)

    section_indexes = [i for i, slot in enumerate(slots) if str(slot.get("kind") or "") == "section"]
    section_pages = candidates({"kind": "section"}, catalog)
    if section_indexes:
        if reuse_section and section_pages:
            wanted = _base_no(base, "section")
            chosen = _by_no(section_pages, wanted) if wanted else None
            if chosen is None:
                chosen, _value, _reasons = _best(slots[section_indexes[0]], section_pages, None, {})
            for index in section_indexes:
                if result[index] is not None:
                    continue
                value, reasons = score(slots[index], chosen, None, {})
                result[index] = _packed(slot_no(index, slots[index]), chosen, value, reasons, False)
        else:
            for nth, index in enumerate(section_indexes):
                if result[index] is not None:
                    continue
                if not section_pages:
                    result[index] = _blank(slot_no(index, slots[index]), ["没有这种模板页"])
                    continue
                chosen = section_pages[nth % len(section_pages)]
                value, reasons = score(slots[index], chosen, None, {})
                result[index] = _packed(slot_no(index, slots[index]), chosen, value, reasons, False)

    content_indexes = [i for i, slot in enumerate(slots)
                       if str(slot.get("kind") or "content") in {"content", "summary"}]
    content_pool = candidates({"kind": "content"}, catalog)
    content_no = _base_no(base, "content")
    if content_no:
        content_pool = [page for page in content_pool if int(page.get("page") or 0) != content_no]
    cap = 2 if len(content_pool) >= len(content_indexes) else 3

    order = sorted(
        [i for i in content_indexes if result[i] is None],
        key=lambda i: (len(_eligible(slots[i], catalog, base)), i),
    )
    for index in order:
        slot = slots[index]
        pages = _eligible(slot, catalog, base)
        chosen, value, reasons = _best(slot, pages, None, used)
        low = chosen is None or value < _LOW_SCORE
        if low and chosen is not None and str(slot.get("kind") or "") == "summary" \
                and chosen.get("role") == "summary":
            # 骨架里的总结位通常不带形态和条数，分数上不去；页说明明确标成总结的页照用。
            low = False
            reasons = list(reasons) + ["页说明标成总结"]
        form = str(slot.get("form_hint") or "")
        near = _NEAR.get(form, ())
        form_exists = (not form) or any(
            str(page.get("form") or "") == form or str(page.get("form") or "") in near
            for page in pages
        )
        if low and chosen is not None and not form_exists:
            low = False
            reasons = list(reasons) + ["模板没有这种形态，用得分最高的内容页"]
        if low:
            result[index] = _blank(slot_no(index, slot), reasons or ["分数不够"], value)
            continue
        result[index] = _packed(slot_no(index, slot), chosen, value, reasons, False)
        page_no = int(chosen["page"])
        used[page_no] = used.get(page_no, 0) + 1

    _spread(result, slots, catalog, base, content_indexes, cap, len(content_pool) < len(content_indexes))
    return [item or _blank(index + 1, ["没有选中"]) for index, item in enumerate(result)]


def _spread(result, slots, catalog, base, content_indexes, cap: int, short: bool) -> None:
    """同一张内容页不连续，默认最多用两次。模板页不够时放到三次。"""
    used: dict[int, int] = {}
    prev = 0
    for index in content_indexes:
        item = result[index]
        if not item or item.get("fallback") or not item.get("page"):
            prev = 0
            continue
        if slots[index].get("pick_locked"):
            page_no = int(item["page"])
            used[page_no] = used.get(page_no, 0) + 1
            prev = page_no
            continue
        page_no = int(item["page"])
        blocked = page_no == prev or used.get(page_no, 0) >= cap
        if blocked:
            pages = _eligible(slots[index], catalog, base)
            ranked = []
            for page in pages:
                number = int(page.get("page") or 0)
                if number == prev or used.get(number, 0) >= cap:
                    continue
                value, reasons = score(slots[index], page, None, used)
                ranked.append((value, number, reasons, page))
            ranked.sort(key=lambda row: (-row[0], row[1]))
            if ranked:
                value, number, reasons, page = ranked[0]
                if short:
                    reasons = list(reasons) + ["模板内容页不够，重复使用"]
                low = value < _LOW_SCORE
                result[index] = _packed(
                    item["no"], None if low else page, value, reasons, low)
                page_no = 0 if low else number
        elif short and used.get(page_no, 0) >= 1:
            item["reasons"] = list(item["reasons"]) + ["模板内容页不够，重复使用"]
        if page_no:
            used[page_no] = used.get(page_no, 0) + 1
            prev = page_no


def apply_picks(plan: dict, picks: list[dict], catalog: dict | None = None) -> dict:
    """把选页结果写到计划的每一页上。用户锁住的页不动。"""
    by_no = {}
    for page in (catalog or {}).get("pages") or []:
        if isinstance(page, dict) and page.get("page"):
            by_no[int(page["page"])] = page
    slides = (plan or {}).get("slides") or []
    for index, pick in enumerate(picks or []):
        if index >= len(slides) or not isinstance(slides[index], dict):
            continue
        slide = slides[index]
        if slide.get("pick_locked") and slide.get("template_page"):
            continue
        page_no = pick.get("page")
        if page_no:
            slide["template_page"] = int(page_no)
            card = by_no.get(int(page_no)) or {}
            slide["template_form"] = pick.get("form") or card.get("form") or ""
            slide["template_role"] = pick.get("role") or card.get("role") or ""
        else:
            slide.pop("template_page", None)
            slide["template_form"] = ""
            slide["template_role"] = ""
        slide["pick_reason"] = list(pick.get("reasons") or [])
        slide["pick_fallback"] = bool(pick.get("fallback"))
        slide.setdefault("pick_locked", False)
    return plan
