"""出计划后的讲法检查。规则能判定的放这里，衔接打分也在这里。"""

from __future__ import annotations

import re

from services.ppt import ppt_story

_STRUCTURAL = {"cover", "toc", "section", "end"}
_OPEN_ROLES = {"background", "hook", "concept"}
_SUMMARY_ROLES = {"summary", "conclusion"}
_QUESTION_TYPES = {"research_talk", "defense", "proposal", "paper_report"}
_METHOD_TYPES = {"research_talk", "defense", "proposal", "survey_report"}
_ASSERT = (
    "是", "有", "会", "能", "比", "让", "使", "导致", "说明", "表明", "决定", "影响",
    "不", "更", "最", "没", "但", "需",
)
_JUDGE = (
    "当作", "稳定", "较稳", "改变", "强化", "催生", "塑造", "引发", "遮蔽", "赋予",
    "并存", "包含", "推动", "转向", "强调", "限定", "定义", "产生", "追认", "而非",
    "用得上", "卡在", "先行", "张力", "重新", "抬高", "忘得", "差距", "收归", "接入",
    "支撑", "引入", "优点", "局限", "记得", "认可",
)
_BRIDGE = (
    "上一页", "前面", "接着", "接下来", "拉回", "上面", "刚才", "于是", "可见",
    "但", "然而", "进一步", "例如", "为例", "为什么", "回到", "所以", "因此",
)
_QUESTION = re.compile(r"[?？]|为什么|是否|如何|怎样|哪些|哪个|吗")
_STOP_WORDS = {
    "如何", "为什么", "什么", "是否", "怎么", "怎样", "我们", "你们", "他们",
    "一个", "可以", "通过", "进行", "以及", "其中", "如果", "因为", "所以",
    "但是", "没有", "不是", "这个", "那个", "哪些", "哪个",
}
_STOP_CHARS = set("的了是在和与及或而但被把对从为以也都就还又很更最这那")


def check_story(plan: dict) -> list[dict]:
    """返回讲法问题。没有叙事骨架时只查章节、目录和讲稿。"""
    slides = [s for s in (plan or {}).get("slides") or [] if isinstance(s, dict)]
    story = (plan or {}).get("storyline") if isinstance((plan or {}).get("storyline"), dict) else {}
    deck_type = str((story or {}).get("deck_type") or "research_talk")
    issues: list[dict] = []
    issues.extend(_section_rules(slides))
    issues.extend(_toc_mismatch(slides))
    issues.extend(_notes_short(slides))
    if not story:
        return issues
    issues.extend(_background(slides))
    if deck_type in _QUESTION_TYPES:
        issues.extend(_question(slides))
    if deck_type in _METHOD_TYPES:
        issues.extend(_method(slides))
    issues.extend(_summary(slides))
    issues.extend(_summary_answers(slides, story))
    issues.extend(_titles(slides))
    issues.extend(_leads(slides))
    issues.extend(_dup_titles(slides))
    issues.extend(_form_repeat(slides))
    issues.extend(_evidence(slides, story))
    return issues


def _issue(code: str, level: str, page: int, detail: str, fix: str) -> dict:
    return {"code": code, "level": level, "page": page, "detail": detail, "fix": fix}


def _is_content(slide: dict) -> bool:
    return str(slide.get("layout") or "") not in _STRUCTURAL


def _content_pages(slides: list[dict]) -> list[int]:
    return [index for index, slide in enumerate(slides, 1) if _is_content(slide)]


def _chapters(slides: list[dict]) -> list[dict]:
    chapters: list[dict] = []
    current = None
    for index, slide in enumerate(slides, 1):
        if slide.get("layout") == "section":
            current = {"section": index, "pages": []}
            chapters.append(current)
        elif _is_content(slide):
            if current is None:
                current = {"section": 0, "pages": []}
                chapters.append(current)
            current["pages"].append(index)
    return chapters


def _role(slide: dict) -> str:
    return str(slide.get("role") or "").strip()


def _title(slide: dict) -> str:
    return str(slide.get("title") or "").strip()


def _notes(slide: dict) -> str:
    return str(slide.get("notes") or "").strip()


def _lead(slide: dict) -> str:
    if str(slide.get("lead") or "").strip():
        return str(slide.get("lead")).strip()
    slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else {}
    return str(slots.get("lead") or "").strip()


def _first_sentence(text: str) -> str:
    parts = re.split(r"[。！？\n]", text or "")
    for part in parts:
        if part.strip():
            return part.strip()
    return ""


