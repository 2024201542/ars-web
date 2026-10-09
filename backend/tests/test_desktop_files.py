from pathlib import Path

from services.workspace_manager import workspace_manager
import services.workspace_manager as workspace_module


def test_scan_keeps_root_articles_and_skips_shortcuts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(workspace_module, "MAX_LISTED_FILES", 3)
    (tmp_path / "late.pdf").write_bytes(b"%PDF")
    (tmp_path / "Chrome.lnk").write_bytes(b"lnk")
    (tmp_path / "desktop.ini").write_text("x", encoding="utf-8")
    nested = tmp_path / "subdir"
    nested.mkdir()
    for name in ("a.txt", "b.txt", "c.txt"):
        (nested / name).write_text(name, encoding="utf-8")

    files: list = []
    truncated = workspace_manager._scan_limited(tmp_path, tmp_path, files, 0)
    names = [item["name"] for item in files]

    assert "late.pdf" in names
    assert "subdir" in names
    assert "Chrome.lnk" not in names
    assert "desktop.ini" not in names
    assert truncated is True
    assert len(files) <= 3
