"""对话改 PPT：这句话是修改、提问，还是要新做一份。"""

import pathlib

import pytest

from services.ppt import ppt_edit_intent
from services.ppt.ppt_chat import wants_ppt


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    sandbox = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "pytest-env"
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(sandbox / "test_ars.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(sandbox / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(sandbox / "workspaces"))


@pytest.mark.parametrize("text", [
    "第3页文字太挤",
    "第 5 页和第 6 页衔接不上",
    "把背景介绍加在前面",
    "这页字压住图了",
    "结尾加一页总结",
    "整体压到 10 页",
    "第六页改成时间轴",
    "第7页 换成 对比",
    "封面副标题太长了",
    "上一页太挤了",
    "最后一页太空",
    "目录太长了",
    "开头太空",
    "后面接不上",
    "第 3 到 5 页太散",
    "每页都太挤",
    "所有页精简一下",
    "加个总结",
    "先讲背景",
    "顺序调一下",
    "第 8 页删掉",
    "把第2页往后挪",
    "这一页看不清",
    "封面字出界了",
    "怎么这么挤",
    "为什么接不上",
])
def test_quick_edit(text):
    assert ppt_edit_intent.quick_classify(text) == "edit"
    assert ppt_edit_intent.route_label(text) == "edit"


@pytest.mark.parametrize("text", [
    "为什么第 4 页用时间轴",
    "第4页讲的是什么意思",
    "是什么意思",
    "怎么理解第 3 页",
    "能不能解释一下目录",
    "什么意思",
])
def test_quick_question(text):
    assert ppt_edit_intent.quick_classify(text) == "question"
    assert ppt_edit_intent.route_label(text) == "ask"


def test_messy_line_waits_for_the_model():
    assert ppt_edit_intent.quick_classify("怎么这么乱") == "unsure"


def test_thanks_is_not_an_edit():
    assert ppt_edit_intent.quick_classify("谢谢") == "unsure"
    assert ppt_edit_intent.route_label("谢谢") != "edit"


def test_new_deck_wins_over_edit():
    text = "帮我再做一份新的关于农村改革的 PPT"
    assert wants_ppt(text) is True
    assert ppt_edit_intent.route_label(text) == "new"


def test_chinese_page_and_range():
    assert ppt_edit_intent.page_numbers("第六页改成时间轴") == [6]
    assert ppt_edit_intent.page_numbers("第 5 页和第 6 页衔接不上") == [5, 6]
    assert ppt_edit_intent.page_numbers("第 3 到 5 页太散") == [3, 5]


async def test_unsure_uses_stubbed_edit(monkeypatch):
    async def fake_text(_user_id, _system, _user, model_id="", max_tokens=4000):
        return '{"kind": "edit", "pages": [], "why": "在抱怨太乱"}', "stub", ""

    monkeypatch.setattr("services.ppt.ppt_plan._ask_text", fake_text)
    decision = await ppt_edit_intent.classify("怎么这么乱", {"slides": []}, "m", "u")
    assert decision["kind"] == "edit"


async def test_thanks_stub_stays_out_of_edit(monkeypatch):
    async def fake_text(_user_id, _system, _user, model_id="", max_tokens=4000):
        return '{"kind": "other", "pages": [], "why": "闲聊"}', "stub", ""

    monkeypatch.setattr("services.ppt.ppt_plan._ask_text", fake_text)
    decision = await ppt_edit_intent.classify("谢谢", None, "m", "u")
    assert decision["kind"] == "other"


async def test_model_failure_counts_as_question(monkeypatch):
    async def fake_text(_user_id, _system, _user, model_id="", max_tokens=4000):
        return "", "", "模型没有返回正文"

    monkeypatch.setattr("services.ppt.ppt_plan._ask_text", fake_text)
    decision = await ppt_edit_intent.classify("你好", None, "m", "u")
    assert decision["kind"] == "question"


async def test_bad_json_counts_as_question(monkeypatch):
    async def fake_text(_user_id, _system, _user, model_id="", max_tokens=4000):
        return "不是 JSON", "stub", ""

    monkeypatch.setattr("services.ppt.ppt_plan._ask_text", fake_text)
    decision = await ppt_edit_intent.classify("你好呀", None, "m", "u")
    assert decision["kind"] == "question"
