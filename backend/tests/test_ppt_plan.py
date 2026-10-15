"""读材料 → 出计划：提料压缩、计划规范化、校验、兜底截断（都不调模型）。"""

import asyncio
import copy
import json
import pathlib

import pytest

from services.ppt import ppt_plan


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    """覆盖 conftest 的同名 fixture：不用 pytest 的 tmp_path。"""
    sandbox = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "pytest-env"
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(sandbox / "test_ars.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(sandbox / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(sandbox / "workspaces"))
    monkeypatch.setenv("ARS_PPT_REVIEW", "0")


def _long_material() -> str:
    titles = ["摘要", "一、研究背景与问题", "（一）理论框架", "二、材料与方法",
              "第三章 制度变迁", "1.1 数据来源", "五、结论与讨论"]
    blocks = []
    for i, title in enumerate(titles):
        body = ("这是第 %d 节的正文，交代研究的问题与背景。" % i) + "内容内容内容。" * 900
        body += f"\n{i}98 年的统计显示，比例为 47%。因此本文认为，这一节值得展开。"
        blocks.append(f"{title}\n{body}")
    return "\n".join(blocks)


def test_digest_keeps_every_section_title_and_limit():
    material = _long_material()
    assert len(material) > ppt_plan.DIGEST_LIMIT
    digest = ppt_plan.digest_material(material)
    assert len(digest) <= ppt_plan.DIGEST_LIMIT
    for title in ["摘要", "一、研究背景与问题", "（一）理论框架", "二、材料与方法",
                  "第三章 制度变迁", "1.1 数据来源", "五、结论与讨论"]:
        assert title in digest, f"少了这一节：{title}"


def test_digest_returns_short_material_as_is():
    short = "很短的一段材料。"
    assert ppt_plan.digest_material(short) == short
    assert ppt_plan.digest_material("") == ""


def test_digest_keeps_key_sentences():
    material = _long_material()
    digest = ppt_plan.digest_material(material)
    assert "%" in digest or "因此" in digest      # 带数字/结论的句子被留下了


def test_split_sections_recognizes_heads():
    text = "# 一级标题\n正文甲\n一、第二节\n正文乙\n第2章 第三节\n正文丙"
    sections = ppt_plan.split_sections(text)
    titles = [t for t, _ in sections]
    assert "# 一级标题" in titles
    assert "一、第二节" in titles
    assert "第2章 第三节" in titles


def test_spec_text_lists_every_layout_with_limits():
    text = ppt_plan.spec_text()
    for layout in ppt_plan.CONTENT_LAYOUTS:
        assert layout in text
    assert "≤28" in text        # cards[].desc 的上限
    assert "≤6" in text         # 卡片名


def test_build_plan_prompt_carries_pages_and_guidance():
    prompt = ppt_plan.build_plan_prompt("材料正文", "多用对比", 12)
    assert "12 页" in prompt
    assert "多用对比" in prompt
    assert "材料正文" in prompt


def test_normalize_fixes_first_last_and_unknown_layout():
    plan = {"slides": [
        {"layout": "bullets", "title": "开篇", "points": ["甲", "乙", "丙"]},
        {"layout": "sparkle", "title": "神秘页", "cards": [{"key": "甲", "desc": "说明"}]},
        {"layout": "bullets", "title": "尾页", "points": ["x", "y", "z"]},
    ]}
    slides = ppt_plan.normalize(plan)["slides"]
    assert slides[0]["layout"] == "cover"
    assert slides[-1]["layout"] == "end"
    assert slides[1]["layout"] == "bullets"
    assert slides[1]["points"] == ["甲：说明"]


def test_extra_page_beyond_the_story_keeps_one_end():
    slots = [{"kind": "cover"}] + [{"kind": "content"} for _ in range(11)] + [{"kind": "end"}]
    slides = [{"layout": "cover", "title": "封面"}]
    slides += [{"layout": "bullets", "title": f"第{index}页", "points": ["甲"], "notes": "原讲稿"} for index in range(11)]
    slides.append({"layout": "end", "title": "谢谢", "template_page": 26})
    slides.append({"layout": "bullets", "title": "多出来的一页", "points": ["乙"], "notes": "这页不该单独存在"})
    out = ppt_plan.normalize({"storyline": {"slots": slots}, "slides": slides})["slides"]
    assert len(out) == 13
    assert [slide["layout"] for slide in out if slide["layout"] == "end"] == ["end"]
    assert out[-1]["title"] == "谢谢"
    assert "多出来的一页" in out[-2]["notes"]


def test_blank_extra_end_is_dropped():
    slots = [{"kind": "cover"}, {"kind": "content"}, {"kind": "end"}]
    slides = [
        {"layout": "cover", "title": "封面"},
        {"layout": "bullets", "title": "正文", "points": ["甲"], "notes": "讲稿"},
        {"layout": "end", "title": "谢谢", "template_page": 26, "notes": "收束"},
        {"layout": "end", "title": "", "template_page": None, "notes": ""},
    ]
    out = ppt_plan.normalize({"storyline": {"slots": slots}, "slides": slides})["slides"]
    assert len(out) == 3
    assert sum(1 for slide in out if slide["layout"] == "end") == 1
    assert out[-1]["title"] == "谢谢"


def test_normalize_clamps_item_counts():
    plan = {"slides": [
        {"layout": "cover", "title": "题", "subtitle": "", "info": ["a", "b"]},
        {"layout": "bullets", "title": "要点页", "points": ["1", "2", "3", "4", "5", "6", "7"]},
        {"layout": "end", "info": ["a", "b"]},
    ]}
    slides = ppt_plan.normalize(plan)["slides"]
    assert len(slides[1]["points"]) == 5      # bullets 上限 5 条


def test_validate_plan_reports_page_numbers():
    plan = {"slides": [
        {"layout": "cover", "title": "题", "subtitle": "", "info": ["a"]},
        {"layout": "cards", "title": "卡片页",
         "cards": [{"key": "甲", "desc": "字" * 40}, {"key": "乙", "desc": "短片"}],
         "takeaway": ""},
        {"layout": "end", "info": ["a"]},
    ]}
    issues = ppt_plan.validate_plan(plan)
    assert issues
    assert issues[0]["slide"] == 2
    assert issues[0]["field"] == "cards[0].desc"
    assert issues[0]["limit"] == 28


def test_hard_trim_shortens_and_keeps_original_in_notes():
    long_desc = "产权是一种社会工具，其重要性就在于事实上它们能帮助一个人形成他与其他人进行交易时的合理预期。"
    plan = {"slides": [
        {"layout": "cover", "title": "题", "subtitle": "", "info": ["a"]},
        {"layout": "cards", "title": "卡片页", "notes": "原有备注。",
         "cards": [{"key": "甲", "desc": long_desc}, {"key": "乙", "desc": "短片"}],
         "takeaway": ""},
        {"layout": "end", "info": ["a"]},
    ]}
    issues = ppt_plan.validate_plan(plan)
    assert issues
    fixed = ppt_plan.hard_trim(plan, issues)
    assert ppt_plan.validate_plan(fixed) == []
    trimmed = fixed["slides"][1]["cards"][0]["desc"]
    assert ppt_plan.ppt_layouts.text_len(trimmed) <= 28
    assert long_desc in fixed["slides"][1]["notes"]      # 原文进了备注
    assert "原有备注。" in fixed["slides"][1]["notes"]


def test_coerce_plan_accepts_pages_and_type_keys():
    """实测 DeepSeek 会把 slides 写成 pages、layout 写成 type，必须兜住。"""
    raw = {"title": "题", "pages": [
        {"type": "cover", "title": "甲", "subtitle": "", "info": ["a"]},
        {"type": "bullets", "title": "乙", "points": ["x", "y", "z"]},
    ]}
    out = ppt_plan._coerce_plan(raw)
    assert [s["layout"] for s in out["slides"]] == ["cover", "bullets"]
    assert ppt_plan._coerce_plan({}) == {}
    assert ppt_plan._coerce_plan({"title": "没有 slides"}) == {}
    assert ppt_plan._coerce_plan({"slides": []}) == {}


def test_plan_system_includes_structure_and_specs():
    system = ppt_plan.plan_system()
    assert '"slides"' in system          # 输出结构说明
    assert "layout" in system
    assert "cards" in system and "≤28" in system
    assert "简体中文" in system
    assert "七到九成" in system
    assert "宁可少写" not in system
    assert "提升效率" in system
    assert "需核实" in system


@pytest.mark.asyncio
async def test_make_plan_shortens_when_over_limit(monkeypatch):
    systems: list[str] = []
    calls = {"n": 0}

    async def fake_ask(user_id, system, user, model_id="", max_tokens=6000, retries=1):
        calls["n"] += 1
        systems.append(system)
        if calls["n"] == 1:
            over = {"slides": [
                {"layout": "cover", "title": "土地产权", "subtitle": "", "info": ["a"]},
                {"layout": "bullets", "title": "要点页", "points": ["甲" * 40, "乙", "丙"]},
                {"layout": "end", "info": ["b"]},
            ]}
            return over, "fake-model", ""
        fixed = {"slides": [
            {"layout": "cover", "title": "土地产权", "subtitle": "", "info": ["a"]},
            {"layout": "bullets", "title": "一九五二年的土改",
             "points": [
                 "1952年华北各县按人口把耕地分到户例如三口之家",
                 "隔七天再回忆一次比当晚连着读三遍会记得更加牢靠才会更好啊",
                 "用自己的话讲给同桌听讲不出的地方就是还没有学会啊呀呢",
             ],
             "notes": "这页讲土改怎么分地，以及为什么要隔几天再回忆一次。" * 4},
            {"layout": "end", "info": ["b"]},
        ]}
        return fixed, "fake-model", ""

    monkeypatch.setattr(ppt_plan, "_ask_json", fake_ask)

    async def _no_story(*_args, **_kwargs):
        return None, "skip"

    monkeypatch.setattr("services.ppt.ppt_story.make_storyline", _no_story)
    plan, model_name, err = await ppt_plan.make_plan("u1", "材料正文", pages=3)
    assert err == ""
    assert model_name == "fake-model"
    assert calls["n"] == 2                       # 第二次是"改短"
    assert ppt_plan.validate_plan(plan) == []
    assert len(plan["slides"]) == 3


@pytest.mark.asyncio
async def test_make_plan_hard_trims_when_shorten_fails(monkeypatch):
    async def fake_ask(user_id, system, user, model_id="", max_tokens=6000, retries=1):
        over = {"slides": [
            {"layout": "cover", "title": "题", "subtitle": "", "info": ["a"]},
            {"layout": "bullets", "title": "要点页", "points": ["甲" * 60, "乙", "丙"]},
            {"layout": "end", "info": ["b"]},
        ]}
        return over, "fake-model", ""            # 每次都给同一份超限计划

    monkeypatch.setattr(ppt_plan, "_ask_json", fake_ask)

    async def _no_story(*_args, **_kwargs):
        return None, "skip"

    monkeypatch.setattr("services.ppt.ppt_story.make_storyline", _no_story)
    plan, _, err = await ppt_plan.make_plan("u1", "材料", pages=3)
    assert err == ""
    assert ppt_plan.validate_plan(plan) == []    # 兜底截断之后不再超限
    assert "甲" * 60 in plan["slides"][1]["notes"]


@pytest.mark.asyncio
async def test_make_plan_returns_error_without_model(monkeypatch):
    async def fake_ask(user_id, system, user, model_id="", max_tokens=6000, retries=1):
        return {}, "", "DeepSeek 还没配 API Key，请到设置里填"

    monkeypatch.setattr(ppt_plan, "_ask_json", fake_ask)

    async def _no_story(*_args, **_kwargs):
        return None, "skip"

    monkeypatch.setattr("services.ppt.ppt_story.make_storyline", _no_story)
    plan, _, err = await ppt_plan.make_plan("u1", "材料")
    assert plan == {}
    assert "API Key" in err


@pytest.mark.asyncio
async def test_revise_plan_passes_instruction(monkeypatch):
    seen = {}

    async def fake_ask(user_id, system, user, model_id="", max_tokens=6000, retries=1):
        seen["user"] = user
        return {"slides": [{"layout": "cover", "title": "题", "subtitle": "", "info": ["a"]},
                           {"layout": "timeline", "title": "时间轴页",
                            "nodes": [{"year": "1952", "head": "起步", "desc": "开始"},
                                      {"year": "1978", "head": "转折", "desc": "包产到户"},
                                      {"year": "1982", "head": "定型", "desc": "合法化"}]},
                           {"layout": "end", "info": ["b"]}]}, "fake-model", ""

    monkeypatch.setattr(ppt_plan, "_ask_json", fake_ask)
    plan, err = await ppt_plan.revise_plan({"slides": []}, "第 6 页改成时间轴")
    assert err == ""
    assert "第 6 页改成时间轴" in seen["user"]
    assert "layout 改成 timeline" in seen["user"]
    assert plan["slides"][1]["layout"] == "timeline"


def test_pin_other_pages_drops_an_inserted_slide():
    before = {
        "title": "高效学习",
        "slides": [
            {"layout": "cover", "title": "封面", "subtitle": "", "info": ["a"]},
            {"layout": "toc", "title": "目录", "items": [
                {"label": "本质", "desc": "定义"}, {"label": "方法", "desc": "做法"},
                {"label": "习惯", "desc": "坚持"},
            ]},
            {"layout": "section", "index": "01", "title": "学习本质", "subs": ["定义"]},
            {"layout": "compare", "title": "主动回忆与被动重读的差异",
             "left": {"head": "主动回忆", "points": ["合上书回忆", "检验记住"]},
             "right": {"head": "被动重读", "points": ["反复看", "熟悉感"]}},
            {"layout": "timeline", "title": "遗忘曲线", "nodes": [
                {"year": "1天", "head": "遗忘", "desc": "掉得快"},
                {"year": "1周", "head": "复习", "desc": "拉回来"},
                {"year": "1月", "head": "巩固", "desc": "稳住"},
            ]},
            {"layout": "end", "info": ["完"]},
        ],
    }
    inserted = copy.deepcopy(before)
    inserted["slides"].insert(3, {"layout": "timeline", "title": "学习原理的探索过程", "nodes": []})
    pinned = ppt_plan.pin_other_pages(before, inserted, "第  4页改成时间轴")
    # 页数对不上，第 4 页仍用原来的对比页改成时间轴，后面的页不后移
    assert len(pinned["slides"]) == len(before["slides"])
    assert pinned["slides"][3]["layout"] == "timeline"
    assert pinned["slides"][3]["title"] == "主动回忆与被动重读的差异"
    assert pinned["slides"][4] == before["slides"][4]
    same_length = copy.deepcopy(before)
    same_length["slides"][3] = {
        "layout": "timeline", "title": "主动回忆与被动重读的差异",
        "nodes": [
            {"year": "01", "head": "主动", "desc": "合上书"},
            {"year": "02", "head": "被动", "desc": "反复看"},
            {"year": "03", "head": "差异", "desc": "熟悉感"},
        ],
    }
    same_length["slides"][4] = {"layout": "bullets", "title": "被模型改掉", "points": ["一", "二", "三"]}
    kept = ppt_plan.pin_other_pages(before, same_length, "第 4 页改成时间轴")
    assert kept["slides"][3]["layout"] == "timeline"
    assert kept["slides"][3]["nodes"][0]["head"] == "主动"
    assert kept["slides"][4] == before["slides"][4]


def test_force_layout_change_rewrites_a_section_page():
    slides = [{"layout": "cover", "title": "封面", "subtitle": "", "info": ["a"]}]
    slides.append({"layout": "toc", "title": "目录", "items": [
        {"label": "原理", "desc": "怎么学"}, {"label": "方法", "desc": "怎么做"},
        {"label": "习惯", "desc": "怎么坚持"},
    ]})
    slides.append({"layout": "section", "index": "01", "title": "学习原理",
                   "subs": ["主动回忆", "间隔复习", "提取练习"]})
    for _ in range(2):
        slides.append({"layout": "bullets", "title": "要点", "points": ["一", "二", "三"]})
    slides.append({"layout": "section", "index": "02", "title": "学习原理",
                   "subs": ["遗忘曲线", "复习节奏", "提取练习"]})
    slides.append({"layout": "end", "info": ["完"]})
    plan = ppt_plan.normalize({"title": "高效学习", "slides": slides})
    updated = ppt_plan.force_layout_change(plan, "第 6 页改成时间轴")
    page = updated["slides"][5]
    assert page["layout"] == "timeline"
    assert len(page["nodes"]) >= 3
    assert page["nodes"][0]["head"]
    untouched = ppt_plan.force_layout_change(plan, "第 6 页讲的是什么？")
    assert untouched["slides"][5]["layout"] == "section"


def _rich_slide() -> dict:
    return {
        "layout": "bullets",
        "title": "合上书才记得住",
        "points": [
            "1952年华北各县按人口把耕地分到户例如三口之家",
            "隔七天再回忆一次比当晚连着读三遍会记得更加牢靠才会更好啊",
            "用自己的话讲给同桌听讲不出的地方就是还没有学会啊呀呢",
        ],
        "notes": "这页讲主动回忆为什么比重读有效。原因是提取比重复更费力。例如合上教材讲一遍。下一页看复习间隔。" * 2,
    }


def test_thin_reasons_hit_and_miss_each_rule():
    rich = _rich_slide()
    assert ppt_plan.thin_reasons(rich) == []
    assert ppt_plan.thin_reasons({"layout": "cover", "title": "只有标题"}) == []

    short = copy.deepcopy(rich)
    short["title"] = "短"
    short["points"] = ["太短", "也很短", "还是短"]
    assert "short" in ppt_plan.thin_reasons(short)
    assert "short" not in ppt_plan.thin_reasons(rich)

    banned = copy.deepcopy(rich)
    banned["title"] = "用工具提升效率"
    assert "banned" in ppt_plan.thin_reasons(banned)
    assert "banned" not in ppt_plan.thin_reasons(rich)

    brief = copy.deepcopy(rich)
    brief["notes"] = "太短"
    assert "notes" in ppt_plan.thin_reasons(brief)
    assert "notes" not in ppt_plan.thin_reasons(rich)

    plain = copy.deepcopy(rich)
    plain["title"] = "学习要主动一些"
    plain["points"] = [
        "主动思考比被动接收更有效果一些",
        "好的习惯要天天做到才会慢慢变稳",
        "方法要对着自己的薄弱处来调整",
    ]
    assert "plain" in ppt_plan.thin_reasons(plain)
    assert "plain" not in ppt_plan.thin_reasons(rich)

    thin = copy.deepcopy(short)
    thin["notes"] = ""
    plan = {"slides": [
        {"layout": "cover", "title": "封"},
        thin,
        {"layout": "end", "info": ["谢谢"]},
    ]}
    assert ppt_plan.thin_page_numbers(plan) == [2]
    assert len(ppt_plan.thin_reasons(thin)) >= 2


@pytest.mark.asyncio
async def test_enrich_plan_keeps_unnamed_pages(monkeypatch):
    before = {
        "title": "原标题",
        "slides": [
            {"layout": "cover", "title": "封面不动", "subtitle": "", "info": ["a"]},
            {"layout": "bullets", "title": "薄页", "points": ["甲", "乙", "丙"], "notes": ""},
            {"layout": "bullets", "title": "厚页不动", "points": ["一", "二", "三"], "notes": "够长"},
            {"layout": "end", "info": ["谢谢"]},
        ],
    }

    async def fake_ask(user_id, system, user, model_id="", max_tokens=6000, retries=1):
        changed = copy.deepcopy(before)
        changed["title"] = "被改掉的标题"
        changed["slides"][0]["title"] = "封面被改"
        changed["slides"][1]["title"] = "充实后的标题"
        changed["slides"][2]["title"] = "厚页不该变"
        return changed, "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_json", fake_ask)
    out, err = await ppt_plan.enrich_plan(before, [2], "材料里有1952年的例子", "", "u")
    assert err == ""
    assert out["title"] == "原标题"
    assert out["slides"][0]["title"] == "封面不动"
    assert out["slides"][1]["title"] == "充实后的标题"
    assert out["slides"][2]["title"] == "厚页不动"


