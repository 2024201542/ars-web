"""模板拼接（M1 核心）：按大纲挑"版式样本页" → 克隆 → 替换文字。

思路借自 PPTAgent 的"参考模板 → 结构解析 → 保真填充"，但在本项目里自己实现：
- 用 `copy.deepcopy` 复制样本页的形状（含图片/表格/装饰图形），所以**外观与模板一致**；
- 只替换文字（标题 / 正文要点 / 备注），并把新 run 的字体、字号、加粗、颜色
  设成样本里原来的样式，避免"填进去的字像贴上去的"；
- 破坏性最小：原模板页在生成后会被删除，产物只含克隆出来的页。

降级规则（宁可少字也不破坏版面）：
- 要点比样本容量多 → 多出的写进演讲备注，并在 warnings 里报；
- 要点比样本容量少 → 直接少写，空段落清掉；
- 找不到正文框（纯标题页）→ 只写标题。
"""

from __future__ import annotations

import copy
import pathlib
import re
import tempfile
import uuid
from typing import Optional

from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn

from services.ppt import ppt_template

R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# ────────────────────────── 克隆 ──────────────────────────

def _remap_rel_ids(element, id_map: dict[str, str]) -> None:
    """把复制出来的形状里引用的 rId 换成新页里的 rId（图片/图表/超链接要用）。"""
    if not id_map:
        return
    for node in element.iter():
        for attr, value in list(node.attrib.items()):
            if attr.startswith(f"{{{R_NS}}}") and value in id_map:
                node.set(attr, id_map[value])


def _clone_slide(prs: Presentation, src):
    """复制一页（形状 + 图片关系 + 备注），返回新页。"""
    dest = prs.slides.add_slide(src.slide_layout)
    # 去掉版式自动带进来的占位符，避免多出空框
    for shape in list(dest.shapes):
        shape._element.getparent().remove(shape._element)
    for shape in src.shapes:
        dest.shapes._spTree.append(copy.deepcopy(shape._element))

    id_map: dict[str, str] = {}
    for rel in src.part.rels.values():
        if rel.reltype in (RT.SLIDE_LAYOUT, RT.NOTES_SLIDE):
            continue
        try:
            if rel.is_external:
                new_id = dest.part.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref)
            else:
                new_id = dest.part.rels.get_or_add(rel.reltype, rel._target)
        except Exception:
            continue
        id_map[rel.rId] = new_id
    _remap_rel_ids(dest.shapes._spTree, id_map)

    try:
        if src.has_notes_slide:
            text = src.notes_slide.notes_text_frame.text.strip()
            if text:
                dest.notes_slide.notes_text_frame.text = text
    except Exception:
        pass
    return dest


def _delete_slides(prs: Presentation, count: int) -> None:
    """删掉模板原本的前 count 页（产物只保留克隆页）。"""
    sld_id_lst = prs.slides._sldIdLst
    for element in list(sld_id_lst)[:count]:
        r_id = element.get(f"{{{R_NS}}}id")
        try:
            prs.part.drop_rel(r_id)
        except Exception:
            pass
        sld_id_lst.remove(element)


# ────────────────────────── 填字 ──────────────────────────

MARKER_RE = re.compile(r"^\s*([▪·•◦●○\-–—*]|\d+[.、)）]|[（(]\d+[)）])\s*")
# "前提：国家是产权界定的前提" 这类带标签的要点，拆成"小标题 + 说明"两行，
# 填进卡片/两栏样本里才不会显得空（样本本身就是"标题 + 两行说明"的结构）。
LABEL_RE = re.compile(r"^([^：:]{1,12})[：:]\s*(.{2,})$")


