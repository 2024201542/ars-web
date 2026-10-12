"""读写 .pptx 的幻灯片文字，供预览区"就地修改"用（python-pptx）。

只动文字（标题 / 正文要点 / 演讲备注），不动版式与主题：
- 读：标题占位符 + 正文占位符（index=1 或第一个非标题文本框）+ 备注；
- 写：清空后按 (level, text) 重写，字体沿用原文第一个 run 的字体名，
  原文没有则退回微软雅黑；标题保持加粗。

这样"预览里改几个字 → 存回 pptx"不会把模板的主题色、logo、版式弄丢。
"""

from __future__ import annotations

import pathlib
from typing import Optional

from pptx import Presentation
from pptx.util import Pt

DEFAULT_FONT = "微软雅黑"


def _text_frame_of(slide, want_body: bool):
    """拿标题或正文文本框。"""
    if not want_body:
        try:
            return slide.shapes.title.text_frame if slide.shapes.title is not None else None
        except Exception:
            return None
    try:
        for ph in slide.placeholders:
            if ph.placeholder_format.idx == 1:
                return ph.text_frame
        for ph in slide.placeholders:
            if ph.placeholder_format.idx != 0:
                return ph.text_frame
    except Exception:
        pass
    # 没有占位符（例如空白版式）时，退而取第一个文本框
    for shape in slide.shapes:
        if shape.has_text_frame and shape.text_frame.text.strip():
            try:
                if slide.shapes.title is not None and shape == slide.shapes.title:
                    continue
            except Exception:
                pass
            return shape.text_frame
    return None


def _has_title(slide) -> bool:
    try:
        return slide.shapes.title is not None
    except Exception:
        return False


# 拼出来的 pptx 往往是"文本框标题"（不是占位符），所以这里也用和解析器一样的判断：
# 占位符优先，否则取"页面上部 + 字号最大"的文本框当标题。
SIDE_MARK = "〔右栏〕"      # 两栏页在编辑框里的分栏标记


def _slide_height_in(slide) -> float:
    try:
        return slide.part.package.presentation_part.presentation.slide_height / 914400
    except Exception:
        return 7.5


def _shape_font_size(shape) -> int:
    try:
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                if run.font.size is not None:
                    return int(run.font.size.pt)
    except Exception:
        pass
    return 0


def _candidate_shapes(slide) -> list:
    from services.ppt_template import is_text_candidate

    return [s for s in slide.shapes if is_text_candidate(s)]


def _title_shape(slide):
    """认标题：占位符优先；否则"页面上部最靠上"的那个文本框；只有一两个大字的页（分节/结尾）放宽。"""
    try:
        if slide.shapes.title is not None:
            return slide.shapes.title
    except Exception:
        pass
    height = _slide_height_in(slide)
    cands = _candidate_shapes(slide)
    pool = [s for s in cands if (s.top or 0) / 914400 <= height * 0.3]
    if not pool and len(cands) <= 2:
        pool = [s for s in cands if _shape_font_size(s) >= 20]
    if not pool:
        return None
    best = sorted(pool, key=lambda s: ((s.top or 0), -_shape_font_size(s)))[0]
    return best if _shape_font_size(best) >= 16 else None


def _body_shapes(slide, title_shape) -> list:
    """除标题外的文本框。

    注意：python-pptx 每次遍历 slide.shapes 都会新建包装对象，
    所以必须比较底层 XML 元素，不能用 `is` 比对象身份。
    """
    title_el = getattr(title_shape, "_element", None)
    return [s for s in _candidate_shapes(slide) if s._element is not title_el]


def _side_by_side(left, right) -> bool:
    try:
        lx, lw = (left.left or 0) / 914400, (left.width or 0) / 914400
        rx = (right.left or 0) / 914400
        return lx + lw <= rx + 0.25
    except Exception:
        return False


def read_slides(path: str | pathlib.Path) -> list[dict]:
    """读出一份 pptx 的逐页文字（文本框标题也认；两栏页用〔右栏〕分栏）。"""
    prs = Presentation(str(path))
    slides: list[dict] = []
    for index, slide in enumerate(prs.slides, 1):
        title_shape = _title_shape(slide)
        title = title_shape.text_frame.text.strip() if title_shape is not None else ""
        bullets: list[dict] = []
        prev = None
        for shape in _body_shapes(slide, title_shape):
            if prev is not None and _side_by_side(prev, shape):
                bullets.append({"text": SIDE_MARK, "children": []})
            prev = shape
            for para in shape.text_frame.paragraphs:
                text = "".join(run.text for run in para.runs).strip() or (para.text or "").strip()
                if not text:
                    continue
                level = int(getattr(para, "level", 0) or 0)
                if level <= 0 or not bullets:
                    bullets.append({"text": text, "children": []})
                else:
                    bullets[-1]["children"].append(text)
        notes = ""
        try:
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
        except Exception:
            notes = ""
        slides.append({"index": index, "title": title, "bullets": bullets, "notes": notes})
    return slides


def _font_name_from(frame) -> str:
    try:
        for para in frame.paragraphs:
            for run in para.runs:
                if run.font.name:
                    return run.font.name
    except Exception:
        pass
    return DEFAULT_FONT


def _write_lines(frame, lines: list[tuple[int, str]], font: str, title: bool) -> None:
    frame.clear()
    first = True
    for level, text in lines:
        para = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        run = para.add_run()
        run.text = text
        para.level = 0 if title else level
        try:
            run.font.name = font
            if title:
                run.font.bold = True
            elif level > 0:
                run.font.size = Pt(14)
            else:
                run.font.size = Pt(17)
        except Exception:
            pass


def write_slides(path: str | pathlib.Path, slides: list[dict]) -> int:
    """把改过的文字写回 pptx（版式/主题不动），返回实际改到的页数。"""
    target = pathlib.Path(path)
    prs = Presentation(str(target))
    changed = 0
    for pos, slide in enumerate(prs.slides):
        if pos >= len(slides):
            break
        item = slides[pos] or {}

        title_shape = _title_shape(slide)
        if title_shape is not None and str(item.get("title") or "").strip():
            font = _font_name_from(title_shape.text_frame)
            _write_lines(title_shape.text_frame, [(0, str(item["title"]).strip())], font, title=True)

        # 正文：按〔右栏〕切成若干组，分别写回对应的文本框（两栏页才不会串位）
        bodies = _body_shapes(slide, title_shape)
        groups: list[list[tuple[int, str]]] = [[]]
        for bullet in item.get("bullets") or []:
            text = str(bullet.get("text") if isinstance(bullet, dict) else bullet).strip()
            if text == SIDE_MARK:
                groups.append([])
                continue
            if not text:
                continue
            groups[-1].append((0, text))
            if isinstance(bullet, dict):
                for child in bullet.get("children") or []:
                    child_text = str(child).strip()
                    if child_text:
                        groups[-1].append((1, child_text))
        for pos_body, group in enumerate(groups[: len(bodies)]):
            if not group:
                continue
            frame = bodies[pos_body].text_frame
            _write_lines(frame, group, _font_name_from(frame), title=False)

        notes_text = str(item.get("notes") or "").strip()
        if notes_text:
            try:
                slide.notes_slide.notes_text_frame.text = notes_text
            except Exception:
                pass
        changed += 1
    prs.save(str(target))
    return changed
