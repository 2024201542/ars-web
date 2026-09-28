"""工作区 API — 会话级文件管理"""

import asyncio
import io
import os
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from services.edit_snapshot import restore_backup
from services.workspace_manager import user_dir, workspace_manager
from services.user_manager import get_user_id
from services.state_tracker import tracker as state_tracker

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

async def _verify_session(session_id: str, user_id: str):
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")


async def _pick_directory() -> str:
    """在本机弹出文件夹选择框。只在本地运行时使用。"""
    out = Path(tempfile.gettempdir()) / f"ars-folder-{uuid.uuid4().hex}.txt"
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$owner = New-Object System.Windows.Forms.Form; "
        "$owner.TopMost = $true; $owner.ShowInTaskbar = $false; "
        "$owner.WindowState = [System.Windows.Forms.FormWindowState]::Minimized; "
        "$owner.Show(); "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description = '选择要在 ARS 中打开的文件夹'; "
        "$d.ShowNewFolderButton = $true; "
        "$ok = $d.ShowDialog($owner); "
        "$owner.Close(); "
        "if ($ok -eq [System.Windows.Forms.DialogResult]::OK) { "
        "[System.IO.File]::WriteAllText($env:ARS_FOLDER_OUT, $d.SelectedPath, (New-Object System.Text.UTF8Encoding $false)) }"
    )
    proc = await asyncio.create_subprocess_exec(
        "powershell", "-NoProfile", "-STA", "-Command", script,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "ARS_FOLDER_OUT": str(out)},
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        raise ValueError("选择文件夹超时")
    if not out.exists():
        return ""
    try:
        return out.read_text(encoding="utf-8-sig").strip()
    finally:
        out.unlink(missing_ok=True)


class FolderBody(BaseModel):
    path: str = ""


class CreateFileBody(BaseModel):
    kind: str
    directory: str = ""
    name: str = ""
    source: str = "site"


class CreateDirBody(BaseModel):
    name: str
    directory: str = ""
    source: str = "site"


class SaveTextBody(BaseModel):
    path: str
    content: str
    source: str = "site"


class RenameFileBody(BaseModel):
    path: str
    name: str
    source: str = "site"


@router.get("/files")
async def list_files(session_id: str = Query(...), user_id: str = Depends(get_user_id)):
    await _verify_session(session_id, user_id)
    return await workspace_manager.list_active(user_id)


