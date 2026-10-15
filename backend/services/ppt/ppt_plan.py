"""读材料 → 出计划：把长材料整理成提料，让模型按版式清单出一份逐页计划。

模型只决定"写什么内容、用哪种版式"；字数上限、条数范围、截字兜底都在本地做，
上限表来自 `ppt_layouts.LAYOUT_SPECS`，和出片用的是同一份。
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re

from services.ppt import ppt_layouts

logger = logging.getLogger(__name__)

DIGEST_LIMIT = 14000        # 送给模型的材料上限
SECTION_HEAD = 600          # 每节至少保留的开头字数
KEY_SECTION_RATIO = 1.5     # 摘要、引言、结论多给的倍数
PLAN_MAX_TOKENS = 6000
_CALL_DEADLINE = 300
CONTENT_LAYOUTS = tuple(k for k in ppt_layouts.LAYOUT_SPECS
                        if k not in ppt_layouts.PLAIN_LAYOUTS)

PLAN_SYSTEM = """你是学术汇报的 PPT 策划。读完材料，按下面的版式清单做一份逐页计划，只输出 JSON。
规则：
1. 默认 10–16 页；用户给了页数就按页数。第一页 cover，第二页 toc，最后一页 end。
2. 每一章前放一张 section；toc 的项和 section 一一对应。
3. 每张内容页只讲一件事，标题写成一句结论，不超过 20 字。
4. 按内容挑版式：有年份或阶段用 timeline；有前后、正反用 compare；2–4 个并列点用 cards；
   结论和建议用 numbered；原文里有分量的一句话用 quote；有关键数字用 bignum；其余用 bullets。
5. 同一种版式不要连续超过 2 页。
6. 每个字段都不能超过版式清单里的字数上限。每个字段尽量写满上限的七到九成；写不满说明内容不够具体，回去材料里找例子、数据或对比。
7. 有材料时只用材料里的事实；材料是内容稿时，标了（需核实）的内容照写，并在讲稿里保留（需核实）。材料没给数字就不要用 bignum。
8. 每张内容页至少有一处具体内容：一个例子、一个数据、一个对比、一个步骤或一句原文。没有就别做这一页。
9. 每张内容页写 notes（120–200 字讲稿，口语，按「这页讲什么、为什么、举个例子、过渡到下一页」）和 from（来自原文哪一节）。
10. 不要用这些套话：{banned}。
11. 全部用简体中文书写，原文是繁体也转成简体。
12. 同一页，坏的写法是「主动思考比被动接收更有效」；好的写法是「合上书复述一遍，比再读三遍记得牢，例如合上教材用自己的话讲给同桌听」。
13. 输出结构：顶层是 {"title": "汇报标题", "subtitle": "副标题", "slides": [...]}；
   每张幻灯片用 layout 字段指定版式，取值就是下面清单里的版式名，其余字段名照清单写。
