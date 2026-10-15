"""按模板底板配色，把内容排进安全区的版式库。

底板（页眉、红条、校徽、页码）由阶段 4 从模板复制；这里只负责在
`base["safe_area"]` 里画内容。颜色一律从 `base["colors"]` 取，不写死。

放不下就抛 `Overflow`，不把字号缩到看不清——
字数超上限、数组条数超范围、字号降到下限还放不下（含换行后最后一行只剩一两个字），
三种情况都交给"改短"那一步处理。
"""

from __future__ import annotations

import math
import re

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LINE_GRAY = RGBColor(0xD9, 0xD9, 0xD9)

BASE_WIDTH = 13.33      # 字数上限表按这个宽度的模板给，窄模板按比例缩
BODY_MIN_PT = 13        # 正文字号下限
TITLE_MIN_PT = 18       # 标题字号下限
PIC_SLOT_NAME = "ppt_pic_slot"   # 图文页图片位占位框的名字，阶段 4 按它换真图

# 字数不计标点和空白：计划里的示例标题「所有权悖论：产权离不开国家，也容易被国家侵蚀」
# 连着标点是 22 个字符，按汉字算是 20 字，正好等于上限。
_PUNCT = set("，。、；：？！“”‘’（）《》〈〉【】—…·,.;:?!\"'()[]{}<>~`-—_/\\|　 \t\r\n")

# 中文排版里占全角宽的符号（按半宽估会算少）
_WIDE_SYMBOLS = set("→←↑↓%℃°±×÷≈≠≤≥∞§¶※★☆●○■□▲△▼▽")


class Overflow(Exception):
    """版式放不下。limit 为 None 表示"降字号到底仍放不下"。"""

    def __init__(self, field: str, text: str, limit: int | None):
        self.field = field
        self.text = text
        self.limit = limit
        detail = f"超过上限 {limit} 字" if limit is not None else "放不下"
        super().__init__(f"{field}：{detail}（{str(text)[:24]}）")


# ───────────── 字段上限表 ─────────────
# 12 种版式共用这一张表：阶段 3 用它生成提示词、校验计划、让界面显示「12/20」。
# 上限按"字"算，标点和空白不计（见 text_len）。
# 约定：有 item 的字段是对象数组（递归校验子字段）；有 limit 又有 min/max 的是字符串数组；
# 有 group 的是嵌套对象（如对比的左右栏）；optional 的字段可以为空。

