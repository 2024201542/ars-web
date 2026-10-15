"""讲法检查：每条规则一个通过样本、一个不通过样本。"""

import copy
import pathlib

import pytest

from services.ppt import ppt_plan, ppt_story_check

STORY = {"deck_type": "research_talk", "central_question": "土地制度如何变化", "sections": [{"title": "背景"}]}
NOTES = "讲" * 80


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    sandbox = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "pytest-env"
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(sandbox / "test_ars.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(sandbox / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(sandbox / "workspaces"))


def _content(**extra):
    slide = {
        "layout": "bullets",
        "title": "土地制度是在变化的",
        "role": "finding",
        "notes": NOTES,
        "lead": "接着看材料",
    }
    slide.update(extra)
    return slide


def _codes(plan):
    return [item["code"] for item in ppt_story_check.check_story(plan)]


def test_background_rule():
    ok = {"storyline": STORY, "slides": [
        {"layout": "section", "title": "背景"},
        _content(role="background"),
        _content(),
        {"layout": "end", "title": "谢谢", "role": "end"},
    ]}
    bad = {"storyline": STORY, "slides": [
        {"layout": "section", "title": "发现"},
        _content(role="finding"),
        _content(),
        {"layout": "end", "title": "谢谢"},
    ]}
    assert "S_NO_BACKGROUND" not in _codes(ok)
    assert "S_NO_BACKGROUND" in _codes(bad)


def test_question_rule():
    ok = {"storyline": STORY, "slides": [
        _content(role="question", title="土地制度为什么会变化？"),
        {"layout": "summary", "role": "conclusion", "title": "土地制度的变化已经写明", "notes": NOTES},
        {"layout": "end", "title": "谢谢"},
    ]}
    bad = {"storyline": STORY, "slides": [
        _content(role="finding", title="土地制度已经发生变化"),
        {"layout": "summary", "role": "conclusion", "title": "土地制度的变化已经写明", "notes": NOTES},
        {"layout": "end", "title": "谢谢"},
    ]}
    lecture = {"storyline": {"deck_type": "lecture"}, "slides": bad["slides"]}
    assert "S_NO_QUESTION" not in _codes(ok)
    assert "S_NO_QUESTION" in _codes(bad)
    assert "S_NO_QUESTION" not in _codes(lecture)


def test_method_rule():
    ok = {"storyline": STORY, "slides": [_content(role="method", title="方法是对照前后土地制度")]}
    bad = {"storyline": STORY, "slides": [_content(role="finding")]}
    assert "S_NO_METHOD" not in _codes(ok)
    assert "S_NO_METHOD" in _codes(bad)


def test_summary_rule():
    ok = {"storyline": STORY, "slides": [
        _content(role="background"),
        {"layout": "summary", "role": "conclusion", "title": "土地制度的变化已经写明", "notes": NOTES},
        {"layout": "end", "title": "谢谢"},
    ]}
    bad = {"storyline": STORY, "slides": [
        _content(role="background"),
        _content(),
        {"layout": "end", "title": "谢谢"},
    ]}
    assert "S_NO_SUMMARY" not in _codes(ok)
    assert "S_NO_SUMMARY" in _codes(bad)


def test_summary_answers_question():
    ok = {"storyline": STORY, "slides": [
        {"layout": "summary", "role": "conclusion", "title": "土地制度的变化已经写明", "notes": NOTES},
        {"layout": "end", "title": "谢谢"},
    ]}
    bad = {"storyline": STORY, "slides": [
        {"layout": "summary", "role": "conclusion", "title": "谢谢各位的时间", "notes": NOTES},
        {"layout": "end", "title": "谢谢"},
    ]}
    assert "S_SUMMARY_NOT_ANSWER" not in _codes(ok)
    assert "S_SUMMARY_NOT_ANSWER" in _codes(bad)


def test_section_heavy():
    light = {"slides": [{"layout": "cover", "title": "题"}]}
    light["slides"] += [{"layout": "section", "title": f"章{i}"} for i in range(3)]
    light["slides"] += [_content() for _ in range(12)]
    heavy = {"slides": [{"layout": "cover", "title": "题"}, {"layout": "toc", "title": "目录", "items": []}]}
    for i in range(6):
        heavy["slides"].append({"layout": "section", "title": f"章{i}"})
        heavy["slides"].append(_content())
        heavy["slides"].append(_content())
    heavy["slides"].append({"layout": "end", "title": "谢谢"})
    assert "S_SECTION_HEAVY" not in _codes(light)
    assert "S_SECTION_HEAVY" in _codes(heavy)


def test_thin_section():
    ok = {"slides": [
        {"layout": "section", "title": "背景"},
        _content(),
        _content(),
    ]}
    bad = {"slides": [
        {"layout": "section", "title": "背景"},
        _content(),
    ]}
    assert "S_THIN_SECTION" not in _codes(ok)
    assert "S_THIN_SECTION" in _codes(bad)


def test_title_assertion():
    ok = {"storyline": STORY, "slides": [_content(title="土地制度是在变化的")]}
    bad = {"storyline": STORY, "slides": [_content(title="背景")]}
    assert "S_TITLE_NOT_ASSERTION" not in _codes(ok)
    assert "S_TITLE_NOT_ASSERTION" in _codes(bad)


def test_title_accepts_a_judgment_outside_the_short_list():
    ok = {"storyline": STORY, "slides": [_content(title="记忆问题一直被当作概念转变的附庸")]}
    bad = {"storyline": STORY, "slides": [_content(title="给教学的两点启发")]}
    assert "S_TITLE_NOT_ASSERTION" not in _codes(ok)
    assert "S_TITLE_NOT_ASSERTION" in _codes(bad)


def test_summary_matches_a_two_character_word():
    story = {"deck_type": "lecture", "central_question": "为什么花了很多时间学习却记不住、用不上"}
    ok = {"storyline": story, "slides": [
        {"layout": "summary", "role": "conclusion", "title": "时间没换来记住", "notes": NOTES},
        {"layout": "end", "title": "谢谢"},
    ]}
    bad = {"storyline": story, "slides": [
        {"layout": "summary", "role": "conclusion", "title": "四个固定动作", "notes": NOTES},
        {"layout": "end", "title": "谢谢"},
    ]}
    assert "S_SUMMARY_NOT_ANSWER" not in _codes(ok)
    assert "S_SUMMARY_NOT_ANSWER" in _codes(bad)


def test_lead_rule():
    ok = {"storyline": STORY, "slides": [
        {"layout": "section", "title": "背景"},
        _content(role="background"),
        _content(lead="接着看下一条"),
    ]}
    bad = {"storyline": STORY, "slides": [
        {"layout": "section", "title": "背景"},
        _content(role="background"),
        _content(lead="", notes="材料显示这里有一条记录。" + "补" * 40),
    ]}
    assert "S_NO_LEAD" not in _codes(ok)
    assert "S_NO_LEAD" in _codes(bad)


def test_lead_accepts_接下来_and_still_flags_a_bare_wrap_up():
    ok = {"storyline": STORY, "slides": [
        {"layout": "section", "title": "背景"},
        _content(role="background"),
        _content(lead="", notes="命题立住了，接下来看作者用什么工具。" + "补" * 40),
    ]}
    bad = {"storyline": STORY, "slides": [
        {"layout": "section", "title": "背景"},
        _content(role="background"),
        _content(lead="", notes="这一页收束全篇。" + "补" * 40),
    ]}
    assert "S_NO_LEAD" not in _codes(ok)
    assert "S_NO_LEAD" in _codes(bad)


def test_notes_short():
    ok = {"slides": [_content(notes=NOTES)]}
    bad = {"slides": [_content(notes="太短")]}
    assert "S_NOTES_SHORT" not in _codes(ok)
    assert "S_NOTES_SHORT" in _codes(bad)


def test_toc_mismatch():
    ok = {"slides": [
        {"layout": "toc", "title": "目录", "items": [{"label": "背景"}, {"label": "方法"}]},
        {"layout": "section", "title": "背景"},
        {"layout": "section", "title": "方法"},
    ]}
    bad = {"slides": [
        {"layout": "toc", "title": "目录", "items": [{"label": "背景"}]},
        {"layout": "section", "title": "背景"},
        {"layout": "section", "title": "方法"},
    ]}
    assert "S_TOC_MISMATCH" not in _codes(ok)
    assert "S_TOC_MISMATCH" in _codes(bad)


def test_dup_message():
    ok = {"storyline": STORY, "slides": [
        _content(title="土地制度已经发生变化"),
        _content(title="听众提问集中在方法上"),
    ]}
    bad = {"storyline": STORY, "slides": [
        _content(title="土地制度已经发生变化"),
        _content(title="土地制度已经发生变化"),
    ]}
    assert "S_DUP_MESSAGE" not in _codes(ok)
    assert "S_DUP_MESSAGE" in _codes(bad)


def test_form_repeat():
    ok = {"storyline": STORY, "slides": [
        _content(layout="bullets"),
        _content(layout="bullets"),
        _content(layout="cards"),
    ]}
    bad = {"storyline": STORY, "slides": [
        _content(layout="bullets"),
        _content(layout="bullets"),
        _content(layout="bullets"),
    ]}
    assert "S_FORM_REPEAT" not in _codes(ok)
    assert "S_FORM_REPEAT" in _codes(bad)


def test_evidence_missing():
    slides = [_content(), _content()]
    ok = {"storyline": {"deck_type": "research_talk", "slots": [
        {"kind": "content", "evidence": "档案"},
        {"kind": "content", "evidence": "统计"},
    ]}, "slides": slides}
    bad = {"storyline": {"deck_type": "research_talk", "slots": [
        {"kind": "content", "evidence": "材料不足"},
        {"kind": "content", "evidence": "统计"},
    ]}, "slides": slides}
    assert "S_EVIDENCE_MISSING" not in _codes(ok)
    assert "S_EVIDENCE_MISSING" in _codes(bad)


def test_old_plan_only_checks_structure_and_notes():
    plan = {"slides": [
        {"layout": "section", "title": "只有一章"},
        {"layout": "bullets", "title": "背景", "notes": ""},
    ]}
    codes = set(_codes(plan))
    assert "S_THIN_SECTION" in codes
    assert "S_NOTES_SHORT" in codes
    assert "S_NO_QUESTION" not in codes
    assert "S_NO_SUMMARY" not in codes


def test_diagnosed_21_page_shape_reports_core_issues():
    slides = [{"layout": "cover", "title": "题目"}, {
        "layout": "toc", "title": "目录",
        "items": [{"label": f"章{i}"} for i in range(6)],
    }]
    for index in range(6):
        slides.append({"layout": "section", "title": f"章{index}"})
        for nth in range(2):
            slides.append({
                "layout": "bullets",
                "title": "占位标题甲乙丙丁",
                "role": "finding",
                "notes": "" if index * 2 + nth < 7 else NOTES,
            })
    slides.append({"layout": "end", "title": "谢谢"})
    plan = {"storyline": STORY, "slides": slides}
    assert len(slides) == 21
    codes = set(_codes(plan))
    assert {"S_NO_QUESTION", "S_NO_SUMMARY", "S_SECTION_HEAVY", "S_NOTES_SHORT"} <= codes


def _scores(bridge=2):
    return {"opening": 4, "order": 3, "bridge": bridge, "focus": 4, "closing": 3, "evidence": 4}


async def test_fix_story_rewrites_only_named_page():
    slides = [_content(title=f"第{index}页土地制度是在变化的") for index in range(1, 8)]
    slides.append({"layout": "end", "title": "谢谢", "role": "end"})
    original = copy.deepcopy(slides)
    plan = {"storyline": STORY, "slides": slides}
    review = {
        "scores": _scores(),
        "issues": [{"page": 6, "dim": "bridge", "problem": "第 6 页接不上", "fix": "改承接句"}],
        "error": "",
    }
    calls = []

    async def write_page(current, page, _problems):
        calls.append(page)
        current["slides"][page - 1]["title"] = "这一页改成了承接句"
        current["slides"][0]["title"] = "不该被留下"
        return current

    updated, fixed = await ppt_plan.fix_story(plan, [], review, write_page=write_page)
    assert calls == [6]
    assert fixed == [6]
    assert updated["slides"][5]["title"] == "这一页改成了承接句"
    for index, slide in enumerate(updated["slides"]):
        if index == 5:
            continue
        assert slide["title"] == original[index]["title"]
        assert slide.get("notes") == original[index].get("notes")


def test_toc_rule_reads_slots_when_written_by_slots():
    def build(second_head):
        return {"storyline": STORY, "slides": [
            {"layout": "toc", "items": [{"label": "被截短"}, {"label": "的旧字"}],
             "slots": {"item1.head": "研究问题", "item2.head": second_head}},
            {"layout": "section", "title": "改写过的判断句标题", "slots": {"section_title": "研究问题"}},
            {"layout": "section", "title": "另一个改写", "slots": {"section_title": "综述方法"}},
        ]}
    assert "S_TOC_MISMATCH" not in _codes(build("综述方法"))
    assert "S_TOC_MISMATCH" not in _codes(build("综述方"))
    assert "S_TOC_MISMATCH" in _codes(build("别的名字"))


async def test_fix_story_leaves_section_pages_alone():
    slides = [
        {"layout": "section", "title": "背景", "role": "section"},
        _content(title="土地制度是在变化的"),
        {"layout": "end", "title": "谢谢", "role": "end"},
    ]
    review = {"scores": _scores(), "error": "", "issues": [
        {"page": 1, "dim": "bridge", "problem": "章节页太短", "fix": "改长"},
        {"page": 2, "dim": "bridge", "problem": "接不上", "fix": "改承接"},
    ]}
    calls = []

    async def write_page(current, page, _problems):
        calls.append(page)
        return current

    _updated, fixed = await ppt_plan.fix_story({"storyline": STORY, "slides": slides}, [], review, write_page=write_page)
    assert calls == [2]
    assert fixed == [2]


async def test_failed_rewrite_keeps_written_slots(monkeypatch):
    async def fake_text(_user_id, _system, _user, model_id="", max_tokens=4000):
        return "", "", "不认识的模型"

    monkeypatch.setattr(ppt_plan, "_ask_text", fake_text)
    catalog = {"pages": [{"page": 4, "role": "content", "slots": [
        {"name": "title", "max_chars": 20, "required": True},
        {"name": "body", "max_chars": 80, "required": True},
    ]}]}
    written = _content(template_page=4, slots={"title": "土地制度是在变化的", "body": "材料里写了三次调整"})
    plan = {"storyline": {"slots": [{"kind": "content", "role": "finding"}]}, "slides": [written]}
    updated = await ppt_plan._rewrite_one(plan, 1, [{"problem": "接不上"}], "u", "", "", catalog)
    slide = updated["slides"][0]
    assert slide["slots"] == {"title": "土地制度是在变化的", "body": "材料里写了三次调整"}
    assert not slide.get("write_fallback")


async def test_failed_first_write_still_falls_back(monkeypatch):
    async def fake_text(_user_id, _system, _user, model_id="", max_tokens=4000):
        return "", "", "不认识的模型"

    monkeypatch.setattr(ppt_plan, "_ask_text", fake_text)
    catalog = {"pages": [{"page": 4, "role": "content", "slots": [
        {"name": "title", "max_chars": 20, "required": True},
    ]}]}
    plan = {"slides": [_content(template_page=4)]}
    story = {"slots": [{"kind": "content", "role": "finding"}]}
    updated, note = await ppt_plan.write_pages(plan, story, [], catalog, "", "", "u")
    assert updated["slides"][0]["write_fallback"] is True
    assert "slots" not in updated["slides"][0]
    assert note


async def test_make_plan_passes_model_id_to_review(monkeypatch):
    seen = {}

    async def fake_storyline(*_args, **_kwargs):
        return None, "跳过"

    async def fake_json(_user_id, _system, _user, model_id="", max_tokens=0, retries=1):
        return {"slides": [_content(), {"layout": "end", "title": "谢谢"}]}, "显示名", ""

    async def fake_enrich(plan, *_args, **_kwargs):
        return plan

    async def fake_enabled(_user_id):
        return True

    async def fake_review(plan, user_id, writer_model="", material="", catalog=None):
        seen["writer"] = writer_model
        return plan

    from services.ppt import ppt_story
    monkeypatch.setattr(ppt_story, "make_storyline", fake_storyline)
    monkeypatch.setattr(ppt_plan, "_ask_json", fake_json)
    monkeypatch.setattr(ppt_plan, "_enrich_thin", fake_enrich)
    monkeypatch.setattr(ppt_plan, "_review_enabled", fake_enabled)
    monkeypatch.setattr(ppt_plan, "run_story_review", fake_review)
    await ppt_plan.make_plan("u", "材料" * 50, model_id="deepseek-chat", pages=3)
    assert seen["writer"] == "deepseek-chat"
    assert seen["writer"] != "显示名"


async def test_bad_review_json_keeps_the_plan(monkeypatch):
    async def fake_judge(_user_id="", _writer_model=""):
        return "judge-stub", False

    async def fake_text(_user_id, _system, _user, model_id="", max_tokens=4000):
        return "这不是 JSON", "judge-stub", ""

    monkeypatch.setattr(ppt_story_check, "pick_judge", fake_judge)
    monkeypatch.setattr(ppt_plan, "_ask_text", fake_text)
    plan = {"storyline": STORY, "slides": [
        _content(),
        {"layout": "summary", "role": "conclusion", "title": "土地制度的变化已经写明", "notes": NOTES},
        {"layout": "end", "title": "谢谢"},
    ]}
    produced = await ppt_plan.run_story_review(copy.deepcopy(plan), "u", "writer")
    assert produced["slides"][0]["title"] == plan["slides"][0]["title"]
    assert "JSON" in produced["review"]["error"]
    assert produced["review"]["rounds"] == 1
    assert produced["review"]["fixed_pages"] == []
    assert produced["review"]["review_calls"] == 1


async def test_missing_summary_writes_only_the_new_page():
    story = {
        "deck_type": "research_talk",
        "central_question": "土地制度如何变化",
        "answer": "土地制度的变化已经写明",
        "sections": [{"no": 1, "title": "背景", "role": "background", "pages": 2}],
        "slots": [
            {"kind": "cover"},
            {"kind": "content", "role": "background", "message": "土地制度是在变化的", "section": 1},
            {"kind": "content", "role": "finding", "message": "比较前后能看出差别", "section": 1},
            {"kind": "end"},
        ],
    }
    slides = [
        {"layout": "cover", "title": "封面标题在这里", "role": "cover"},
        _content(role="background", title="土地制度是在变化的"),
        _content(role="finding", title="比较前后能看出差别"),
        {"layout": "end", "title": "谢谢", "role": "end"},
    ]
    plan = {"storyline": story, "slides": slides, "plan_version": 2}
    assert "S_NO_SUMMARY" in _codes(plan)
    calls = []

    async def write_page(current, page, _problems):
        calls.append(page)
        current["slides"][page - 1]["title"] = "总结回答了问题"
        current["slides"][page - 1]["notes"] = NOTES
        return current

    updated, fixed = await ppt_plan.fix_story(
        plan, ppt_story_check.check_story(plan), {"scores": {}, "issues": [], "error": ""},
        write_page=write_page)
    assert calls == [4]
    assert fixed == [4]
    assert updated["slides"][3]["role"] == "conclusion"
    assert updated["slides"][0]["title"] == "封面标题在这里"
    assert updated["slides"][1]["title"] == "土地制度是在变化的"
    assert updated["slides"][2]["title"] == "比较前后能看出差别"
    assert updated["slides"][4]["title"] == "谢谢"
    assert updated["slides"][1]["notes"] == NOTES


async def test_review_stops_after_two_rounds(monkeypatch):
    calls = {"review": 0, "write": 0}

    async def fake_review(_plan, _user_id="", _writer_model=""):
        calls["review"] += 1
        return {
            "scores": _scores(),
            "issues": [{"page": 1, "dim": "bridge", "problem": "接不上", "fix": "改承接"}],
            "judge_model": "judge",
            "same_model": False,
            "error": "",
        }

    async def fake_one(plan, page, problems, user_id="", model_id="", material="",
                       catalog=None, write_page=None):
        calls["write"] += 1
        return plan

    monkeypatch.setattr(ppt_story_check, "review_story", fake_review)
    monkeypatch.setattr(ppt_plan, "_rewrite_one", fake_one)
    plan = {"storyline": STORY, "story_issues": ppt_story_check.check_story({
        "storyline": STORY,
        "slides": [
            _content(role="question", title="土地制度为什么会变化？"),
            {"layout": "summary", "role": "conclusion", "title": "土地制度的变化已经写明", "notes": NOTES},
            {"layout": "end", "title": "谢谢"},
        ],
    }), "slides": [
        _content(role="question", title="土地制度为什么会变化？"),
        {"layout": "summary", "role": "conclusion", "title": "土地制度的变化已经写明", "notes": NOTES},
        {"layout": "end", "title": "谢谢"},
    ]}
    produced = await ppt_plan.run_story_review(plan, "u", "writer")
    assert calls["review"] == 2
    assert calls["write"] >= 1
    assert calls["review"] < 3
    assert produced["review"]["rounds"] == 2


async def test_worse_second_review_restores_the_slides(monkeypatch):
    calls = {"review": 0}

    async def fake_review(_plan, _user_id="", _writer_model=""):
        calls["review"] += 1
        scores = _scores(bridge=4 if calls["review"] == 1 else 1)
        return {
            "scores": scores,
            "issues": [{"page": 1, "dim": "bridge", "problem": "接不上", "fix": "改承接"}],
            "judge_model": "judge",
            "same_model": False,
            "error": "",
        }

    async def fake_one(plan, page, problems, user_id="", model_id="", material="",
                       catalog=None, write_page=None):
        plan["slides"][page - 1]["title"] = "改坏了的标题"
        return plan

    monkeypatch.setattr(ppt_story_check, "review_story", fake_review)
    monkeypatch.setattr(ppt_plan, "_rewrite_one", fake_one)
    plan = {"storyline": STORY, "slides": [
        _content(title="土地制度是在变化的"),
        {"layout": "end", "title": "谢谢"},
    ]}
    produced = await ppt_plan.run_story_review(plan, "u", "writer")
    assert produced["slides"][0]["title"] == "土地制度是在变化的"
    assert produced["review"]["fixed_pages"] == []
    assert produced["review"]["scores_after"]["bridge"] == 4


def test_review_brief_uses_the_notes_when_lead_is_empty():
    plan = {"storyline": STORY, "slides": [
        _content(lead="", notes="上一页讲了现象。这一页给原因。" + "证" * 40),
    ]}
    text = ppt_story_check.review_brief(plan)
    assert "承接：上一页讲了现象" in text


async def test_pick_judge_prefers_another_provider(monkeypatch):
    async def fake_settings(_user_id="default"):
        return {"model": "deepseek-chat", "deepseek_api_key": "set", "qwen_api_key": "set"}

    monkeypatch.setattr("services.state_tracker.tracker.get_settings", fake_settings)
    monkeypatch.setattr("services.state_tracker.inspect_secret", lambda _key, stored: (bool(stored), False))
    judge, same = await ppt_story_check.pick_judge("u", "deepseek-chat")
    assert judge != "deepseek-chat"
    assert same is False
    assert ppt_story_check._model_provider(judge) == "qwen"


async def test_pick_judge_same_model_when_one_provider(monkeypatch):
    async def fake_settings(_user_id="default"):
        return {"model": "deepseek-chat", "deepseek_api_key": "set"}

    monkeypatch.setattr("services.state_tracker.tracker.get_settings", fake_settings)
    monkeypatch.setattr("services.state_tracker.inspect_secret", lambda _key, stored: (bool(stored), False))
    judge, same = await ppt_story_check.pick_judge("u", "deepseek-chat")
    assert judge == "deepseek-chat"
    assert same is True


def test_review_sentence():
    text = ppt_story_check.review_sentence({
        "review": {
            "scores_after": _scores(bridge=2),
            "fixed_pages": [6, 9, 11],
            "same_model": True,
        },
    })
    assert text.startswith("衔接评分 3.3 / 5，修了 3 页")
    assert "评委和写稿是同一个模型" in text
