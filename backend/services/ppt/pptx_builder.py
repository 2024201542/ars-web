"""大纲 → .pptx 生成器（python-pptx）。

设计要点：
1. **不依赖 LibreOffice**：本机没有 soffice 时也能出文件（预览另走 HTML 结构示意）。
2. **中文字体**：python-pptx 的 font.name 只管西文，中文要另设 `a:ea` 字体，否则 WPS 里会回退成宋体。
3. **模板可选**：给了 .pptx 模板就沿用它的版式与配色；没给就用内置 16:9 主题。
4. **溢出保护**：页面上的要点数与字数有上限，超出的内容自动挪到「演讲备注」，不让文字挤出版面。

大纲结构见 services/ppt/pptx_outline.py 的 OUTLINE_SCHEMA 注释。
"""

from __future__ import annotations

import copy
import io
import pathlib
import re
from typing import Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt
from pptx.oxml.ns import qn

# 版面限制（可按需调整）
MAX_BULLETS = 7          # 每页一级要点最多几条
MAX_CHILDREN = 4         # 每条要点下最多几条子项
MAX_BULLET_CHARS = 40    # 每条要点最多多少字（中文按字算）
MAX_SLIDES = 20          # 整份最多多少页

DEFAULT_FONT = "微软雅黑"
DEFAULT_ACCENT = "9E1B32"   # 人大红

_LAYOUT_ALIASES = {
    "title": ("title slide", "标题幻灯片", "扉页", "封面"),
    "content": ("title and content", "标题和内容", "内容"),
    "section": ("section header", "节标题", "分节"),
    "toc": ("content", "内容", "目录"),
    "end": ("blank", "空白", "结束"),
}


def _clean_hex(value: str, fallback: str = DEFAULT_ACCENT) -> str:
    raw = str(value or "").strip().lstrip("#")
    return raw.upper() if re.fullmatch(r"[0-9A-Fa-f]{6}", raw) else fallback