LAYOUT_SPECS: dict[str, dict] = {
    "cover": {
        "name": "封面", "use": "第一页",
        "fields": [
            {"key": "title", "label": "标题", "limit": 14},
            {"key": "subtitle", "label": "副标题", "limit": 22},
            {"key": "info", "label": "信息行", "limit": 16, "min": 1, "max": 2},
        ],
    },
    "toc": {
        "name": "目录", "use": "汇报框架，3–6 个章节",
        "fields": [
            {"key": "title", "label": "标题", "limit": 20},
            {"key": "items", "label": "章节", "min": 3, "max": 6, "item": [
                {"key": "label", "label": "名称", "limit": 6},
                {"key": "desc", "label": "说明", "limit": 12},
            ]},
        ],
    },
    "section": {
        "name": "章节页", "use": "每一章前面",
        "fields": [
            {"key": "index", "label": "序号", "limit": 2},
            {"key": "title", "label": "标题", "limit": 6},
            {"key": "subs", "label": "小节", "limit": 10, "min": 1, "max": 3},
        ],
    },
    "cards": {
        "name": "卡片", "use": "2–4 个并列要点",
        "fields": [
            {"key": "title", "label": "标题", "limit": 20},
            {"key": "cards", "label": "卡片", "min": 2, "max": 4, "item": [
                {"key": "key", "label": "卡片名", "limit": 6},
                {"key": "desc", "label": "说明", "limit": 28},
            ]},
            {"key": "takeaway", "label": "小结", "limit": 34, "optional": True},
        ],
    },
    "compare": {
        "name": "对比", "use": "前后、正反、两派",
        "fields": [
            {"key": "title", "label": "标题", "limit": 20},
            {"key": "left", "label": "左栏", "group": [
                {"key": "head", "label": "栏标题", "limit": 8},
                {"key": "points", "label": "条目", "limit": 18, "min": 2, "max": 4},
            ]},
            {"key": "right", "label": "右栏", "group": [
                {"key": "head", "label": "栏标题", "limit": 8},
                {"key": "points", "label": "条目", "limit": 18, "min": 2, "max": 4},
            ]},
        ],
    },
    "timeline": {
        "name": "时间轴", "use": "3–6 个年份或阶段",
        "fields": [
            {"key": "title", "label": "标题", "limit": 20},
            {"key": "nodes", "label": "节点", "min": 3, "max": 6, "item": [
                {"key": "year", "label": "年份", "limit": 6},
                {"key": "head", "label": "小标题", "limit": 6},
                {"key": "desc", "label": "说明", "limit": 10},
            ]},
        ],
    },
    "quote": {
        "name": "金句", "use": "原文里一句有分量的话",
        "fields": [
            {"key": "title", "label": "标题", "limit": 20},
            {"key": "quote", "label": "引文", "limit": 40},
            {"key": "source", "label": "出处", "limit": 20, "optional": True},
            {"key": "note", "label": "解读", "limit": 40, "optional": True},
        ],
    },
    "numbered": {
        "name": "编号结论", "use": "结论、建议、步骤",
        "fields": [
            {"key": "title", "label": "标题", "limit": 20},
            {"key": "rows", "label": "条目", "min": 2, "max": 4, "item": [
                {"key": "head", "label": "小标题", "limit": 9},
                {"key": "desc", "label": "说明", "limit": 30},
            ]},
        ],
    },
    "bullets": {
        "name": "要点", "use": "归不了类的要点",
        "fields": [
            {"key": "title", "label": "标题", "limit": 20},
            {"key": "points", "label": "要点", "limit": 30, "min": 3, "max": 5},
        ],
    },
    "bignum": {
        "name": "大数字", "use": "有关键数字",
        "fields": [
            {"key": "title", "label": "标题", "limit": 20},
            {"key": "stats", "label": "数字", "min": 1, "max": 3, "item": [
                {"key": "value", "label": "数值", "limit": 6},
                {"key": "label", "label": "名称", "limit": 10},
                {"key": "desc", "label": "说明", "limit": 24},
            ]},
        ],
    },
    "image_text": {
        "name": "图文", "use": "有配图",
        "fields": [
            {"key": "title", "label": "标题", "limit": 20},
            {"key": "image", "label": "图片序号", "limit": 3, "optional": True},
            {"key": "points", "label": "要点", "limit": 24, "min": 2, "max": 4},
        ],
    },
    "end": {
        "name": "结尾", "use": "最后一页",
        "fields": [
            {"key": "info", "label": "信息行", "limit": 16, "min": 1, "max": 2},
        ],
    },
}

# 走底板换字的版式（封面、章节页、结尾），阶段 4 按 base["slots"] 改字，不走版式库
PLAIN_LAYOUTS = ("cover", "section", "end")


def text_len(text) -> int:
    """字段字数：不计标点和空白，供校验和界面显示「12/20」共用。"""
    return sum(1 for ch in str(text) if ch not in _PUNCT)


def truncate(text, limit: int, ellipsis: str = "…") -> str:
    """按字数截到上限内，末尾一小段里有标点就从那儿断开。

    给"超限了先把这页画出来"用（出片时按上限重画、阶段 3 的 hard_trim 兜底），
    所以只在字数超限时动刀。
    """
    raw = str(text or "")
    if limit <= 0 or text_len(raw) <= limit:
        return raw
    kept: list[str] = []
    count = 0
    for ch in raw:
        if ch not in _PUNCT:
            if count >= limit:
                break
            count += 1
        kept.append(ch)
    cut = "".join(kept).rstrip()
    for i in range(len(cut) - 1, max(-1, len(cut) - 10), -1):
        if cut[i] in _PUNCT:
            return cut[:i + 1]
    return cut + ellipsis


def _scale(base: dict | None) -> float:
    """窄模板按宽度比例缩字数上限；比基准宽的模板不放大。"""
    size = (base or {}).get("slide_size") or [BASE_WIDTH, 7.5]
    try:
        width = float(size[0])
    except (TypeError, ValueError, IndexError):
        width = BASE_WIDTH
    if width <= 0:
        width = BASE_WIDTH
    return min(1.0, width / BASE_WIDTH)


def _scaled(limit: int, scale: float) -> int:
    return max(1, math.floor(limit * scale))


