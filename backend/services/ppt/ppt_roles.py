"""PPT 的三套词表：页面角色、内容形态、叙事角色，以及格子命名。

出计划、选页、审稿、对话改稿共用这一份，避免各写各的名字。
"""

from __future__ import annotations

import re

from services.ppt import ppt_layouts

PAGE_ROLES = {
    "cover": "封面",
    "toc": "目录",
    "section": "章节过渡",
    "content": "内容",
    "summary": "总结",
    "end": "结尾",
    "qa": "提问",
    "blank": "空白",
}

CONTENT_FORMS = {
    "bullets": "要点",
    "numbered": "编号结论",
    "cards": "并列卡片",
    "compare": "左右对比",
    "timeline": "时间轴",
    "process": "流程步骤",
    "quote": "金句",
    "bignum": "大数字",
    "image_text": "图文",
    "table": "表格",
    "chart": "图表",
    "text": "大段文字",
    "none": "无",
}

NARRATIVE_ROLES = {
    "hook": "开场引子",
    "background": "背景",
    "significance": "意义",
    "question": "研究问题",
    "literature": "已有研究",
    "theory": "理论框架",
    "method": "方法与设计",
    "data": "数据与材料",
    "concept": "概念界定",
    "principle": "原理机制",
    "finding": "主要发现",
    "case": "案例",
    "comparison": "对比",
    "example": "举例",
    "misconception": "常见误区",
    "discussion": "讨论",
    "recommendation": "建议",
    "conclusion": "结论",
    "limitation": "不足",
    "outlook": "展望",
    "innovation": "创新点",
    "schedule": "进度安排",
    "takeaway": "启发",
    "summary": "小结",
}

FORM_TO_LAYOUT = {
    "bullets": "bullets",
    "numbered": "numbered",
    "cards": "cards",
    "compare": "compare",
    "timeline": "timeline",
    "process": "numbered",
    "quote": "quote",
    "bignum": "bignum",
    "image_text": "image_text",
    "table": "bullets",
    "chart": "image_text",
    "text": "bullets",
}

# item0、stat0 不合法；编号从 1 起。重名格子改成 name_2，后缀也合法。
_SLOT_RE = re.compile(
    r"^(?:title|subtitle|lead|section_index|section_title|section_question|"
    r"quote|source|body|caption|"
    r"left\.head|left\.body|right\.head|right\.body|"
    r"item([1-9]\d*)\.(head|body)|"
    r"stat([1-9]\d*)\.(value|label)|"
    r"info([1-9]\d*))(?:_[1-9]\d*)?$"
)


def slot_pattern_ok(name: str) -> bool:
    return bool(_SLOT_RE.match(str(name or "")))


def form_layouts_ok() -> list[str]:
    """FORM_TO_LAYOUT 的值必须都是现成版式。返回对不上的项。"""
    return [key for key, layout in FORM_TO_LAYOUT.items()
            if layout not in ppt_layouts.LAYOUT_SPECS]