@pytest.mark.asyncio
async def test_enrich_plan_drops_an_inserted_slide(monkeypatch):
    before = {"slides": [
        {"layout": "cover", "title": "封面", "subtitle": "", "info": ["a"]},
        {"layout": "bullets", "title": "薄", "points": ["甲", "乙", "丙"]},
        {"layout": "end", "info": ["谢谢"]},
    ]}

    async def fake_ask(user_id, system, user, model_id="", max_tokens=6000, retries=1):
        extra = copy.deepcopy(before)
        extra["slides"].insert(1, {"layout": "bullets", "title": "多出来的", "points": ["甲", "乙", "丙"]})
        return extra, "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_json", fake_ask)
    out, err = await ppt_plan.enrich_plan(before, [2], "材料", "", "u")
    assert "页数" in err
    assert len(out["slides"]) == 3
    assert out["slides"][1]["title"] == "薄"


@pytest.mark.asyncio
async def test_enrich_retries_once_when_the_connection_drops(monkeypatch):
    before = {"title": "原", "slides": [
        {"layout": "cover", "title": "封面", "subtitle": "", "info": ["a"]},
        {"layout": "bullets", "title": "薄", "points": ["甲", "乙", "丙"]},
        {"layout": "end", "info": ["谢谢"]},
    ]}
    calls = {"n": 0}

    async def fake_ask(user_id, system, user, model_id="", max_tokens=6000, retries=1):
        calls["n"] += 1
        if calls["n"] == 1:
            return {}, "", "DeepSeek Chat 没有连上：ConnectError"
        changed = copy.deepcopy(before)
        changed["slides"][1]["title"] = "补上了"
        return changed, "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_json", fake_ask)
    out, err = await ppt_plan.enrich_plan(before, [2], "材料", "", "u")
    assert err == ""
    assert calls["n"] == 2
    assert out["slides"][1]["title"] == "补上了"
    assert out["slides"][0]["title"] == "封面"