def limits_of(layout: str, base: dict | None = None) -> dict[str, int]:
    """该版式每个字段的字数上限，键是字段路径（如 cards[].desc、left.points[]）。"""
    spec = LAYOUT_SPECS.get(layout)
    if not spec:
        return {}
    scale = _scale(base)
    out: dict[str, int] = {}

    def walk(fields: list[dict], prefix: str) -> None:
        for field in fields:
            key = field["key"]
            path = prefix + key
            item = field.get("item")
            is_array = item is not None or "min" in field or "max" in field
            if "limit" in field:
                out[path + ("[]" if is_array else "")] = _scaled(int(field["limit"]), scale)
            if item:
                walk(item, path + "[].")
            if field.get("group"):
                walk(field["group"], path + ".")

    walk(spec["fields"], "")
    return out


_FIELD_RE = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)(?:\[(\d+)\])?")


def field_slot(plan_slide: dict, field: str):
    """把 `cards[1].desc` 这样的字段路径解析成 (容器, 键)，用于就地改这个字段。

    出片时按上限截字、以及"改计划"时定位字段，都用这一处规则。
    """
    parts = [(m.group(1), int(m.group(2)) if m.group(2) else None)
             for m in _FIELD_RE.finditer(field or "")]
    if not parts:
        return None
    node = plan_slide
    for i, (name, index) in enumerate(parts):
        last = i == len(parts) - 1
        if isinstance(node, dict):
            if last and index is None:
                return node, name
            node = node.get(name)
        if index is not None:
            if not isinstance(node, list) or index >= len(node):
                return None
            if last:
                return node, index
            node = node[index]
    return None


def check_slide(plan_slide: dict, base: dict | None = None) -> list[dict]:
    """校验一页计划，返回 [{"field", "text", "limit"}]（页号由调用方补）。

    只报超出上限；条数不足交给 normalize 去夹。
    """
    spec = LAYOUT_SPECS.get((plan_slide or {}).get("layout", ""))
    if not spec:
        return [{"field": "layout", "text": str((plan_slide or {}).get("layout", "")), "limit": None}]
    issues: list[dict] = []
    for field in spec["fields"]:
        _check_field(plan_slide, field, "", base, issues)
    return issues


def _check_field(data, field: dict, prefix: str, base, issues: list[dict]) -> None:
    key = field["key"]
    path = prefix + key
    value = (data or {}).get(key)
    empty = value is None or value == "" or (isinstance(value, (list, dict)) and not value)
    if empty:
        # 只校验上限：缺内容和条数不足交给 normalize 去补/去夹，不算"超限"
        return

    if field.get("item"):
        rows = value if isinstance(value, list) else []
        if len(rows) > int(field["max"]):
            issues.append({"field": path, "text": f"{len(rows)} 条", "limit": int(field["max"])})
        for i, row in enumerate(rows):
            for sub in field["item"]:
                _check_field(row if isinstance(row, dict) else {}, sub, f"{path}[{i}].", base, issues)
        return

    if field.get("group"):
        for sub in field["group"]:
            _check_field(value if isinstance(value, dict) else {}, sub, path + ".", base, issues)
        return

    if isinstance(value, list):
        if "max" in field and len(value) > int(field["max"]):
            issues.append({"field": path, "text": f"{len(value)} 条", "limit": int(field["max"])})
        limit = _scaled(int(field.get("limit", 0)), _scale(base))
        for i, text in enumerate(value):
            if text_len(text) > limit:
                issues.append({"field": f"{path}[{i}]", "text": str(text), "limit": limit})
        return

    if "limit" in field:
        limit = _scaled(int(field["limit"]), _scale(base))
        if text_len(value) > limit:
            issues.append({"field": path, "text": str(value), "limit": limit})


# ───────────── 取色与安全区 ─────────────

def _rgb(value) -> RGBColor:
    """'#9B1B30' / '9B1B30' / RGBColor 都能吃。"""
    if isinstance(value, RGBColor):
        return value
    return RGBColor.from_string(str(value).lstrip("#").strip().upper())


def _colors(base: dict | None) -> dict[str, RGBColor]:
    raw = (base or {}).get("colors") or {}
    return {
        "accent": _rgb(raw.get("accent") or "9B1B30"),
        "accent_soft": _rgb(raw.get("accent_soft") or "F6ECEE"),
        "dark": _rgb(raw.get("dark") or "262626"),
        "gray": _rgb(raw.get("gray") or "595959"),
        "muted": _rgb(raw.get("muted") or "8C8C8C"),
    }


