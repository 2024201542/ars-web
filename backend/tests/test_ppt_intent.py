"""做 PPT、改计划的说法识别，以及列计划时材料从哪来。"""

import asyncio
import json
import os
import pathlib

import pytest

from services.ppt import ppt_layouts, ppt_plan
from services.ppt.ppt_chat import (
    attached_names,
    compose_out_dir,
    load_folder_material,
    pack_folder_texts,
    pick_folder,
    recent_discussion,
    select_folder_files,
    source_label,
    wants_plan_revise,
    wants_ppt,
    wants_rebuild_from_draft,
)


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    sandbox = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "pytest-env"
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(sandbox / "test_ars.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(sandbox / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(sandbox / "workspaces"))


@pytest.mark.parametrize("text", [
    "做Ppt", "做 ppt", "根据这个做个PPT。", "出片", "做个幻灯片吧", "按这个计划出片",
])
def test_wants_ppt_accepts_casual_phrasing(text):
    assert wants_ppt(text) is True


def test_wants_ppt_rejects_a_question():
    assert wants_ppt("PPT 怎么做比较好看？") is False


@pytest.mark.parametrize("text", ["第 6 页改成时间轴", "把第3页删了", "整体压到 10 页"])
def test_wants_plan_revise_accepts_edits(text):
    assert wants_plan_revise(text) is True


def test_wants_plan_revise_rejects_a_question():
    assert wants_plan_revise("第 6 页讲的是什么？") is False


def test_rebuild_from_draft_accepts_the_set_phrase():
    assert wants_rebuild_from_draft("按内容稿重出计划") is True
    assert wants_rebuild_from_draft("内容稿怎么重出？") is False
    assert wants_ppt("按内容稿重出计划") is False


_DIRS = [
    {"is_dir": True, "path": "论文创作"},
    {"is_dir": True, "path": "土地改革论文写作"},
]


def test_pick_folder_from_at_mention():
    path, name = pick_folder("生成一个关于学习的ppt 在@论文创作 这个文件夹下", _DIRS)
    assert path == "论文创作"
    assert name == "论文创作"


def test_pick_folder_from_plain_sentence():
    path, name = pick_folder("生成在论文创作这个文件夹下面", _DIRS)
    assert path == "论文创作"
    assert name == "论文创作"


def test_pick_folder_reports_a_missing_name():
    path, name = pick_folder("放到不存在这个文件夹", _DIRS)
    assert path == ""
    assert name == "不存在"


def test_compose_keeps_a_subfolder_inside_the_opened_folder():
    root = pathlib.Path(r"C:\desk")
    parent = root / "论文创作"
    assert compose_out_dir(parent, True, root) == parent
    assert compose_out_dir(pathlib.Path(r"D:\site\generated"), True, root) == root


def test_layout_limits_cover_every_field_the_editor_asks_for():
    """编辑页按 info[]、items[].label、left.points[] 这几种键去查上限，每条都得能查到。"""
    for layout, spec in ppt_layouts.LAYOUT_SPECS.items():
        limits = ppt_layouts.limits_of(layout)
        for field in spec["fields"]:
            key = field["key"]
            if "limit" not in field and not field.get("item") and not field.get("group"):
                continue
            if field.get("item"):
                for sub in field["item"]:
                    if "limit" in sub:
                        assert f"{key}[].{sub['key']}" in limits
                        assert limits[f"{key}[].{sub['key']}"] > 0
            elif field.get("group"):
                for sub in field["group"]:
                    if "limit" not in sub:
                        continue
                    path = f"{key}.{sub['key']}"
                    if "min" in sub or "max" in sub:
                        path += "[]"
                    assert path in limits
                    assert limits[path] > 0
            elif "limit" in field:
                path = key + ("[]" if "min" in field or "max" in field else "")
                assert path in limits
                assert limits[path] > 0


def test_status_replies_are_dropped_and_real_discussion_is_kept():
    messages = [
        {"role": "assistant", "content": "学习要主动回忆，合上书复述一遍。"},
        {"role": "assistant", "content": "你可以先把要点写下来，再决定要不要生成 PPT。"},
        {"role": "assistant", "content": "已列出 12 页计划，放在「论文创作」。确认后点「生成 PPT」。",
         "metadata": json.dumps({"ppt_plan": {"plan_path": "a.ppt计划.json"}})},
        {"role": "assistant", "content": "已按你的要求改了计划（第 7 页）。"},
        {"role": "assistant", "content": "这次没能列出 PPT 计划：超时"},
        {"role": "assistant", "content": "已出片：关于学习.pptx"},
        {"role": "assistant", "content": "已生成 PPT：**关于学习**",
         "metadata": {"ppt": {"name": "关于学习.pptx"}}},
        {"role": "user", "content": "已列出 这句是用户说的，要留下来当题目"},
    ]
    got = recent_discussion(messages, keep=3)
    assert got == [
        "学习要主动回忆，合上书复述一遍。",
        "你可以先把要点写下来，再决定要不要生成 PPT。",
    ]


def test_source_label_names_the_files_or_says_topic_only():
    assert source_label(["甲.docx", "乙.pdf"], False) == "甲.docx、乙.pdf"
    assert source_label([], True) == "最近的对话"
    assert source_label([], False) == "只有题目"
    assert attached_names("[文件: 甲.docx]\n正文\n[文件: 乙.pdf]（这份文件这次没读出正文）") == ["甲.docx", "乙.pdf"]


def test_select_folder_files_keeps_drafts_and_skips_generated():
    folder = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "ppt-c1-folder"
    folder.mkdir(parents=True, exist_ok=True)
    for child in folder.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            for nested in child.iterdir():
                if nested.is_file():
                    nested.unlink()
            child.rmdir()
    kept = ["笔记.md", "学习.内容稿.md", "摘录.txt", "正文.docx", "扫描.pdf"]
    skipped = ["图片说明.md", "图片说明.json", "甲.ppt计划.json", "图.png", "汇报.pptx", ".草稿.md"]
    for index, name in enumerate(kept + skipped):
        path = folder / name
        path.write_text("x", encoding="utf-8")
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
    nested = folder / "子目录"
    nested.mkdir()
    (nested / "里面.md").write_text("不该读到子目录", encoding="utf-8")
    names = [path.name for path in select_folder_files(folder)]
    assert names == ["扫描.pdf", "正文.docx", "摘录.txt", "学习.内容稿.md", "笔记.md"]


def test_pack_folder_texts_stops_at_the_limit():
    text, names = pack_folder_texts([("a.md", "甲" * 100), ("b.md", "乙" * 80)], limit=120)
    assert names == ["a.md", "b.md"]
    assert text.count("甲") == 100
    assert text.count("乙") == 20
    text, names = pack_folder_texts([("a.md", "甲" * 50), ("b.md", ""), ("c.md", "丙")], limit=50)
    assert names == ["a.md"]


def test_load_folder_material_reads_only_inside_the_opened_folder(monkeypatch):
    folder = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "ppt-c1-read"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "甲.md").write_text("土地改革从一九五零年开始。", encoding="utf-8")
    (folder / "图片说明.md").write_text("这张图不该进材料。", encoding="utf-8")

    async def fake_root(_user_id):
        return folder

    async def fake_content(_session_id, rel, _user_id, source):
        assert source == "local"
        return (folder / rel).read_text(encoding="utf-8")

    monkeypatch.setattr("services.ppt.ppt_chat.workspace_manager.get_local_root", fake_root)
    monkeypatch.setattr("services.ppt.ppt_chat.workspace_manager.get_content", fake_content)
    text, names = asyncio.run(load_folder_material("u", "s", folder))
    assert names == ["甲.md"]
    assert "一九五零年" in text
    assert "不该进材料" not in text

    async def other_root(_user_id):
        return pathlib.Path(r"C:\not-the-user-folder")

    async def forbid(*_args, **_kwargs):
        raise AssertionError("文件夹不在用户目录里，不应该读")

    monkeypatch.setattr("services.ppt.ppt_chat.workspace_manager.get_local_root", other_root)
    monkeypatch.setattr("services.ppt.ppt_chat.workspace_manager.get_content", forbid)
    text, names = asyncio.run(load_folder_material("u", "s", folder))
    assert text == ""
    assert names == []


def test_normalize_rebuilds_toc_to_match_sections():
    plan = ppt_plan.normalize({
        "title": "题",
        "slides": [
            {"layout": "cover", "title": "题"},
            {"layout": "toc", "title": "目录", "items": [{"label": "只有一项", "desc": ""}]},
            {"layout": "section", "index": "01", "title": "背景", "subs": ["数据"]},
            {"layout": "section", "index": "02", "title": "方法", "subs": ["对照"]},
            {"layout": "end", "info": ["谢谢"]},
        ],
    })
    toc = next(slide for slide in plan["slides"] if slide["layout"] == "toc")
    assert [item["label"] for item in toc["items"]] == ["背景", "方法"]