def test_needs_content_draft_only_when_the_material_is_short():
    assert ppt_plan.needs_content_draft("生成一个关于学习方法的 PPT") is True
    assert ppt_plan.needs_content_draft("材" * 800) is False
    assert ppt_plan.draft_title("# 学习方法\n\n## 回忆\n- 合上书") == "学习方法"
    fenced = "```markdown\n# 标题\n正文\n```"
    assert ppt_plan._strip_fence(fenced).startswith("# 标题")


@pytest.mark.asyncio
async def test_write_content_draft_returns_markdown(monkeypatch):
    async def fake_text(user_id, system, user, model_id="", max_tokens=4000):
        assert "需核实" in system
        assert "学习方法" in user
        return "# 学习方法\n\n## 回忆\n- 合上书复述，例如讲给同桌听。1952年（需核实）", "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", fake_text)
    text, name, err = await ppt_plan.write_content_draft("u", "生成一个关于学习方法的 PPT")
    assert err == ""
    assert name == "fake"
    assert text.startswith("# 学习方法")
    assert "（需核实）" in text


def _ready_plan() -> dict:
    return {"title": "土地产权", "subtitle": "副标题", "slides": [
        {"layout": "cover", "title": "土地产权", "subtitle": "", "info": ["a"]},
        {"layout": "bullets", "title": "一九五二年的土改",
         "points": [
             "1952年华北各县按人口把耕地分到户例如三口之家",
             "隔七天再回忆一次比当晚连着读三遍会记得更加牢靠才会更好啊",
             "用自己的话讲给同桌听讲不出的地方就是还没有学会啊呀呢",
         ],
         "notes": "这页讲土改怎么分地，以及为什么要隔几天再回忆一次。" * 4},
        {"layout": "end", "info": ["b"]},
    ]}