def _expand_for_slot(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for level, text in lines:
        match = LABEL_RE.match(text.strip())
        if match:
            out.append((0, match.group(1).strip()))
            out.append((1, match.group(2).strip()))
        else:
            out.append((level, text))
    return out


def _frames(slide) -> list:
    """按与解析时相同的顺序取文本框（同一条 is_text_candidate 规则，索引才对得上）。"""
    return [s for s in slide.shapes if ppt_template.is_text_candidate(s)]


def _para_prefix(text: str) -> str:
    """样本段落开头的项目符号/编号（▪ · 1. 之类），填字时保留。"""
    match = MARKER_RE.match(text or "")
    return match.group(0) if match else ""


def _fill_frame(frame, lines: list[tuple[int, str]], *, keep_bold: Optional[bool] = None,
                add_prefix: bool = True, size_scale: float = 1.0) -> None:
    """用**样本自己的段落**当容器来填字。

    比"清空重写"讲究的地方：
    - 段落级格式（缩进、段前距、项目符号、行距）留在原段落上，不会被抹掉；
    - 每个新 run 复制样本同序号段的 run 属性（字号/字重/颜色/字体）；
    - 样本里的项目符号前缀（"▪ "、"1. "）跟着保留，版面观感才一致；
    - 行数多了就克隆最后一段（连 pPr 一起），少了就删掉多余段落。
    """
    tx_body = frame._txBody
    p_elems = list(tx_body.findall(qn("a:p")))
    if not p_elems or not lines:
        return

    samples: list[dict] = []
    for el in p_elems:
        el_text = "".join(t.text or "" for t in el.iter(qn("a:t")))
        run = el.find(qn("a:r"))
        rpr = None
        if run is not None:
            rpr_el = run.find(qn("a:rPr"))
            if rpr_el is not None:
                rpr = copy.deepcopy(rpr_el)
        samples.append({"prefix": _para_prefix(el_text), "rpr": rpr})

    # 段落不够 → 克隆最后一段（带 pPr）
    while len(p_elems) < len(lines):
        clone = copy.deepcopy(p_elems[-1])
        p_elems[-1].addnext(clone)
        p_elems = list(tx_body.findall(qn("a:p")))
        samples.append({"prefix": "", "rpr": samples[-1]["rpr"]})
    # 段落多了 → 删掉
    for el in p_elems[len(lines):]:
        tx_body.remove(el)
    p_elems = list(tx_body.findall(qn("a:p")))

    for i, (level, text) in enumerate(lines):
        el = p_elems[i]
        for child in list(el):
            if child.tag != qn("a:pPr"):
                el.remove(child)
        rpr = samples[i]["rpr"]
        if rpr is None:
            rpr = el.makeelement(qn("a:rPr"), {"lang": "zh-CN", "dirty": "0"})
        if keep_bold is not None:
            rpr.set("b", "1" if keep_bold else "0")
        # 长标题按比例缩小字号，避免溢出到幻灯片外（封面长标题实测会跑到边界外）
        if size_scale and abs(size_scale - 1.0) > 0.01:
            try:
                size = rpr.get("sz")
                if size:
                    rpr.set("sz", str(max(800, int(int(size) * size_scale))))
            except Exception:
                pass
        run = el.makeelement(qn("a:r"), {})
        run.append(rpr)
        node = el.makeelement(qn("a:t"), {})
        prefix = samples[i]["prefix"] if add_prefix else ""
        node.text = f"{prefix}{text}"
        run.append(node)
        el.append(run)
        ppr = el.find(qn("a:pPr"))
        if ppr is not None:
            try:
                ppr.set("lvl", str(max(0, int(level))))
            except Exception:
                pass


def _set_notes(slide, text: str) -> None:
    if not text.strip():
        return
    try:
        slide.notes_slide.notes_text_frame.text = text
    except Exception:
        pass


def _slide_text(slide) -> str:
    parts = []
    for shape in slide.shapes:
        if shape.has_text_frame:
            parts.append(shape.text_frame.text.strip())
    return "".join(parts).strip()


def _ensure_not_empty(slide, title_text: str, lines: list[tuple[int, str]], accent: str) -> bool:
    """设计模板的标题框可能选偏，导致整页写不进去 → 补一个文本框，绝不留空白页。

    返回 True 表示补写了。
    """
    if _slide_text(slide):
        return False
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    from services.ppt.pptx_builder import _set_run_font

    body = slide.shapes.add_textbox(Inches(0.8), Inches(1.1), Inches(11.7), Inches(5.6))
    tf = body.text_frame
    tf.word_wrap = True
    items = ([title_text] if title_text else []) + [text for _, text in lines]
    for i, text in enumerate(items):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = para.add_run()
        run.text = text
        if i == 0:
            _set_run_font(run, "微软雅黑", size=28, bold=True, color=accent)
        else:
            _set_run_font(run, "微软雅黑", size=16, color="262626")
        para.space_after = Pt(8)
    return True


def _blips(slide) -> list:
    """按 XML 顺序取这一页所有的图片引用元素（与解析时的序号一一对应）。"""
    return [b for b in slide._element.iter(qn("a:blip")) if b.get(qn("r:embed"))]


def _replace_picture(slide, slot_index: int, image_path: str, slot_ratio: float) -> bool:
    """把第 slot_index 张图换成我们的图（先按位比例裁好，避免被拉伸变形）。

    用 XML 里的 blip 序号定位，所以"组合里的图 / 形状的图片填充 / 页面底图"都能替换。
    """
    from services.ppt import ppt_image

    blips = _blips(slide)
    if slot_index >= len(blips):
        return False
    fitted = ppt_image.fit_to_slot(
        image_path, slot_ratio or 1.0,
        pathlib.Path(tempfile.gettempdir()) / f"ppt_fit_{uuid.uuid4().hex[:8]}.png",
    )
    source = fitted or pathlib.Path(image_path)
    try:
        _image_part, r_id = slide.part.get_or_add_image_part(str(source))
    except Exception:
        return False
    blips[slot_index].set(qn("r:embed"), r_id)
    return True


def _add_picture(slide, image_path: str, orient: str, slide_w: float, slide_h: float) -> bool:
    """给**没有图片位**的页新加一张图（③ 之外补的：截图模板/纯文字页也能配图）。

    位置规则（保守，尽量不压到文字）：
    - 竖图 → 右侧 1/3 竖条（x 从 68% 开始）；
    - 横图 / 方图 → 底部通栏（占下半部分，高度 30%）。
    图片先按目标框比例裁好，避免变形。
    """
    from services.ppt import ppt_image
    from pptx.util import Inches

    try:
        if orient in ("portrait", "tall"):
            left, top = slide_w * 0.665, slide_h * 0.20
            width, height = slide_w * 0.30, slide_h * 0.62
        else:
            left, top = slide_w * 0.075, slide_h * 0.585
            width, height = slide_w * 0.85, slide_h * 0.31
        fitted = ppt_image.fit_to_slot(
            image_path, width / height if height else 1.0,
            pathlib.Path(tempfile.gettempdir()) / f"ppt_add_{uuid.uuid4().hex[:8]}.png",
        )
        source = fitted or pathlib.Path(image_path)
        slide.shapes.add_picture(str(source), Inches(left), Inches(top),
                                 Inches(width), Inches(height))
        return True
    except Exception:
        return False


# 模板自带的占位文字（没被我们填过的框里若是这些，就清掉——
# 否则成品里会留着"添加标题内容""ADD A TITLE"这种尴尬字样）
PLACEHOLDER_RE = re.compile(
    r"添加标题|添加副标题|添加文字|请输入|点击输入|单击此处|此处输入|在此输入|输入文字|输入标题"
    r"|您的内容|内容打在这里|键入|示例文字|标题文字|正文文字|占位|replace\s*text"
    r"|add\s*a?\s*title|lorem\s*ipsum|click\s+to\s+add|your\s+text\s+here|sample\s+text"
    r"|click\s+here|enter\s+your\s+text|change\s+the\s+color|type\s+your\s+text|insert\s+text",
    re.IGNORECASE,
)


def _scrub_placeholders(slide, keep_indices: set[int], force: bool = False) -> int:
    """把没被我们写过的文本框里的"模板占位文字"清空，返回清掉的框数。

    force=True 时（封面/结尾页）不看内容，**凡是没写过的一律清空**——
    那些页上剩下的都是模板示例（实测留着别人的"指导教师：某某某"）。
    """
    scrubbed = 0
    for index, shape in enumerate(ppt_template._iter_text_shapes(slide)):
        if index in keep_indices:
            continue
        try:
            text = shape.text_frame.text or ""
        except Exception:
            continue
        if not text.strip():
            continue
        if force or PLACEHOLDER_RE.search(text):
            try:
                _fill_frame(shape.text_frame, [(0, "")], add_prefix=False)
                scrubbed += 1
            except Exception:
                continue
    return scrubbed


def _want_tag(slide: dict) -> str:
    """大纲里的一页想要什么版式。"""
    layout = str(slide.get("layout") or "").strip().lower()
    mapping = {
        "title": ppt_template.TAG_COVER, "cover": ppt_template.TAG_COVER,
        "toc": ppt_template.TAG_TOC, "section": ppt_template.TAG_SECTION,
        "end": ppt_template.TAG_END, "two-col": ppt_template.TAG_TWO_COL,
        "two_col": ppt_template.TAG_TWO_COL, "quote": ppt_template.TAG_QUOTE,
        "big-number": ppt_template.TAG_BIG_NUMBER, "image+text": ppt_template.TAG_IMAGE_TEXT,
        "cards-3": ppt_template.TAG_CARDS, "cards": ppt_template.TAG_CARDS,
        "timeline": ppt_template.TAG_TIMELINE,
        "content": "", "bullets": "",
    }
    if layout in mapping and mapping[layout]:
        return mapping[layout]
    n = len(slide.get("bullets") or [])
    if n <= 0:
        return ppt_template.TAG_SECTION
    return f"{ppt_template.TAG_BULLETS}-{max(1, min(7, n))}"


def _flatten_bullets(bullets) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for bullet in bullets or []:
        if isinstance(bullet, dict):
            text = str(bullet.get("text") or "").strip()
            if text:
                lines.append((0, text))
            for child in bullet.get("children") or []:
                child_text = str(child).strip()
                if child_text:
                    lines.append((1, child_text))
        else:
            text = str(bullet).strip()
            if text:
                lines.append((0, text))
    return lines


# ────────────────────────── 主流程 ──────────────────────────

def splice(analysis: dict, outline: dict, template_path: str | pathlib.Path,
           out_path: str | pathlib.Path, images: list[str] | None = None) -> dict:
    """按模板风格生成 pptx。返回 {pages, used_tags, warnings, images_used}。

    images 给了就按"图片位"填图：每页挑一张比例最接近的，按位比例裁好再塞进去。
    """
    template = pathlib.Path(template_path)
    out = pathlib.Path(out_path)
    prs = Presentation(str(template))
    original_count = len(prs.slides)

    # 图片素材：先读元信息（比例/方位），后面按位匹配
    from services.ppt import ppt_image

    assets = ppt_image.collect([str(p) for p in (images or [])])
    used_images: set[str] = set()
    images_used: list[str] = []
    images_added = 0
    placeholders_removed = 0

    slides = outline.get("slides") or []
    deck_subtitle = str(outline.get("subtitle") or "").strip()
    plan: list[tuple[object, dict, dict]] = []   # (克隆页, 样本, 大纲页)
    warnings: list[str] = []

    for item in slides:
        tag = _want_tag(item)
        # 这一页大概要写多少字（标题 + 要点），用来挑"装得下"的样本页
        needed = len(str(item.get("title") or "")) + sum(
            len(str(b.get("text") if isinstance(b, dict) else b))
            for b in (item.get("bullets") or [])
        )
        spec = ppt_template.pick_specimen(analysis, tag, needed_chars=needed)
        # 目录页专用判断：卡片式的"框架页"（一堆小框）装不下目录条目，
        # 实测会挤成一团、还留着模板自己的示例字 → 改用简版要点页
        if spec is not None and tag == ppt_template.TAG_TOC and len(spec.get("bodies_i") or []) > 3:
            alt_tag = f"{ppt_template.TAG_BULLETS}-{max(2, min(7, len(item.get('bullets') or []) or 4))}"
            alt = ppt_template.pick_specimen(analysis, alt_tag, needed_chars=needed)
            if alt is not None:
                spec = alt
                warnings.append("目录页改用简版要点页（原页是卡片框，装不下目录条目）")
        if spec is None:
            warnings.append("模板里没有可用样本页，已跳过一页")
            continue
        # 有配图时优先挑"带图片位"的样本页：同一套模板里换一页，比往没图位的页硬塞安全。
        # 但封面/目录/结尾不换（换了整份片子就没骨架了），只在内容型页面上换。
        swappable = (
            spec["tag"].startswith(ppt_template.TAG_BULLETS)
            or spec["tag"] in (ppt_template.TAG_CONTENT, ppt_template.TAG_TWO_COL, ppt_template.TAG_SECTION)
        )
        if assets and swappable and not spec.get("image_usable"):
            alternative = next(
                (s for s in (analysis.get("specimens") or [])
                 if s.get("image_usable") and s["tag"] in (tag, ppt_template.TAG_IMAGE_TEXT, ppt_template.TAG_TWO_COL)),
                None,
            )
            if alternative is not None:
                spec = alternative
        if spec["tag"] != tag:
            warnings.append(f"「{item.get('title') or '未命名'}」想用 {tag}，模板里用了 {spec['tag']}")
        src_slide = prs.slides[spec["index"]]
        clone = _clone_slide(prs, src_slide)
        plan.append((clone, spec, item))

    if not plan:
        raise ValueError("模板里没有可用的版式样本")

    _delete_slides(prs, original_count)

    for clone, spec, item in plan:
        shapes = _frames(clone)
        tf = [s.text_frame for s in shapes]          # 索引与解析时一一对应
        title_text = str(item.get("title") or "").strip()
        lines = _flatten_bullets(item.get("bullets"))
        capacity = max(1, int(spec.get("capacity") or 1))
        overflow_lines: list[tuple[int, str]] = []

        title_i = spec.get("title_i")
        body_i = spec.get("body_i")
        body2_i = spec.get("body2_i")

        written: set[int] = set()

        def write(idx, payload, *, bold=None, prefix=True, scale=1.0):
            if idx is None or idx >= len(tf) or not payload:
                return
            # 按"框能装多少字"再压一次字号：不够就缩，避免字挤在一起/溢出
            if scale > 0.61:
                try:
                    shape = shapes[idx]
                    width_in = (shape.width or 0) / 914400
                    height_in = (shape.height or 0) / 914400
                    sample_pt = 16.0
                    for para in tf[idx].paragraphs:
                        for run in para.runs:
                            if run.font.size is not None:
                                sample_pt = float(run.font.size.pt)
                                break
                        else:
                            continue
                        break
                    char_w = max(6.0, sample_pt) / 72.0
                    cap = max(1, int(width_in / char_w)) * max(1, int(height_in / (char_w * 1.45)))
                    need = sum(len(t) for _, t in payload)
                    if need > cap:
                        import math

                        scale = max(0.62, min(scale, math.sqrt(cap / need)))
                except Exception:
                    pass
            _fill_frame(tf[idx], payload, keep_bold=bold, add_prefix=prefix, size_scale=scale)
            written.add(idx)

        # 标题：太长就缩字号（封面长标题会溢出到幻灯片外）
        if title_text:
            scale = 1.0
            if len(title_text) > 16:
                scale = 0.82 if len(title_text) <= 24 else 0.66
            write(title_i, [(0, title_text)], bold=True, scale=scale)

        # 封面副标题
        if spec["tag"] == ppt_template.TAG_COVER and not lines and deck_subtitle:
            write(body_i, [(0, deck_subtitle)], bold=False)

        # 正文
        if lines:
            bodies_i = [i for i in (spec.get("bodies_i") or [body_i, body2_i]) if i is not None]
            if len(bodies_i) >= 2 and len(lines) >= 2 and spec["tag"] not in (
                    ppt_template.TAG_BIG_NUMBER, ppt_template.TAG_QUOTE):
                # 多框页（目录卡片、并列框…）：**一条要点填一个框**。
                # 之前只往第一个框里灌，结果挤成一团、后面的框还空着（目录页实测踩过）。
                for slot, idx in enumerate(bodies_i):
                    if slot < len(lines):
                        write(idx, [lines[slot]])
                if len(lines) > len(bodies_i):
                    overflow_lines = lines[len(bodies_i):]
            elif spec["tag"] in (ppt_template.TAG_TWO_COL, ppt_template.TAG_CARDS) and len(bodies_i) >= 2:
                # 两栏 / 多卡片：要点按栏数均分；带标签的要点拆成"小标题 + 说明"
                slots = len(bodies_i)
                size = (len(lines) + slots - 1) // slots
                for slot, idx in enumerate(bodies_i):
                    group = lines[slot * size:(slot + 1) * size]
                    if group:
                        write(idx, _expand_for_slot(group))
            elif body_i is not None:
                if spec["tag"] == ppt_template.TAG_BIG_NUMBER:
                    # 大数字页：第一条进大字号框，其余进说明框（没有就进备注）
                    write(body_i, [lines[0]])
                    rest = lines[1:]
                    if rest and body2_i is not None:
                        write(body2_i, [(0, " ".join(t for _, t in rest))])
                    else:
                        overflow_lines = rest
                elif spec["tag"] == ppt_template.TAG_QUOTE:
                    write(body_i, [(0, " ".join(t for _, t in lines))])
                else:
                    # 竖排列表（中文模板常见：一条要点一个文本框）→ 一条一个框，多的进备注
                    if len(bodies_i) >= 2:
                        for slot, idx in enumerate(bodies_i):
                            write(idx, [lines[slot]] if slot < len(lines) else [(0, "")])
                        overflow_lines = lines[len(bodies_i):]
                    else:
                        # 容量 = 样本里显示了几条；超出部分进备注
                        sample_capacity = int(spec.get("capacity") or 0) or capacity
                        title_lines = [ln for ln in lines if ln[0] == 0]
                        keep = title_lines[:sample_capacity] if sample_capacity else title_lines
                        overflow_lines = title_lines[len(keep):]
                        children = [ln for ln in lines if ln[0] == 1]   # 子项跟着保留的要点
                        write(body_i, keep + children)
            else:
                overflow_lines = lines

        # 备注：大纲备注 + 放不下的要点
        notes_parts = [str(item.get("notes") or "").strip()]
        if overflow_lines:
            extra = "\n".join(f"· {t}" for _, t in overflow_lines)
            notes_parts.append(f"（以下内容版面放不下，放在备注里）\n{extra}")
        _set_notes(clone, "\n\n".join(p for p in notes_parts if p))

        # 清洗残留的模板占位文字：只保留**真正写过**的框，其余带占位字样的框一律清空
        keep = set(written) | {i for i in [title_i, body_i, body2_i] if i is not None and i in written}
        # 封面/结尾这类页面上剩下的文字基本都是模板自带的示例（含示例人名），一律清掉
        force_clear = spec["tag"] in (ppt_template.TAG_COVER, ppt_template.TAG_END)
        scrubbed = _scrub_placeholders(clone, keep, force=force_clear)
        if scrubbed:
            placeholders_removed += scrubbed

        # 兜底：这一页一个字都没写进去 → 补文本框，避免空白页
        if not _slide_text(clone):
            accent = (analysis.get("theme") or {}).get("accent") or "9E1B32"
            if _ensure_not_empty(clone, title_text, lines, accent):
                warnings.append(f"「{title_text or '未命名'}」那页的标题框没识别到，已改用默认排版")

        # 填图：这一页有图片位、我们还有没用过的图 → 挑比例最接近的填进去
        if assets and spec.get("image_i") is not None:
            slot = next((s for s in (spec.get("images") or []) if s["i"] == spec["image_i"]), None)
            ratio = (slot or {}).get("ratio") or spec.get("image_ratio") or 1.0
            picked = ppt_image.pick_for_slot(assets, ratio, used_images)
            if picked and _replace_picture(clone, int(spec["image_i"]), picked["path"], ratio):
                used_images.add(picked["path"])
                images_used.append(picked["name"])

        # 这一页没有可用图片位、但还有图没用完 → 直接加一张（页面不太挤时才加，最多加 3 页）
        elif (assets and images_added < 3
              and spec["tag"] not in (ppt_template.TAG_COVER, ppt_template.TAG_TOC, ppt_template.TAG_END)
              and len([f for f in (spec.get("frames") or []) if f["i"] != spec.get("title_i")]) <= 2):
            leftover = ppt_image.pick_for_slot(assets, 1.0, used_images)
            if leftover and _add_picture(clone, leftover["path"], leftover["orient"],
                                         analysis.get("slide_width") or 13.333,
                                         analysis.get("slide_height") or 7.5):
                used_images.add(leftover["path"])
                images_used.append(leftover["name"])
                images_added += 1

    prs.save(str(out))
    used = [spec["tag"] for _, spec, _ in plan]
    return {
        "pages": len(plan),
        "used_tags": used,
        "warnings": warnings,
        "template": template.name,
        "images_used": images_used,
        "images_added": images_added,
        "placeholders_removed": placeholders_removed,
        "images_available": len(assets),
    }