def _safe(base: dict | None) -> tuple[float, float, float, float]:
    raw = (base or {}).get("safe_area") or [0.74, 1.45, 12.6, 6.75]
    x0, y0, x1, y1 = (float(v) for v in list(raw)[:4])
    return x0, y0, x1, y1


# 样片安全区高 6.75-1.45。更矮的模板按这个比例把纵向偏移和高度缩进去。
_DESIGN_ROOM = 5.3


def _span(base: dict | None) -> float:
    _, y0, _, y1 = _safe(base)
    room = y1 - y0
    if room <= 0:
        return 1.0
    return min(1.0, room / _DESIGN_ROOM)


def _dy(base: dict | None, offset: float) -> float:
    _, y0, _, _ = _safe(base)
    return y0 + offset * _span(base)


def _dh(base: dict | None, height: float) -> float:
    return height * _span(base)


# ───────────── 上限检查 ─────────────

def _cap(text, field: str, limit: int, base: dict | None = None) -> None:
    if text is None or str(text) == "":
        return
    cap = _scaled(limit, _scale(base))
    if text_len(text) > cap:
        raise Overflow(field, str(text), cap)


def _count(rows, field: str, lo: int, hi: int) -> None:
    n = len(rows or [])
    if n < lo or n > hi:
        raise Overflow(field, f"{n} 条", hi)


# ───────────── 量字与自适应字号 ─────────────

def _em(text: str) -> float:
    """中文按 1 个字宽算，ASCII 按 0.55。

    箭头、百分号这类符号在中文排版里也占一个全角宽，按半宽估会低估宽度、
    给出偏大的字号，最后渲染时被文本框截掉。
    """
    return sum(1.0 if (ord(c) > 0x2E80 or c in _WIDE_SYMBOLS) else 0.55 for c in text)


def _wrap_widths(text: str, w_in: float, pt: int) -> list[float]:
    """按当前字号贪心换行，返回每行的 _em 宽度，用来找孤字。"""
    per_line = max(1.0, w_in * 72 * 0.94 / pt)
    widths: list[float] = []
    for para in text.split("\n"):
        cur = 0.0
        for ch in para:
            w = 1.0 if ord(ch) > 0x2E80 else 0.55
            if cur > 0 and cur + w > per_line:
                widths.append(cur)
                cur = 0.0
            cur += w
        widths.append(cur)
    return widths or [0.0]


def _orphan(text: str, w_in: float, pt: int) -> bool:
    """最后一行只剩一两个字。"""
    widths = _wrap_widths(text, w_in, pt)
    return len(widths) > 1 and widths[-1] < 2.0


def fit_one_line(text: str, w_in: float, max_pt: int, min_pt: int) -> int:
    """只按"一行放得下"找最大字号，用在底板换字上（那里不换行）。"""
    for pt in range(max_pt, min_pt - 1, -1):
        if _em(text) * pt / 72.0 <= w_in:
            return pt
    return min_pt


def fit_pt(text: str, w_in: float, h_in: float, max_pt: int, min_pt: int,
           spacing: float = 1.3) -> int | None:
    """在 [min_pt, max_pt] 里找能放下的最大字号；放不下返回 None。"""
    for pt in range(max_pt, min_pt - 1, -1):
        per_line = max(1, math.floor(w_in * 72 * 0.94 / pt))
        lines = sum(max(1, math.ceil(_em(part) / per_line)) for part in text.split("\n"))
        if lines * pt * spacing <= h_in * 72:
            return pt
    return None


def _fit_no_orphan(text: str, w_in: float, h_in: float, max_pt: int, min_pt: int,
                   spacing: float = 1.3) -> int | None:
    """先求最大可容纳字号；有孤字就降 1pt，降到下限还孤字就返回 None。"""
    pt = fit_pt(text, w_in, h_in, max_pt, min_pt, spacing)
    if pt is None:
        return None
    while pt > min_pt and _orphan(text, w_in, pt):
        pt -= 1
    return None if _orphan(text, w_in, pt) else pt


# ───────────── 画图元 ─────────────

def text_box(slide, x, y, w, h, text, *, field: str, max_pt: int, min_pt: int, color,
             bold: bool = False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
             spacing: float = 1.3):
    pt = _fit_no_orphan(text, w, h, max_pt, min_pt, spacing)
    if pt is None:
        raise Overflow(field, text, None)
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for side in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, side, Inches(0.03))
    for i, line in enumerate(text.split("\n")):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        para.line_spacing = spacing
        run = para.add_run()
        run.text = line
        run.font.size = Pt(pt)
        run.font.bold = bold
        run.font.color.rgb = color
    return box