@pytest.mark.asyncio
async def test_make_plan_attaches_storyline(monkeypatch):
    story = {
        "deck_type": "research_talk",
        "central_question": "间隔复习有没有用？",
        "answer": "有用。",
        "sections": [{"no": 1, "title": "研究背景", "role": "background", "question": "背景是什么", "pages": 2}],
        "slots": [{"no": 1, "kind": "cover"}, {"no": 2, "kind": "end"}],
    }
    seen = {}

    async def fake_story(*_args, **_kwargs):
        return story, ""

    async def fake_ask(user_id, system, user, model_id="", max_tokens=6000, retries=1):
        seen["system"] = system
        seen["user"] = user
        return _ready_plan(), "fake-model", ""

    monkeypatch.setattr("services.ppt.ppt_story.make_storyline", fake_story)
    monkeypatch.setattr(ppt_plan, "_ask_json", fake_ask)
    plan, _, err = await ppt_plan.make_plan("u1", "材料", pages=12, guidance="做成研究汇报")
    assert err == ""
    assert plan["plan_version"] == 2
    assert plan["storyline"]["central_question"] == "间隔复习有没有用？"
    assert "叙事骨架" in seen["user"]
    assert "按叙事骨架逐页写" in seen["system"]
    assert "默认 10" not in seen["system"]


