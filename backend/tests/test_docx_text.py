"""Word 正文读出再写回。"""

from services.docx_text import (
    apply_docx_text,
    extract_docx_text,
    finish_docx_sidecars,
    prepare_docx_sidecars,
    write_new_docx,
)


def test_roundtrip_keeps_extra_paragraph_style(tmp_path):
    path = tmp_path / "稿.docx"
    write_new_docx(path, "甲\n乙")
    assert extract_docx_text(path) == "甲\n乙"
    apply_docx_text(path, "甲\n丙\n丁")
    assert extract_docx_text(path) == "甲\n丙\n丁"


def test_sidecar_writes_back_and_removes_txt(tmp_path):
    folder = tmp_path / "论文"
    folder.mkdir()
    docx = folder / "试稿.docx"
    write_new_docx(docx, "原文")
    created = prepare_docx_sidecars(folder)
    assert len(created) == 1
    created[0].write_text("改过", encoding="utf-8")
    changed = finish_docx_sidecars(created)
    assert changed == ["试稿.docx"]
    assert extract_docx_text(docx) == "改过"
    assert not created[0].exists()


def test_old_doc_upload_message():
    from services.workspace_manager import _check_upload_ext
    try:
        _check_upload_ext(".doc")
        assert False, "old word should be refused"
    except ValueError as exc:
        assert ".docx" in str(exc)
    _check_upload_ext(".docx")