def _set_run_font(run, name: str, size: Optional[int] = None,
                  bold: Optional[bool] = None, color: Optional[str] = None) -> None:
    """设置西文 + 中文字体（中文必须写 a:ea，否则中文不生效）。"""
    run.font.name = name
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = rpr.makeelement(qn(tag), {})
            rpr.append(el)
        el.set("typeface", name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(_clean_hex(color))


def _truncate(text: str, limit: int = MAX_BULLET_CHARS) -> tuple[str, str]:
    """超长文本截断，返回 (显示文本, 溢出部分)。"""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(raw) <= limit:
        return raw, ""
    return raw[:limit] + "…", raw


def _pick_layout(prs: Presentation, kind: str):
    """按名称模糊匹配版式；匹配不到退回索引。"""
    names = _LAYOUT_ALIASES.get(kind, ())
    for layout in prs.slide_layouts:
        lname = (layout.name or "").lower()
        if any(alias in lname for alias in names):
            return layout
    fallback = {"title": 0, "content": 1, "section": 5, "toc": 1, "end": 6}.get(kind, 1)
    try:
        return prs.slide_layouts[fallback]
    except IndexError:
        return prs.slide_layouts[0]


def _title_shape(slide):
    try:
        return slide.shapes.title
    except Exception:
        return None


def _body_placeholder(slide, skip_title: bool = True):
    """找正文占位符：优先 body/object，其次 index=1。"""
    try:
        for ph in slide.placeholders:
            if skip_title and ph.placeholder_format.idx == 0:
                continue
            if ph.placeholder_format.idx == 1:
                return ph
        for ph in slide.placeholders:
            if skip_title and ph.placeholder_format.idx == 0:
                continue
            return ph
    except Exception:
        return None
    return None


def _fill_bullets(text_frame, bullets: list, font: str, size: int, color: str,
                  overflow: list[str]) -> None:
    """把要点写进文本框，支持二级子项；超限的内容进 overflow。"""
    text_frame.clear()
    first = True
    used_top = 0
    for item in bullets:
        if isinstance(item, dict):
            text, children = item.get("text", ""), list(item.get("children") or [])
        else:
            text, children = item, []
        shown, extra = _truncate(text)
        if extra:
            overflow.append(extra)
        if not shown:
            continue
        if used_top >= MAX_BULLETS:
            overflow.append(shown)
            continue
        paragraph = text_frame.paragraphs[0] if first else text_frame.add_paragraph()
        first = False
        run = paragraph.add_run()
        run.text = shown
        _set_run_font(run, font, size, bold=False, color=color)
        paragraph.level = 0
        used_top += 1
        for child in children[:MAX_CHILDREN]:
            cshown, cextra = _truncate(child, MAX_BULLET_CHARS + 20)
            if cextra:
                overflow.append(cextra)
            if not cshown:
                continue
            cp = text_frame.add_paragraph()
            crun = cp.add_run()
            crun.text = cshown
            _set_run_font(crun, font, max(12, size - 4), bold=False, color="595959")
            cp.level = 1
        if len(children) > MAX_CHILDREN:
            overflow.extend(str(c) for c in children[MAX_CHILDREN:])


def _add_accent_bar(slide, color: str, top=Inches(0.92), left=Inches(0.62),
                    width=Inches(1.1), height=Pt(4.5)) -> None:
    try:
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(_clean_hex(color))
        bar.line.fill.background()
        bar.shadow.inherit = False
    except Exception:
        pass


def build_pptx(outline: dict, template_path: Optional[pathlib.Path] = None) -> bytes:
    """按大纲生成 .pptx，返回字节。模板可选（保留模板版式与主题）。"""
    theme = outline.get("theme") or {}
    font = str(theme.get("font") or DEFAULT_FONT)
    accent = _clean_hex(theme.get("accent") or DEFAULT_ACCENT)
    by_template = bool(template_path)

    if by_template:
        prs = Presentation(str(template_path))
    else:
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

    slides = list(outline.get("slides") or [])[:MAX_SLIDES]
    used_layouts = {
        "title": _pick_layout(prs, "title"),
        "content": _pick_layout(prs, "content"),
        "section": _pick_layout(prs, "section"),
        "toc": _pick_layout(prs, "toc"),
        "end": _pick_layout(prs, "end"),
    }

    for index, item in enumerate(slides):
        kind = str(item.get("layout") or ("title" if index == 0 else "content")).lower()
        if kind not in used_layouts:
            kind = "content"
        slide = prs.slides.add_slide(used_layouts[kind])
        notes: list[str] = []
        note_text = str(item.get("notes") or "").strip()
        if note_text:
            notes.append(note_text)

        title_shape = _title_shape(slide)
        if item.get("title"):
            if title_shape is not None:
                title_shape.text_frame.text = ""
                run = title_shape.text_frame.paragraphs[0].add_run()
                run.text = str(item["title"])
                # 模板模式下不改字体，沿用模板；内置主题才设中文字体
                _set_run_font(run, font, None if by_template else 30,
                              bold=True, color=None if by_template else accent)
            else:
                # 有些版式（如空白页）没有标题占位符，补一个文本框，否则标题会丢
                box = slide.shapes.add_textbox(Inches(0.9), Inches(0.6),
                                               prs.slide_width - Inches(1.8), Inches(1.0))
                run = box.text_frame.paragraphs[0].add_run()
                run.text = str(item["title"])
                _set_run_font(run, font, None if by_template else 30,
                              bold=True, color=None if by_template else accent)

        if kind == "title":
            sub = item.get("subtitle") or outline.get("subtitle") or ""
            if sub:
                body = _body_placeholder(slide)
                if body is not None:
                    body.text_frame.clear()
                    run = body.text_frame.paragraphs[0].add_run()
                    run.text = str(sub)
                    _set_run_font(run, font, None if by_template else 18,
                                  color=None if by_template else "595959")
            if not by_template:
                _add_accent_bar(slide, accent, top=Inches(3.05), left=Inches(5.9), width=Inches(1.5), height=Pt(5))
        else:
            bullets = item.get("bullets") or []
            if bullets:
                body = _body_placeholder(slide)
                if body is None:
                    box = slide.shapes.add_textbox(Inches(0.9), Inches(1.6), prs.slide_width - Inches(1.8), prs.slide_height - Inches(2.4))
                    text_frame = box.text_frame
                else:
                    text_frame = body.text_frame
                _fill_bullets(text_frame, bullets, font,
                              18 if by_template else 17, "262626", notes)
            if not by_template and kind not in ("end",):
                _add_accent_bar(slide, accent)

        if notes:
            try:
                slide.notes_slide.notes_text_frame.text = "\n".join(notes)
            except Exception:
                pass

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def outline_from_markdown(text: str, title: str = "") -> dict:
    """兜底：模型没给出合法 JSON 时，用标题/要点启发式拼一份最简大纲。"""
    lines = [l.rstrip() for l in (text or "").splitlines()]
    slides: list[dict] = [{"layout": "title", "title": title or "汇报", "subtitle": ""}]
    current: dict | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if current and current.get("bullets"):
                slides.append(current)
            current = {"layout": "content", "title": stripped.lstrip("# ").strip(), "bullets": []}
        elif re.match(r"^([-*•]|\d+[.、)])\s*", stripped):
            bullet = re.sub(r"^([-*•]|\d+[.、)])\s*", "", stripped)
            if current is None:
                current = {"layout": "content", "title": "要点", "bullets": []}
            current["bullets"].append(bullet)
        elif current is not None:
            current["bullets"].append(stripped)
    if current and current.get("bullets"):
        slides.append(current)
    if len(slides) == 1:
        body = [l.strip() for l in lines if l.strip()][:MAX_BULLETS]
        slides.append({"layout": "content", "title": title or "要点", "bullets": body})
    return {"title": title or "汇报", "subtitle": "", "theme": {}, "slides": slides,
            "fallback": True}