@pytest.mark.asyncio
async def test_make_plan_falls_back_when_storyline_fails(monkeypatch):
    seen = {}

    async def fake_story(*_args, **_kwargs):
        return None, "解析失败"

    async def fake_ask(user_id, system, user, model_id="", max_tokens=6000, retries=1):
        seen["user"] = user
        seen["system"] = system
        return _ready_plan(), "fake-model", ""

    monkeypatch.setattr("services.ppt.ppt_story.make_storyline", fake_story)
    monkeypatch.setattr(ppt_plan, "_ask_json", fake_ask)
    plan, _, err = await ppt_plan.make_plan("u1", "材料", pages=12)
    assert err == ""
    assert plan.get("plan_version") != 2
    assert "storyline" not in plan
    assert plan["story_note"] == "这次没能先排讲法，按旧方法出的"
    assert "叙事骨架" not in seen["user"]
    assert "默认 10" in seen["system"]


@pytest.mark.asyncio
async def test_write_content_draft_uses_deck_headings(monkeypatch):
    systems: list[str] = []

    async def fake_text(user_id, system, user, model_id="", max_tokens=4000):
        systems.append(system)
        return "# 题\n\n## 一\n- 例子（需核实）", "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", fake_text)
    await ppt_plan.write_content_draft("u", "中国近代女性形象研究")
    await ppt_plan.write_content_draft("u", "做一个讲解学习方法的课件")
    assert "研究背景" in systems[0] and "研究问题" in systems[0]
    assert "从一个例子说起" in systems[1]
    assert "需核实" in systems[0]