def _section_rules(slides: list[dict]) -> list[dict]:
    issues = []
    total = len(slides)
    sections = [index for index, slide in enumerate(slides, 1) if slide.get("layout") == "section"]
    if total:
        cap = int(ppt_story.budget_for(total)["section"][1])
        ratio = len(sections) / total
        if ratio > 0.25 or len(sections) > cap:
            page = sections[0] if sections else 1
            issues.append(_issue(
                "S_SECTION_HEAVY", "error", page,
                f"章节页 {len(sections)} 张，占 {round(ratio * 100)}%，上限 {cap} 张",
                "合并章节，每章至少两张内容页",
            ))
    for chapter in _chapters(slides):
        if not chapter["section"]:
            continue
        if len(chapter["pages"]) < 2:
            issues.append(_issue(
                "S_THIN_SECTION", "error", chapter["section"],
                f"第 {chapter['section']} 页这一章只有 {len(chapter['pages'])} 张内容页",
                "并进相邻章节，或补一页",
            ))
    return issues


def _item_name(item) -> str:
    if isinstance(item, str):
        return re.sub(r"\s+", "", item)
    if isinstance(item, dict):
        return re.sub(r"\s+", "", str(item.get("label") or item.get("title") or item.get("text") or ""))
    return ""


def _names_align(names: list[str], section_names: list[str]) -> bool:
    """目录名和章节名相同，或目录名是章节名按字数上限截下来的开头。"""
    if len(names) != len(section_names):
        return False
    for toc_name, section_name in zip(names, section_names):
        if not toc_name or not section_name:
            return False
        if toc_name != section_name and not section_name.startswith(toc_name):
            return False
    return True


def _toc_mismatch(slides: list[dict]) -> list[dict]:
    toc_index = next((i for i, slide in enumerate(slides, 1) if slide.get("layout") == "toc"), 0)
    if not toc_index:
        return []
    items = slides[toc_index - 1].get("items") if isinstance(slides[toc_index - 1].get("items"), list) else []
    sections = [slide for slide in slides if slide.get("layout") == "section"]
    names = [_item_name(item) for item in items]
    section_names = [re.sub(r"\s+", "", _title(slide)) for slide in sections]
    toc_slots = slides[toc_index - 1].get("slots")
    section_slots = [slide.get("slots") for slide in sections]
    if isinstance(toc_slots, dict) and sections and all(
            isinstance(slots, dict) and str(slots.get("section_title") or "").strip() for slots in section_slots):
        # 按格子出片时屏幕上是格子里的字，旧字段可能已被截短或改写。
        names = []
        for index in range(1, 10):
            text = str(toc_slots.get(f"item{index}.head") or toc_slots.get(f"item{index}.body") or "").strip()
            if text:
                names.append(re.sub(r"\s+", "", text))
        section_names = [re.sub(r"\s+", "", str(slots["section_title"])) for slots in section_slots]
    if _names_align(names, section_names):
        return []
    return [_issue(
        "S_TOC_MISMATCH", "error", toc_index,
        f"目录 {len(names)} 项，章节页 {len(section_names)} 张",
        "目录改成章节名",
    )]


def _notes_short(slides: list[dict]) -> list[dict]:
    issues = []
    for index in _content_pages(slides):
        if len(_notes(slides[index - 1])) < 80:
            issues.append(_issue(
                "S_NOTES_SHORT", "error", index,
                f"第 {index} 页讲稿少于 80 字",
                "按「承接、证据、引出下一页」补讲稿",
            ))
    return issues


def _background(slides: list[dict]) -> list[dict]:
    chapters = [chapter for chapter in _chapters(slides) if chapter["pages"]]
    if not chapters:
        return []
    page = chapters[0]["pages"][0]
    role = _role(slides[page - 1])
    if role in _OPEN_ROLES:
        return []
    return [_issue(
        "S_NO_BACKGROUND", "error", page,
        f"第 {page} 页不是背景、引子或概念",
        "把该页改成背景，或在它前面加一页背景",
    )]


def _question(slides: list[dict]) -> list[dict]:
    window = max(1, int(len(slides) * 0.4))
    for index, slide in enumerate(slides[:window], 1):
        if _role(slide) == "question" or _QUESTION.search(_title(slide)):
            return []
    page = _content_pages(slides[:window])
    return [_issue(
        "S_NO_QUESTION", "error", page[0] if page else 1,
        f"前 {window} 页没有一页写出要回答的问题",
        "在背景之后加一页，标题写成要回答的问题",
    )]


