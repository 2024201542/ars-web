"""PPT 大纲：让「当前选中的任意模型」产出结构化 JSON，并做解析容错。

模型无关：DeepSeek / 通义千问 / Kimi / 智谱 / Claude 都走同一条路径——
按 providers.py 的路由取 Key 与 base_url，再交给 idea_debate._complete（它已覆盖
OpenAI 兼容与 Anthropic 两种协议）。用户选中哪个模型就用哪个。

解析容错三件事：剥 ```json 围栏；截取首尾大括号内的 JSON；失败则用
pptx_builder.outline_from_markdown 做启发式兜底（并标记 fallback=True）。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from providers import MODELS, PROVIDERS

LAYOUTS = {"title", "toc", "content", "section", "end"}

OUTLINE_SYSTEM = (
    "你在把一份材料整理成学术汇报用的 PPT 大纲。"
    "只输出 JSON，不要输出任何解释、不要写代码块以外的文字。"
)

_SCHEMA_HINT = """{
  "title": "整份汇报的标题",
  "subtitle": "副标题，可为空",
  "theme": {"accent": "#9E1B32", "font": "微软雅黑"},
  "slides": [
    {"layout": "title", "title": "封面标题", "subtitle": "汇报人/日期", "notes": "开场白"},
    {"layout": "toc", "title": "汇报框架", "bullets": ["一、…", "二、…"], "notes": ""},
    {"layout": "content", "title": "某节标题",
     "bullets": ["要点一", {"text": "要点二", "children": ["子要点", "子要点"]}],
     "notes": "这一页要讲的话，写详细一点"},
    {"layout": "end", "title": "谢谢", "notes": ""}
  ]
}"""


def build_outline_prompt(material: str, guidance: str = "", pages: int = 0,
                         title_hint: str = "") -> str:
    page_line = f"共 {pages} 页左右。" if pages else "页数根据内容自定（8–14 页之间）。"
    title_line = f"标题建议用：{title_hint}。" if title_hint else ""
    return (
        "请把下面的材料整理成学术汇报 PPT 的大纲。\n\n"
        f"输出要求：\n"
        f"1. 只输出 JSON，结构如下（字段含义见注释，不要照抄注释）：\n{_SCHEMA_HINT}\n"
        f"2. {page_line}layout 只能用 title / toc / content / section / end。\n"
        f"3. 每页要点最多 7 条、每条不超过 40 字；细节写进 notes（演讲备注），不要堆在页面上。\n"
        f"4. 内容必须来自材料，不要编造材料里没有的观点、数据或文献。\n"
        f"5. 学术汇报风格：先问题意识，再论证，最后结论。{title_line}\n\n"
        f"材料：\n{material}\n\n"
        f"用户的补充要求：{guidance.strip() or '无'}\n"
    )


def _extract_json(text: str) -> Optional[dict]:
    raw = (text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = raw[start:end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # 常见毛病：尾随逗号
        fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def normalize_outline(data: dict, title_hint: str = "") -> dict:
    """校验并补齐字段，顺手把超标的页数/要点截断。"""
    title = str(data.get("title") or title_hint or "汇报").strip()
    slides_in = data.get("slides")
    slides: list[dict] = []
    if isinstance(slides_in, list):
        for item in slides_in:
            if not isinstance(item, dict):
                continue
            layout = str(item.get("layout") or "content").lower().strip()
            if layout not in LAYOUTS:
                layout = "content"
            bullets_in = item.get("bullets") or []
            bullets: list = []
            if isinstance(bullets_in, list):
                for b in bullets_in:
                    if isinstance(b, dict) and b.get("text"):
                        bullets.append({
                            "text": str(b.get("text"))[:200],
                            "children": [str(c)[:120] for c in (b.get("children") or [])][:6],
                        })
                    elif isinstance(b, str) and b.strip():
                        bullets.append(b.strip()[:200])
            slides.append({
                "layout": layout,
                "title": str(item.get("title") or "").strip()[:120],
                "subtitle": str(item.get("subtitle") or "").strip()[:160],
                "bullets": bullets,
                "notes": str(item.get("notes") or "").strip()[:2000],
            })
    slides = slides[:20]
    if not slides:
        return {}
    if slides[0].get("layout") != "title":
        slides.insert(0, {"layout": "title", "title": title,
                          "subtitle": str(data.get("subtitle") or "").strip(),
                          "bullets": [], "notes": ""})
    theme = data.get("theme") if isinstance(data.get("theme"), dict) else {}
    return {
        "title": title,
        "subtitle": str(data.get("subtitle") or "").strip()[:160],
        "theme": {
            "accent": str(theme.get("accent") or "#9E1B32"),
            "font": str(theme.get("font") or "微软雅黑"),
        },
        "slides": slides,
        "fallback": False,
    }


def parse_outline(text: str, title_hint: str = "") -> dict:
    """模型输出 → 大纲 dict；解析不了就启发式兜底。"""
    from services.ppt.pptx_builder import outline_from_markdown

    data = _extract_json(text)
    if data:
        normalized = normalize_outline(data, title_hint)
        if normalized:
            return normalized
    return outline_from_markdown(text, title_hint)


async def resolve_model(user_id: str, model_id: str = "") -> tuple[Optional[dict], str, str, str]:
    """解析成 (模型条目, key, base_url, 错误信息)。模型没配 Key 时给出可读提示。"""
    from config import DEFAULT_MODEL
    from services.state_tracker import tracker

    wanted = (model_id or "").strip()
    if not wanted:
        wanted = (await tracker.get_setting("model", user_id) or "") or DEFAULT_MODEL
    entry = next((m for m in MODELS if m["id"] == wanted), None)
    if entry is None:
        return None, "", "", f"不认识的模型：{wanted}"
    provider = PROVIDERS[entry["provider"]]
    key = (await tracker.get_setting(provider["key_setting"], user_id) or "").strip()
    if not key:
        return None, "", "", f"{provider['display_name']} 还没配 API Key，请到设置里填"
    base = (await tracker.get_setting(provider["base_url_setting"], user_id) or "").strip() \
        or (provider.get("default_base_url") or "")
    return entry, key, base, ""


_YEAR_RE = re.compile(r"^\s*(1[89]\d{2}|20\d{2})\s*年?|^\s*第[一二三四五六七八九十]+阶段")


def suggest_layout(slide: dict) -> str:
    """按"内容形状"猜版式（模型没明确指定时用）。

    模型实测很爱把所有页面都写成 content，导致整份片子一个样；
    这里按要点数量与形态挑更合适的版式，只在它没给明确版式时生效。
    """
    bullets = slide.get("bullets") or []
    texts = [str(b.get("text") if isinstance(b, dict) else b or "").strip() for b in bullets]
    texts = [t for t in texts if t]
    n = len(texts)
    if n == 0:
        return "section"
    if n >= 3 and sum(1 for t in texts if _YEAR_RE.search(t)) >= 3:
        return "timeline"
    if n == 2:
        return "two-col"
    if n == 3 and not any(isinstance(b, dict) and b.get("children") for b in bullets):
        return "cards-3"
    if n == 1:
        only = texts[0]
        if len(only) >= 28:
            return "quote"
        if re.search(r"\d", only) and len(only) <= 24:
            return "big-number"
        return "content"
    return "content"


def normalize_layouts(outline: dict) -> dict:
    """兜底版式：第一页封面、最后一页结尾、没有版式的按内容形状推断。

    模型偶尔漏写 layout，或把封面写成 content；这里统一收口，拼接时才不会挑错样本。
    """
    slides = outline.get("slides") or []
    for i, slide in enumerate(slides):
        layout = str(slide.get("layout") or "").strip().lower()
        if i == 0:
            layout = "cover"
        elif i == len(slides) - 1 and len(slides) > 2:
            layout = "end"
        elif not layout or layout in ("content", "bullets"):
            layout = suggest_layout(slide)
        slide["layout"] = layout
    return outline


def is_degenerate(outline: dict, pages: int = 0) -> str:
    """大纲是不是明显不合格（页数太少 / 标题全一样）。返回原因，合格返回空串。"""
    slides = outline.get("slides") or []
    want = pages if pages and pages > 0 else 8
    floor = max(4, min(6, want // 2))
    if len(slides) < floor:
        return f"只给了 {len(slides)} 页，至少要 {floor} 页"
    titles = [str(s.get("title") or "").strip() for s in slides]
    if len(set(t for t in titles if t)) <= 1 and len(slides) > 2:
        return "所有页面标题都一样"
    if not any(str(s.get("bullets") or "") != "[]" and (s.get("bullets") or []) for s in slides[1:-1] or []):
        return "中间页没有要点"
    return ""


def local_outline(material: str, pages: int = 10, title_hint: str = "") -> dict:
    """本地兜底大纲：模型两次都不给合格结果时，按材料自己切页。

    做法很朴素但稳定：按句子切成若干组，每组 3 条要点一页；
    第一页封面、最后一页结尾，中间页标题取该组第一句的前 20 字。
    """
    import re as _re

    text = _re.sub(r"\s+", " ", (material or "").strip())
    title = (title_hint or "").strip() or (text[:24] if text else "汇报")
    sentences = [s.strip() for s in _re.split(r"(?<=[。！？；;.!?])\s*", text) if len(s.strip()) >= 8]
    if not sentences:
        sentences = [text[i:i + 40] for i in range(0, min(len(text), 800), 40)] or ["（材料为空）"]

    want = max(6, min(14, pages or 10))
    body_pages = max(1, want - 2)
    per_page = max(2, min(4, (len(sentences) + body_pages - 1) // body_pages))
    chunks = [sentences[i:i + per_page] for i in range(0, len(sentences), per_page)][:body_pages]

    slides = [{"layout": "cover", "title": title, "bullets": [],
               "notes": "开场：交代材料来源与本次汇报要回答的问题。"}]
    for index, chunk in enumerate(chunks):
        head = chunk[0][:22] if chunk else f"第 {index + 1} 部分"
        slides.append({
            "layout": "content",
            "title": _re.sub(r"^[一二三四五六七八九十\d]+[、.．)\s]*", "", head) or f"第 {index + 1} 部分",
            "bullets": [{"text": s[:60], "children": []} for s in chunk],
            "notes": "",
        })
    slides.append({"layout": "end", "title": "谢谢", "bullets": [], "notes": "请批评指正。"})
    return {"title": title, "subtitle": "", "theme": {}, "slides": slides}


async def generate_outline(user_id: str, material: str, model_id: str = "",
                           guidance: str = "", pages: int = 0,
                           title_hint: str = "") -> tuple[dict, str, str]:
    """调模型生成大纲。返回 (大纲, 使用的模型名, 错误信息)。

    四个实测得来的处理：
    1. **流式调用**：慢速思考型模型非流式会在读超时前一直没数据，流式持续有分片，不会假超时。
    2. **优先用正式回答**：思考型模型（Kimi K3 / DeepSeek R1）会把思考写进 reasoning_content，
       里面常有半截 JSON 草稿；先解析 content，失败再退回"思考+正文"全文。
    3. **Kimi 关思考**：Moonshot 支持 thinking 开关，关掉后 JSON 落在 content 且快很多。
    4. **退化大纲重试一次**：实测同一素材两次调用，一次 11 页、一次只有 2 页；
       页数太少/标题雷同就带更强的要求再要一次，避免出一份"两页糊弄"的片子。
    """
    from providers import PROVIDERS
    from services.idea_debate import _stream_complete

    entry, key, base, err = await resolve_model(user_id, model_id)
    if err:
        return {}, "", err
    model = {"id": entry["id"], "provider": entry["provider"], "name": entry["name"]}

    extra_body = None
    if entry["provider"] == "moonshot":
        extra_body = {"thinking": {"type": "disabled"}}

    attempt_guidance = guidance
    result: dict = {}
    for attempt in range(2):
        prompt = build_outline_prompt(material, attempt_guidance, pages, title_hint)

        answer_parts: list[str] = []
        thinking_parts: list[str] = []
        error = ""
        async for chunk in _stream_complete(model, key, base, OUTLINE_SYSTEM, prompt,
                                            max_tokens=4000, marker_mode=False,
                                            extra_body=extra_body):
            kind = chunk.get("kind")
            if kind == "error":
                error = chunk.get("delta") or "模型没有返回内容"
                break
            delta = chunk.get("delta") or ""
            (thinking_parts if kind == "thinking" else answer_parts).append(delta)

        if error:
            return {}, entry["name"], error
        answer = "".join(answer_parts).strip()
        combined = ("".join(thinking_parts) + "\n" + answer).strip()
        if not answer and not combined:
            return {}, entry["name"], f"{entry['name']} 没有返回内容"

        result = {}
        for source in (answer, combined):
            if not source:
                continue
            data = _extract_json(source)
            if data:
                normalized = normalize_outline(data, title_hint)
                if normalized:
                    result = normalized
                    break
        if not result:
            from services.ppt.pptx_builder import outline_from_markdown

            result = outline_from_markdown(answer or combined, title_hint)

        result = normalize_layouts(result)
        reason = is_degenerate(result, pages)
        if not reason:
            return result, entry["name"], ""
        if attempt == 1:
            # 两次都不合格 → 不再指望模型，本地按材料切一份兜底大纲（保证页数与结构）
            fallback = local_outline(material, pages, title_hint)
            fallback["fallback"] = True
            return normalize_layouts(fallback), entry["name"], ""
        attempt_guidance = (guidance + "\n" if guidance else "") + (
            f"上一次的输出不合格（{reason}）。这次必须满足："
            f"总页数不少于 {max(6, min(12, (pages or 10)))} 页；"
            "第一页是封面、最后一页是结尾，中间每一页标题各不相同且都有 2–5 条要点；"
            "遇到新的章节先用 section 页分隔再展开。"
        )
    return result, entry["name"], ""