def rect(slide, x, y, w, h, fill, *, shape=MSO_SHAPE.RECTANGLE, line=None):
    item = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    item.fill.solid()
    item.fill.fore_color.rgb = fill
    if line is None:
        item.line.fill.background()
    else:
        item.line.color.rgb = line
        item.line.width = Pt(1)
    item.shadow.inherit = False
    if item.has_text_frame:
        item.text_frame.text = ""
    return item


def badge(slide, x, y, d, label, *, fill, pt: int = 16):
    circle = rect(slide, x, y, d, d, fill, shape=MSO_SHAPE.OVAL)
    tf = circle.text_frame
    tf.margin_left = tf.margin_right = Inches(0)
    para = tf.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    run = para.add_run()
    run.text = label
    run.font.size = Pt(pt)
    run.font.bold = True
    run.font.color.rgb = WHITE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE


# ───────────── 9 种内容版式 ─────────────

def layout_toc(slide, base, items) -> dict:
    c = _colors(base)
    x0, y0, x1, _ = _safe(base)
    _count(items, "items", 3, 6)
    gap = (x1 - x0) / len(items)
    for i, item in enumerate(items):
        _cap(item.get("label"), f"items[{i}].label", 6, base)
        _cap(item.get("desc"), f"items[{i}].desc", 12, base)
        cx = x0 + gap * i + gap / 2
        badge(slide, cx - 0.5, _dy(base, 1.0), _dh(base, 1.0), f"{i + 1:02d}", fill=c["accent"], pt=22)
        text_box(slide, cx - gap / 2 + 0.1, _dy(base, 2.25), gap - 0.2, _dh(base, 0.55), item.get("label", ""),
                 field=f"items[{i}].label", max_pt=22, min_pt=TITLE_MIN_PT,
                 color=c["dark"], bold=True, align=PP_ALIGN.CENTER)
        rect(slide, cx - 0.3, _dy(base, 2.9), 0.6, _dh(base, 0.05), c["accent"])
        text_box(slide, cx - gap / 2 + 0.15, _dy(base, 3.1), gap - 0.3, _dh(base, 0.8), item.get("desc", ""),
                 field=f"items[{i}].desc", max_pt=14, min_pt=BODY_MIN_PT,
                 color=c["muted"], align=PP_ALIGN.CENTER)
    return {}


def layout_cards(slide, base, cards, takeaway: str = "") -> dict:
    c = _colors(base)
    x0, y0, x1, _ = _safe(base)
    _count(cards, "cards", 2, 4)
    gap = 0.35
    w = (x1 - x0 - gap * (len(cards) - 1)) / len(cards)
    for i, card in enumerate(cards):
        _cap(card.get("key"), f"cards[{i}].key", 6, base)
        _cap(card.get("desc"), f"cards[{i}].desc", 28, base)
        x = x0 + i * (w + gap)
        rect(slide, x, _dy(base, 0.2), w, _dh(base, 3.55), c["accent_soft"])
        rect(slide, x, _dy(base, 0.2), w, _dh(base, 0.08), c["accent"])
        badge(slide, x + 0.3, _dy(base, 0.55), _dh(base, 0.62), f"{i + 1:02d}", fill=c["accent"], pt=14)
        text_box(slide, x + 0.3, _dy(base, 1.35), w - 0.6, _dh(base, 0.6), card.get("key", ""),
                 field=f"cards[{i}].key", max_pt=22, min_pt=TITLE_MIN_PT,
                 color=c["accent"], bold=True)
        text_box(slide, x + 0.3, _dy(base, 2.0), w - 0.6, _dh(base, 1.6), card.get("desc", ""),
                 field=f"cards[{i}].desc", max_pt=16, min_pt=BODY_MIN_PT, color=c["gray"])
    if takeaway:
        _cap(takeaway, "takeaway", 34, base)
        rect(slide, x0, _dy(base, 4.15), x1 - x0, _dh(base, 0.85), c["accent"])
        text_box(slide, x0 + 0.35, _dy(base, 4.15), x1 - x0 - 0.7, _dh(base, 0.85), takeaway,
                 field="takeaway", max_pt=18, min_pt=BODY_MIN_PT, color=WHITE,
                 bold=True, anchor=MSO_ANCHOR.MIDDLE)
    return {}