def _method(slides: list[dict]) -> list[dict]:
    if any(_role(slide) == "method" for slide in slides):
        return []
    pages = _content_pages(slides)
    return [_issue(
        "S_NO_METHOD", "warn", pages[0] if pages else 1,
        "没有方法页",
        "加一页方法，写材料、步骤或对象",
    )]


def _page_before_end(slides: list[dict]) -> int:
    for index, slide in enumerate(slides, 1):
        if slide.get("layout") == "end" and index > 1:
            return index - 1
    return len(slides)


def _is_summary(slide: dict) -> bool:
    return slide.get("layout") == "summary" or _role(slide) in _SUMMARY_ROLES


def _summary(slides: list[dict]) -> list[dict]:
    if not slides:
        return []
    page = _page_before_end(slides)
    if _is_summary(slides[page - 1]):
        return []
    return [_issue(
        "S_NO_SUMMARY", "error", page,
        f"第 {page} 页不是总结，结尾前面缺一页总结",
        "在结尾前加一页总结",
    )]


def _emit_word(words: list[str], buf: str) -> None:
    """整句粘成一个词时，总结页对不上。长片段改按两字词去对。"""
    if len(buf) < 2 or buf in _STOP_WORDS:
        return
    if len(buf) <= 4:
        words.append(buf)
        return
    for index in range(len(buf) - 1):
        gram = buf[index:index + 2]
        if gram not in _STOP_WORDS:
            words.append(gram)


def _content_words(text: str) -> list[str]:
    words = []
    stops = sorted(_STOP_WORDS, key=len, reverse=True)
    for part in re.split(r"[^\u4e00-\u9fff]+", text or ""):
        chunks = [part]
        for stop in stops:
            nxt = []
            for chunk in chunks:
                nxt.extend(piece for piece in chunk.split(stop) if piece)
            chunks = nxt
        for chunk in chunks:
            buf = ""
            for char in chunk:
                if char in _STOP_CHARS:
                    _emit_word(words, buf)
                    buf = ""
                else:
                    buf += char
            _emit_word(words, buf)
    return words


def _summary_text(slide: dict) -> str:
    parts = [_title(slide), _notes(slide), str(slide.get("message") or "")]
    for key in ("points", "items"):
        for item in slide.get(key) or []:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(" ".join(str(value) for value in item.values()))
    slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else {}
    parts.extend(str(value) for value in slots.values())
    return "\n".join(parts)


def _summary_answers(slides: list[dict], story: dict) -> list[dict]:
    question = str(story.get("central_question") or "").strip()
    if not question:
        return []
    page = _page_before_end(slides)
    if not slides or not _is_summary(slides[page - 1]):
        return []
    words = _content_words(question)
    blob = _summary_text(slides[page - 1])
    if words and any(word in blob for word in words):
        return []
    if not words and question in blob:
        return []
    return [_issue(
        "S_SUMMARY_NOT_ANSWER", "warn", page,
        "总结页的文字里没有中心问题的实词",
        "总结的每句话回扣中心问题",
    )]


def _titles(slides: list[dict]) -> list[dict]:
    issues = []
    for index in _content_pages(slides):
        title = _title(slides[index - 1])
        if len(title) >= 8 and (
            any(word in title for word in _ASSERT) or any(word in title for word in _JUDGE)
        ):
            continue
        issues.append(_issue(
            "S_TITLE_NOT_ASSERTION", "warn", index,
            f"第 {index} 页标题不是一句判断",
            "改成一句有主语的判断",
        ))
    return issues


def _leads(slides: list[dict]) -> list[dict]:
    issues = []
    for chapter in _chapters(slides):
        for page in chapter["pages"][1:]:
            slide = slides[page - 1]
            if _lead(slide):
                continue
            opening = _first_sentence(_notes(slide))
            if any(word in opening for word in _BRIDGE):
                continue
            issues.append(_issue(
                "S_NO_LEAD", "warn", page,
                f"第 {page} 页没有承接",
                "补 lead，或把承接写进讲稿第一句",
            ))
    return issues


def _bigrams(text: str) -> set[str]:
    chars = re.sub(r"\s+", "", text or "")
    if len(chars) < 2:
        return set()
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


