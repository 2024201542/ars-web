"""选页：手写页说明，不读真模板。"""

import pathlib

import pytest

from services.ppt import ppt_pagepick


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    sandbox = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "pytest-env"
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(sandbox / "test_ars.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(sandbox / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(sandbox / "workspaces"))


def _page(number: int, role: str, form: str = "none", repeat: int = 0) -> dict:
    slots = [{"name": "title", "max_chars": 18}, {"name": "body", "max_chars": 80}]
    if role == "toc":
        for index in range(1, (repeat or 1) + 1):
            slots.append({"name": f"item{index}.head", "max_chars": 12})
            slots.append({"name": f"item{index}.body", "max_chars": 24})
    return {
        "page": number,
        "role": role,
        "form": form,
        "repeat": repeat,
        "narrative_fit": [],
        "slots": slots,
        "variant_group": 0,
        "usable": True,
        "vision_ok": True,
    }


def _catalog_26() -> dict:
    pages = [_page(1, "cover"), _page(2, "toc")]
    pages += [_page(number, "section") for number in range(3, 7)]
    pages += [_page(number, "content", "cards", 3) for number in (7, 8, 9)]
    pages.append(_page(10, "content", "cards", 4))
    pages.append(_page(11, "content", "timeline", 5))
    pages += [_page(number, "content", "compare", 2) for number in (12, 13)]
    pages += [_page(number, "content", "image_text", 0) for number in range(14, 20)]
    pages += [_page(number, "content", "bullets", 4) for number in range(20, 26)]
    pages.append(_page(26, "end"))
    return {"pages": pages}


def _deck_slots() -> list[dict]:
    return [
        {"no": 1, "kind": "cover"},
        {"no": 2, "kind": "toc"},
        {"no": 3, "kind": "section"},
        {"no": 4, "kind": "content", "form_hint": "cards", "items": 3, "role": "background", "message": "背景"},
        {"no": 5, "kind": "content", "form_hint": "timeline", "items": 5, "role": "method", "message": "分了五个阶段"},
        {"no": 6, "kind": "section"},
        {"no": 7, "kind": "content", "form_hint": "compare", "items": 2, "role": "comparison", "message": "两边不一样"},
        {"no": 8, "kind": "content", "form_hint": "bullets", "items": 4, "role": "finding", "message": "四点"},
        {"no": 9, "kind": "content", "form_hint": "image_text", "items": 1, "role": "example", "message": "一个例子"},
        {"no": 10, "kind": "content", "form_hint": "cards", "items": 3, "role": "finding", "message": "三张卡"},
        {"no": 11, "kind": "summary", "form_hint": "bullets", "items": 3, "role": "conclusion", "message": "回答开头的问题"},
        {"no": 12, "kind": "end"},
    ]


def test_pick_pages_covers_a_twelve_page_deck():
    picks = ppt_pagepick.pick_pages(_deck_slots(), _catalog_26(), None)
    assert len(picks) == 12
    assert picks[0]["page"] == 1
    assert picks[-1]["page"] == 26
    sections = [item["page"] for item in picks if item["role"] == "section" or _deck_slots()[picks.index(item)]["kind"] == "section"]
    assert sections and len(set(sections)) == 1
    content_pages = [item["page"] for slot, item in zip(_deck_slots(), picks)
                     if slot["kind"] in {"content", "summary"}]
    assert all(page for page in content_pages)
    assert all(left != right for left, right in zip(content_pages, content_pages[1:]))


def test_timeline_slot_picks_the_matching_page():
    slot = {"no": 1, "kind": "content", "form_hint": "timeline", "items": 5, "message": "五个阶段"}
    picks = ppt_pagepick.pick_pages([slot], _catalog_26(), None)
    assert picks[0]["page"] == 11
    assert any("形态一致" in reason for reason in picks[0]["reasons"])


def test_cards_prefer_the_same_repeat():
    slot = {"no": 1, "kind": "content", "form_hint": "cards", "items": 3, "message": "三列"}
    picks = ppt_pagepick.pick_pages([slot], _catalog_26(), None)
    assert picks[0]["page"] in {7, 8, 9}
    assert picks[0]["page"] != 10


def test_short_catalog_reuses_pages_without_running_twice_in_a_row():
    catalog = {"pages": [
        _page(1, "cover"),
        _page(2, "content", "bullets", 3),
        _page(3, "content", "bullets", 3),
        _page(4, "end"),
    ]}
    slots = [{"no": 1, "kind": "cover"}]
    slots += [{"no": index, "kind": "content", "form_hint": "bullets", "items": 3, "message": "要点"}
              for index in range(2, 8)]
    slots.append({"no": 8, "kind": "end"})
    picks = ppt_pagepick.pick_pages(slots, catalog, None)
    content = [item for slot, item in zip(slots, picks) if slot["kind"] == "content"]
    pages = [item["page"] for item in content]
    assert all(pages.count(page) <= 3 for page in set(pages))
    assert all(left != right for left, right in zip(pages, pages[1:]))
    assert any("重复使用" in reason for item in content for reason in item["reasons"])


def test_bare_summary_slot_uses_a_summary_page():
    catalog = _catalog_26()
    catalog["pages"][4] = _page(5, "summary", "cards", 4)
    slot = {"no": 1, "kind": "summary", "role": "conclusion", "message": "回答开头的问题"}
    picks = ppt_pagepick.pick_pages([slot], catalog, None)
    assert picks[0]["fallback"] is False
    assert picks[0]["page"] == 5


def test_bare_summary_slot_without_summary_page_still_falls_back():
    slot = {"no": 1, "kind": "summary", "role": "conclusion", "message": "回答开头的问题"}
    picks = ppt_pagepick.pick_pages([slot], _catalog_26(), None)
    assert picks[0]["fallback"] is True


def test_missing_toc_falls_back():
    catalog = {"pages": [_page(1, "cover"), _page(2, "end")]}
    picks = ppt_pagepick.pick_pages(
        [{"kind": "cover"}, {"kind": "toc"}, {"kind": "end"}], catalog, None)
    assert picks[1]["fallback"] is True
    assert picks[1]["page"] is None


def test_pick_pages_is_stable():
    slots = _deck_slots()
    catalog = _catalog_26()
    first = ppt_pagepick.pick_pages(slots, catalog, None)
    for _ in range(4):
        assert ppt_pagepick.pick_pages(slots, catalog, None) == first


def test_locked_page_stays():
    slot = {
        "kind": "content", "form_hint": "timeline", "items": 5,
        "pick_locked": True, "template_page": 8, "message": "锁住",
    }
    picks = ppt_pagepick.pick_pages([slot], _catalog_26(), None)
    assert picks[0]["page"] == 8
    assert "用户指定" in picks[0]["reasons"]


def test_toc_prefers_the_page_with_as_many_rows_as_sections():
    catalog = {"pages": [
        _page(1, "cover"),
        _page(2, "toc", "numbered", 4),
        _page(3, "toc", "numbered", 2),
        _page(4, "section"),
        _page(5, "end"),
    ]}
    slots = [
        {"kind": "cover"},
        {"kind": "toc"},
        {"kind": "section"},
        {"kind": "section"},
        {"kind": "end"},
    ]
    picks = ppt_pagepick.pick_pages(slots, catalog, None)
    assert picks[1]["page"] == 3
    assert any("章节数 2" in reason for reason in picks[1]["reasons"])


def test_toc_skips_a_page_that_has_no_item_head():
    bare = {
        "page": 9, "role": "toc", "form": "bullets", "repeat": 2,
        "slots": [{"name": "title", "max_chars": 18}, {"name": "body", "max_chars": 80}],
        "usable": True,
    }
    catalog = {"pages": [_page(2, "toc", "numbered", 2), bare]}
    picks = ppt_pagepick.pick_pages(
        [{"kind": "toc"}, {"kind": "section"}, {"kind": "section"}], catalog, None)
    assert picks[0]["page"] == 2


def test_toc_stays_blank_when_no_page_has_item_heads():
    catalog = {"pages": [{
        "page": 2, "role": "toc", "form": "bullets", "repeat": 0,
        "slots": [{"name": "title", "max_chars": 22}, {"name": "body", "max_chars": 497}],
        "usable": True,
    }]}
    picks = ppt_pagepick.pick_pages([{"kind": "toc"}], catalog, None)
    assert picks[0]["page"] is None
    assert picks[0]["fallback"] is True


def test_toc_keeps_the_only_page_when_the_row_count_differs():
    catalog = {"pages": [
        _page(1, "cover"),
        _page(2, "toc", "numbered", 4),
        _page(4, "section"),
        _page(5, "end"),
    ]}
    slots = [{"kind": "cover"}, {"kind": "toc"}, {"kind": "section"}, {"kind": "section"}, {"kind": "end"}]
    picks = ppt_pagepick.pick_pages(slots, catalog, None)
    assert picks[1]["page"] == 2
    assert not any("章节数" in reason for reason in picks[1]["reasons"])


def test_quote_keeps_the_best_page_when_the_template_has_no_quote_form():
    catalog = {"pages": [
        _page(11, "content", "cards", 1),
        _page(13, "content", "cards", 3),
    ]}
    slot = {"kind": "content", "role": "question", "form_hint": "quote", "items": 2, "message": "命题"}
    picks = ppt_pagepick.pick_pages([slot], catalog, None)
    assert picks[0]["fallback"] is False
    assert picks[0]["page"] == 11
    assert any("没有这种形态" in reason for reason in picks[0]["reasons"])
