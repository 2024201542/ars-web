"""叙事 skill 的加载，以及出计划前的讲法骨架。按汇报类型只拼需要的那一段。"""

from __future__ import annotations

import re
from pathlib import Path

_DIR = Path(__file__).resolve().parents[2] / "skills" / "ppt-storyline"
_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_VERSION = re.compile(r"^version:\s*(\d+)\s*$", re.M)
_cache: dict = {}


def skill_dir() -> Path:
    return _DIR


def _read(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


def skill_version() -> int:
    text = _read("SKILL.md")
    front = _FRONT.match(text)
    body = front.group(1) if front else text
    found = _VERSION.search(body)
    return int(found.group(1)) if found else 0


def _body(text: str) -> str:
    front = _FRONT.match(text)
    return text[front.end():] if front else text


def _type_section(markdown: str, deck_type: str) -> str:
    parts = re.split(r"(?=^## )", markdown, flags=re.M)
    for part in parts:
        if not part.startswith("## "):
            continue
        heading = part.splitlines()[0][3:].strip()
        if heading == deck_type or heading.startswith(deck_type + " "):
            return part.strip()
    return ""


def load_skill(deck_type: str) -> str:
    """总规则 + 这一种汇报的骨架 + 承接 + 页数分配。"""
    wanted = deck_type or "research_talk"
    stamps = tuple(path.stat().st_mtime_ns for path in (
        _DIR / "SKILL.md",
        _DIR / "references" / "deck-types.md",
        _DIR / "references" / "bridges.md",
        _DIR / "references" / "page-budget.md",
    ))
    key = (wanted, stamps)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    types = _read("references/deck-types.md")
    section = _type_section(types, wanted) or _type_section(types, "research_talk")
    text = "\n\n".join([
        _body(_read("SKILL.md")).strip(),
        section,
        _read("references/bridges.md").strip(),
        _read("references/page-budget.md").strip(),
    ])
    _cache.clear()
    _cache[key] = text
    return text


# 用户原话里先命中靠前的类型。长词放在短词前面，避免「毕业论文」被「论文」截走。
_KEYWORDS = (
    ("defense", ("毕业答辩", "毕业论文", "答辩", "学位", "defense")),
    ("proposal", ("研究计划", "开题", "选题", "proposal")),
    ("paper_report", ("读书报告", "文献汇报", "这篇论文", "组会")),
    ("survey_report", ("调研", "访谈", "问卷", "调查")),
    ("review", ("研究现状", "文献回顾", "综述")),
    ("lecture", ("给学生讲", "讲解", "课程", "介绍", "科普", "课件", "lecture")),
    ("research_talk", ("研究", "论文", "课题")),
)
_KNOWN = {name for name, _words in _KEYWORDS}
_BY_STRUCTURE = (
    ("开题", "proposal"),
    ("答辩", "defense"),
    ("毕业", "defense"),
    ("组会", "paper_report"),
    ("读书", "paper_report"),
    ("综述", "review"),
    ("调研", "survey_report"),
    ("调查", "survey_report"),
    ("讲解", "lecture"),
    ("课程", "lecture"),
    ("课件", "lecture"),
    ("科普", "lecture"),
    ("研究", "research_talk"),
)
_HEADING = re.compile(
    r"(?m)^(?:#{1,4}\s*|[一二三四五六七八九十]{1,3}[、.．]\s*"
    r"|第\s*[0-9一二三四五六七八九十]{1,3}\s*[章节部分]\s*|\d{1,2}[.．]\s*)(.+)$")
SECTION_TITLES = {
    "research_talk": ["研究背景", "研究问题", "研究方法", "主要发现", "讨论与结论"],
    "defense": ["选题背景", "研究问题", "文献与不足", "研究设计", "研究发现", "结论与展望"],
    "proposal": ["选题背景", "研究意义", "文献不足", "研究问题", "研究内容与方法", "进度安排"],
    "paper_report": ["这篇论文在回答什么", "作者怎么做的", "主要结果", "优点与不足", "对我们的启发"],
    "lecture": ["从一个例子说起", "这个概念指什么", "它是怎么起作用的", "两个例子", "容易搞错的地方", "可以怎么做"],
    "review": ["这个问题从哪来", "研究脉络", "几种做法的差别", "还在争什么", "接下来可能往哪走"],
    "survey_report": ["为什么做这次调研", "对象与方法", "听到了什么", "原因", "建议"],
}
DECK_NAMES = {
    "research_talk": "研究汇报",
    "defense": "毕业答辩",
    "proposal": "开题报告",
    "paper_report": "文献汇报",
    "lecture": "讲解",
    "review": "综述",
    "survey_report": "调研报告",
}
ROLE_SHORT = {
    "hook": "引子", "background": "背景", "significance": "意义", "question": "问题",
    "literature": "文献", "theory": "理论", "method": "方法", "data": "数据",
    "concept": "概念", "principle": "原理", "finding": "发现", "case": "案例",
    "comparison": "对比", "example": "例子", "misconception": "误区",
    "discussion": "讨论", "recommendation": "建议", "conclusion": "结论",
    "limitation": "不足", "outlook": "展望", "innovation": "创新",
    "schedule": "进度", "takeaway": "启发", "summary": "小结",
}
STORYLINE_SYSTEM = """你是学术汇报的讲法策划。先读讲法规则，再读材料，做一份叙事骨架，只输出 JSON。
讲法规则：
{skill}

要求：
1. 汇报类型是 {deck_type}，按规则里这种类型的骨架排章节；材料的章节顺序只作参考。
2. 总页数 {pages} 页左右，按页数分配表定章节页和内容页的数量。
3. 先写 central_question（一句问句）和 answer（一句话回答）。
4. 每张内容页写 message（一句判断，就是这页的标题意思）、evidence（这页用材料里的什么证据）、form_hint（bullets/numbered/cards/compare/timeline/process/quote/bignum/image_text）、bridge（承接/递进/转折/举例/因果/回扣）、items（并列点数，没有就 0）。
5. 倒数第二页是 summary，message 回答 central_question。
6. 材料里没有的内容不编；材料缺背景或方法时，slots 里照样留这一页，evidence 写「材料不足，需要补充」。
7. sections 每一项写 no、title、role、question。role 用规则里的英文角色名，例如 background、question、method、hook、concept。
8. slots 每一项写 no、kind、message、evidence。kind 只能是 cover、toc、section、content、summary、end。章节页和内容页再写 section（第几章）和 role。
{template_story}
输出结构：{"deck_type","central_question","answer","sections":[...],"slots":[...]}
"""

ROLE_SEQUENCE = {
    "research_talk": ["background", "question", "method", "finding", "discussion"],
    "defense": ["background", "question", "literature", "method", "finding", "conclusion"],
    "proposal": ["background", "significance", "literature", "question", "method", "schedule"],
    "paper_report": ["question", "method", "finding", "discussion", "takeaway"],
    "lecture": ["hook", "concept", "principle", "example", "misconception", "recommendation"],
    "review": ["background", "literature", "comparison", "discussion", "outlook"],
    "survey_report": ["background", "method", "finding", "discussion", "recommendation"],
}
_KIND_ALIAS = {
    "cover": "cover", "封面": "cover",
    "toc": "toc", "目录": "toc",
    "section": "section", "章节": "section", "章节页": "section",
    "content": "content", "内容": "content", "内容页": "content",
    "summary": "summary", "总结": "summary", "总结页": "summary", "小结": "summary",
    "end": "end", "结尾": "end", "结尾页": "end",
}


def section_titles(deck_type: str) -> list[str]:
    return list(SECTION_TITLES.get(deck_type) or SECTION_TITLES["research_talk"])


def structure_line(story: dict) -> str:
    """计划卡片上的一行：研究汇报（背景 → 问题 → 方法）。"""
    sections = [s for s in (story or {}).get("sections") or [] if isinstance(s, dict)]
    if not sections:
        return ""
    kind = DECK_NAMES.get(str((story or {}).get("deck_type") or ""), "汇报")
    chain = " → ".join(
        ROLE_SHORT.get(str(s.get("role") or ""), str(s.get("title") or "内容"))
        for s in sections)
    return f"{kind}（{chain}）"


def pages_from_text(text: str) -> int:
    """从「做成 12 页」「12 页左右」里取出页数。没写就返回 0。"""
    raw = text or ""
    found = re.search(r"(?:做成|压到|控制在|大约|大概)\s*(\d+)\s*页", raw)
    if not found:
        found = re.search(r"(\d+)\s*页左右", raw)
    if not found:
        return 0
    count = int(found.group(1))
    return count if 4 <= count <= 40 else 0


def _match_keywords(text: str) -> str:
    folded = (text or "").casefold()
    if not folded.strip():
        return ""
    for deck_type, words in _KEYWORDS:
        if any(word.casefold() in folded for word in words):
            return deck_type
    return ""


def _method_and_result(text: str) -> bool:
    heads = "\n".join(_HEADING.findall(text or ""))
    return ("方法" in heads) and ("结果" in heads or "发现" in heads)


def detect_deck_type(user_text: str, material: str, deck_hint: str = "") -> str:
    """用户原话优先，其次模板提示，再看材料里的方法/结果小标题。"""
    user = user_text or ""
    explicit = re.search(r"按(.{0,12}?)的结构", user)
    if explicit:
        chunk = explicit.group(1)
        for phrase, deck_type in _BY_STRUCTURE:
            if phrase in chunk:
                return deck_type
    if re.search(r"当成.{0,8}(?:课|讲解|课件)", user):
        return "lecture"
    hit = _match_keywords(user)
    if hit:
        return hit
    hint = (deck_hint or "").strip()
    if hint in _KNOWN:
        return hint
    body = material or ""
    if _method_and_result(body):
        return "research_talk"
    if len(body.strip()) <= 120:
        hit = _match_keywords(body)
        if hit:
            return hit
    return "lecture"


def budget_for(pages: int) -> dict:
    """页数分配。section 是 (最少, 最多)；内容页下限按总页数的六成。"""
    count = max(1, int(pages or 12))
    if count <= 8:
        toc, section = 0, (0, 0)
    elif count <= 11:
        toc, section = 1, (0, 0)
    elif count <= 14:
        toc, section = 1, (2, 3)
    elif count <= 18:
        toc, section = 1, (3, 4)
    else:
        toc, section = 1, (4, 5)
    content_min = max(1, (count * 6 + 9) // 10)  # 向上取六成
    return {"cover": 1, "toc": toc, "section": section, "content_min": content_min, "end": 1}


def _slot_kind(slot: dict) -> str:
    raw = str(slot.get("kind") or slot.get("type") or "").strip()
    return _KIND_ALIAS.get(raw) or _KIND_ALIAS.get(raw.casefold()) or ""


def _section_role(sec: dict, index: int, deck_type: str, title: str) -> str:
    role = str(sec.get("role") or "").strip()
    if role:
        return role
    titles = SECTION_TITLES.get(deck_type) or []
    roles = ROLE_SEQUENCE.get(deck_type) or ROLE_SEQUENCE["research_talk"]
    if title in titles:
        return roles[titles.index(title)]
    if index - 1 < len(roles):
        return roles[index - 1]
    return "finding"


def _clean_content(slot: dict, role: str) -> dict:
    out = {
        "kind": "content",
        "role": str(slot.get("role") or role or "finding"),
        "message": str(slot.get("message") or ""),
        "evidence": str(slot.get("evidence") or ""),
    }
    if slot.get("form_hint"):
        out["form_hint"] = str(slot["form_hint"])
    if slot.get("bridge"):
        out["bridge"] = str(slot["bridge"])
    if slot.get("items") is not None:
        try:
            out["items"] = int(slot["items"])
        except (TypeError, ValueError):
            pass
    return out


def _blank_chapter() -> dict:
    return {"title": "正文", "role": "finding", "question": "", "contents": []}


def _merge_chapters(kept: dict, dropped: dict, *, dropped_first: bool = False) -> dict:
    """留下那一章的名字。被并掉的那章，问题写进它原来第一张内容页的承接。"""
    kept_pages = list(kept.get("contents") or [])
    dropped_pages = list(dropped.get("contents") or [])
    question = str(dropped.get("question") or "").strip()
    if dropped_pages and question:
        first = dict(dropped_pages[0])
        bridge = str(first.get("bridge") or "").strip()
        if question not in bridge:
            first["bridge"] = f"{question} {bridge}".strip() if bridge else question
        dropped_pages[0] = first
    contents = (dropped_pages + kept_pages) if dropped_first else (kept_pages + dropped_pages)
    return {
        "title": kept.get("title") or dropped.get("title") or "",
        "role": kept.get("role") or dropped.get("role") or "",
        "question": kept.get("question") or dropped.get("question") or "",
        "contents": contents,
    }


def _parse_chapters(story: dict) -> tuple[list[dict], dict | None]:
    slots = [s for s in (story.get("slots") or []) if isinstance(s, dict)]
    sections_in = [s for s in (story.get("sections") or []) if isinstance(s, dict)]
    deck_type = str(story.get("deck_type") or "research_talk")
    chapters: list[dict] = []
    by_no: dict[int, dict] = {}
    for index, sec in enumerate(sections_in, 1):
        try:
            no = int(sec.get("no") or index)
        except (TypeError, ValueError):
            no = index
        title = str(sec.get("title") or sec.get("name") or f"第{index}部分").strip() or f"第{index}部分"
        chapter = {
            "title": title,
            "role": _section_role(sec, index, deck_type, title),
            "question": str(sec.get("question") or "").strip(),
            "contents": [],
        }
        chapters.append(chapter)
        by_no[no] = chapter
    summary = None
    pending: list[dict] = []
    current = None
    opened = 0
    for slot in slots:
        kind = _slot_kind(slot)
        if kind == "summary":
            summary = slot
            continue
        if kind == "section":
            title = str(slot.get("message") or slot.get("title") or slot.get("name") or "").strip()
            match = next((i for i, ch in enumerate(chapters) if title and ch["title"] == title), None)
            if match is None and opened < len(chapters):
                match = opened
            if match is None:
                try:
                    no = int(slot.get("section") or 0)
                except (TypeError, ValueError):
                    no = 0
                current = {
                    "title": title or f"第{len(chapters) + 1}部分",
                    "role": str(slot.get("role") or "finding"),
                    "question": "",
                    "contents": [],
                }
                chapters.append(current)
                if no:
                    by_no[no] = current
                opened = len(chapters)
            else:
                current = chapters[match]
                opened = match + 1
            continue
        if kind != "content":
            continue
        try:
            no = int(slot.get("section") or slot.get("section_no") or 0)
        except (TypeError, ValueError):
            no = 0
        target = by_no.get(no) if no else current
        if target is None:
            pending.append(slot)
            continue
        target["contents"].append(_clean_content(slot, target["role"]))
    if pending:
        if not chapters:
            chapters.append(_blank_chapter())
        for slot in pending:
            chapters[-1]["contents"].append(_clean_content(slot, chapters[-1]["role"]))
    return chapters, summary


def _absorb_thin(chapters: list[dict]) -> None:
    """内容页不足 2 的章节并进前一章。第一章没有前一章时，并进后一章。"""
    guard = 0
    while len(chapters) > 1 and guard < 24:
        guard += 1
        thin = next((i for i, ch in enumerate(chapters) if len(ch["contents"]) < 2), None)
        if thin is None:
            return
        if thin > 0:
            chapters[thin - 1] = _merge_chapters(chapters[thin - 1], chapters[thin])
            chapters.pop(thin)
        else:
            chapters[1] = _merge_chapters(chapters[1], chapters[0], dropped_first=True)
            chapters.pop(0)


def _page_count(chapters: list[dict], toc: bool, emit_sections: bool) -> int:
    content = sum(len(ch["contents"]) for ch in chapters)
    sections = len(chapters) if emit_sections and chapters else 0
    return 1 + (1 if toc else 0) + sections + content + 1 + 1


_OPEN_ROLES = {"background", "hook", "concept"}
_OPENING_TYPES = {"research_talk", "paper_report"}


def _ensure_opening(chapters: list[dict], deck_type: str, fallback: str) -> None:
    """研究汇报和论文汇报：第一章第一张内容页改成背景，页数保持不变。"""
    if deck_type not in _OPENING_TYPES or not chapters:
        return
    contents = chapters[0].get("contents") or []
    if not contents or str(contents[0].get("role") or "") in _OPEN_ROLES:
        return
    if len(contents) == 1:
        contents[0]["role"] = "background"
        return
    question = str(chapters[0].get("question") or "").strip()
    contents.insert(0, {
        "kind": "content",
        "role": "background",
        "message": question or fallback or "先交代这件事的背景",
        "evidence": "",
    })
    contents.pop()


def _drop_one(chapter: dict) -> None:
    contents = chapter["contents"]
    index = min(
        range(len(contents)),
        key=lambda i: (len(str(contents[i].get("evidence") or "")), -i),
    )
    contents.pop(index)


def _add_one(chapter: dict) -> None:
    evidences = [str(item.get("evidence") or "") for item in chapter["contents"]]
    longest = max(evidences, key=len) if evidences else ""
    chapter["contents"].append({
        "kind": "content",
        "role": chapter["role"] or "finding",
        "message": ("补充：" + chapter["title"])[:40],
        "evidence": longest or "材料不足，需要补充",
        "form_hint": "bullets",
        "bridge": "承接",
        "items": 0,
    })


def _richest(chapters: list[dict]) -> int:
    def score(index: int) -> tuple:
        total = sum(len(str(item.get("evidence") or "")) for item in chapters[index]["contents"])
        return (total, -index)
    return max(range(len(chapters)), key=score)


def normalize_storyline(story: dict, pages: int, allow_toc: bool = True) -> dict:
    """把模型给的骨架收成固定形状。同一份输入每次结果相同。"""
    count = max(1, int(pages or 12))
    budget = budget_for(count)
    source = story or {}
    chapters, summary = _parse_chapters(source)
    _sec_min, sec_max = budget["section"]
    emit_sections = sec_max > 0
    while emit_sections and len(chapters) > sec_max:
        chapters[-2] = _merge_chapters(chapters[-2], chapters[-1])
        chapters.pop()
    _absorb_thin(chapters)
    answer = str(source.get("answer") or "").strip()
    summary_message = ""
    if isinstance(summary, dict):
        summary_message = str(summary.get("message") or "").strip()
    if not summary_message:
        summary_message = answer or "总结"
    use_toc = bool(allow_toc) and count >= 9
    low, high = count - 1, count + 1
    content_min = budget["content_min"]
    for _ in range(48):
        total = _page_count(chapters, use_toc, emit_sections)
        # 总结页算内容页。页数在范围内但内容页不够六成时，不能停。
        content_n = sum(len(ch["contents"]) for ch in chapters) + 1
        if low <= total <= high and content_n >= content_min:
            break
        over_pages = total > high
        short = content_n < content_min
        need = content_min - content_n
        if over_pages or (short and total + need > high):
            if not chapters:
                break
            if emit_sections and len(chapters) > max(_sec_min, 1):
                chapters[-2] = _merge_chapters(chapters[-2], chapters[-1])
                chapters.pop()
                continue
            fat = max(range(len(chapters)), key=lambda i: (len(chapters[i]["contents"]), -i))
            if len(chapters[fat]["contents"]) > 2 or (over_pages and chapters[fat]["contents"]):
                _drop_one(chapters[fat])
                chapters[:] = [ch for ch in chapters if ch["contents"]] or chapters
                continue
            break
        if total >= high:
            break
        if not chapters:
            chapters.append(_blank_chapter())
        _add_one(chapters[_richest(chapters)])
    _ensure_opening(
        chapters,
        str(source.get("deck_type") or "research_talk"),
        str(source.get("central_question") or "").strip(),
    )
    sections_out = []
    slots: list[dict] = [{"kind": "cover"}]
    if use_toc:
        slots.append({"kind": "toc"})
    for index, chapter in enumerate(chapters, 1):
        sections_out.append({
            "no": index,
            "title": chapter["title"],
            "role": chapter["role"],
            "question": chapter["question"],
            "pages": len(chapter["contents"]),
        })
        if emit_sections:
            slots.append({"kind": "section", "section": index})
        for content in chapter["contents"]:
            item = dict(content)
            item["section"] = index
            slots.append(item)
    slots.append({"kind": "summary", "role": "conclusion", "message": summary_message})
    slots.append({"kind": "end"})
    for index, slot in enumerate(slots, 1):
        slot["no"] = index
    return {
        "skill_version": int(source.get("skill_version") or skill_version() or 1),
        "deck_type": str(source.get("deck_type") or "research_talk"),
        "central_question": str(source.get("central_question") or ""),
        "answer": answer,
        "sections": sections_out,
        "slots": slots,
    }


def storyline_system(deck_type: str, pages: int, template_story: list | None) -> str:
    line = ""
    if template_story:
        names = " → ".join(str(item) for item in template_story if str(item).strip())
        if names:
            line = f"这套模板原来的讲法是：{names}。章节顺序和规则一致时可以沿用它的章节名。"
    return (STORYLINE_SYSTEM
            .replace("{skill}", load_skill(deck_type))
            .replace("{deck_type}", deck_type or "research_talk")
            .replace("{pages}", str(pages))
            .replace("{template_story}", line))


async def make_storyline(material: str, user_text: str, pages: int, deck_type: str,
                         template_story: list | None, model: str, user_id: str,
                         allow_toc: bool = True) -> tuple[dict | None, str]:
    """让模型先排讲法，再收成固定骨架。失败时返回 (None, 原因)，调用方退回旧流程。"""
    from services.ppt.ppt_plan import _ask_text
    from services.ppt.pptx_outline import _extract_json

    wanted = deck_type or "research_talk"
    count = max(1, int(pages or 12))
    system = storyline_system(wanted, count, template_story)
    prompt = f"用户原话：{user_text or ''}\n\n材料：\n{material or ''}"
    text, _name, err = await _ask_text(user_id, system, prompt, model or "", max_tokens=4000)
    if err or not (text or "").strip():
        return None, err or "叙事骨架没有返回"
    data = _extract_json(text)
    if not isinstance(data, dict) or not (data.get("slots") or data.get("sections")):
        return None, "叙事骨架不是可用的 JSON"
    data["deck_type"] = wanted
    data["skill_version"] = skill_version()
    try:
        return normalize_storyline(data, count, allow_toc=allow_toc), ""
    except Exception as exc:
        return None, f"叙事骨架整理失败：{exc}"