def _three_card_catalog() -> dict:
    slots = [
        {"name": "title", "max_chars": 18, "max_lines": 1, "required": True},
        {"name": "item1.body", "max_chars": 40, "max_lines": 3, "required": True},
        {"name": "item2.body", "max_chars": 40, "max_lines": 3, "required": True},
        {"name": "item3.body", "max_chars": 40, "max_lines": 3, "required": True},
    ]
    return {"pages": [{
        "page": 12, "role": "content", "form": "cards",
        "description": "标题在上，下面三张并列卡片", "slots": slots,
    }]}


def test_slot_schema_text_lists_the_third_card_body():
    card = _three_card_catalog()["pages"][0]
    card = {**card, "no": 5}
    text = ppt_plan.slot_schema_text(card)
    assert "item3.body" in text
    assert "≤40 字" in text


def test_project_legacy_and_thin_pages_read_slots():
    slide = {
        "layout": "cards",
        "notes": "短",
        "slots": {"title": "合上书才记得住", "item1.head": "提取", "item1.body": "合上书复述"},
        "slot_limits": {"title": 18, "item1.body": 40, "item2.body": 40, "item3.body": 40},
    }
    ppt_plan.project_legacy(slide)
    assert slide["title"] == "合上书才记得住"
    assert slide["points"] == ["提取：合上书复述"]
    numbers = ppt_plan.thin_page_numbers({"slides": [slide]})
    assert numbers == [1]


def test_unknown_slot_name_is_dropped():
    slide = {"layout": "cards", "locked_slots": []}
    warnings = ppt_plan.apply_written_slots(slide, _three_card_catalog()["pages"][0], {
        "slots": {"title": "听懂不等于会做", "item4.head": "编的", "item1.body": "合上书复述一遍"},
    })
    assert warnings == ["item4.head"]
    assert "item4.head" not in slide["slots"]
    assert slide["slots"]["item1.body"] == "合上书复述一遍"


def test_lead_is_kept_when_the_page_has_no_lead_slot():
    slide = {"layout": "cards", "locked_slots": []}
    ppt_plan.apply_written_slots(slide, _three_card_catalog()["pages"][0], {
        "slots": {"title": "听懂不等于会做"},
        "lead": "上一页只讲了现象，这一页给出原因",
        "notes": "承接上一页。实验里合上书复述的人记得更牢。",
    })
    assert slide["lead"] == "上一页只讲了现象，这一页给出原因"
    assert "lead" not in slide["slots"]


@pytest.mark.asyncio
async def test_overlong_slot_is_cut_into_notes(monkeypatch):
    long = "字" * 30
    plan = {"slides": [{
        "layout": "cards", "template_page": 12, "notes": "",
        "slots": {"title": long}, "slot_limits": {"title": 18},
    }]}
    issues = [item for item in ppt_plan.validate_slots(plan, _three_card_catalog()) if item["kind"] == "over"]
    assert issues and issues[0]["field"] == "title"

    async def still_long(*_args, **_kwargs):
        return '{"pages": [{"no": 1, "slots": {"title": "' + long + '"}}]}', "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", still_long)
    shortened, err = await ppt_plan.shorten_slots(plan, issues)
    assert err == ""
    still = [item for item in ppt_plan.validate_slots(shortened, _three_card_catalog()) if item["kind"] == "over"]
    assert still and still[0]["field"] == "title"
    trimmed = ppt_plan.trim_slot_overflow(shortened, still)
    assert ppt_plan.ppt_layouts.text_len(trimmed["slides"][0]["slots"]["title"]) <= 18
    assert f"原句：{long}" in trimmed["slides"][0]["notes"]
    assert trimmed["slides"][0]["slots"]["title"] != "谢谢"


@pytest.mark.asyncio
async def test_blank_required_slots_count_as_not_written(monkeypatch):
    plan, story = _chapter_plan()

    async def empty_page(*_args, **_kwargs):
        return json.dumps({"pages": [
            {"no": 3, "slots": {}},
            {"no": 5, "slots": {"title": ""}},
        ]}, ensure_ascii=False), "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", empty_page)
    written, _note = await ppt_plan.write_pages(plan, story, [], _three_card_catalog(), "材料")
    assert written["slides"][2].get("write_fallback") is True
    assert "slots" not in written["slides"][2]
    assert written["slides"][4].get("write_fallback") is True
    assert "slots" not in written["slides"][4]


@pytest.mark.asyncio
async def test_blank_rewrite_keeps_the_old_slots(monkeypatch):
    plan, story = _chapter_plan()
    plan["slides"][2]["slots"] = {
        "title": "原标题", "item1.body": "原内容", "item2.body": "乙", "item3.body": "丙",
    }
    plan["slides"][2]["write_fallback"] = False

    async def empty_page(*_args, **_kwargs):
        return '{"pages": [{"no": 3, "slots": {}}]}', "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", empty_page)
    written, _note = await ppt_plan.write_pages(
        plan, story, [], _three_card_catalog(), "材料", only={2})
    assert written["slides"][2]["slots"]["title"] == "原标题"
    assert written["slides"][2]["slots"]["item1.body"] == "原内容"
    assert written["slides"][2].get("write_fallback") is False