def _dup_titles(slides: list[dict]) -> list[dict]:
    pages = _content_pages(slides)
    issues = []
    for left in range(len(pages)):
        for right in range(left + 1, len(pages)):
            a = _bigrams(_title(slides[pages[left] - 1]))
            b = _bigrams(_title(slides[pages[right] - 1]))
            if not a or not b:
                continue
            if len(a & b) / len(a | b) > 0.6:
                issues.append(_issue(
                    "S_DUP_MESSAGE", "warn", pages[right],
                    f"第 {pages[left]} 页和第 {pages[right]} 页标题过于相似",
                    "合并，或改成不同的判断",
                ))
    return issues


def _form_repeat(slides: list[dict]) -> list[dict]:
    issues = []
    run_layout = ""
    run = 0
    for index, slide in enumerate(slides, 1):
        if not _is_content(slide):
            run_layout = ""
            run = 0
            continue
        layout = str(slide.get("form") or slide.get("layout") or "")
        if layout and layout == run_layout:
            run += 1
        else:
            run_layout = layout
            run = 1
        if run == 3:
            issues.append(_issue(
                "S_FORM_REPEAT", "warn", index,
                f"第 {index} 页起，{layout} 已连续 {run} 页",
                "换一页的形态",
            ))
    return issues


def _evidence(slides: list[dict], story: dict) -> list[dict]:
    slots = [slot for slot in (story.get("slots") or []) if isinstance(slot, dict)]
    issues = []
    aligned = len(slots) == len(slides)
    for index, slot in enumerate(slots, 1):
        if "材料不足" not in str(slot.get("evidence") or ""):
            continue
        page = index if aligned else 1
        try:
            page = int(slot.get("page") or slot.get("no") or page)
        except (TypeError, ValueError):
            page = index if aligned else 1
        issues.append(_issue(
            "S_EVIDENCE_MISSING", "warn", page,
            f"第 {page} 页骨架写了材料不足",
            "在卡片上标明，不编造",
        ))
    return issues


REVIEW_SYSTEM = """你在审一份学术汇报 PPT 的讲法。下面是每页的角色、标题、承接句和讲稿开头。请只输出 JSON。
按 6 个维度打 1–5 分：
- opening：开场是否交代了背景，并引出要回答的问题
- order：章节顺序是否讲得通（为什么 → 是什么/怎么做 → 发现 → 所以呢）
- bridge：相邻两页是否接得上，跳跃的地方有没有承接
- focus：每页是否只讲一件事，标题是不是一句判断
- closing：结尾是否回答了开头的问题
- evidence：内容页是否有具体的例子、数据、对比或原文
再列出最多 6 个具体问题，每个问题指明页号，说清怎么改：
{"scores": {"opening": 4, "order": 3, "bridge": 2, "focus": 4, "closing": 3, "evidence": 4},
 "issues": [{"page": 6, "dim": "bridge", "problem": "第 5 页讲完现象，第 6 页直接给结论，中间缺原因", "fix": "第 6 页 lead 改成因果句；或在第 5、6 页之间补一页原因"}]}
只指出真正影响听众理解的问题，不要挑措辞。"""

_SCORE_KEYS = ("opening", "order", "bridge", "focus", "closing", "evidence")


def review_brief(plan: dict) -> str:
    """只给页号、角色、标题、承接和讲稿前 60 字，加上问题和预定回答。不超过 3000 字。"""
    story = (plan or {}).get("storyline") if isinstance(plan, dict) else {}
    story = story if isinstance(story, dict) else {}
    lines = []
    question = str(story.get("central_question") or "").strip()
    answer = str(story.get("answer") or "").strip()
    if question:
        lines.append("要回答的问题：" + question)
    if answer:
        lines.append("预定的回答：" + answer)
    for index, slide in enumerate((plan or {}).get("slides") or [], 1):
        if not isinstance(slide, dict):
            continue
        slots = slide.get("slots") if isinstance(slide.get("slots"), dict) else {}
        notes_full = str(slide.get("notes") or "").replace("\n", " ")
        lead = str(slide.get("lead") or slots.get("lead") or "")
        if not lead:
            lead = _first_sentence(notes_full)
        notes = notes_full[:60]
        role = str(slide.get("role") or slide.get("layout") or "")
        title = str(slide.get("title") or "")
        lines.append(f"{index}. {role}｜{title}｜承接：{lead}｜讲稿：{notes}")
    text = "\n".join(lines)
    return text[:3000]


def _score_value(raw) -> int | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not 1 <= value <= 5:
        return None
    return int(round(value))