@router.post("/folder")
async def open_folder(
    session_id: str = Query(...),
    body: FolderBody = FolderBody(),
    user_id: str = Depends(get_user_id),
):
    await _verify_session(session_id, user_id)
    raw = (body.path or "").strip()
    if not raw:
        try:
            raw = await _pick_directory()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not raw:
            return {"cancelled": True}
    try:
        return await workspace_manager.set_local_root(user_id, raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/folder")
async def close_folder(session_id: str = Query(...), user_id: str = Depends(get_user_id)):
    await _verify_session(session_id, user_id)
    await workspace_manager.clear_local_root(user_id)
    return await workspace_manager.list_active(user_id)


@router.post("/files/create")
async def create_file(
    session_id: str = Query(...),
    body: CreateFileBody = CreateFileBody(kind="draft"),
    user_id: str = Depends(get_user_id),
):
    await _verify_session(session_id, user_id)
    try:
        return await workspace_manager.create_file(
            user_id, body.kind, body.directory, body.name, body.source or "site",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/dirs")
async def create_directory(
    session_id: str = Query(...),
    body: CreateDirBody = ...,
    user_id: str = Depends(get_user_id),
):
    await _verify_session(session_id, user_id)
    try:
        return await workspace_manager.create_directory(user_id, body.name, body.directory, body.source or "site")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/files/rename")
async def rename_file(
    session_id: str = Query(...),
    body: RenameFileBody = ...,
    user_id: str = Depends(get_user_id),
):
    await _verify_session(session_id, user_id)
    try:
        return await workspace_manager.rename_file(user_id, body.path, body.name, body.source or "site")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/files")
async def upload_file(
    session_id: str = Query(...),
    file: UploadFile = File(...),
    relative_path: str = Form(""),
    source: str = Query("site"),
    user_id: str = Depends(get_user_id),
):
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    name = (relative_path or "").strip() or (file.filename or "")
    if not name:
        raise HTTPException(status_code=400, detail="文件名为空")
    try:
        content = await file.read()
        if source == "local":
            return await workspace_manager.save_local_file(user_id, name, content)
        return await workspace_manager.save_user_file(user_id, name, content, file.content_type or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/files/content")
async def file_content(
    session_id: str = Query(...),
    path: str = Query(...),
    source: str = Query("site"),
    user_id: str = Depends(get_user_id),
):
    await _verify_session(session_id, user_id)
    content = await workspace_manager.get_content(session_id, path, user_id=user_id, source=source)
    if content is None:
        raise HTTPException(status_code=406, detail="无法预览此文件类型")
    return {"content": content, "path": path}


@router.put("/files/content")
async def save_file_content(
    session_id: str = Query(...),
    body: SaveTextBody = ...,
    user_id: str = Depends(get_user_id),
):
    await _verify_session(session_id, user_id)
    try:
        return await workspace_manager.save_text(user_id, body.path, body.content, body.source or "site")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/files/preview")
async def preview_file(
    session_id: str = Query(...),
    path: str = Query(...),
    source: str = Query("site"),
    user_id: str = Depends(get_user_id),
):
    """DOCX/XLSX → HTML 转换预览。"""
    await _verify_session(session_id, user_id)
    fp = await workspace_manager.resolve_file(user_id, path, source)
    if not fp:
        raise HTTPException(status_code=404, detail="文件不存在")
    ext = fp.suffix.lower()

    if ext == ".docx":
        try:
            import mammoth
            with open(fp, "rb") as f:
                result = mammoth.convert_to_html(f)
            return {"type": "html", "content": result.value}
        except Exception:
            from html import escape
            from services.docx_text import extract_docx_text
            text = extract_docx_text(fp)
            body = "".join(f"<p>{escape(line) or '<br>'}</p>" for line in text.split("\n"))
            return {"type": "html", "content": body}

    if ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(fp, read_only=True, data_only=True)
            parts = []
            for name in wb.sheetnames[:5]:
                ws = wb[name]
                rows = list(ws.iter_rows(values_only=True))[:1001]
                if not rows: continue
                nc = max(len(r) for r in rows)
                h = '<h4 class="text-xs font-ui text-ruc-text-dim mt-3 mb-1">' + name + '</h4><table>'
                h += '<thead><tr>' + ''.join(f'<th>{c or ""}</th>' for c in rows[0]) + '</tr></thead><tbody>'
                for row in rows[1:]:
                    cells = list(row) + [''] * (nc - len(row))
                    h += '<tr>' + ''.join(f'<td>{c or ""}</td>' for c in cells[:nc]) + '</tr>'
                h += '</tbody></table>'
                parts.append(h)
            wb.close()
            return {"type": "html", "content": ''.join(parts)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Excel 转换失败: {e}")

    raise HTTPException(status_code=406, detail=f"不支持预览: {ext}")


@router.get("/files/download")
async def download_file(
    session_id: str = Query(...),
    path: str = Query(...),
    source: str = Query("site"),
    user_id: str = Depends(get_user_id),
):
    await _verify_session(session_id, user_id)
    fp = await workspace_manager.resolve_file(user_id, path, source)
    if not fp:
        raise HTTPException(status_code=404)
    return FileResponse(path=str(fp), filename=fp.name)


@router.delete("/files")
async def delete_file(
    session_id: str = Query(...),
    path: str = Query(...),
    source: str = Query("site"),
    user_id: str = Depends(get_user_id),
):
    await _verify_session(session_id, user_id)
    try:
        await workspace_manager.delete_project_file(user_id, path, source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.get("/search")
async def search_files(session_id: str = Query(...), q: str = Query(""), user_id: str = Depends(get_user_id)):
    """搜索工作区文件（@ 引用用）。"""
    await _verify_session(session_id, user_id)
    listed = await workspace_manager.list_active(user_id)
    files = listed.get("data") or []
    def rank(item: dict) -> tuple:
        return (0 if item.get("is_dir") else 1, (item.get("name") or "").lower())

    if not q:
        return {"data": sorted(files, key=rank)[:20]}
    ql = q.lower()
    matched = [
        f for f in files
        if ql in (f.get("name") or "").lower() or ql in (f.get("path") or "").lower() or ql in (f.get("dir") or "").lower()
    ]
    return {"data": sorted(matched, key=rank)[:20]}


class GenerateDocRequest(BaseModel):
    format: str = "markdown"
    filename: str = ""
    message_ids: list[int] = Field(default_factory=list)
    template_path: str = ""


def _draft_markdown(session: dict, picked: list[dict]) -> str:
    title = (session.get("title") or "论文稿").strip()
    if len(picked) == 1:
        body = (picked[0].get("content") or "").strip()
        if body.startswith("#"):
            return body + "\n"
        return f"# {title}\n\n{body}\n"
    parts = [f"# {title}", ""]
    for i, m in enumerate(picked, 1):
        content = (m.get("content") or "").strip()
        role = "回复" if m.get("role") == "assistant" else "提问"
        parts.append(f"## {role} {i}")
        parts.append("")
        parts.append(content)
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def _safe_stem(name: str) -> str:
    stem = "".join(c for c in (name or "论文稿") if c.isalnum() or c in "._- （）()【】")[:60]
    return stem.strip(" .") or "论文稿"


def _style_names(doc) -> set[str]:
    try:
        return {s.name for s in doc.styles}
    except Exception:
        return set()


def _first_style(names: set[str], *candidates: str) -> str | None:
    for name in candidates:
        if name in names:
            return name
    return None


def _strip_body_keep_section(doc) -> None:
    """清掉模板正文，保留分节、页边距、页眉页脚和样式表。"""
    body = doc.element.body
    for child in list(body):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "sectPr":
            continue
        body.remove(child)


def _add_styled(doc, text: str, style: str | None, *, bold: bool = False):
    if style:
        try:
            return doc.add_paragraph(text, style=style)
        except KeyError:
            pass
    paragraph = doc.add_paragraph(text)
    if bold and paragraph.runs:
        paragraph.runs[0].bold = True
    return paragraph


def _fill_markdown(doc, markdown: str) -> None:
    names = _style_names(doc)
    headings = {
        1: _first_style(names, "Heading 1", "标题 1", "标题1", "Title"),
        2: _first_style(names, "Heading 2", "标题 2", "标题2"),
        3: _first_style(names, "Heading 3", "标题 3", "标题3"),
    }
    bullet = _first_style(names, "List Bullet", "列表项目符号", "列表段落")
    number = _first_style(names, "List Number", "列表编号")
    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            _add_styled(doc, _plain(line[4:]), headings[3], bold=True)
        elif line.startswith("## "):
            _add_styled(doc, _plain(line[3:]), headings[2], bold=True)
        elif line.startswith("# "):
            _add_styled(doc, _plain(line[2:]), headings[1], bold=True)
        elif line.startswith(("- ", "* ")):
            text = _plain(line[2:])
            if bullet:
                _add_styled(doc, text, bullet)
            else:
                doc.add_paragraph("• " + text)
        elif re.match(r"^\d+\.\s", line):
            text = _plain(re.sub(r"^\d+\.\s*", "", line))
            if number:
                _add_styled(doc, text, number)
            else:
                doc.add_paragraph(line.strip())
        else:
            doc.add_paragraph(_plain(line))


def _markdown_to_docx_bytes(markdown: str, template_path: Path | None = None) -> bytes:
    """用 python-docx 直接生成 Word。传入模板时套用其样式、页边距和页眉页脚。"""
    from docx import Document

    if template_path:
        doc = Document(str(template_path))
        _strip_body_keep_section(doc)
    else:
        doc = Document()
    _fill_markdown(doc, markdown)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _plain(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


@router.post("/generate-doc")
async def generate_doc(
    session_id: str = Query(...),
    req: GenerateDocRequest = GenerateDocRequest(),
    user_id: str = Depends(get_user_id),
):
    """把对话里的论文稿写成用户工作区文件（Markdown 或普通 Word）。"""
    await _verify_session(session_id, user_id)
    session = await state_tracker.get_session(session_id)
    messages = await state_tracker.get_messages(session_id)
    wanted = set(req.message_ids or [])
    if wanted:
        picked = [m for m in messages if m.get("id") in wanted and (m.get("content") or "").strip()]
        if not picked:
            raise HTTPException(status_code=400, detail="所选消息没有可写入的正文")
    else:
        assistants = [
            m for m in messages
            if m.get("role") == "assistant" and (m.get("content") or "").strip()
            and not (m.get("content") or "").strip().startswith("——")
        ]
        if not assistants:
            raise HTTPException(status_code=400, detail="还没有可生成文档的回复，请先对话或勾选消息")
        picked = [assistants[-1]]

    markdown = _draft_markdown(session or {}, picked)
    fmt = (req.format or "markdown").lower()
    stem = _safe_stem(req.filename or (session or {}).get("title") or "论文稿")

    if fmt in ("md", "markdown"):
        info = await workspace_manager.save_generated_file(
            user_id, f"{stem}.md", markdown.encode("utf-8")
        )
        info["format"] = "markdown"
        info["source"] = "selected" if wanted else "latest_reply"
        return info

    if fmt == "docx":
        template = None
        if (req.template_path or "").strip():
            template = await workspace_manager.get_user_file_path(user_id, req.template_path.strip())
            if not template or template.suffix.lower() != ".docx":
                raise HTTPException(status_code=400, detail="模板必须是工作区里的 .docx 文件")
        try:
            data = _markdown_to_docx_bytes(markdown, template)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"生成 Word 失败：{e}")
        info = await workspace_manager.save_generated_file(user_id, f"{stem}.docx", data)
        info["format"] = "docx"
        info["source"] = "selected" if wanted else "latest_reply"
        info["template"] = req.template_path.strip() if template else ""
        return info

    raise HTTPException(status_code=400, detail="仅支持 markdown 或 docx")


@router.post("/edits/{backup_id}/undo")
async def undo_edits(backup_id: str, user_id: str = Depends(get_user_id)):
    """把一轮对话改过的文稿恢复到改之前。"""
    root = await workspace_manager.get_local_root(user_id)
    if root is None:
        root = user_dir(user_id)
    try:
        restored = restore_backup(backup_id, user_id, root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "files": restored}


@router.post("/refresh")
async def refresh_workspace(session_id: str = Query(...), user_id: str = Depends(get_user_id)):
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404)
    return await workspace_manager.list_active(user_id)