def test_end_title_over_the_limit_becomes_thanks():
    original = "记忆机制与提取练习"
    plan = {"slides": [{
        "layout": "end", "notes": "",
        "slots": {"title": original},
    }]}
    trimmed = ppt_plan.trim_slot_overflow(plan, [{
        "slide": 1, "field": "title", "kind": "over", "limit": 5, "text": original,
    }])
    assert trimmed["slides"][0]["slots"]["title"] == "谢谢"
    assert original in trimmed["slides"][0]["notes"]


def _chapter_plan() -> tuple[dict, dict]:
    story = {
        "deck_type": "lecture",
        "central_question": "为什么听懂了还是做不出？",
        "sections": [
            {"no": 1, "title": "例子", "role": "hook", "question": "为什么", "pages": 1},
            {"no": 2, "title": "概念", "role": "concept", "question": "是什么", "pages": 1},
        ],
        "slots": [
            {"no": 1, "kind": "cover"},
            {"no": 2, "kind": "section", "section": 1},
            {"no": 3, "kind": "content", "role": "hook", "message": "听懂做不出", "bridge": "承接"},
            {"no": 4, "kind": "section", "section": 2},
            {"no": 5, "kind": "content", "role": "concept", "message": "提取不是重读", "bridge": "递进"},
            {"no": 6, "kind": "end"},
        ],
    }
    plan = {"title": "学习方法", "subtitle": "从知道到做到", "slides": [
        {"layout": "cover", "title": "旧封面"},
        {"layout": "section", "title": "旧章节", "index": "00", "subs": ["旧"]},
        {"layout": "bullets", "title": "旧内容一", "template_page": 12, "pick_fallback": False, "points": ["旧"]},
        {"layout": "section", "title": "旧章节二", "index": "00", "subs": ["旧"]},
        {"layout": "bullets", "title": "旧内容二", "template_page": 12, "pick_fallback": False, "points": ["旧"]},
        {"layout": "end", "info": ["旧"]},
    ]}
    return plan, story


@pytest.mark.asyncio
async def test_failed_chapter_keeps_old_fields(monkeypatch):
    plan, story = _chapter_plan()
    calls = []

    async def fake_text(_user, _system, user, model_id="", max_tokens=4000):
        if "第 5 页（模板" in user:
            calls.append("fail")
            return "", "fake", "失败"
        calls.append("ok")
        return json.dumps({"pages": [{"no": 3, "slots": {
            "title": "听懂不等于会做",
            "item1.body": "上课是在认",
            "item2.body": "做题是在取",
            "item3.body": "例如睡前回忆",
        }, "notes": "这一页先讲听懂和做不出的差别，再用背单词的例子说明。下一页去分输入和提取。", "from": "材料第 1 节"}]}, ensure_ascii=False), "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", fake_text)
    written, note = await ppt_plan.write_pages(plan, story, [], _three_card_catalog(), "材料")
    assert calls == ["ok", "fail", "fail", "fail", "fail"]
    assert written["slides"][2]["slots"]["title"] == "听懂不等于会做"
    assert written["slides"][2]["points"][0].startswith("上课是在认") or "上课是在认" in "".join(written["slides"][2]["points"])
    assert "slots" not in written["slides"][4]
    assert written["slides"][4]["title"] == "旧内容二"
    assert "仍用原来的版式" in note
    assert written["slides"][0]["layout"] == "cover"
    assert written["slides"][1]["title"] == "例子"


@pytest.mark.asyncio
async def test_failed_page_is_rewritten_once(monkeypatch):
    plan, story = _chapter_plan()
    fails = {"n": 0}

    async def fake_text(_user, _system, user, model_id="", max_tokens=4000):
        if "第 5 页（模板" in user:
            fails["n"] += 1
            if fails["n"] <= 2:
                return "", "fake", "失败"
            return json.dumps({"pages": [{"no": 5, "slots": {
                "title": "关键变量不是市场",
                "item1.body": "国家界定产权",
                "item2.body": "农民反复争取",
                "item3.body": "制度因此变化",
            }, "notes": "这一页用国家与农民的例子说明命题。先承接上一页的背景，再给出判断，最后引出方法。"}]}, ensure_ascii=False), "fake", ""
        return json.dumps({"pages": [{"no": 3, "slots": {
            "title": "听懂不等于会做",
            "item1.body": "上课是在认",
            "item2.body": "做题是在取",
            "item3.body": "例如睡前回忆",
        }, "notes": "这一页先讲听懂和做不出的差别，再用背单词的例子说明。下一页去分输入和提取。"}]}, ensure_ascii=False), "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", fake_text)
    written, _note = await ppt_plan.write_pages(plan, story, [], _three_card_catalog(), "材料")
    assert fails["n"] == 3
    assert written["slides"][4]["write_fallback"] is False
    assert written["slides"][4]["slots"]["title"] == "关键变量不是市场"


@pytest.mark.asyncio
async def test_structural_pages_do_not_call_the_model(monkeypatch):
    calls = []

    async def fake_text(*_args, **_kwargs):
        calls.append(1)
        return '{"pages": []}', "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", fake_text)
    plan, story = _chapter_plan()
    for slide in plan["slides"]:
        slide["pick_fallback"] = True
        slide.pop("template_page", None)
    await ppt_plan.write_pages(plan, story, [], _three_card_catalog(), "材料")
    assert calls == []

    plan, story = _chapter_plan()
    plan["slides"][4]["pick_fallback"] = True
    plan["slides"][4].pop("template_page", None)

    async def one_page(_user, _system, user, model_id="", max_tokens=4000):
        calls.append(user)
        return json.dumps({"pages": [{"no": 3, "slots": {
            "title": "听懂不等于会做", "item1.body": "认", "item2.body": "取", "item3.body": "例如",
        }, "notes": "承接上一页。中间讲一个例子。最后引出下一页的概念。"}]}), "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", one_page)
    await ppt_plan.write_pages(plan, story, [], _three_card_catalog(), "材料")
    assert len(calls) == 1
    assert "第 3 页（模板" in calls[0]
    assert "第 1 页（模板" not in calls[0]
    assert "第 2 页（模板" not in calls[0]


