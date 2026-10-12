"""生成内置 PPT 模板（每个主题一套，覆盖 7 种版式），并写好 analysis.json。

跑法（在后端目录）：
    python scripts/ppt/make_builtin_templates.py
产物：
    backend/assets/ppt_templates/builtin/<theme-id>.pptx
    backend/assets/ppt_templates/builtin/<theme-id>.analysis.json
"""

from __future__ import annotations

import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from pptx import Presentation                                    # noqa: E402
from pptx.enum.text import PP_ALIGN                              # noqa: E402
from pptx.util import Emu, Inches, Pt                            # noqa: E402

from services.ppt import ppt_template, ppt_theme                      # noqa: E402
from services.ppt.pptx_builder import _set_run_font                   # noqa: E402

OUT_DIR = BACKEND / "assets" / "ppt_templates" / "builtin"
W = 13.333
H = 7.5


def _new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)
    return prs


def _blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _rect(slide, x, y, w, h, fill: str, line: str = ""):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(fill)
    if line:
        shape.line.color.rgb = RGBColor.from_string(line)
        shape.line.width = Pt(0.75)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def _text(slide, x, y, w, h, lines, font, *, align=PP_ALIGN.LEFT, spacing=6):
    """lines: [(text, size, color, bold)]"""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    for i, (text, size, color, bold) in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        if i:
            para.space_before = Pt(spacing)
        run = para.add_run()
        run.text = text
        _set_run_font(run, font, size=size, bold=bold, color=color)
    return box


BULLET_MARK = "▪ "