def layout_compare(slide, base, left, right) -> dict:
    c = _colors(base)
    x0, y0, x1, _ = _safe(base)
    w = (x1 - x0 - 0.9) / 2
    for col, (side, fill) in enumerate([(left, c["gray"]), (right, c["accent"])]):
        side = side or {}
        name = "left" if col == 0 else "right"
        head = side.get("head", "")
        points = side.get("points") or []
        _cap(head, f"{name}.head", 8, base)
        _count(points, f"{name}.points", 2, 4)
        x = x0 + col * (w + 0.9)
        rect(slide, x, _dy(base, 0.2), w, _dh(base, 0.7), fill)
        text_box(slide, x + 0.3, _dy(base, 0.2), w - 0.6, _dh(base, 0.7), head,
                 field=f"{name}.head", max_pt=20, min_pt=TITLE_MIN_PT, color=WHITE,
                 bold=True, anchor=MSO_ANCHOR.MIDDLE)
        rect(slide, x, _dy(base, 0.9), w, _dh(base, 4.1), WHITE, line=LINE_GRAY)
        # 3 条时步长 1.25 与样片一致；条数多再压缩
        step = _dh(base, min(1.25, 4.1 / len(points)))
        for j, point in enumerate(points):
            _cap(point, f"{name}.points[{j}]", 18, base)
            y = _dy(base, 1.2) + j * step
            rect(slide, x + 0.35, y + _dh(base, 0.14), _dh(base, 0.14), _dh(base, 0.14), fill)
            text_box(slide, x + 0.65, y, w - 1.0, step - _dh(base, 0.2), point,
                     field=f"{name}.points[{j}]", max_pt=17, min_pt=BODY_MIN_PT, color=c["dark"])
    mid = x0 + w + 0.45
    badge(slide, mid - 0.32, _dy(base, 2.6), _dh(base, 0.64), "→", fill=c["accent"], pt=20)
    return {}


def layout_timeline(slide, base, nodes) -> dict:
    c = _colors(base)
    x0, y0, x1, _ = _safe(base)
    _count(nodes, "nodes", 3, 6)
    line_y = _dy(base, 2.0)
    rect(slide, x0, line_y, x1 - x0, _dh(base, 0.05), c["accent"])
    gap = (x1 - x0) / len(nodes)
    for i, node in enumerate(nodes):
        for key, limit in (("year", 6), ("head", 6), ("desc", 10)):
            _cap(node.get(key), f"nodes[{i}].{key}", limit, base)
        cx = x0 + gap * i + gap / 2
        text_box(slide, cx - gap / 2, line_y - _dh(base, 1.0), gap, _dh(base, 0.7), node.get("year", ""),
                 field=f"nodes[{i}].year", max_pt=28, min_pt=22, color=c["accent"],
                 bold=True, align=PP_ALIGN.CENTER)
        rect(slide, cx - 0.14, line_y - _dh(base, 0.115), _dh(base, 0.28), _dh(base, 0.28), c["accent"], shape=MSO_SHAPE.OVAL)
        text_box(slide, cx - gap / 2 + 0.1, line_y + _dh(base, 0.45), gap - 0.2, _dh(base, 0.5), node.get("head", ""),
                 field=f"nodes[{i}].head", max_pt=18, min_pt=TITLE_MIN_PT, color=c["dark"],
                 bold=True, align=PP_ALIGN.CENTER)
        text_box(slide, cx - gap / 2 + 0.15, line_y + _dh(base, 1.05), gap - 0.3, _dh(base, 1.5), node.get("desc", ""),
                 field=f"nodes[{i}].desc", max_pt=14, min_pt=BODY_MIN_PT, color=c["gray"],
                 align=PP_ALIGN.CENTER)
    return {}