@pytest.mark.asyncio
async def test_enrich_rewrites_only_named_slots(monkeypatch):
    plan = {"slides": [
        {"layout": "cards", "title": "旧", "slots": {"title": "旧", "item1.body": "旧"}, "slot_limits": {"title": 18, "item1.body": 40}},
        {"layout": "bullets", "title": "别动", "points": ["别动"]},
    ]}

    async def fake_text(*_args, **_kwargs):
        return json.dumps({"pages": [
            {"no": 1, "slots": {"title": "合上书才记得住", "item1.body": "例如睡前回忆一遍", "item9.body": "编的"}, "notes": "这一页用背单词的例子说明提取。先承接上一页，再举一个例子，最后引出下一页。"},
            {"no": 2, "slots": {"title": "不该出现"}},
        ]}), "fake", ""

    monkeypatch.setattr(ppt_plan, "_ask_text", fake_text)
    updated, err = await ppt_plan.enrich_plan(plan, [1], "材料")
    assert err == ""
    assert updated["slides"][0]["slots"]["title"] == "合上书才记得住"
    assert "item9.body" not in updated["slides"][0]["slots"]
    assert updated["slides"][0]["title"] == "合上书才记得住"
    assert updated["slides"][1]["title"] == "别动"


@pytest.mark.asyncio
async def test_model_call_stops_when_the_stream_never_returns(monkeypatch):
    async def hang(*_args, **_kwargs):
        await asyncio.sleep(5)
        return "不会走到", "", ""

    monkeypatch.setattr(ppt_plan, "_read_stream", hang)
    monkeypatch.setattr(ppt_plan, "_CALL_DEADLINE", 0.05)
    answer, _thinking, error = await ppt_plan._read_stream_limited(None, "", "", "", "", 8, None)
    assert answer == ""
    assert "时限" in error


def test_structural_end_uses_the_template_heading():
    catalog = {"pages": [{
        "page": 26,
        "role": "end",
        "sample_heading": "感谢您的观看",
        "slots": [{"name": "title", "max_chars": 12}],
    }]}
    slide = {"template_page": 26, "notes": "讲完了。"}
    ppt_plan._fill_structural(
        slide, {"kind": "end"}, {}, {"title": "物理学习记忆机制与干预"}, catalog)
    assert slide["slots"]["title"] == "感谢您的观看"
    assert "物理学习记忆机制与干预" in slide["notes"]
    assert slide["notes"].startswith("讲完了。")


def test_structural_toc_uses_the_section_name_and_truncates():
    catalog = {"pages": [{
        "page": 2,
        "slots": [
            {"name": "title", "max_chars": 12},
            {"name": "item1.head", "max_chars": 4},
            {"name": "item1.body", "max_chars": 20},
        ],
    }]}
    slide = {"template_page": 2}
    storyline = {"sections": [{"no": 1, "title": "研究问题很长", "question": "问什么"}]}
    ppt_plan._fill_structural(slide, {"kind": "toc"}, storyline, {"title": "汇报"}, catalog)
    assert slide["slots"]["item1.head"] == "研究问题"
    assert any("截断" in line for line in slide["slot_warnings"])
    assert "item1.head" in slide["locked_slots"]


def test_align_toc_rewrites_heads_from_section_titles():
    plan = {"slides": [
        {"layout": "toc", "items": [{"label": "问与做法"}],
         "slots": {"item1.head": "问与做法"}, "slot_limits": {"item1.head": 12}},
        {"layout": "section", "title": "旧标题",
         "slots": {"section_title": "这篇论文在回答什么"}, "slot_limits": {"section_title": 24}},
    ]}
    catalog = {"pages": [{"role": "toc", "usable": True, "slots": [{"name": "item1.head", "max_chars": 12}]}]}
    ppt_plan.align_toc(plan, catalog)
    assert plan["slides"][0]["slots"]["item1.head"] == "这篇论文在回答什么"


def test_align_toc_drops_the_page_when_the_template_has_no_item_slots():
    plan = {
        "slides": [
            {"layout": "cover"},
            {"layout": "toc", "role": "toc", "slots": {"title": "汇报框架"}},
            {"layout": "section", "slots": {"section_title": "背景"}},
            {"layout": "end"},
        ],
        "storyline": {"slots": [
            {"kind": "cover"}, {"kind": "toc"}, {"kind": "section"}, {"kind": "end"},
        ]},
    }
    catalog = {"pages": [{
        "role": "toc", "usable": True,
        "slots": [{"name": "title", "max_chars": 22}, {"name": "body", "max_chars": 80}],
    }]}
    ppt_plan.align_toc(plan, catalog)
    assert [slide.get("layout") for slide in plan["slides"]] == ["cover", "section", "end"]
    assert [slot.get("kind") for slot in plan["storyline"]["slots"]] == ["cover", "section", "end"]