def build_deck(theme_id: str) -> pathlib.Path:
    cfg = ppt_theme.get_theme(theme_id)
    accent, secondary = cfg["accent"], cfg["secondary"]
    text_c, muted, font = cfg["text"], cfg["muted"], cfg["font"]
    prs = _new_deck()

    # 1 封面
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.22, accent)
    _rect(s, 0, 0.22, 3.2, 0.06, secondary)
    _text(s, 1.0, 1.55, 11.3, 1.7, [("演示文稿标题", 40, accent, True)], font)
    _text(s, 1.0, 3.25, 11.3, 0.9, [("副标题：研究主题与核心结论", 18, muted, False)], font)
    _text(s, 1.0, 6.35, 11.3, 0.6, [("汇报人：XXX　　日期：2026 年 X 月", 12, muted, False)], font)

    # 2 目录
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.12, accent)
    _text(s, 0.7, 0.5, 12, 0.9, [("汇报框架", 28, text_c, True)], font)
    _text(s, 1.0, 1.75, 11.3, 4.6, [
        (f"{BULLET_MARK}一、研究背景与问题提出", 18, text_c, False),
        (f"{BULLET_MARK}二、已有讨论与理论框架", 18, text_c, False),
        (f"{BULLET_MARK}三、制度变迁的历史过程", 18, text_c, False),
        (f"{BULLET_MARK}四、机制分析与证据", 18, text_c, False),
        (f"{BULLET_MARK}五、结论与讨论", 18, text_c, False),
    ], font, spacing=10)

    # 3 三条要点页
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.12, accent)
    _text(s, 0.7, 0.5, 12, 0.9, [("一、研究背景与问题提出", 26, text_c, True)], font)
    _rect(s, 0.72, 1.42, 2.1, 0.06, secondary)
    _text(s, 1.0, 1.9, 11.3, 4.4, [
        (f"{BULLET_MARK}要点一：把研究问题收成一句可检验的命题", 18, text_c, False),
        (f"{BULLET_MARK}要点二：交代材料来源与时间范围", 18, text_c, False),
        (f"{BULLET_MARK}要点三：指出既有解释留下的缺口", 18, text_c, False),
    ], font, spacing=16)

    # 4 五条要点页
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.12, accent)
    _text(s, 0.7, 0.5, 12, 0.9, [("二、已有讨论与理论框架", 26, text_c, True)], font)
    _rect(s, 0.72, 1.42, 2.1, 0.06, secondary)
    _text(s, 1.0, 1.8, 11.3, 4.8, [
        (f"{BULLET_MARK}讨论一：所有权与国家关系的经典解释", 15, text_c, False),
        (f"{BULLET_MARK}讨论二：诺斯难题与制度变迁的动因", 15, text_c, False),
        (f"{BULLET_MARK}讨论三：交易费用与产权界定的关系", 15, text_c, False),
        (f"{BULLET_MARK}讨论四：集体行动与国家能力", 15, text_c, False),
        (f"{BULLET_MARK}讨论五：本文的推进方向", 15, text_c, False),
    ], font, spacing=12)

    # 5 两栏对照页
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.12, accent)
    _text(s, 0.7, 0.5, 12, 0.9, [("三、两种解释的对照", 26, text_c, True)], font)
    for x, head in ((0.8, "既有解释"), (6.95, "本文解释")):
        _rect(s, x, 1.7, 5.6, 4.4, "FFFFFF", secondary)
        _text(s, x + 0.35, 1.95, 5.0, 3.9, [
            (head, 18, accent, True),
            ("· 把制度变迁归因于外部冲击", 14, muted, False),
            ("· 忽略行为主体的策略选择", 14, muted, False),
        ], font, spacing=12)

    # 6 大数字页
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.12, accent)
    _text(s, 0.7, 0.5, 12, 0.9, [("关键数据", 26, text_c, True)], font)
    _text(s, 1.0, 2.15, 11.3, 1.8, [("50 年", 54, accent, True)], font, align=PP_ALIGN.CENTER)
    _text(s, 1.0, 4.3, 11.3, 0.9, [("1949—1999：制度变迁的时间跨度与关键节点", 15, muted, False)],
          font, align=PP_ALIGN.CENTER)

    # 7 引用页（一整句原文金句）
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.12, accent)
    _text(s, 0.7, 0.5, 12, 0.9, [("原文摘录", 26, text_c, True)], font)
    _text(s, 0.9, 2.3, 11.5, 2.6, [
        ("“如果不把国家及其代理人的行为引进来，就无法理解产权安排及其变迁，也无法解释为什么有效率的产权制度难以长期维持。”", 20, accent, False),
    ], font)

    # 8 三卡片页
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.12, accent)
    _text(s, 0.7, 0.5, 12, 0.9, [("三个要点并列", 26, text_c, True)], font)
    for i, x in enumerate((0.8, 4.72, 8.64)):
        _rect(s, x, 1.75, 3.6, 4.2, "FFFFFF", secondary)
        _rect(s, x, 1.75, 3.6, 0.12, accent if i == 0 else secondary)
        _text(s, x + 0.28, 2.1, 3.05, 3.5, [
            (f"卡片 {i + 1}", 17, accent, True),
            ("· 一句话说明这一点的含义", 13, muted, False),
        ], font, spacing=10)

    # 9 时间线页（四个节点，带年份）
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.12, accent)
    _text(s, 0.7, 0.5, 12, 0.9, [("制度变迁的三个节点", 26, text_c, True)], font)
    _rect(s, 1.1, 3.55, 11.1, 0.05, secondary)
    for i, x in enumerate((0.9, 3.9, 6.9, 9.9)):
        _rect(s, x + 0.55, 3.35, 0.28, 0.28, accent)
        # 每个节点一个文本框（年份在第一段），解析时才认得出这是时间线
        _text(s, x, 2.25, 2.9, 3.1, [
            (f"{1949 + i * 20} 年", 18, accent, True),
            ("· 这一阶段的制度特征与关键事件", 13, muted, False),
        ], font, spacing=14)

    # 10 分节页（只有一个大标题，用来分隔章节）
    s = _blank(prs)
    _rect(s, 0, 0, 4.6, H, accent)
    _text(s, 5.4, 3.05, 7.3, 1.4, [("四、结论与讨论", 32, text_c, True)], font)

    # 11 结尾页
    s = _blank(prs)
    _rect(s, 0, 0, W, 0.12, accent)
    _text(s, 1.0, 2.9, 11.3, 1.4, [("谢谢", 40, accent, True)], font, align=PP_ALIGN.CENTER)
    _text(s, 1.0, 4.6, 11.3, 0.8, [("请批评指正", 15, muted, False)], font, align=PP_ALIGN.CENTER)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{theme_id}.pptx"
    prs.save(str(path))
    return path


def main() -> None:
    made = []
    for theme_id, cfg in ppt_theme.THEMES.items():
        path = build_deck(theme_id)
        analysis = ppt_template.analyze_pptx(
            path, tid=f"builtin-{theme_id}", name=f"{cfg['name']}（内置）", source="builtin"
        )
        ppt_template.save_analysis(OUT_DIR / f"{theme_id}.analysis.json", analysis)
        tags = "、".join(f"{k}×{v}" for k, v in analysis["stats"]["tags"].items())
        made.append(f"  {cfg['name']:6s} {analysis['stats']['slides']} 页  {tags}")
    print(f"生成 {len(made)} 套内置模板 → {OUT_DIR}")
    print("\n".join(made))


if __name__ == "__main__":
    main()