def parse_review(text: str) -> dict | None:
    from services.ppt.pptx_outline import _extract_json

    data = _extract_json(text or "")
    if not isinstance(data, dict) or not isinstance(data.get("scores"), dict):
        return None
    scores = {}
    for key in _SCORE_KEYS:
        value = _score_value(data["scores"].get(key))
        if value is None:
            return None
        scores[key] = value
    issues = []
    for item in (data.get("issues") or [])[:6]:
        if not isinstance(item, dict):
            continue
        try:
            page = int(item.get("page") or 0)
        except (TypeError, ValueError):
            continue
        if page < 1:
            continue
        issues.append({
            "page": page,
            "dim": str(item.get("dim") or ""),
            "problem": str(item.get("problem") or ""),
            "fix": str(item.get("fix") or ""),
        })
    return {"scores": scores, "issues": issues}


def _configured_models(settings: dict) -> list[str]:
    from providers import PROVIDERS, list_models
    from services.state_tracker import inspect_secret

    found = []
    for model in list_models():
        provider = PROVIDERS.get(model.get("provider") or "") or {}
        key_name = provider.get("key_setting") or ""
        if not key_name:
            continue
        usable, _broken = inspect_secret(key_name, str((settings or {}).get(key_name) or ""))
        if usable:
            found.append(model["id"])
    return found


def _model_provider(model_id: str) -> str:
    from providers import MODELS

    for model in MODELS:
        if model["id"] == model_id:
            return model["provider"]
    return ""


async def pick_judge(user_id: str, writer_model: str = "") -> tuple[str, bool]:
    """从已配置 Key 的模型里挑评委。返回 (模型 id, 是否和写稿同一个)。"""
    from services.state_tracker import tracker

    try:
        settings = await tracker.get_settings(user_id)
    except Exception:
        return "", False
    usable = _configured_models(settings)
    writer = (writer_model or str(settings.get("model") or "")).strip()
    others = [mid for mid in usable if mid != writer]
    cross = [mid for mid in others if _model_provider(mid) != _model_provider(writer)]
    if cross:
        return cross[0], False
    if writer and writer in usable:
        return writer, True
    if usable:
        return usable[0], usable[0] == writer
    return "", False


async def review_story(plan: dict, user_id: str = "", writer_model: str = "") -> dict:
    """审一份计划的衔接。

    评委从密钥能解开的模型里挑，模型名不写死。存了但解不开的不算。
    优先选和写稿不同提供商的模型；只有一个提供商时用写稿那个模型，
    same_model 为真，卡片上写「评委和写稿是同一个模型」。
    返回的 JSON 不合法时，error 用中文说明，调用方不改计划。
    """
    judge, same = await pick_judge(user_id, writer_model)
    if not judge:
        return {
            "error": "还没配可用的评委模型，跳过衔接审稿",
            "scores": {},
            "issues": [],
            "judge_model": "",
            "same_model": False,
        }
    from services.ppt.ppt_plan import _ask_text

    text, name, err = await _ask_text(
        user_id, REVIEW_SYSTEM, review_brief(plan), judge, max_tokens=1200)
    shown = name or judge
    if err or not (text or "").strip():
        return {
            "error": err or "衔接审稿没有返回评分",
            "scores": {},
            "issues": [],
            "judge_model": shown,
            "same_model": same,
        }
    parsed = parse_review(text)
    if not parsed:
        return {
            "error": "衔接审稿返回的不是可用的评分 JSON",
            "scores": {},
            "issues": [],
            "judge_model": shown,
            "same_model": same,
        }
    return {
        "scores": parsed["scores"],
        "issues": parsed["issues"],
        "judge_model": shown,
        "same_model": same,
        "error": "",
    }


def review_sentence(plan: dict) -> str:
    """卡片上的一句：衔接评分 4.2 / 5，修了 3 页。"""
    review = (plan or {}).get("review") if isinstance(plan, dict) else None
    if not isinstance(review, dict):
        return ""
    scores = review.get("scores_after") or review.get("scores_before") or {}
    if not isinstance(scores, dict) or not scores:
        return ""
    nums = []
    for value in scores.values():
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    if not nums:
        return ""
    avg = sum(nums) / len(nums)
    pages = review.get("fixed_pages") or []
    count = len(pages) if isinstance(pages, list) else 0
    text = f"衔接评分 {avg:.1f} / 5，修了 {count} 页"
    if review.get("same_model"):
        text += "。评委和写稿是同一个模型"
    return text
