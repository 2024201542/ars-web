"""把 Word（.docx）的正文当成一段一行的文本来读、来改。

表格、图片、页眉页脚留在原文件里。旧版 .doc 不在这里转换。
"""

import zipfile
from pathlib import Path

from services.workspace_manager import SKIP_DIRS

MAX_SIDECARS = 20
MAX_SIDECAR_CHARS = 200_000


def extract_docx_text(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(paragraph.text for paragraph in doc.paragraphs)


def _set_paragraph_text(paragraph, text: str) -> None:
    bold = italic = None
    font_name = font_size = None
    if paragraph.runs:
        src = paragraph.runs[0]
        bold, italic = src.bold, src.italic
        font_name, font_size = src.font.name, src.font.size
    for child in list(paragraph._element):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in {"r", "hyperlink"}:
            paragraph._element.remove(child)
    run = paragraph.add_run(text)
    run.bold = bold
    run.italic = italic
    if font_name:
        run.font.name = font_name
    if font_size:
        run.font.size = font_size


def _drop_paragraph(paragraph) -> None:
    element = paragraph._element
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def apply_docx_text(path: Path, text: str) -> None:
    """按行写回正文。行数变了就增删末尾段落，已有段落的样式尽量留着。"""
    from docx import Document

    doc = Document(str(path))
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paragraphs = list(doc.paragraphs)
    if not paragraphs:
        for line in lines:
            doc.add_paragraph(line)
        doc.save(str(path))
        return
    style = paragraphs[-1].style
    for index, line in enumerate(lines):
        if index < len(paragraphs):
            _set_paragraph_text(paragraphs[index], line)
        else:
            added = doc.add_paragraph(line)
            try:
                added.style = style
            except ValueError:
                pass
    for paragraph in reversed(paragraphs[len(lines):]):
        _drop_paragraph(paragraph)
    doc.save(str(path))


def write_new_docx(path: Path, text: str) -> None:
    from docx import Document

    doc = Document()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if doc.paragraphs:
        _set_paragraph_text(doc.paragraphs[0], lines[0] if lines else "")
        rest = lines[1:]
    else:
        rest = lines
    for line in rest:
        doc.add_paragraph(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def is_docx_zip(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as archive:
            return "word/document.xml" in archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def sidecar_path(docx: Path) -> Path:
    return docx.with_name(docx.name + ".txt")


def prepare_docx_sidecars(root: Path) -> list[Path]:
    """在每个 Word 旁边放一份正文，供对话读取。已有同名 txt 的不覆盖。"""
    base = root.resolve()
    created: list[Path] = []
    if not base.is_dir():
        return created
    for path in base.rglob("*.docx"):
        if len(created) >= MAX_SIDECARS:
            break
        try:
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(base)
        except (OSError, ValueError):
            continue
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel.parts):
            continue
        if path.name.startswith("~$"):
            continue
        side = sidecar_path(path)
        if side.exists():
            continue
        try:
            text = extract_docx_text(path)
        except Exception:
            continue
        if len(text) > MAX_SIDECAR_CHARS:
            text = text[:MAX_SIDECAR_CHARS]
        try:
            side.write_text(text, encoding="utf-8")
        except OSError:
            continue
        created.append(side)
    return created


def finish_docx_sidecars(created: list[Path]) -> list[str]:
    """把改过的正文写回 Word，并删掉这次临时放上的 txt。"""
    changed: list[str] = []
    for side in created:
        try:
            if not side.is_file():
                continue
            docx = side.with_name(side.name[:-4] if side.name.lower().endswith(".docx.txt") else side.name)
            text = side.read_text(encoding="utf-8")
            if docx.is_file() and is_docx_zip(docx):
                current = extract_docx_text(docx)
                if text != current:
                    apply_docx_text(docx, text)
                    changed.append(docx.name)
            elif not docx.exists():
                write_new_docx(docx, text)
                changed.append(docx.name)
        except Exception:
            continue
        else:
            try:
                side.unlink()
            except OSError:
                pass
    return changed


def restore_broken_docx(root: Path, before: dict[str, bytes]) -> None:
    """对话若把 .docx 写成了普通文本，用改之前的文件换回来。"""
    base = root.resolve()
    for rel, old in before.items():
        if not rel.lower().endswith(".docx"):
            continue
        path = (base / rel).resolve()
        try:
            path.relative_to(base)
        except ValueError:
            continue
        if path.is_file() and not is_docx_zip(path):
            path.write_bytes(old)