def layout_quote(slide, base, quote, source: str = "", note: str = "") -> dict:
    c = _colors(base)
    x0, y0, x1, _ = _safe(base)
    _cap(quote, "quote", 40, base)
    _cap(source, "source", 20, base)
    _cap(note, "note", 40, base)
    rect(slide, x0 + 1.2, _dy(base, 1.15), 0.08, _dh(base, 1.4), c["accent"])
    text_box(slide, x0 + 1.2, _dy(base, 1.05), x1 - x0 - 2.4, _dh(base, 1.6), quote,
             field="quote", max_pt=30, min_pt=24, color=c["dark"], bold=True,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    rect(slide, (x0 + x1) / 2 - 0.4, _dy(base, 2.9), 0.8, _dh(base, 0.05), c["accent"])
    if source:
        text_box(slide, x0 + 1.2, _dy(base, 3.1), x1 - x0 - 2.4, _dh(base, 0.45), source,
                 field="source", max_pt=16, min_pt=BODY_MIN_PT, color=c["muted"],
                 align=PP_ALIGN.CENTER)
    if note:
        rect(slide, x0 + 1.2, _dy(base, 3.9), x1 - x0 - 2.4, _dh(base, 1.0), c["accent_soft"])
        text_box(slide, x0 + 1.5, _dy(base, 3.9), x1 - x0 - 3.0, _dh(base, 1.0), note,
                 field="note", max_pt=16, min_pt=BODY_MIN_PT, color=c["gray"],
                 anchor=MSO_ANCHOR.MIDDLE)
    return {}


def layout_numbered(slide, base, rows) -> dict:
    c = _colors(base)
    x0, y0, x1, y1 = _safe(base)
    _count(rows, "rows", 2, 4)
    span = _span(base)
    room = max(0.5, y1 - y0)
    # 3 行时高 1.35 与样片一致；行数多再压缩。矮模板按安全区缩小。
    h = min(1.35 * span, (room - 0.2 * span - (len(rows) - 1) * 0.22 * span) / len(rows))
    gap_y = 0.22 * span
    for i, row in enumerate(rows):
        _cap(row.get("head"), f"rows[{i}].head", 9, base)
        _cap(row.get("desc"), f"rows[{i}].desc", 30, base)
        y = y0 + 0.2 * span + i * (h + gap_y)
        rect(slide, x0, y, 1.2, h, c["accent"])
        text_box(slide, x0, y, 1.2, h, f"{i + 1:02d}", field=f"rows[{i}].no", max_pt=32,
                 min_pt=26, color=WHITE, bold=True, align=PP_ALIGN.CENTER,
                 anchor=MSO_ANCHOR.MIDDLE)
        rect(slide, x0 + 1.2, y, x1 - x0 - 1.2, h, c["accent_soft"])
        text_box(slide, x0 + 1.55, y + 0.15 * span, 3.2, h - 0.3 * span, row.get("head", ""),
                 field=f"rows[{i}].head", max_pt=20, min_pt=TITLE_MIN_PT, color=c["accent"],
                 bold=True, anchor=MSO_ANCHOR.MIDDLE)
        text_box(slide, x0 + 4.9, y + 0.12 * span, x1 - x0 - 5.2, h - 0.24 * span, row.get("desc", ""),
                 field=f"rows[{i}].desc", max_pt=16, min_pt=BODY_MIN_PT, color=c["gray"],
                 anchor=MSO_ANCHOR.MIDDLE)
    return {}


def layout_bullets(slide, base, points) -> dict:
    """左侧一条竖线，每条一个小方块，归不了类的要点都用它。"""
    c = _colors(base)
    x0, y0, x1, y1 = _safe(base)
    _count(points, "points", 3, 5)
    top = y0 + 0.35
    avail = (y1 - y0) - 0.7
    step = avail / len(points)
    rect(slide, x0 + 0.75, top, 0.08, avail, c["accent"])
    for i, point in enumerate(points):
        _cap(point, f"points[{i}]", 30, base)
        y = top + i * step
        rect(slide, x0 + 1.15, y + step / 2 - 0.07, 0.14, 0.14, c["accent"])
        text_box(slide, x0 + 1.5, y, x1 - x0 - 1.8, step - 0.15, point,
                 field=f"points[{i}]", max_pt=20, min_pt=BODY_MIN_PT, color=c["dark"],
                 anchor=MSO_ANCHOR.MIDDLE)
    return {}


def layout_bignum(slide, base, stats) -> dict:
    """1–3 个大数字横排，下面接名称和说明。"""
    c = _colors(base)
    x0, y0, x1, _ = _safe(base)
    _count(stats, "stats", 1, 3)
    gap = 0.4
    w = (x1 - x0 - gap * (len(stats) - 1)) / len(stats)
    for i, stat in enumerate(stats):
        _cap(stat.get("value"), f"stats[{i}].value", 6, base)
        _cap(stat.get("label"), f"stats[{i}].label", 10, base)
        _cap(stat.get("desc"), f"stats[{i}].desc", 24, base)
        x = x0 + i * (w + gap)
        cx = x + w / 2
        text_box(slide, x + 0.2, _dy(base, 1.1), w - 0.4, _dh(base, 1.0), str(stat.get("value", "")),
                 field=f"stats[{i}].value", max_pt=54, min_pt=32, color=c["accent"],
                 bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        text_box(slide, x + 0.2, _dy(base, 2.3), w - 0.4, _dh(base, 0.5), stat.get("label", ""),
                 field=f"stats[{i}].label", max_pt=20, min_pt=TITLE_MIN_PT, color=c["dark"],
                 bold=True, align=PP_ALIGN.CENTER)
        rect(slide, cx - 0.3, _dy(base, 2.95), 0.6, _dh(base, 0.05), c["accent"])
        text_box(slide, x + 0.3, _dy(base, 3.2), w - 0.6, _dh(base, 1.2), stat.get("desc", ""),
                 field=f"stats[{i}].desc", max_pt=15, min_pt=BODY_MIN_PT, color=c["gray"],
                 align=PP_ALIGN.CENTER)
    return {}


def layout_image_text(slide, base, points, image=None) -> dict:
    """左图右文。图片位只画占位框并把位置返回给阶段 4 换真图。"""
    c = _colors(base)
    x0, y0, x1, y1 = _safe(base)
    _count(points, "points", 2, 4)
    if image is not None:
        _cap(str(image), "image", 3, base)
    pic_w = (x1 - x0) * 0.42
    pic_h = (y1 - y0) - 0.4
    x, y = x0, y0 + 0.2
    slot = rect(slide, x, y, pic_w, pic_h, c["accent_soft"], line=LINE_GRAY)
    slot.name = PIC_SLOT_NAME
    text_x = x + pic_w + 0.5
    text_w = x1 - text_x
    step = (pic_h - 0.2) / len(points)
    for i, point in enumerate(points):
        _cap(point, f"points[{i}]", 24, base)
        yy = y + i * step
        rect(slide, text_x, yy + step / 2 - 0.07, 0.14, 0.14, c["accent"])
        text_box(slide, text_x + 0.35, yy, text_w - 0.35, step - 0.15, point,
                 field=f"points[{i}]", max_pt=17, min_pt=BODY_MIN_PT, color=c["gray"],
                 anchor=MSO_ANCHOR.MIDDLE)
    return {"image_slot": (x, y, pic_w, pic_h), "image": image}


# ───────────── 分发 ─────────────

_RENDERERS = {
    "toc": lambda slide, base, plan: layout_toc(slide, base, plan.get("items") or []),
    "cards": lambda slide, base, plan: layout_cards(slide, base, plan.get("cards") or [],
                                                    plan.get("takeaway") or ""),
    "compare": lambda slide, base, plan: layout_compare(slide, base, plan.get("left") or {},
                                                        plan.get("right") or {}),
    "timeline": lambda slide, base, plan: layout_timeline(slide, base, plan.get("nodes") or []),
    "quote": lambda slide, base, plan: layout_quote(slide, base, plan.get("quote") or "",
                                                    plan.get("source") or "", plan.get("note") or ""),
    "numbered": lambda slide, base, plan: layout_numbered(slide, base, plan.get("rows") or []),
    "bullets": lambda slide, base, plan: layout_bullets(slide, base, plan.get("points") or []),
    "bignum": lambda slide, base, plan: layout_bignum(slide, base, plan.get("stats") or []),
    "image_text": lambda slide, base, plan: layout_image_text(slide, base,
                                                              plan.get("points") or [],
                                                              plan.get("image")),
}


def render(slide, base, plan_slide: dict) -> dict:
    """按计划里的一种版式画一页。封面/章节页/结尾返回空（它们走底板换字）。

    先整体校验一遍字段上限，再画；返回附加信息（目前只有图文页的图片位）。
    """
    layout = (plan_slide or {}).get("layout")
    if layout in PLAIN_LAYOUTS:
        return {}
    issues = check_slide(plan_slide, base)
    if issues:
        first = issues[0]
        raise Overflow(first["field"], first["text"], first["limit"])
    drawer = _RENDERERS.get(layout)
    if drawer is None:
        raise Overflow("layout", str(layout), None)
    return drawer(slide, base, plan_slide)
