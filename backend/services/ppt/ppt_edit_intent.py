"""判断一句对话是在改已经做好的 PPT，还是在提问。规则能定的不调模型。"""

from __future__ import annotations

import re

INTENT_SYSTEM = """用户正在修改一份已经做好的 PPT。判断用户这句话是要求修改 PPT，还是在提问或闲聊。只输出 JSON：
{"kind": "edit" 或 "question" 或 "other", "pages": [涉及的页号，没说就空], "why": "一句话"}
抱怨某页不好（太挤、接不上、看不清、太乱）也算 edit。
PPT 目录：
{outline}"""

_CN = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_PAGE = re.compile(
    r"第\s*(\d+)\s*(?:到|至|—|-)\s*(\d+)\s*页"
    r"|第\s*(\d+)\s*页"
    r"|第\s*([一二三四五六七八九十两]+)\s*页"
    r"|这一页|这页|上一页|最后一页|封面|目录|结尾|开头|前面|后面"
)
_PROBLEM = re.compile(
    r"看不清|接不上|跑出去|压住|挡住|重叠|出界|衔接|没逻辑|不通顺|啰嗦|突兀|太散"
    r"|挤|乱|空|满|重复|多|少|长|短|跳"
)
_ACTION = re.compile(
    r"缩短|精简|展开|扩写|改成|做成|变成|去掉|换成|放到|提前|往后|合并|拆分|拆"
    r"|改|换|删|加|补|调|挪|移"
)
_OVERALL = re.compile(
    r"整体|所有页|每页|全部|加一页|删一页|压到\s*\d+\s*页|背景介绍|加个总结|先讲|后讲|顺序"
)
_QUESTION_START = re.compile(r"^(为什么|为啥|是什么|什么意思|怎么理解|能不能解释)")
_QUESTION_BODY = re.compile(r"什么意思|是什么|怎么理解|能不能解释")
# 测试表把这句交给模型，不在规则里定成修改。
_LEAVE_UNSURE = {"怎么这么乱"}


def _cn_number(text: str) -> int | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    if raw == "十":
        return 10
    if raw.startswith("十") and len(raw) == 2 and raw[1] in _CN:
        return 10 + _CN[raw[1]]
    if "十" in raw:
        left, right = raw.split("十", 1)
        tens = _CN.get(left, 1) if left else 1
        ones = _CN.get(right, 0) if right else 0
        if left and left not in _CN:
            return None
        if right and right not in _CN:
            return None
        return tens * 10 + ones
    if len(raw) == 1 and raw in _CN:
        return _CN[raw]
    return None


def page_numbers(text: str) -> list[int]:
    """从原话里抽出页号。封面、目录、这页这类说法不猜页号。"""
    found: list[int] = []
    for match in _PAGE.finditer(text or ""):
        start, end, single, chinese = match.groups()
        if start and end:
            found.extend([int(start), int(end)])
        elif single:
            found.append(int(single))
        elif chinese:
            number = _cn_number(chinese)
            if number:
                found.append(number)
    return found


def quick_classify(text: str) -> str:
    """纯规则。返回 edit、question 或 unsure。"""
    from services.ppt.ppt_chat import wants_plan_revise

    raw = (text or "").strip()
    if not raw or len(raw) > 400:
        return "unsure"
    if raw.rstrip("？?") in _LEAVE_UNSURE:
        return "unsure"
    paged = _PAGE.search(raw) is not None
    problem = _PROBLEM.search(raw) is not None
    action = _ACTION.search(raw) is not None
    if paged and (problem or action):
        return "edit"
    if _OVERALL.search(raw):
        return "edit"
    if wants_plan_revise(raw):
        return "edit"
    if problem and (_QUESTION_START.search(raw) or raw.startswith("怎么这么")):
        return "edit"
    if (_QUESTION_START.search(raw) or _QUESTION_BODY.search(raw)) and not action and not problem:
        return "question"
    return "unsure"


def outline_of(plan: dict | None) -> str:
    lines = []
    for index, slide in enumerate((plan or {}).get("slides") or [], 1):
        if not isinstance(slide, dict):
            continue
        role = str(slide.get("role") or slide.get("layout") or "")
        title = str(slide.get("title") or "")
        lines.append(f"{index} {role} {title}")
    return "\n".join(lines)[:2000]


def route_label(text: str) -> str:
    """新建优先于修改。返回 new、edit、ask、unsure。"""
    from services.ppt.ppt_chat import wants_ppt, wants_rebuild_from_draft

    if wants_ppt(text) or wants_rebuild_from_draft(text):
        return "new"
    quick = quick_classify(text)
    if quick == "edit":
        return "edit"
    if quick == "question":
        return "ask"
    return "unsure"


async def classify(text: str, plan: dict | None = None, model: str = "",
                   user_id: str = "") -> dict:
    """规则能定就直接返回。拿不准时问一次当前模型，失败就当成提问。"""
    quick = quick_classify(text)
    pages = page_numbers(text)
    if quick == "edit":
        return {"kind": "edit", "pages": pages, "why": "这句话在改已经做好的 PPT"}
    if quick == "question":
        return {"kind": "question", "pages": pages, "why": "这句话在提问"}
    from services.ppt.ppt_plan import _ask_text
    from services.ppt.pptx_outline import _extract_json

    system = INTENT_SYSTEM.replace("{outline}", outline_of(plan))
    answer, _name, err = await _ask_text(user_id, system, text or "", model or "", max_tokens=300)
    if err or not (answer or "").strip():
        return {"kind": "question", "pages": pages, "why": "没能判断，先当作提问"}
    data = _extract_json(answer)
    kind = str((data or {}).get("kind") or "") if isinstance(data, dict) else ""
    if kind not in {"edit", "question", "other"}:
        return {"kind": "question", "pages": pages, "why": "没能判断，先当作提问"}
    model_pages = data.get("pages") if isinstance(data, dict) else None
    cleaned: list[int] = []
    if isinstance(model_pages, list):
        for item in model_pages:
            try:
                cleaned.append(int(item))
            except (TypeError, ValueError):
                continue
    return {"kind": kind, "pages": cleaned or pages, "why": str((data or {}).get("why") or "")}