版式清单：
{specs}
"""

SHORTEN_SYSTEM = """你在改一份 PPT 计划。只把超出字数上限的字段改短：意思不变、尽量保留原来的说法、
不要新增事实；其它字段一个字都不要动。只输出完整的 JSON。
"""

DRAFT_SYSTEM = """你在为一份学术汇报写内容稿，后面会按这份稿做成 PPT。只输出 Markdown，用简体中文。
先写一个一级标题。下面按这个顺序写二级标题，标题用这些名字，不要改名，不要增删节：
{sections}
每节 2 到 4 个要点。
每个要点单独成行，用「- 」开头，写成「判断 + 依据或例子」。
常识可以写。具体数字、年份、人名、引文后面必须紧跟（需核实）。
不要用这些套话：{banned}。
总长 2000 到 3500 字。写不满 2000 字就继续补例子，不要提前收束。不要写页码，不要输出 JSON。
"""

# 短于这么多字就先写内容稿。够长的材料（论文、文件夹文稿）直接出计划。
DRAFT_THRESHOLD = 800

ENRICH_SYSTEM = """你在充实一份 PPT 计划里偏薄的页。只改点名的那几页，每个字段写到字数上限的七到九成，不要超过上限。
每页至少有一处具体内容：例子、数据、对比、步骤或原文。讲稿 notes 用口语写 120 到 200 字，
顺序是：这页讲什么、为什么、举个例子、过渡到下一页。
不要用这些套话：{banned}。
其它页一个字都不要动，不要增删页。只用材料里有的事实，不要编造数字和引文。
材料里标了（需核实）的内容照写，并在讲稿里保留（需核实）。
只输出完整 JSON，顶层是 {"title": "标题", "subtitle": "副标题", "slides": [...]}。
"""

WRITE_SYSTEM = """你在按叙事骨架写 PPT 的每一页。每页已经选好了模板页，只能往给定的格子里写字，只输出 JSON。
规则：
1. 每页的意思以骨架里的 message 为准，title 写成一句判断，意思和 message 一致。
2. lead 写这一页和上一页的关系（承接、递进、转折、举例、因果、回扣），按骨架里的 bridge，不重复标题。没有 lead 格子时，把这句话写成 notes 的第一句，第一句要点出上一页讲了什么，不要只写「这一页收束」。
3. 每个格子不能超过给定字数，尽量写到七到九成；必填的格子不能空。
4. 并列格子之间要真的并列：同一个层级、同一种说法，小标题用名词短语。
5. 只用材料里的事实；材料是内容稿时，（需核实）照写并在 notes 里保留。骨架 evidence 写了「材料不足」时，notes 里保留「（需核实）」，不要写成已有出处。
6. notes 写 120–200 字口语讲稿：第一句承接上一页，中间讲证据，最后一句引出下一页。
7. 不要用这些套话：{banned}。
输出：{"pages": [{"no": 5, "slots": {"格子名": "文字"}, "lead": "这一页怎么接上一页", "notes": "……", "from": "材料第几节"}]}
"""

REVISE_SYSTEM = """你在改一份 PPT 计划。按用户的要求修改，返回**完整**的新计划 JSON。
没被要求改的地方原样保留；改完仍然要满足版式清单里的字数上限和条数范围。
版式清单：
{specs}
"""

# 章节标题：`#`、`一、`、`（一）`、`第X章`、`1.`、`1.1`
HEAD_PATTERNS = [
    re.compile(r"^#{1,4}\s+\S"),
    re.compile(r"^[一二三四五六七八九十]{1,3}[、.．]\s*\S"),
    re.compile(r"^（[一二三四五六七八九十]{1,3}）"),
    re.compile(r"^第\s*[0-9一二三四五六七八九十百]{1,4}\s*[章节部分]"),
    re.compile(r"^\d{1,2}(\.\d{1,2})*[、.．]?\s+\S"),
    re.compile(r"^\d{1,2}\.\d{1,2}\s*\S"),
]
KEY_SENTENCE_RE = re.compile(
    r"\d{4}\s*年|百分之|%|「|『|“|”|因此|总之|本文认为|本文以为|结论|可见|说明|表明")
KEY_SECTION_RE = re.compile(r"摘要|引言|导论|绪论|结论|结语|余论|总结")
RESERVED_FIELDS = {"layout", "notes", "from"}
# 封面、目录、章节、结尾不参与「偏薄」打分，它们本来就只有标题。
_STRUCTURAL = {"cover", "toc", "section", "end"}
# 出现在屏幕文字或讲稿里就算这条偏薄。提示词和自检共用这一张表。
BANNED_PHRASES = (
    "提升效率", "非常重要", "具有重要意义", "不断提高",
    "多方面", "有效提升", "综合运用", "全面", "持续优化",
)
_CONCRETE_RE = re.compile(r"\d|[「『“”\"」』']|例如|比如|对比|相比|比起|不同于")
_ENRICH_LIMIT = 5


# ───────────── 版式清单（给提示词用，和上限表同源） ─────────────

def _field_text(field: dict) -> str:
    key = field["key"]
    limit = field.get("limit")
    if field.get("item"):
        inner = "、".join(_field_text(sub) for sub in field["item"])
        return f"{key} {field['min']}–{field['max']} 项（每项 {inner}）"
    if field.get("group"):
        inner = "、".join(_field_text(sub) for sub in field["group"])
        return f"{key}（{inner}）"
    if limit is None:
        return key
    cap = f"≤{limit} 字"
    if field.get("optional"):
        cap += "，可空"
    if "min" in field and "max" in field:
        return f"{key} {field['min']}–{field['max']} 条，每条 {cap}"
    return f"{key} {cap}"


def spec_text() -> str:
    """版式清单文本，直接从 LAYOUT_SPECS 生成，改上限不用改提示词。"""
    lines = []
    for key, spec in ppt_layouts.LAYOUT_SPECS.items():
        fields = "；".join(_field_text(f) for f in spec["fields"])
        lines.append(f"- {key}（{spec['name']}，{spec['use']}）：{fields}")
    return "\n".join(lines)


def build_plan_prompt(material: str, guidance: str = "", pages: int = 0) -> str:
    parts = []
    if pages:
        parts.append(f"页数要求：做成 {pages} 页左右。")
    if guidance:
        parts.append(f"用户补充要求：{guidance}")
    parts.append("材料：\n" + (material or ""))
    return "\n\n".join(parts)


_PLAN_RULES = (
    "1. 默认 10–16 页；用户给了页数就按页数。第一页 cover，第二页 toc，最后一页 end。\n"
    "2. 每一章前放一张 section；toc 的项和 section 一一对应。"
)
_PLAN_RULES_STORY = (
    "1. 按叙事骨架逐页写。页数、顺序、每页的 message 不能改。标题用 message 的意思写成 20 字以内。\n"
    "2. 骨架里 kind 为 cover、toc、section、summary、end 的各写一页；内容页的标题就是该页 message。section 与骨架章节一一对应。"
)


def plan_system(storyline: dict | None = None) -> str:
    # 用 replace 不用 format：提示词里有 JSON 示例的花括号，format 会当成占位符
    text = PLAN_SYSTEM
    if storyline and storyline.get("slots"):
        text = text.replace(_PLAN_RULES, _PLAN_RULES_STORY)
    return (text
            .replace("{specs}", spec_text())
            .replace("{banned}", "、".join(BANNED_PHRASES)))


def revise_system() -> str:
    return REVISE_SYSTEM.replace("{specs}", spec_text())


# ───────────── 3.1 整理材料 ─────────────

def _is_heading(line: str) -> bool:
    raw = line.strip()
    if not raw or len(raw) > 40:
        return False
    return any(pattern.match(raw) for pattern in HEAD_PATTERNS)


def split_sections(text: str) -> list[tuple[str, str]]:
    """按标题切节，返回 [(标题, 正文)]；开头没有标题的一段标题为空串。"""
    sections: list[tuple[str, list[str]]] = []
    title = ""
    buf: list[str] = []
    for line in (text or "").splitlines():
        if _is_heading(line):
            if title or any(x.strip() for x in buf):
                sections.append((title, buf))
            title = line.strip()
            buf = []
        else:
            buf.append(line)
    if title or any(x.strip() for x in buf):
        sections.append((title, buf))
    return [(t, "\n".join(b).strip()) for t, b in sections]


def _key_sentences(body: str) -> str:
    """挑出带年份、百分比、数字、引号和结论词的句子。"""
    picked = []
    for sentence in re.split(r"(?<=[。！？；])", body or ""):
        text = sentence.strip()
        if text and KEY_SENTENCE_RE.search(text):
            picked.append(text)
    return "\n".join(picked)


def _shrink_section(title: str, body: str, quota: int) -> str:
    """一节压到 quota 字以内：标题 + 开头若干字 + 关键句。"""
    head = (body or "")[:SECTION_HEAD]
    head_part = f"{title}\n{head}".strip() if title else head
    if len(head_part) >= quota:
        return head_part[:quota]
    rest = [s for s in _key_sentences(body).splitlines()
            if s and s not in head_part]
    out = head_part
    for sentence in rest:
        if len(out) + len(sentence) + 1 > quota:
            break
        out = f"{out}\n{sentence}"
    return out


def digest_material(text: str, limit: int = DIGEST_LIMIT) -> str:
    """把长材料压到 limit 字以内；材料本身就短就原样返回。

    替代"只截头尾"的老做法：按节平均分配字数，摘要/引言/结论多给一半，
    每节都保留标题，节里补上带数字和结论的句子。
    """
    raw = (text or "").strip()
    if not raw or len(raw) <= limit:
        return raw
    sections = split_sections(raw)
    if not sections:
        return raw[:limit]

    weights = [KEY_SECTION_RATIO if KEY_SECTION_RE.search(t) else 1.0
               for t, _ in sections]
    total = sum(weights) or 1.0
    chunks = []
    for (title, body), weight in zip(sections, weights):
        quota = max(200, int(limit * weight / total))
        chunks.append(_shrink_section(title, body, quota))
    digest = "\n\n".join(c for c in chunks if c)
    return digest[:limit]


# ───────────── 3.4 校验与改短 ─────────────

def _page_has_text(slide: dict) -> bool:
    if slide.get("template_page"):
        return True
    if str(slide.get("title") or "").strip() or str(slide.get("notes") or "").strip():
        return True
    slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else {}
    if any(str(value or "").strip() for value in slots.values()):
        return True
    points = slide.get("points") if isinstance(slide.get("points"), list) else []
    return any(str(item or "").strip() for item in points)


def _fold_page_into_notes(slides: list, extra: dict) -> None:
    """多出来的一页不单留。有字就写进前面最近一张内容页的讲稿。"""
    text = "\n".join(part for part in (
        str(extra.get("title") or "").strip(),
        str(extra.get("notes") or "").strip(),
    ) if part)
    if not text:
        return
    host = len(slides) - 1
    while host >= 0 and str(slides[host].get("layout") or "") in {"cover", "toc", "section", "end"}:
        host -= 1
    if host < 0:
        return
    notes = str(slides[host].get("notes") or "").strip()
    if text not in notes:
        slides[host]["notes"] = (notes + "\n" + text).strip()


def _fit_story_pages(slides: list, storyline: dict | None) -> list:
    """模型比骨架多给的页：空页丢掉，有字的并进前一张内容页。结尾只留一张。"""
    slots = [slot for slot in ((storyline or {}).get("slots") or []) if isinstance(slot, dict)]
    if not slots:
        return slides
    while len(slides) > len(slots) and not _page_has_text(slides[-1]):
        slides.pop()
    while len(slides) > len(slots):
        _fold_page_into_notes(slides, slides.pop())
    ends = [index for index, slide in enumerate(slides) if slide.get("layout") == "end" or slide.get("role") == "end"]
    if len(ends) > 1:
        filled = [index for index in ends if _page_has_text(slides[index])]
        keep = filled[-1] if filled else ends[-1]
        for index in reversed(ends):
            if index == keep or index >= len(slides):
                continue
            extra = slides.pop(index)
            if _page_has_text(extra):
                _fold_page_into_notes(slides, extra)
    return slides


def normalize(plan: dict) -> dict:
    """首页改成封面、末页改成结尾、未知版式改要点、数组条数夹到范围内。"""
    out = copy.deepcopy(plan or {})
    slides = out.get("slides")
    if not isinstance(slides, list):
        slides = []
    slides = [s for s in slides if isinstance(s, dict)]
    slides = _fit_story_pages(slides, out.get("storyline") if isinstance(out.get("storyline"), dict) else None)
    if not slides:
        out["slides"] = []
        return out
    if len(slides) == 1:
        slides[0]["layout"] = "cover"
    else:
        slides[0]["layout"] = "cover"
        slides[-1]["layout"] = "end"
    for index, slide in enumerate(slides):
        if index in (0, len(slides) - 1):
            continue
        layout = slide.get("layout")
        if layout in ppt_layouts.PLAIN_LAYOUTS:
            continue
        if layout not in ppt_layouts.LAYOUT_SPECS:
            slide["layout"] = _to_bullets(slide)
        _clamp(slide)
    _sync_toc(slides)
    out["slides"] = slides
    return out


def _sync_toc(slides: list) -> None:
    """目录项和章节页对不上时，按章节页标题重建目录。"""
    sections = [slide for slide in slides if slide.get("layout") == "section"]
    if not sections:
        return
    for slide in slides:
        if slide.get("layout") != "toc":
            continue
        items = slide.get("items") if isinstance(slide.get("items"), list) else []
        if len(items) == len(sections):
            continue
        rebuilt = []
        for section in sections:
            subs = section.get("subs") if isinstance(section.get("subs"), list) else []
            rebuilt.append({
                "label": str(section.get("title") or ""),
                "desc": str(subs[0]) if subs else "",
            })
        slide["items"] = rebuilt


def _to_bullets(slide: dict) -> str:
    """模型给了不认识的版式：尽量把已有内容挪成要点，挪不动就当空要点页。"""
    if not slide.get("points"):
        collected = []
        for card in slide.get("cards") or []:
            if isinstance(card, dict):
                text = "：".join(x for x in (card.get("key"), card.get("desc")) if x)
                collected.append(text)
        for row in slide.get("rows") or []:
            if isinstance(row, dict):
                text = "：".join(x for x in (row.get("head"), row.get("desc")) if x)
                collected.append(text)
        for node in slide.get("nodes") or []:
            if isinstance(node, dict):
                text = " ".join(x for x in (node.get("year"), node.get("head")) if x)
                collected.append(text)
        if slide.get("quote"):
            collected.append(str(slide["quote"]))
        slide["points"] = collected[:5]
    return "bullets"


def _clamp(slide: dict) -> None:
    """数组条数夹到 [min, max]；顺带删掉空元素的尾巴。"""
    spec = ppt_layouts.LAYOUT_SPECS.get(slide.get("layout") or "")
    if not spec:
        return
    for field in spec["fields"]:
        key = field["key"]
        if "min" not in field or "max" not in field:
            continue
        value = slide.get(key)
        if not isinstance(value, list):
            continue
        low, high = int(field["min"]), int(field["max"])
        trimmed = value[:high]
        slide[key] = trimmed if len(trimmed) >= low else value[:max(low, 0)]


def validate_plan(plan: dict) -> list[dict]:
    """逐页校验，返回带页号的 [{"slide", "field", "text", "limit"}]。"""
    issues: list[dict] = []
    for index, slide in enumerate((plan or {}).get("slides") or [], 1):
        if not isinstance(slide, dict):
            continue
        for issue in ppt_layouts.check_slide(slide):
            issues.append({"slide": index, **issue})
    slides = [s for s in ((plan or {}).get("slides") or []) if isinstance(s, dict)]
    toc_index = next((i for i, s in enumerate(slides, 1) if s.get("layout") == "toc"), 0)
    if toc_index:
        items = slides[toc_index - 1].get("items") if isinstance(slides[toc_index - 1].get("items"), list) else []
        sections = [s for s in slides if s.get("layout") == "section"]
        if sections and len(items) != len(sections):
            issues.append({
                "slide": toc_index, "field": "toc", "text": "", "limit": 0,
                "detail": f"目录 {len(items)} 项，章节页 {len(sections)} 张",
            })
    return issues


def hard_trim(plan: dict, issues: list[dict]) -> dict:
    """兜底：把超限字段截到上限内最后一个标点，原文追加到该页 notes。"""
    out = copy.deepcopy(plan or {})
    slides = out.get("slides") or []
    for issue in issues or []:
        index = int(issue.get("slide") or 0) - 1
        limit = issue.get("limit")
        if index < 0 or index >= len(slides) or not isinstance(limit, int) or limit <= 0:
            continue
        slide = slides[index]
        if not isinstance(slide, dict):
            continue
        slot = ppt_layouts.field_slot(slide, issue.get("field") or "")
        if not slot:
            continue
        container, key = slot
        original = str(container[key])
        leaf = str(issue.get("field") or "").split(".")[-1].split("[")[0]
        trimmed = ppt_layouts.truncate(original, limit, ellipsis="" if leaf in {
            "key", "label", "head", "index", "year", "value"} else "…")
        if trimmed == original:
            continue
        container[key] = trimmed
        note = str(slide.get("notes") or "").strip()
        slide["notes"] = (note + f"（原句：{original}）").strip()
    out["slides"] = slides
    return out


# ───────────── 调模型 ─────────────

def _coerce_plan(data) -> dict:
    """模型偶尔把 slides 写成 pages、layout 写成 type，这里兜一下。

    实测 DeepSeek 第一次就写成 {"pages": [{"type": "cover", ...}]}——
    提示词里说明了结构还是会飘，容错比反复重问便宜。
    """
    if not isinstance(data, dict):
        return {}
    slides = data.get("slides")
    if not isinstance(slides, list):
        for key in ("pages", "slide_list", "slides_list"):
            if isinstance(data.get(key), list):
                slides = data[key]
                break
    if not isinstance(slides, list) or not slides:
        return {}
    cleaned = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        if not slide.get("layout"):
            slide["layout"] = slide.get("type") or slide.get("layout_name") or ""
        cleaned.append(slide)
    out = dict(data)
    out["slides"] = cleaned
    return out


def _retry_call(error: str) -> bool:
    text = error or ""
    return "没有连上" in text or "Connect" in text or "时限" in text


async def _read_stream(model, key, base, system, user, max_tokens, extra_body) -> tuple[str, str, str]:
    from services.idea_debate import _stream_complete

    answer_parts: list[str] = []
    thinking_parts: list[str] = []
    async for chunk in _stream_complete(model, key, base, system, user,
                                        max_tokens=max_tokens, marker_mode=False,
                                        extra_body=extra_body):
        kind = chunk.get("kind")
        if kind == "error":
            return "", "", chunk.get("delta") or "模型没有返回内容"
        if kind == "thinking":
            thinking_parts.append(chunk.get("delta") or "")
        else:
            answer_parts.append(chunk.get("delta") or "")
    return "".join(answer_parts), "".join(thinking_parts), ""


async def _read_stream_limited(model, key, base, system, user, max_tokens, extra_body) -> tuple[str, str, str]:
    """整次调用的总时限。服务端排队时只发保活行，读超时不会触发；实测排队可达 150 秒。"""
    try:
        return await asyncio.wait_for(
            _read_stream(model, key, base, system, user, max_tokens, extra_body),
            timeout=_CALL_DEADLINE,
        )
    except asyncio.TimeoutError:
        return "", "", "模型没有在时限内返回"


async def _ask_json(user_id: str, system: str, user: str, model_id: str = "",
                    max_tokens: int = PLAN_MAX_TOKENS, retries: int = 1):
    """问一次模型并解析 JSON，解析不出来就再问一次。返回 (数据, 模型名, 错误)。"""
    from services.ppt.pptx_outline import _extract_json, resolve_model

    entry, key, base, err = await resolve_model(user_id, model_id)
    if err:
        return {}, "", err
    model = {"id": entry["id"], "provider": entry["provider"], "name": entry["name"]}
    extra_body = {"thinking": {"type": "disabled"}} if entry["provider"] == "moonshot" else None

    last_error = "模型没有返回可解析的 JSON"
    for _ in range(retries + 1):
        answer, thinking, error = await _read_stream_limited(
            model, key, base, system, user, max_tokens, extra_body,
        )
        if error:
            last_error = error
            if _retry_call(error):
                continue
            return {}, entry["name"], error
        answer = answer.strip()
        combined = (thinking + "\n" + answer).strip()
        for source in (answer, combined):
            data = _coerce_plan(_extract_json(source)) if source else {}
            if data.get("slides"):
                return data, entry["name"], ""
        last_error = "模型返回的不是可用的计划 JSON"
    return {}, entry["name"], last_error


def needs_content_draft(material: str) -> bool:
    """材料太短，先写内容稿再出计划。"""
    return ppt_layouts.text_len(material or "") < DRAFT_THRESHOLD


def draft_title(text: str) -> str:
    """内容稿的一级标题，用来做文件名。"""
    for line in (text or "").splitlines():
        raw = line.strip()
        if raw.startswith("#") and not raw.startswith("##"):
            title = raw.lstrip("#").strip()
            if title:
                return title[:40]
    return ""


def _strip_fence(text: str) -> str:
    raw = (text or "").strip()
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


async def _ask_text(user_id: str, system: str, user: str, model_id: str = "",
                    max_tokens: int = 4000) -> tuple[str, str, str]:
    """问一次模型，要正文不要 JSON。连不上再试一次。返回 (正文, 模型名, 错误)。"""
    from services.ppt.pptx_outline import resolve_model

    entry, key, base, err = await resolve_model(user_id, model_id)
    if err:
        return "", "", err
    model = {"id": entry["id"], "provider": entry["provider"], "name": entry["name"]}
    extra_body = {"thinking": {"type": "disabled"}} if entry["provider"] == "moonshot" else None
    last_error = "模型没有返回正文"
    for _ in range(2):
        answer, _thinking, error = await _read_stream_limited(
            model, key, base, system, user, max_tokens, extra_body,
        )
        if error:
            last_error = error
            if _retry_call(error):
                continue
            return "", entry["name"], error
        answer = _strip_fence(answer)
        if answer:
            return answer, entry["name"], ""
        last_error = "模型没有返回正文"
    return "", entry["name"], last_error


async def write_content_draft(user_id: str, topic: str, model_id: str = "") -> tuple[str, str, str]:
    """按题目写一份内容稿。二级标题用这种汇报的段名。返回 (正文, 模型名, 错误)。"""
    from services.ppt import ppt_story

    deck = ppt_story.detect_deck_type(topic, topic)
    system = (DRAFT_SYSTEM
              .replace("{banned}", "、".join(BANNED_PHRASES))
              .replace("{sections}", "、".join(ppt_story.section_titles(deck))))
    prompt = "题目和已有材料：\n" + (topic or "").strip()
    return await _ask_text(user_id, system, prompt, model_id, max_tokens=4000)


async def shorten(plan: dict, issues: list[dict], model_id: str = "",
                  user_id: str = "") -> tuple[dict, str]:
    """只把超限字段和上限发给模型，要求意思不变、改到上限内。返回 (计划, 错误)。"""
    lines = []
    for issue in issues or []:
        lines.append(f"- 第 {issue.get('slide')} 页 {issue.get('field')}：上限 {issue.get('limit')}，"
                     f"现在 「{str(issue.get('text'))[:60]}」")
    prompt = ("下面这份计划里有字段超过字数上限：\n" + "\n".join(lines) +
              "\n\n只改这些字段，其它一个字都不要动。计划：\n" +
              json.dumps(plan, ensure_ascii=False))
    data, _, err = await _ask_json(user_id, SHORTEN_SYSTEM, prompt, model_id, max_tokens=4000)
    return (data if data else plan), err


# 用户说「第 6 页改成时间轴」时，模型经常把整份计划原样返回。
# 先按这句话定位页码和版式；模型没改到这一页，就用该页已有文字改过去。
_LAYOUT_WORDS = (
    ("时间轴", "timeline"), ("时间线", "timeline"),
    ("对比", "compare"), ("卡片", "cards"), ("金句", "quote"),
    ("要点", "bullets"), ("编号", "numbered"), ("大数字", "bignum"),
    ("图文", "image_text"), ("章节", "section"), ("目录", "toc"),
)
_PAGE_CHANGE_RE = re.compile(r"第\s*(\d+)\s*页")
_CHANGE_VERBS = ("改成", "换成", "变成", "做成")


def parse_layout_change(instruction: str) -> tuple[int, str] | None:
    """「第 6 页改成时间轴」→ (6, "timeline")。对不上就返回 None。"""
    text = instruction or ""
    found = _PAGE_CHANGE_RE.search(text)
    if not found or not any(verb in text for verb in _CHANGE_VERBS):
        return None
    for word, layout in _LAYOUT_WORDS:
        if word in text:
            return int(found.group(1)), layout
    return None


def _slide_texts(slide: dict) -> list[str]:
    texts: list[str] = []
    for key in ("title", "subtitle", "quote", "note", "takeaway"):
        if slide.get(key):
            texts.append(str(slide[key]))
    for key in ("points", "subs", "info"):
        texts.extend(str(item) for item in (slide.get(key) or []) if item)
    for key in ("cards", "rows", "nodes", "stats", "items"):
        for item in slide.get(key) or []:
            if isinstance(item, dict):
                texts.extend(str(v) for v in item.values() if isinstance(v, str) and v)
    for side in ("left", "right"):
        block = slide.get(side)
        if isinstance(block, dict):
            if block.get("head"):
                texts.append(str(block["head"]))
            texts.extend(str(p) for p in (block.get("points") or []) if p)
    return texts


def retarget_slide(slide: dict, layout: str) -> dict:
    """把一页已有文字改成目标版式。模型没改这一页时用。"""
    texts = _slide_texts(slide or {})
    title = str((slide or {}).get("title") or (texts[0] if texts else "这一页"))
    rest = [t for t in texts if t != title] or ["待补充"]
    out: dict = {
        "layout": layout,
        "title": title,
        "notes": (slide or {}).get("notes") or "",
        "from": (slide or {}).get("from") or "",
    }
    if layout == "timeline":
        rows = rest[:6]
        if len(rows) < 3 and title not in rows:
            rows = [title] + rows
        while len(rows) < 3:
            rows.append(f"阶段{len(rows) + 1}")
        out["nodes"] = [
            {"year": f"{i:02d}", "head": text[:6], "desc": text[:10]}
            for i, text in enumerate(rows, 1)
        ]
    elif layout == "compare":
        mid = max(1, len(rest) // 2)
        out["left"] = {"head": "一方面", "points": (rest[:mid] or ["待补充"])[:4]}
        out["right"] = {"head": "另一方面", "points": (rest[mid:] or ["待补充"])[:4]}
        for side in ("left", "right"):
            while len(out[side]["points"]) < 2:
                out[side]["points"].append("待补充")
    elif layout == "cards":
        cards = [{"key": text[:6], "desc": text[:28]} for text in rest[:4]]
        while len(cards) < 2:
            cards.append({"key": "补充", "desc": "待补充"})
        out["cards"] = cards
    elif layout == "bullets":
        points = rest[:5]
        while len(points) < 3:
            points.append("待补充")
        out["points"] = points
    elif layout == "numbered":
        rows = [{"head": text[:9], "desc": text[:30]} for text in rest[:4]]
        while len(rows) < 2:
            rows.append({"head": "补充", "desc": "待补充"})
        out["rows"] = rows
    elif layout == "quote":
        out["quote"] = rest[0][:40]
    elif layout == "bignum":
        out["stats"] = [
            {"value": "—", "label": text[:10], "desc": text[:24]}
            for text in rest[:3]
        ]
    elif layout == "image_text":
        points = rest[:4]
        while len(points) < 2:
            points.append("待补充")
        out["points"] = points
    elif layout == "section":
        out["index"] = str((slide or {}).get("index") or "01")[:2]
        out["title"] = title[:6]
        out["subs"] = rest[:3]
    else:
        return dict(slide or {})
    return out


def force_layout_change(plan: dict, instruction: str) -> dict:
    """用户指定了「第 N 页改成某版式」，而这一页还不是那个版式时，直接改。"""
    parsed = parse_layout_change(instruction)
    if not parsed:
        return plan
    page, layout = parsed
    slides = list((plan or {}).get("slides") or [])
    if not (1 <= page <= len(slides)):
        return plan
    if (slides[page - 1] or {}).get("layout") == layout:
        return plan
    slides[page - 1] = retarget_slide(slides[page - 1], layout)
    updated = dict(plan)
    updated["slides"] = slides
    return updated


def pin_other_pages(before: dict, after: dict, instruction: str) -> dict:
    """「第 N 页改成某版式」只替换这一页。

    模型常在这一页前面再插一页，后面的页全部后移，对比时就会从第 N 页一直变到最后一页。
    页数对不上时不用模型的结果，改用原来这一页的文字。
    """
    parsed = parse_layout_change(instruction)
    if not parsed:
        return after
    page, layout = parsed
    base = copy.deepcopy(before or {})
    slides = list(base.get("slides") or [])
    if not (1 <= page <= len(slides)):
        return after or base
    after_slides = list((after or {}).get("slides") or [])
    chosen = None
    if len(after_slides) == len(slides):
        candidate = after_slides[page - 1]
        if isinstance(candidate, dict) and candidate.get("layout") == layout:
            chosen = candidate
    if chosen is None:
        chosen = retarget_slide(slides[page - 1], layout)
    slides[page - 1] = chosen
    base["slides"] = slides
    return base


async def revise_plan(plan: dict, instruction: str, model_id: str = "",
                      user_id: str = "") -> tuple[dict, str]:
    """按用户一句话改计划，返回完整的新计划。"""
    ask = instruction
    parsed = parse_layout_change(instruction)
    if parsed:
        page, layout = parsed
        name = ppt_layouts.LAYOUT_SPECS[layout]["name"]
        ask = (f"只把第 {page} 页的 layout 改成 {layout}（{name}），"
               f"并按这个版式重写该页字段。其它页保持原样。用户原话：{instruction}")
    prompt = (f"用户的要求：{ask}\n\n当前计划：\n" +
              json.dumps(plan, ensure_ascii=False))
    data, _, err = await _ask_json(user_id, revise_system(), prompt, model_id)
    return (data if data else plan), err


def _screen_budget(layout: str) -> int:
    """这一版式屏幕上能写的字数上限合计。数组按最多条数算。"""
    spec = ppt_layouts.LAYOUT_SPECS.get(layout) or {}

    def walk(fields: list[dict]) -> int:
        total = 0
        for field in fields:
            if field.get("item"):
                total += walk(field["item"]) * int(field.get("max") or 1)
            elif field.get("group"):
                total += walk(field["group"])
            elif "limit" in field:
                count = int(field["max"]) if "max" in field else 1
                total += int(field["limit"]) * count
        return total

    return walk(spec.get("fields") or [])


def _screen_len(slide: dict) -> int:
    return sum(ppt_layouts.text_len(text) for text in _slide_texts(slide))


def _slot_budget(slide: dict) -> int:
    limits = slide.get("slot_limits") if isinstance(slide, dict) else None
    if not isinstance(limits, dict):
        return 0
    total = 0
    for value in limits.values():
        try:
            total += int(value)
        except (TypeError, ValueError):
            continue
    return total


def _slot_used(slide: dict) -> int:
    slots = slide.get("slots") if isinstance(slide, dict) else None
    if not isinstance(slots, dict):
        return 0
    return sum(ppt_layouts.text_len(value) for value in slots.values())


def thin_reasons(slide: dict) -> list[str]:
    """一页偏薄的原因。结构页（封面、目录、章节、结尾）不打分。"""
    if not isinstance(slide, dict) or slide.get("layout") in _STRUCTURAL:
        return []
    reasons = []
    slot_budget = _slot_budget(slide)
    if slot_budget:
        if _slot_used(slide) * 2 < slot_budget:
            reasons.append("short")
        blob = "".join(str(value) for value in (slide.get("slots") or {}).values()) + str(slide.get("notes") or "")
    else:
        budget = _screen_budget(str(slide.get("layout") or ""))
        if budget and _screen_len(slide) * 2 < budget:
            reasons.append("short")
        blob = "".join(_slide_texts(slide)) + str(slide.get("notes") or "")
    if any(phrase in blob for phrase in BANNED_PHRASES):
        reasons.append("banned")
    if ppt_layouts.text_len(slide.get("notes") or "") < 80:
        reasons.append("notes")
    screen = "".join(_slide_texts(slide))
    if isinstance(slide.get("slots"), dict):
        screen += "".join(str(value) for value in slide["slots"].values())
    if not _CONCRETE_RE.search(screen):
        reasons.append("plain")
    return reasons


def thin_page_numbers(plan: dict) -> list[int]:
    """满足任意两条偏薄原因的内容页，页码从 1 起。"""
    found = []
    for index, slide in enumerate((plan or {}).get("slides") or [], 1):
        if len(thin_reasons(slide)) >= 2:
            found.append(index)
    return found


def adopt_pages(before: dict, after: dict, pages: list[int]) -> dict | None:
    """只换上指定页。页数变了就返回 None，调用方继续用改之前的计划。"""
    old = [slide for slide in (before.get("slides") or []) if isinstance(slide, dict)]
    new = [slide for slide in (after.get("slides") or []) if isinstance(slide, dict)]
    if not old or len(old) != len(new):
        return None
    wanted = set(pages)
    out = copy.deepcopy(before)
    merged = []
    for index, (left, right) in enumerate(zip(old, new), 1):
        if index not in wanted or not isinstance(right, dict):
            merged.append(copy.deepcopy(left))
            continue
        slide = copy.deepcopy(right)
        for key in ("template_page", "template_form", "template_role", "pick_reason",
                    "pick_fallback", "pick_locked", "slot_limits", "role", "message", "locked_slots"):
            if key in left and key not in slide:
                slide[key] = copy.deepcopy(left[key])
        if isinstance(left.get("slots"), dict) and not isinstance(slide.get("slots"), dict):
            slide["slots"] = copy.deepcopy(left["slots"])
        if isinstance(slide.get("slots"), dict):
            project_legacy(slide)
        merged.append(slide)
    out["slides"] = merged
    return out


async def enrich_plan(plan: dict, pages: list[int], material: str, model_id: str = "",
                      user_id: str = "") -> tuple[dict, str]:
    """只充实点名的页。模型改了别的页或增删了页，那些改动丢掉。"""
    targets = list(pages)[:_ENRICH_LIMIT]
    if not targets:
        return plan, ""
    slides = plan.get("slides") or []
    slotted = [page for page in targets
               if 0 < page <= len(slides) and isinstance(slides[page - 1], dict)
               and isinstance(slides[page - 1].get("slots"), dict)]
    if slotted:
        system = ("你在充实 PPT 格子里的文字。只输出 JSON，顶层是 {\"pages\": [{\"no\": 1, \"slots\": {}, \"notes\": \"\"}]}。"
                  "每个格子写到上限的七到九成，不要超过上限。讲稿 120 到 200 字。"
                  "不要用这些套话：" + "、".join(BANNED_PHRASES))
        brief = []
        for page in slotted:
            slide = slides[page - 1]
            brief.append({
                "no": page,
                "message": slide.get("message") or slide.get("title") or "",
                "limits": slide.get("slot_limits") or {},
                "slots": slide.get("slots") or {},
                "notes": slide.get("notes") or "",
            })
        prompt = "只改下面这些页里已经有的格子，不要新增格子名。\n材料：\n" + (material or "") + "\n\n" + json.dumps(brief, ensure_ascii=False)
        text, _, err = await _ask_text(user_id, system, prompt, model_id, max_tokens=4000)
        if err and ("没有连上" in err or "Connect" in err):
            text, _, err = await _ask_text(user_id, system, prompt, model_id, max_tokens=4000)
        pages = _written_pages(text)
        if not pages:
            return plan, err or "充实没有返回格子"
        out = copy.deepcopy(plan)
        wanted = set(slotted)
        for page in pages:
            try:
                number = int(page.get("no") or 0)
            except (TypeError, ValueError):
                continue
            if number not in wanted:
                continue
            slide = out["slides"][number - 1]
            incoming = page.get("slots")
            if isinstance(incoming, dict) and isinstance(slide.get("slots"), dict):
                allowed = set(slide["slots"]) | set(slide.get("slot_limits") or {})
                for name, value in incoming.items():
                    if name in allowed:
                        slide["slots"][name] = str(value or "")
            if page.get("notes"):
                slide["notes"] = str(page["notes"])
            project_legacy(slide)
        return out, ""
    system = ENRICH_SYSTEM.replace("{banned}", "、".join(BANNED_PHRASES))
    prompt = (f"只充实第 {'、'.join(str(page) for page in targets)} 页。\n\n材料：\n"
              + (material or "") + "\n\n计划：\n" + json.dumps(plan, ensure_ascii=False))
    data, _, err = await _ask_json(user_id, system, prompt, model_id, max_tokens=4000)
    # 出计划刚连上，紧接着的第二次请求偶尔会断。再试一次，避免偏薄页全留下。
    if err and ("没有连上" in err or "Connect" in err):
        data, _, err = await _ask_json(user_id, system, prompt, model_id, max_tokens=4000)
    if err or not data.get("slides"):
        return plan, err or "充实没有返回计划"
    adopted = adopt_pages(plan, data, targets)
    if adopted is None:
        return plan, "充实时页数变了，已保留原计划"
    return adopted, ""


def _page_card(catalog: dict | None, page_no) -> dict:
    try:
        number = int(page_no)
    except (TypeError, ValueError):
        return {}
    for page in (catalog or {}).get("pages") or []:
        if isinstance(page, dict) and int(page.get("page") or 0) == number:
            return page
    return {}


def slot_schema_text(page_card: dict) -> str:
    """给模型看的一页格子说明。"""
    from services.ppt import ppt_roles

    card = page_card or {}
    form = str(card.get("form") or "")
    desc = str(card.get("description") or ppt_roles.CONTENT_FORMS.get(form) or ppt_roles.PAGE_ROLES.get(card.get("role"), "") or "模板页")
    lines = [f"第 {card.get('no') or '？'} 页（模板第 {card.get('page') or '？'} 页：{desc}）"]
    grouped: dict[tuple, list] = {}
    for slot in card.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        name = str(slot.get("name") or "")
        match = re.match(r"^(item|stat)(\d+)\.(head|body|value|label)$", name)
        if not match:
            continue
        key = (match.group(1), match.group(3), int(slot.get("max_chars") or 0), int(slot.get("max_lines") or 0))
        grouped.setdefault(key, []).append(slot)
    emitted: set[tuple] = set()
    for index, slot in enumerate(card.get("slots") or []):
        if not isinstance(slot, dict):
            continue
        name = str(slot.get("name") or "")
        match = re.match(r"^(item|stat)(\d+)\.(head|body|value|label)$", name)
        if match:
            key = (match.group(1), match.group(3), int(slot.get("max_chars") or 0), int(slot.get("max_lines") or 0))
            if key in emitted:
                continue
            emitted.add(key)
            names = " / ".join(str(item.get("name") or "") for item in grouped[key])
            cap = int(key[2] or 0)
            bits = f"每个 ≤{cap} 字" if cap else "字数不限"
            if key[3]:
                bits += f"，≤{key[3]} 行"
            lines.append(f"- {names}：{bits}")
            continue
        cap = int(slot.get("max_chars") or 0)
        bits = f"≤{cap} 字" if cap else "字数不限"
        if slot.get("max_lines"):
            bits += f"，{int(slot['max_lines'])} 行"
        if slot.get("required") is False:
            bits += "，可空"
        lines.append(f"- {name}：{bits}")
    return "\n".join(lines)


def project_legacy(slide: dict) -> dict:
    """用格子推出旧字段，编辑页和自检继续能读。"""
    slots = slide.get("slots") if isinstance(slide, dict) else None
    if not isinstance(slots, dict):
        return slide
    if slots.get("title"):
        slide["title"] = str(slots["title"])
    elif slots.get("section_title"):
        slide["title"] = str(slots["section_title"])
    if slots.get("subtitle"):
        slide["subtitle"] = str(slots["subtitle"])
    if slots.get("quote"):
        slide["quote"] = str(slots["quote"])
    if slots.get("source"):
        slide["source"] = str(slots["source"])
    points = []
    cards = []
    index = 1
    while f"item{index}.body" in slots or f"item{index}.head" in slots:
        head = str(slots.get(f"item{index}.head") or "")
        body = str(slots.get(f"item{index}.body") or "")
        if head and body:
            points.append(f"{head}：{body}")
        elif body or head:
            points.append(body or head)
        cards.append({"key": head, "desc": body})
        index += 1
    if points:
        slide["points"] = points
        if slide.get("layout") == "cards":
            slide["cards"] = [{"key": item["key"], "desc": item["desc"]} for item in cards]
        elif slide.get("layout") == "numbered":
            slide["rows"] = [{"head": item["key"], "desc": item["desc"]} for item in cards]
    if slots.get("lead") and slide.get("layout") == "cards":
        slide["takeaway"] = str(slots["lead"])
    return slide


def _assign_slot(slots: dict, limits: dict, name: str, value: str, warnings: list | None = None) -> None:
    if name not in limits:
        return
    text = str(value or "")
    limit = int(limits.get(name) or 0)
    if warnings is not None and limit > 0 and ppt_layouts.text_len(text) > limit:
        warnings.append(f"{name} 超过 {limit} 字，已截断")
        text = ppt_layouts.truncate(text, limit, ellipsis="")
    slots[name] = text


def _fill_structural(slide: dict, story_slot: dict, storyline: dict, plan: dict, catalog: dict) -> None:
    """封面、目录、章节、结尾按骨架填，不调模型。"""
    kind = str((story_slot or {}).get("kind") or "")
    sections = [item for item in (storyline or {}).get("sections") or [] if isinstance(item, dict)]
    card = {} if slide.get("pick_fallback") or not slide.get("template_page") else _page_card(catalog, slide.get("template_page"))
    limits = {str(item.get("name") or ""): int(item.get("max_chars") or 0)
              for item in (card.get("slots") or []) if isinstance(item, dict)}
    slots: dict[str, str] = {}
    if kind == "cover":
        slide["layout"] = "cover"
        slide["title"] = str(plan.get("title") or storyline.get("central_question") or slide.get("title") or "")
        slide["subtitle"] = str(plan.get("subtitle") or slide.get("subtitle") or "")
        _assign_slot(slots, limits, "title", slide["title"])
        _assign_slot(slots, limits, "subtitle", slide["subtitle"])
    elif kind == "toc":
        slide["layout"] = "toc"
        slide["title"] = str(slide.get("title") or "目录")
        slide["items"] = [{
            "label": str(item.get("title") or ""),
            "desc": str(item.get("question") or ""),
        } for item in sections]
        _assign_slot(slots, limits, "title", slide["title"])
        head_warnings: list[str] = []
        for index, item in enumerate(sections, 1):
            _assign_slot(slots, limits, f"item{index}.head", item.get("title") or "", head_warnings)
            _assign_slot(slots, limits, f"item{index}.body", item.get("question") or "")
        if head_warnings:
            slide["slot_warnings"] = list(slide.get("slot_warnings") or []) + head_warnings
    elif kind == "section":
        try:
            number = int(story_slot.get("section") or 0)
        except (TypeError, ValueError):
            number = 0
        section = next((item for item in sections if int(item.get("no") or 0) == number), {})
        slide["layout"] = "section"
        slide["index"] = f"{number:02d}" if number else str(slide.get("index") or "")
        slide["title"] = str(section.get("title") or slide.get("title") or "")
        question = str(section.get("question") or "")
        slide["subs"] = [question] if question else list(slide.get("subs") or [])
        _assign_slot(slots, limits, "section_index", slide["index"])
        _assign_slot(slots, limits, "section_title", slide["title"])
        _assign_slot(slots, limits, "section_question", question)
        _assign_slot(slots, limits, "title", slide["title"])
        _assign_slot(slots, limits, "item1.body", question)
    elif kind == "end":
        slide["layout"] = "end"
        from services.ppt import ppt_pages

        heading = ppt_pages.closing_title((card or {}).get("sample_heading"))
        slide["title"] = heading
        _assign_slot(slots, limits, "title", heading)
        deck_title = str((plan or {}).get("title") or "").strip()
        notes = str(slide.get("notes") or "")
        if deck_title and deck_title not in notes:
            slide["notes"] = (notes + "\n" + deck_title).strip()
    if card and slots:
        slide["slots"] = slots
        slide["slot_limits"] = {name: limits[name] for name in slots}
        slide.setdefault("locked_slots", [])
        heads = [name for name in slots if re.match(r"^item\d+\.head$", name)]
        if heads:
            locked = list(slide.get("locked_slots") or [])
            for name in heads:
                if name not in locked:
                    locked.append(name)
            slide["locked_slots"] = locked
    elif kind in {"cover", "toc", "section", "end"}:
        slide.pop("slots", None)
        slide.pop("slot_limits", None)
    if story_slot.get("role"):
        slide["role"] = story_slot["role"]
    elif kind:
        slide["role"] = kind
    if story_slot.get("message"):
        slide["message"] = story_slot["message"]


def apply_written_slots(slide: dict, card: dict, payload: dict) -> list[str]:
    """把模型写的格子放上这一页。页面上没有的格子名丢掉。"""
    limits = {str(item.get("name") or ""): int(item.get("max_chars") or 0)
              for item in (card.get("slots") or []) if isinstance(item, dict)}
    locked = set(slide.get("locked_slots") or [])
    old = slide.get("slots") if isinstance(slide.get("slots"), dict) else {}
    written = payload.get("slots") if isinstance(payload, dict) else {}
    if not isinstance(written, dict):
        written = {}
    slots: dict[str, str] = {}
    warnings = []
    for name, value in written.items():
        if name not in limits:
            warnings.append(str(name))
            continue
        if name in locked and name in old:
            slots[name] = old[name]
        else:
            slots[name] = str(value or "")
    for name in locked:
        if name in old and name not in slots and name in limits:
            slots[name] = old[name]
    slide["slots"] = slots
    slide["slot_limits"] = {name: limits[name] for name in limits}
    slide["slot_warnings"] = warnings
    if payload.get("notes"):
        slide["notes"] = str(payload["notes"])
    if str(payload.get("lead") or "").strip():
        # 模板页通常没有 lead 格子，承接句仍要留给审稿和讲稿开头。
        slide["lead"] = str(payload["lead"]).strip()
    if payload.get("from"):
        slide["from"] = str(payload["from"])
    from services.ppt import ppt_roles

    form = str((card or {}).get("form") or "")
    mapped = ppt_roles.FORM_TO_LAYOUT.get(form)
    if mapped:
        slide["layout"] = mapped
    slide["template_form"] = form or slide.get("template_form") or ""
    project_legacy(slide)
    return warnings


def validate_slots(plan: dict, catalog: dict | None) -> list[dict]:
    """格子超字数、必填为空。模型编的格子名在写入时已经丢掉。"""
    issues = []
    for index, slide in enumerate((plan or {}).get("slides") or [], 1):
        if not isinstance(slide, dict) or not isinstance(slide.get("slots"), dict):
            continue
        card = _page_card(catalog, slide.get("template_page"))
        specs = {str(item.get("name") or ""): item
                 for item in (card.get("slots") or []) if isinstance(item, dict)}
        limits = slide.get("slot_limits") if isinstance(slide.get("slot_limits"), dict) else {}
        for name, spec in specs.items():
            if spec.get("required") and not str(slide["slots"].get(name) or "").strip():
                issues.append({
                    "slide": index, "field": name, "text": "",
                    "limit": int(spec.get("max_chars") or 0), "kind": "empty",
                })
        for name, value in slide["slots"].items():
            cap = int((specs.get(name) or {}).get("max_chars") or limits.get(name) or 0)
            if cap and ppt_layouts.text_len(value) > cap:
                issues.append({
                    "slide": index, "field": name, "text": str(value),
                    "limit": cap, "kind": "over",
                })
    return issues


def trim_slot_overflow(plan: dict, issues: list[dict]) -> dict:
    """格子仍超限时硬截，原文放进讲稿。"""
    out = copy.deepcopy(plan or {})
    slides = out.get("slides") or []
    for issue in issues or []:
        if issue.get("kind") not in (None, "over"):
            continue
        index = int(issue.get("slide") or 0) - 1
        limit = issue.get("limit")
        if index < 0 or index >= len(slides) or not isinstance(limit, int) or limit <= 0:
            continue
        slide = slides[index]
        slots = slide.get("slots") if isinstance(slide, dict) else None
        name = str(issue.get("field") or "")
        if not isinstance(slots, dict) or name not in slots:
            continue
        original = str(slots[name])
        if ppt_layouts.text_len(original) <= limit:
            continue
        if str(slide.get("layout") or "") == "end" and name == "title" and limit >= 2:
            # 结尾标题按示例字的窄框截开会剩半句，放不下就改成「谢谢」。
            slots[name] = "谢谢"
        else:
            slots[name] = ppt_layouts.truncate(original, limit, ellipsis="")
        note = str(slide.get("notes") or "").strip()
        slide["notes"] = (note + f"（原句：{original}）").strip()
        project_legacy(slide)
    out["slides"] = slides
    return out


def _section_slides(slides: list) -> list[dict]:
    return [slide for slide in slides if isinstance(slide, dict) and slide.get("layout") == "section"]


def _toc_source_name(slide: dict) -> tuple[str, str]:
    """章节页用来对目录的名字。有 section_title 格子就用格子，否则用标题。"""
    slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else {}
    limits = slide.get("slot_limits") if isinstance(slide.get("slot_limits"), dict) else {}
    if "section_title" in slots or "section_title" in limits:
        return "slot", str(slots.get("section_title") or slide.get("title") or "").strip()
    return "title", str(slide.get("title") or "").strip()


def align_toc(plan: dict, catalog: dict | None = None) -> dict:
    """目录项按章节名重写。整套模板没有 itemN.head 时，从计划和骨架里去掉目录页。"""
    from services.ppt import ppt_pagepick

    slides = [slide for slide in (plan.get("slides") or []) if isinstance(slide, dict)]
    if catalog and not ppt_pagepick.toc_pages_with_items(catalog):
        plan["slides"] = [
            slide for slide in slides
            if slide.get("layout") != "toc" and slide.get("role") != "toc"
        ]
        story = plan.get("storyline")
        if isinstance(story, dict) and isinstance(story.get("slots"), list):
            story["slots"] = [
                slot for slot in story["slots"]
                if not (isinstance(slot, dict) and slot.get("kind") == "toc")
            ]
        return plan
    sections = _section_slides(slides)
    if not sections:
        return plan
    sources = [_toc_source_name(slide) for slide in sections]
    use_slots = all(kind == "slot" for kind, _name in sources)
    for slide in slides:
        if slide.get("layout") != "toc" and slide.get("role") != "toc":
            continue
        limits = slide.get("slot_limits") if isinstance(slide.get("slot_limits"), dict) else {}
        if not limits and catalog and slide.get("template_page"):
            card = _page_card(catalog, slide.get("template_page"))
            limits = {
                str(item.get("name") or ""): int(item.get("max_chars") or 0)
                for item in (card.get("slots") or [])
                if isinstance(item, dict) and item.get("name")
            }
        slots = dict(slide.get("slots") or {}) if isinstance(slide.get("slots"), dict) else {}
        warnings = list(slide.get("slot_warnings") or [])
        labels = []
        for index, (_kind, name) in enumerate(sources, 1):
            key = f"item{index}.head"
            text = name
            if key in slots or key in limits:
                limit = int(limits.get(key) or 0)
                if limit > 0 and ppt_layouts.text_len(text) > limit:
                    note = f"{key} 超过 {limit} 字，已截断"
                    if note not in warnings:
                        warnings.append(note)
                    text = ppt_layouts.truncate(text, limit, ellipsis="")
                slots[key] = text
            labels.append({"label": text if use_slots else name})
        if slots:
            slide["slots"] = slots
        if labels:
            slide["items"] = labels
        if warnings:
            slide["slot_warnings"] = warnings
        if use_slots and slots:
            locked = list(slide.get("locked_slots") or [])
            for index in range(1, len(sources) + 1):
                key = f"item{index}.head"
                if key in slots and key not in locked:
                    locked.append(key)
            slide["locked_slots"] = locked
    plan["slides"] = slides
    return plan


def _written_pages(text: str) -> list[dict]:
    from services.ppt.pptx_outline import _extract_json

    data = _extract_json(text or "") or {}
    if not isinstance(data, dict):
        return []
    pages = data.get("pages")
    if not isinstance(pages, list):
        pages = data.get("slides")
    if not isinstance(pages, list):
        return []
    return [item for item in pages if isinstance(item, dict)]


async def shorten_slots(plan: dict, issues: list[dict], model_id: str = "",
                        user_id: str = "") -> tuple[dict, str]:
    """只把超了的格子交给模型改短。"""
    overs = [item for item in (issues or []) if item.get("kind") == "over"]
    if not overs:
        return plan, ""
    lines = []
    for item in overs:
        lines.append(f"第 {item.get('slide')} 页的 {item.get('field')} 现在 {ppt_layouts.text_len(item.get('text'))} 字，上限 {item.get('limit')}：{item.get('text')}")
    prompt = "只改下面这些格子，意思不变，改到上限内。输出 {\"pages\": [{\"no\": 页码, \"slots\": {格子名: 改短后的文字}}]}。\n" + "\n".join(lines)
    text, _, err = await _ask_text(user_id, SHORTEN_SYSTEM, prompt, model_id, max_tokens=2000)
    if err or not text:
        return plan, err or "改短没有返回"
    out = copy.deepcopy(plan)
    slides = out.get("slides") or []
    for page in _written_pages(text):
        try:
            index = int(page.get("no") or 0) - 1
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(slides):
            continue
        slots = slides[index].get("slots")
        incoming = page.get("slots")
        if not isinstance(slots, dict) or not isinstance(incoming, dict):
            continue
        allowed = {item.get("field") for item in overs if item.get("slide") == index + 1}
        locked = set(slides[index].get("locked_slots") or [])
        for name, value in incoming.items():
            if name in locked:
                continue
            if name in allowed and name in slots:
                slots[name] = str(value or "")
        project_legacy(slides[index])
    return out, ""


def _content_batches(story_slots: list, slides: list, only: set[int] | None) -> list[list[int]]:
    batches: list[list[int]] = []
    current: list[int] = []

    def flush() -> None:
        nonlocal current
        if current:
            batches.append(current)
            current = []

    for index, slot in enumerate(story_slots):
        if index >= len(slides) or not isinstance(slot, dict):
            continue
        kind = str(slot.get("kind") or "")
        if only is not None and index not in only:
            continue
        if kind == "section":
            flush()
        elif kind == "summary":
            flush()
            batches.append([index])
        elif kind == "content":
            current.append(index)
    flush()
    return batches


def _has_slots(slide: dict) -> bool:
    slots = (slide or {}).get("slots")
    return isinstance(slots, dict) and any(str(value or "").strip() for value in slots.values())


def _mark_write_fallback(slide: dict) -> None:
    slide.pop("slots", None)
    slide.pop("slot_limits", None)
    slide["write_fallback"] = True


def _required_blank(slide: dict, card: dict) -> bool:
    """必填格子一个字都没有。没有必填格子时不算。"""
    names = [
        str(item.get("name") or "")
        for item in (card.get("slots") or [])
        if isinstance(item, dict) and item.get("required") and str(item.get("name") or "")
    ]
    if not names:
        return False
    slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else {}
    return all(not str(slots.get(name) or "").strip() for name in names)


async def write_pages(plan: dict, storyline: dict, picks: list, catalog: dict,
                      material: str, model: str = "", user_id: str = "",
                      only: set[int] | None = None) -> tuple[dict, str]:
    """按章节把内容页写进格子。封面、目录、章节、结尾不调模型。"""
    from services.ppt import ppt_story

    out = copy.deepcopy(plan or {})
    slides = [slide for slide in (out.get("slides") or []) if isinstance(slide, dict)]
    story_slots = [slot for slot in ((storyline or {}).get("slots") or []) if isinstance(slot, dict)]
    if only is None:
        for index, slot in enumerate(story_slots):
            if index < len(slides) and str(slot.get("kind") or "") in {"cover", "toc", "section", "end"}:
                _fill_structural(slides[index], slot, storyline, out, catalog)
    calls = 0
    failed = []
    last_title = ""
    last_lead = ""
    system = WRITE_SYSTEM.replace("{banned}", "、".join(BANNED_PHRASES))
    skill = ppt_story.load_skill(str((storyline or {}).get("deck_type") or ""))
    skeleton = [{
        "no": slot.get("no") or index,
        "kind": slot.get("kind"),
        "role": slot.get("role") or "",
        "message": slot.get("message") or "",
        "bridge": slot.get("bridge") or "",
    } for index, slot in enumerate(story_slots, 1)]
    for batch in _content_batches(story_slots, slides, only):
        targets = []
        for index in batch:
            slide = slides[index]
            slot = story_slots[index]
            slide["role"] = slot.get("role") or slide.get("role") or ""
            if slot.get("message"):
                slide["message"] = slot["message"]
            if slide.get("pick_fallback") or not slide.get("template_page"):
                _mark_write_fallback(slide)
                continue
            card = _page_card(catalog, slide.get("template_page"))
            if not card.get("slots"):
                _mark_write_fallback(slide)
                continue
            targets.append((index, card))
        if not targets:
            continue
        schemas = []
        for index, card in targets:
            shown = dict(card)
            shown["no"] = index + 1
            schemas.append(slot_schema_text(shown))
        prompt = "\n\n".join([
            "讲法规则：\n" + skill,
            "整份骨架：\n" + json.dumps(skeleton, ensure_ascii=False),
            "这一章要写的格子：\n" + "\n\n".join(schemas),
            "材料：\n" + (material or ""),
            f"上一章最后一页标题：{last_title}；承接：{last_lead}",
        ])
        extra_notes = []
        for index, _card in targets:
            note = str(slides[index].get("rewrite_note") or "").strip()
            if note:
                extra_notes.append(f"第 {index + 1} 页要改：{note}")
        if extra_notes:
            prompt += "\n\n" + "\n".join(extra_notes)
        pages = []
        err = ""
        for _ in range(2):
            calls += 1
            text, _, err = await _ask_text(user_id, system, prompt, model, max_tokens=4000)
            pages = _written_pages(text) if text and not err else []
            got = set()
            for page in pages:
                try:
                    got.add(int(page.get("no") or 0))
                except (TypeError, ValueError):
                    continue
            if any((index + 1) in got for index, _card in targets):
                err = ""
                break
            pages = []
        if not pages:
            failed.append(batch[0] + 1)
            for index, _card in targets:
                if only is None or not _has_slots(slides[index]):
                    _mark_write_fallback(slides[index])
            continue
        by_no = {}
        for page in pages:
            try:
                by_no[int(page.get("no") or 0)] = page
            except (TypeError, ValueError):
                continue
        for index, card in targets:
            payload = by_no.get(index + 1)
            if not payload:
                if only is None or not _has_slots(slides[index]):
                    _mark_write_fallback(slides[index])
                continue
            before = copy.deepcopy(slides[index])
            apply_written_slots(slides[index], card, payload)
            if _required_blank(slides[index], card):
                # 这一页返回了，但必填格子全空，按没写上处理。
                if only is not None and _has_slots(before):
                    slides[index].clear()
                    slides[index].update(before)
                else:
                    _mark_write_fallback(slides[index])
                continue
            slides[index]["write_fallback"] = False
            last_title = str(slides[index].get("title") or "")
            last_lead = str((slides[index].get("slots") or {}).get("lead") or "")
    out["slides"] = slides
    quality = dict(out.get("quality") or {})
    quality["write_calls"] = calls
    out["quality"] = quality
    note = ""
    if failed:
        note = "第 " + "、".join(str(page) for page in failed) + " 页所在的章节没按格子写上，仍用原来的版式"
        out["write_note"] = note
    if only is None:
        retry = {
            index for index, slide in enumerate(slides)
            if slide.get("write_fallback") and slide.get("template_page") and not slide.get("pick_fallback")
        }
        if retry:
            out["slides"] = slides
            quality = dict(out.get("quality") or {})
            quality["write_calls"] = calls
            out["quality"] = quality
            retried, retry_note = await write_pages(
                out, storyline, picks, catalog, material, model, user_id, only=retry)
            merged = dict(retried.get("quality") or {})
            merged["write_calls"] = int(merged.get("write_calls") or 0) + calls
            retried["quality"] = merged
            if retry_note:
                retried["write_note"] = retry_note
            return retried, retry_note or note
    align_toc(out, catalog)
    return out, note


async def rewrite_slide(plan: dict, index: int, catalog: dict, user_id: str = "",
                        model_id: str = "") -> tuple[dict, str]:
    """换了一页模板之后，只重写这一页的格子。"""
    return await write_pages(
        plan, plan.get("storyline") or {}, [], catalog,
        json.dumps(plan.get("storyline") or {}, ensure_ascii=False),
        model_id, user_id, only={index})


_SKELETON_CODES = {"S_NO_QUESTION", "S_NO_SUMMARY", "S_SECTION_HEAVY", "S_THIN_SECTION"}
_REWRITE_LIMIT = 4
_REWRITE_SYSTEM = (
    "你在改学术汇报 PPT 的一页。只输出 JSON："
    '{"title":"","lead":"","notes":""}。'
    "title 至少 8 个字，并写出判断。lead 写这一页怎么接上一页。"
    "notes 是讲稿，不少于 80 字。只改这一页。"
)


def _slide_kind(slide: dict) -> str:
    layout = str((slide or {}).get("layout") or "")
    role = str((slide or {}).get("role") or "")
    if layout in {"cover", "toc", "section", "end"}:
        return layout
    if layout == "summary" or role in {"summary", "conclusion"}:
        return "summary"
    return "content"


def _blank_from_slot(slot: dict) -> dict:
    kind = str((slot or {}).get("kind") or "content")
    layout = {
        "cover": "cover", "toc": "toc", "section": "section",
        "summary": "summary", "end": "end",
    }.get(kind, "bullets")
    role = str(slot.get("role") or "")
    if kind == "summary":
        role = role or "conclusion"
    elif kind == "content":
        role = role or "finding"
    elif not role:
        role = kind
    title = str(slot.get("message") or slot.get("title") or "")
    if kind == "summary" and not title:
        title = "总结"
    return {
        "layout": layout,
        "role": role,
        "title": title,
        "notes": "",
        "lead": str(slot.get("bridge") or ""),
        "message": title,
    }


def _story_from_plan(plan: dict) -> dict:
    story = dict((plan or {}).get("storyline") or {})
    if story.get("slots"):
        return story
    slots = []
    for slide in (plan or {}).get("slides") or []:
        if not isinstance(slide, dict):
            continue
        slots.append({
            "kind": _slide_kind(slide),
            "role": slide.get("role") or "",
            "message": slide.get("title") or "",
            "evidence": "",
        })
    story["slots"] = slots
    story.setdefault("deck_type", "research_talk")
    return story


def _align_slides(old: list, slots: list) -> tuple[list, list[int]]:
    """按骨架槽位对齐。对得上的页原样保留，对不上的记为新增页（从 1 数）。"""
    pool = [slide for slide in old if isinstance(slide, dict)]
    used = [False] * len(pool)
    out: list[dict] = []
    fresh: list[int] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        kind = str(slot.get("kind") or "content")
        found = None
        for index, slide in enumerate(pool):
            if used[index]:
                continue
            if _slide_kind(slide) == kind:
                found = index
                break
        if found is None:
            out.append(_blank_from_slot(slot))
            fresh.append(len(out))
        else:
            used[found] = True
            out.append(copy.deepcopy(pool[found]))
    return out, fresh


def _repair_skeleton(plan: dict) -> tuple[dict, list[int]]:
    from services.ppt import ppt_story

    story = _story_from_plan(plan)
    old = [slide for slide in (plan.get("slides") or []) if isinstance(slide, dict)]
    has_summary = any(_slide_kind(slide) == "summary" for slide in old)
    pages = len(old) + (0 if has_summary else 1)
    normalized = ppt_story.normalize_storyline(story, max(pages, 1))
    slides, fresh = _align_slides(old, normalized.get("slots") or [])
    updated = dict(plan)
    updated["storyline"] = normalized
    updated["slides"] = slides
    if plan.get("plan_version"):
        updated["plan_version"] = plan["plan_version"]
    return updated, fresh


def _pick_new_pages(plan: dict, pages: list[int], catalog: dict | None) -> dict:
    if not catalog or not pages:
        return plan
    from services.ppt import ppt_pagepick

    slots = (plan.get("storyline") or {}).get("slots") or []
    chosen = []
    for page in pages:
        if 1 <= page <= len(slots) and isinstance(slots[page - 1], dict):
            chosen.append(slots[page - 1])
        else:
            chosen.append({"kind": "summary", "role": "conclusion", "message": "总结"})
    picks = ppt_pagepick.pick_pages(chosen, catalog, None)
    slides = plan.get("slides") or []
    for offset, page in enumerate(pages):
        if offset >= len(picks) or not (1 <= page <= len(slides)):
            continue
        ppt_pagepick.apply_picks({"slides": [slides[page - 1]]}, [picks[offset]], catalog)
    return plan


def _problem_text(problems: list) -> str:
    parts = []
    for item in problems or []:
        if not isinstance(item, dict):
            continue
        detail = str(item.get("detail") or item.get("problem") or "").strip()
        fix = str(item.get("fix") or "").strip()
        line = " ".join(part for part in (detail, fix) if part)
        if line:
            parts.append(line)
    return "；".join(parts)


def _text_pages(rule_issues: list, review: dict, skip: set[int]) -> list[tuple[int, list]]:
    grouped: dict[int, list] = {}
    order: list[int] = []

    def add(page: int, item: dict) -> None:
        if page < 1 or page in skip:
            return
        if page not in grouped:
            grouped[page] = []
            order.append(page)
        grouped[page].append(item)

    for item in (review or {}).get("issues") or []:
        if not isinstance(item, dict):
            continue
        try:
            page = int(item.get("page") or 0)
        except (TypeError, ValueError):
            continue
        add(page, {
            "code": str(item.get("dim") or "review"),
            "level": "warn",
            "page": page,
            "detail": str(item.get("problem") or ""),
            "fix": str(item.get("fix") or ""),
        })
    for item in rule_issues or []:
        if not isinstance(item, dict):
            continue
        if item.get("level") != "error" or item.get("code") in _SKELETON_CODES:
            continue
        try:
            page = int(item.get("page") or 0)
        except (TypeError, ValueError):
            continue
        add(page, item)
    return [(page, grouped[page]) for page in order]


def _neighbor_brief(slides: list, index: int) -> str:
    parts = []
    for pos in (index - 1, index + 1):
        if 0 <= pos < len(slides) and isinstance(slides[pos], dict):
            slide = slides[pos]
            parts.append(f"第 {pos + 1} 页 {slide.get('title') or ''} 承接 {slide.get('lead') or ''}")
    return "；".join(parts)


async def _rewrite_text_fields(plan: dict, page: int, note: str, user_id: str, model_id: str) -> dict:
    slides = [slide for slide in (plan.get("slides") or []) if isinstance(slide, dict)]
    if not (1 <= page <= len(slides)):
        return plan
    slide = slides[page - 1]
    prev = slides[page - 2] if page >= 2 else {}
    nxt = slides[page] if page < len(slides) else {}
    prompt = (
        f"要改的问题：{note}\n"
        f"上一页标题：{prev.get('title') or ''}\n"
        f"下一页标题：{nxt.get('title') or ''}\n"
        "这一页：" + json.dumps({
            "title": slide.get("title") or "",
            "lead": slide.get("lead") or "",
            "notes": slide.get("notes") or "",
            "role": slide.get("role") or "",
        }, ensure_ascii=False)
    )
    text, _name, err = await _ask_text(user_id, _REWRITE_SYSTEM, prompt, model_id, max_tokens=1200)
    if err or not text:
        return plan
    from services.ppt.pptx_outline import _extract_json

    data = _extract_json(text)
    if not isinstance(data, dict):
        return plan
    updated = dict(slide)
    if data.get("title"):
        updated["title"] = str(data["title"])
    if data.get("lead"):
        updated["lead"] = str(data["lead"])
    if data.get("notes"):
        updated["notes"] = str(data["notes"])
    slots = dict(updated.get("slots") or {})
    if data.get("lead") and "lead" in slots:
        slots["lead"] = str(data["lead"])
    if data.get("title") and "title" in slots:
        slots["title"] = str(data["title"])
    if slots:
        updated["slots"] = slots
    updated.pop("rewrite_note", None)
    slides = list(slides)
    slides[page - 1] = updated
    out = dict(plan)
    out["slides"] = slides
    return out


async def _rewrite_one(plan: dict, page: int, problems: list, user_id: str = "",
                       model_id: str = "", material: str = "", catalog: dict | None = None,
                       write_page=None) -> dict:
    if write_page is not None:
        updated = await write_page(plan, page, problems)
        return updated if isinstance(updated, dict) else plan
    slides = [slide for slide in (plan.get("slides") or []) if isinstance(slide, dict)]
    if not (1 <= page <= len(slides)):
        return plan
    note = _problem_text(problems)
    slide = dict(slides[page - 1])
    slide["rewrite_note"] = note
    slides[page - 1] = slide
    current = dict(plan)
    current["slides"] = slides
    if catalog and slide.get("template_page"):
        digest = (material or "") + "\n前后页：" + _neighbor_brief(slides, page - 1)
        updated, _err = await write_pages(
            current, current.get("storyline") or {}, [], catalog, digest,
            model_id, user_id, only={page - 1})
        new_slides = list(updated.get("slides") or [])
        if 1 <= page <= len(new_slides) and isinstance(new_slides[page - 1], dict):
            unchanged = _has_slots(slide) and new_slides[page - 1].get("slots") == slide.get("slots")
            if new_slides[page - 1].get("write_fallback") or unchanged:
                updated = await _rewrite_text_fields(updated, page, note, user_id, model_id)
                new_slides = list(updated.get("slides") or [])
            if 1 <= page <= len(new_slides) and isinstance(new_slides[page - 1], dict):
                cleaned = dict(new_slides[page - 1])
                cleaned.pop("rewrite_note", None)
                new_slides[page - 1] = cleaned
                updated["slides"] = new_slides
        return updated
    return await _rewrite_text_fields(current, page, note, user_id, model_id)


async def fix_story(plan: dict, rule_issues: list, review: dict, *, user_id: str = "",
                    model_id: str = "", material: str = "", catalog: dict | None = None,
                    write_page=None) -> tuple[dict, list[int]]:
    """按页修讲法。文字问题只重写那一页；加页、删页、并章回到骨架，只写新增页。每轮最多 4 页。"""
    out = copy.deepcopy(plan or {})
    review = review or {}
    if review.get("error") and not review.get("issues"):
        return out, []
    fixed: list[int] = []
    structural = [
        item for item in (rule_issues or [])
        if isinstance(item, dict) and item.get("level") == "error" and item.get("code") in _SKELETON_CODES
    ]
    if structural:
        out, new_pages = _repair_skeleton(out)
        out = _pick_new_pages(out, new_pages, catalog)
        for page in new_pages:
            if len(fixed) >= _REWRITE_LIMIT:
                break
            out = await _rewrite_one(
                out, page, structural, user_id, model_id, material, catalog, write_page)
            fixed.append(page)
        if new_pages:
            return out, fixed
    for page, problems in _text_pages(rule_issues, review, set(fixed)):
        if len(fixed) >= _REWRITE_LIMIT:
            break
        slides_now = out.get("slides") or []
        if not (1 <= page <= len(slides_now)):
            continue
        if (slides_now[page - 1] or {}).get("layout") in {"cover", "toc", "section", "end"}:
            continue
        before = copy.deepcopy(slides_now)
        out = await _rewrite_one(
            out, page, problems, user_id, model_id, material, catalog, write_page)
        after = list(out.get("slides") or [])
        if len(after) == len(before):
            out["slides"] = [
                after[index] if index == page - 1 else before[index]
                for index in range(len(after))
            ]
        fixed.append(page)
    return out, fixed


async def _review_enabled(user_id: str) -> bool:
    flag = os.environ.get("ARS_PPT_REVIEW", "").strip()
    if flag == "0":
        return False
    if flag == "1":
        return True
    try:
        from services.state_tracker import tracker
        raw = await tracker.get_setting("ppt_review_enabled", user_id)
    except Exception:
        return True
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() not in {"0", "false", "off", "关"}


def _empty_review() -> dict:
    return {
        "rounds": 0,
        "scores_before": {},
        "scores_after": {},
        "fixed_pages": [],
        "judge_model": "",
        "same_model": False,
        "review_calls": 0,
    }


def _score_mean(scores: dict) -> float:
    values = []
    for key in ("opening", "order", "bridge", "focus", "closing", "evidence"):
        value = (scores or {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    if not values:
        return 0
    return sum(values) / len(values)


async def run_story_review(plan: dict, user_id: str, writer_model: str = "",
                           material: str = "", catalog: dict | None = None) -> dict:
    """先审再改，最多两轮。第二轮之后仍有 error 就停，不再审第三次。"""
    from services.ppt import ppt_story_check

    scores_before: dict = {}
    scores_after: dict = {}
    fixed: list[int] = []
    judge = ""
    same = False
    error = ""
    rounds = 0
    review_calls = 0
    snapshot = None
    for _round in range(2):
        rounds += 1
        review_calls += 1
        review = await ppt_story_check.review_story(plan, user_id, writer_model)
        judge = str(review.get("judge_model") or judge)
        same = bool(review.get("same_model"))
        if rounds == 1:
            scores_before = dict(review.get("scores") or {})
        if review.get("scores"):
            scores_after = dict(review.get("scores") or {})
        if rounds == 2 and snapshot is not None and review.get("scores") and (
                _score_mean(scores_after) < _score_mean(scores_before)):
            plan["slides"] = snapshot["slides"]
            if "storyline" in snapshot:
                plan["storyline"] = snapshot["storyline"]
            plan["story_issues"] = ppt_story_check.check_story(plan)
            scores_after = dict(scores_before)
            fixed = []
            break
        if review.get("error"):
            error = str(review["error"])
            break
        issues = list(plan.get("story_issues") or [])
        errors = [item for item in issues if isinstance(item, dict) and item.get("level") == "error"]
        if not errors and not review.get("issues"):
            break
        if rounds == 2 and not errors:
            break
        if rounds == 1:
            snapshot = {
                "slides": copy.deepcopy(plan.get("slides") or []),
                "storyline": copy.deepcopy(plan.get("storyline") or {}),
            }
        review_for_fix = review
        if rounds == 2:
            review_for_fix = dict(review)
            review_for_fix["issues"] = []
        plan, pages = await fix_story(
            plan, issues, review_for_fix,
            user_id=user_id, model_id=writer_model, material=material, catalog=catalog)
        fixed.extend(pages)
        plan["story_issues"] = ppt_story_check.check_story(plan)
    plan["review"] = {
        "rounds": rounds,
        "scores_before": scores_before,
        "scores_after": scores_after,
        "fixed_pages": list(dict.fromkeys(fixed)),
        "judge_model": judge,
        "same_model": same,
        "review_calls": review_calls,
    }
    if error:
        plan["review"]["error"] = error
    quality = dict(plan.get("quality") or {})
    quality["review_calls"] = review_calls
    quality["rewrite_pages"] = len(plan["review"]["fixed_pages"])
    plan["quality"] = quality
    return plan


async def make_plan(user_id: str, material: str, model_id: str = "", pages: int = 0,
                    guidance: str = "", deck_hint: str = "", template_id: str = "") -> tuple[dict, str, str]:
    """读材料 → 出计划。返回 (计划, 模型名, 错误)。

    顺序：先排叙事骨架 → normalize → validate → 超限就 shorten（最多一次）→ 再 validate
    → 还超限就 hard_trim → 偏薄的页最多 5 页充实一次 → 再校验、再截断。
    骨架排不成时按原来的版式规则出计划。JSON 都解析不出来时返回错误，不退回本地规则大纲。
    """
    from services.ppt import ppt_story

    digest = digest_material(material)
    asked = int(pages or 0) or ppt_story.pages_from_text(guidance)
    deck_type = ppt_story.detect_deck_type(guidance, digest, deck_hint)
    early_catalog = None
    early_base = None
    allow_toc = True
    if (template_id or "").strip():
        from services.ppt import ppt_pagepick

        early_catalog, early_base = ppt_pagepick.load_catalog(user_id, template_id.strip())
        if early_catalog is not None and not ppt_pagepick.toc_pages_with_items(early_catalog):
            allow_toc = False
    story, story_err = None, ""
    try:
        story, story_err = await ppt_story.make_storyline(
            digest, guidance, asked or 12, deck_type, None, model_id, user_id, allow_toc)
    except Exception as exc:
        logger.warning("叙事骨架没有排成：%s", exc)
        story, story_err = None, "叙事骨架没有排成"
    prompt = build_plan_prompt(digest, guidance, asked)
    if story:
        prompt += ("\n\n叙事骨架（页数、顺序和每页的 message 不能改）：\n"
                   + json.dumps(story, ensure_ascii=False))
    data, model_name, err = await _ask_json(user_id, plan_system(story), prompt, model_id)
    if err:
        return {}, model_name, err

    if story and isinstance(data, dict):
        data["storyline"] = story
    plan = normalize(data)
    issues = validate_plan(plan)
    if issues:
        fixed, short_err = await shorten(plan, issues, model_id, user_id)
        if short_err:
            logger.warning("改短失败，直接兜底截断：%s", short_err)
        if story and isinstance(fixed, dict) and not fixed.get("storyline"):
            fixed["storyline"] = story
        plan = normalize(fixed)
        issues = validate_plan(plan)
    if issues:
        plan = hard_trim(plan, issues)
        issues = validate_plan(plan)
    if issues:
        logger.warning("计划里仍有 %d 处超限：%s", len(issues), issues[:3])

    review_catalog = None
    defer_slots = bool(story and (template_id or "").strip())
    if not defer_slots:
        plan = await _enrich_thin(plan, digest, model_id, user_id)
    else:
        plan["quality"] = {"thin_before": 0, "enriched": 0, "thin_pages": []}
    if story:
        plan["storyline"] = story
        plan["plan_version"] = 2
        if (template_id or "").strip():
            from services.ppt import ppt_pagepick

            catalog, base = early_catalog, early_base
            if catalog:
                review_catalog = catalog
                picks = ppt_pagepick.pick_pages(story.get("slots") or [], catalog, base)
                ppt_pagepick.apply_picks(plan, picks, catalog)
                plan["template_id"] = template_id.strip()
                plan, _note = await write_pages(
                    plan, story, picks, catalog, digest, model_id, user_id)
                slot_issues = validate_slots(plan, catalog)
                overs = [item for item in slot_issues if item.get("kind") == "over"]
                over_before = len(overs)
                if overs:
                    plan, short_err = await shorten_slots(plan, overs, model_id, user_id)
                    if short_err:
                        logger.warning("格子改短失败，直接截断：%s", short_err)
                    overs = [item for item in validate_slots(plan, catalog) if item.get("kind") == "over"]
                over_shorten = len(overs)
                if overs:
                    plan = trim_slot_overflow(plan, overs)
                    overs = [item for item in validate_slots(plan, catalog) if item.get("kind") == "over"]
                quality = dict(plan.get("quality") or {})
                quality["slots_over_before"] = over_before
                quality["slots_over_after_shorten"] = over_shorten
                quality["slots_over_after_trim"] = len(overs)
                plan["quality"] = quality
                plan = align_toc(plan, catalog)
                field_issues = validate_plan(plan)
                if field_issues:
                    plan = hard_trim(plan, field_issues)
                plan = await _enrich_thin(plan, digest, model_id, user_id)
            else:
                plan = await _enrich_thin(plan, digest, model_id, user_id)
    elif story_err:
        plan["story_note"] = "这次没能先排讲法，按旧方法出的"
    from services.ppt import ppt_story_check

    plan["story_issues"] = ppt_story_check.check_story(plan)
    if await _review_enabled(user_id):
        plan = await run_story_review(plan, user_id, model_id, digest, review_catalog)
    else:
        plan["review"] = _empty_review()
    return plan, model_name, ""


async def _enrich_thin(plan: dict, material: str, model_id: str, user_id: str) -> dict:
    """偏薄的页充实一次，再校验、再截断。已有的 quality 字段保留。"""
    before = thin_page_numbers(plan)
    enriched = 0
    if before:
        updated, enrich_err = await enrich_plan(plan, before, material, model_id, user_id)
        if enrich_err:
            logger.warning("充实偏薄页没有用上：%s", enrich_err)
        else:
            plan = normalize(updated)
            issues = validate_plan(plan)
            if issues:
                plan = hard_trim(plan, issues)
            enriched = len([page for page in before[:_ENRICH_LIMIT]
                            if page not in thin_page_numbers(plan)])
    quality = dict(plan.get("quality") or {})
    quality["thin_before"] = len(before)
    quality["enriched"] = enriched
    quality["thin_pages"] = thin_page_numbers(plan)
    plan["quality"] = quality
    return plan
