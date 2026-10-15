"""评委：给一份计划的结构打连贯性分，并指出哪些页像背景、问题、总结。

V0 的计划没有叙事角色字段，所以这几项靠评委看标题判断。Q2 做完后改为复用那边的提示词。
"""

from __future__ import annotations

JUDGE_SYSTEM = """你在审一份学术汇报 PPT 的讲法。下面每页只有版式、标题和讲稿开头。只输出 JSON，不要解释。
按 6 个维度打 1 到 5 分：
- opening：开场是否交代了背景，并引出要回答的问题
- order：章节顺序是否讲得通（为什么，然后是什么或怎么做，然后发现，然后所以呢）
- bridge：相邻两页是否接得上
- focus：每页是否只讲一件事，标题是不是一句判断
- closing：结尾是否回答了开头的问题
- evidence：内容页是否有具体例子、数据、对比或原文
再指出页号（从 1 开始）：
{"scores": {"opening": 3, "order": 3, "bridge": 3, "focus": 3, "closing": 3, "evidence": 3},
 "background_pages": [3],
 "question_pages": [4],
 "summary_pages": [11]}
background_pages 是在交代背景、引子或概念的页。question_pages 是明确写出要回答的问题的页。
summary_pages 是收束全文、回答开头问题的页。没有就给空数组。不要复述正文。
"""

SCORE_KEYS = ("opening", "order", "bridge", "focus", "closing", "evidence")


def outline_for_judge(plan: dict) -> str:
    """只给结构，每页一行，讲稿只留开头 40 字。"""
    lines = [f"标题：{plan.get('title') or ''}"]
    for index, slide in enumerate(plan.get("slides") or [], 1):
        slide = slide or {}
        title = str(slide.get("title") or slide.get("quote") or "")
        notes = str(slide.get("notes") or "").replace("\n", " ")
        lines.append(f"{index}. {slide.get('layout') or ''}｜{title}｜讲稿开头：{notes[:40]}")
    return "\n".join(lines)


def parse_judge(data: dict) -> dict:
    scores = data.get("scores") if isinstance(data, dict) else None
    if not isinstance(scores, dict):
        scores = {}
    clean = {}
    for key in SCORE_KEYS:
        try:
            value = float(scores.get(key))
        except (TypeError, ValueError):
            value = 0
        clean[key] = max(0, min(5, value))
    def pages(name: str) -> list[int]:
        raw = data.get(name) if isinstance(data, dict) else None
        found = []
        for item in raw or []:
            try:
                found.append(int(item))
            except (TypeError, ValueError):
                continue
        return found
    return {
        "scores": clean,
        "background_pages": pages("background_pages"),
        "question_pages": pages("question_pages"),
        "summary_pages": pages("summary_pages"),
        "mean": round(sum(clean.values()) / len(SCORE_KEYS), 2),
    }
