"""页说明和叙事用的词表。"""

from services.ppt import ppt_roles


def test_every_role_has_a_chinese_name():
    for table in (ppt_roles.PAGE_ROLES, ppt_roles.CONTENT_FORMS, ppt_roles.NARRATIVE_ROLES):
        assert table
        assert all(name for name in table.values())


def test_form_layouts_exist():
    assert ppt_roles.form_layouts_ok() == []


def test_slot_names():
    assert ppt_roles.slot_pattern_ok("title")
    assert ppt_roles.slot_pattern_ok("item3.head")
    assert ppt_roles.slot_pattern_ok("stat1.value")
    assert ppt_roles.slot_pattern_ok("info2")
    assert not ppt_roles.slot_pattern_ok("item0.head")
    assert not ppt_roles.slot_pattern_ok("decor")
