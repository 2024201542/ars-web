"""叙事 skill 按汇报类型加载。"""

import pathlib

import pytest

from services.ppt import ppt_story


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    sandbox = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "pytest-env"
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(sandbox / "test_ars.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(sandbox / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(sandbox / "workspaces"))


def test_each_deck_type_has_a_section():
    for deck_type in (
        "research_talk", "defense", "proposal", "paper_report",
        "lecture", "review", "survey_report",
    ):
        text = ppt_story.load_skill(deck_type)
        assert deck_type in text
        assert "先定中心问题" in text
        assert len(text) <= 6000


def test_unknown_type_falls_back():
    text = ppt_story.load_skill("not-a-type")
    assert "研究汇报" in text
    assert "毕业答辩" not in text


def test_skill_version_matches_front_matter():
    assert ppt_story.skill_version() == 1


def test_detect_deck_type_from_user_words():
    assert ppt_story.detect_deck_type("帮我做毕业答辩 PPT", "") == "defense"
    assert ppt_story.detect_deck_type("做一个讲解学习方法的课件", "这是一项研究") == "lecture"
    assert ppt_story.detect_deck_type("组会要讲这篇论文", "") == "paper_report"
    assert ppt_story.detect_deck_type("中国近代女性形象研究", "") == "research_talk"
    assert ppt_story.detect_deck_type("", "中国近代女性形象研究") == "research_talk"
    material = "毕业答辩\n# 方法\n实验\n# 结果\n数据"
    assert ppt_story.detect_deck_type("按开题的结构来写", material) == "proposal"
    assert ppt_story.detect_deck_type("帮我做个 DEFENSE", "") == "defense"
    assert ppt_story.detect_deck_type("做个答辩", "") == "defense"
    assert ppt_story.detect_deck_type("", "# 方法\n实验\n# 发现\n记得更牢", "") == "research_talk"
    assert ppt_story.detect_deck_type("", "# 从一个例子说起\n合上书", "lecture") == "lecture"
    assert ppt_story.detect_deck_type("毕业答辩", "", "lecture") == "defense"


def test_budget_for_twelve_pages():
    budget = ppt_story.budget_for(12)
    assert budget["section"][1] == 3
    assert budget["content_min"] == 8
    assert budget["toc"] == 1
    assert ppt_story.budget_for(7)["toc"] == 0
    assert ppt_story.budget_for(7)["section"] == (0, 0)


def _chapter_story(chapters: int, per_chapter: int, *, toc: bool, summary: bool) -> dict:
    sections = []
    slots = [{"kind": "cover"}]
    if toc:
        slots.append({"kind": "toc"})
    for index in range(1, chapters + 1):
        sections.append({
            "no": index, "title": f"第{index}章", "role": "finding", "question": "这一章回答什么",
        })
        slots.append({"kind": "section", "section": index})
        for nth in range(per_chapter):
            slots.append({
                "kind": "content", "section": index, "role": "finding",
                "message": f"判断{index}-{nth}", "evidence": "证据" * (index + nth),
            })
    if summary:
        slots.append({"kind": "summary", "role": "conclusion", "message": "已有总结"})
    slots.append({"kind": "end"})
    return {
        "deck_type": "research_talk",
        "central_question": "记忆能不能靠间隔复习变牢？",
        "answer": "隔几天再回忆，比当晚连读记得牢。",
        "sections": sections,
        "slots": slots,
    }


def test_normalize_drops_a_section_to_keep_content_share():
    story = _chapter_story(3, 2, toc=True, summary=True)
    out = ppt_story.normalize_storyline(story, 12)
    slots = out["slots"]
    assert 11 <= len(slots) <= 13
    sections = sum(1 for slot in slots if slot["kind"] == "section")
    content = sum(1 for slot in slots if slot["kind"] in {"content", "summary"})
    assert sections == 2
    assert content / len(slots) >= 0.6
    assert all(section["pages"] >= 2 for section in out["sections"])


def test_normalize_storyline_shrinks_a_long_deck():
    story = _chapter_story(6, 2, toc=True, summary=False)
    assert len(story["slots"]) == 21
    out = ppt_story.normalize_storyline(story, 12)
    slots = out["slots"]
    assert 11 <= len(slots) <= 13
    assert sum(1 for slot in slots if slot["kind"] == "section") <= 3
    assert slots[0]["kind"] == "cover"
    assert slots[-1]["kind"] == "end"
    assert slots[-2]["kind"] == "summary"
    assert slots[-2]["message"] == story["answer"]
    assert all(section["pages"] >= 2 for section in out["sections"])
    assert [slot["no"] for slot in slots] == list(range(1, len(slots) + 1))


def test_normalize_storyline_toc_follows_page_count():
    missing = _chapter_story(3, 2, toc=False, summary=True)
    assert len(missing["slots"]) == 12
    added = ppt_story.normalize_storyline(missing, 12)
    assert added["slots"][1]["kind"] == "toc"

    short = {
        "deck_type": "lecture",
        "answer": "先举例再给概念。",
        "sections": [{"no": 1, "title": "例子", "role": "example", "question": ""}],
        "slots": [
            {"kind": "cover"},
            {"kind": "toc"},
            {"kind": "content", "section": 1, "role": "example", "message": "甲", "evidence": "a"},
            {"kind": "content", "section": 1, "role": "example", "message": "乙", "evidence": "b"},
            {"kind": "content", "section": 1, "role": "example", "message": "丙", "evidence": "c"},
            {"kind": "summary", "message": "先举例"},
            {"kind": "end"},
        ],
    }
    assert len(short["slots"]) == 7
    dropped = ppt_story.normalize_storyline(short, 7)
    assert all(slot["kind"] != "toc" for slot in dropped["slots"])
    assert dropped["slots"][0]["kind"] == "cover"
    assert dropped["slots"][-1]["kind"] == "end"


def test_normalize_storyline_is_stable():
    story = _chapter_story(6, 2, toc=True, summary=False)
    first = ppt_story.normalize_storyline(story, 12)
    for _ in range(4):
        assert ppt_story.normalize_storyline(story, 12) == first


def test_normalize_reads_chinese_slot_types_and_fills_roles():
    story = {
        "deck_type": "lecture",
        "answer": "先举例再给做法。",
        "sections": [
            {"name": "从一个例子说起", "question": "为什么"},
            {"name": "这个概念指什么", "question": "是什么"},
            {"name": "可以怎么做", "question": "怎么做"},
        ],
        "slots": [
            {"type": "封面"},
            {"type": "目录"},
            {"type": "章节页", "message": "从一个例子说起"},
            {"type": "内容页", "message": "读得顺不等于记得住", "evidence": "流畅性错觉"},
            {"type": "内容页", "message": "合上书才能发现不会", "evidence": "复述"},
            {"type": "章节页", "message": "这个概念指什么"},
            {"type": "内容页", "message": "提取比再读有用", "evidence": "实验"},
            {"type": "内容页", "message": "间隔比连着读牢", "evidence": "间隔"},
            {"type": "章节页", "message": "可以怎么做"},
            {"type": "内容页", "message": "讲给同桌听", "evidence": "同桌"},
            {"type": "内容页", "message": "隔天再回忆", "evidence": "隔天"},
            {"type": "结尾"},
        ],
    }
    out = ppt_story.normalize_storyline(story, 12)
    # 三章在 12 页里放不下六成内容页，最后一章并进前一章，内容页的角色还在。
    assert [section["role"] for section in out["sections"]] == ["hook", "concept"]
    assert out["sections"][1]["title"] == "这个概念指什么"
    bridges = [slot.get("bridge") or "" for slot in out["slots"]]
    assert any(bridge.startswith("怎么做") for bridge in bridges)
    assert out["slots"][0]["kind"] == "cover"
    assert out["slots"][1]["kind"] == "toc"
    assert out["slots"][-2]["kind"] == "summary"
    assert out["slots"][-2]["message"] == story["answer"]
    content = [slot["role"] for slot in out["slots"] if slot["kind"] == "content"]
    assert content[:2] == ["hook", "hook"]
    assert "concept" in content and "recommendation" in content


def test_merge_keeps_the_later_chapter_when_the_first_is_absorbed():
    kept = ppt_story._merge_chapters(
        {"title": "留下", "role": "concept", "question": "是什么",
         "contents": [{"role": "concept", "message": "后一章", "bridge": ""}]},
        {"title": "去掉", "role": "hook", "question": "为什么先讲",
         "contents": [{"role": "hook", "message": "前一章", "bridge": "原承接"}]},
        dropped_first=True,
    )
    assert kept["title"] == "留下"
    assert kept["contents"][0]["bridge"].startswith("为什么先讲")
    assert "原承接" in kept["contents"][0]["bridge"]


def test_storyline_omits_toc_when_the_template_has_no_item_slots():
    story = {
        "deck_type": "lecture",
        "central_question": "怎么把知道变成做到",
        "answer": "先提取，再间隔",
        "sections": [
            {"name": "从一个例子说起", "question": "为什么"},
            {"name": "这个概念指什么", "question": "是什么"},
        ],
        "slots": [
            {"type": "封面"},
            {"type": "目录"},
            {"type": "章节页", "message": "从一个例子说起"},
            {"type": "内容页", "message": "读得顺不等于记得住", "evidence": "流畅性错觉"},
            {"type": "内容页", "message": "合上书才能发现不会", "evidence": "复述"},
            {"type": "章节页", "message": "这个概念指什么"},
            {"type": "内容页", "message": "提取比再读有用", "evidence": "实验"},
            {"type": "内容页", "message": "间隔比连着读牢", "evidence": "间隔"},
            {"type": "结尾"},
        ],
    }
    out = ppt_story.normalize_storyline(story, 12, allow_toc=False)
    assert all(slot["kind"] != "toc" for slot in out["slots"])


def test_paper_report_opens_on_a_background_page():
    story = {
        "deck_type": "paper_report",
        "central_question": "为什么会背公式却算不出",
        "answer": "要分三层看",
        "sections": [
            {"title": "这篇论文在回答什么", "role": "question", "question": "论文在回答什么"},
            {"title": "主要结果", "role": "finding", "question": "结果是什么"},
        ],
        "slots": [
            {"kind": "cover"},
            {"kind": "toc"},
            {"kind": "section", "message": "这篇论文在回答什么"},
            {"kind": "content", "role": "question", "message": "会背公式却算不出", "evidence": "电梯"},
            {"kind": "content", "role": "question", "message": "记忆被当成附属议题", "evidence": "文献"},
            {"kind": "section", "message": "主要结果"},
            {"kind": "content", "role": "finding", "message": "遗忘有四条路径", "evidence": "证据"},
            {"kind": "content", "role": "finding", "message": "三项策略比较稳", "evidence": "元分析"},
            {"kind": "end"},
        ],
    }
    out = ppt_story.normalize_storyline(story, 12)
    lecture = ppt_story.normalize_storyline({**story, "deck_type": "lecture"}, 12)
    assert out["slots"][3]["role"] == "background"
    assert out["slots"][4]["role"] == "question"
    assert out["slots"][4]["message"] == "会背公式却算不出"
    assert len(out["slots"]) == len(lecture["slots"])


def test_research_talk_keeps_an_existing_background_page():
    story = _chapter_story(2, 2, toc=True, summary=False)
    story["deck_type"] = "research_talk"
    story["slots"][3]["role"] = "background"
    out = ppt_story.normalize_storyline(story, 12)
    first = next(slot for slot in out["slots"] if slot["kind"] == "content")
    assert first["role"] == "background"


def test_old_plan_without_version_still_validates():
    from services.ppt import ppt_plan

    plan = {"title": "旧计划", "slides": [
        {"layout": "cover", "title": "封面", "subtitle": "", "info": ["汇报人"]},
        {"layout": "end", "info": ["谢谢"]},
    ]}
    assert "plan_version" not in plan
    assert "storyline" not in plan
    assert ppt_plan.validate_plan(plan) == []
