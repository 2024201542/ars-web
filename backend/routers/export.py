"""文件导出 API —— 完整会话问答导出"""

import uuid
import pathlib
import subprocess
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from deps import limiter
from services.state_tracker import tracker as state_tracker
from services.user_manager import get_user_id

router = APIRouter(prefix="/api/sessions", tags=["export"])

EXPORT_DIR = pathlib.Path(__file__).parent.parent / "data" / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


class ExportRequest(BaseModel):
    format: str = "markdown"
    scope: str = "conversation"  # conversation | assistant_only
    sections: Optional[list[str]] = None


def _export_stem(session_id: str, file_id: str) -> str:
    return f"{session_id}__{file_id}"


def _build_markdown(session: dict, messages: list, artifacts: list, scope: str) -> str:
    title = session.get("title") or "学术研究会话"
    skill = session.get("skill_name") or ""
    mode = session.get("mode_name") or ""
    created = session.get("created_at") or ""
    lines = [
        f"# {title}",
        "",
        f"- 技能：{skill}",
        f"- 模式：{mode}",
        f"- 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 会话创建：{created}",
        "",
        "---",
        "",
    ]

    if scope != "assistant_only":
        lines.append("## 对话记录")
        lines.append("")
        n_q = 0
        for m in messages:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                n_q += 1
                lines.append(f"### 问 {n_q}")
                lines.append("")
                lines.append(content)
                lines.append("")
            elif role == "assistant":
                lines.append(f"### 答 {n_q if n_q else ''}".rstrip())
                lines.append("")
                lines.append(content)
                lines.append("")
                lines.append("---")
                lines.append("")
    else:
        lines.append("## 助手输出")
        lines.append("")
        for m in messages:
            if m.get("role") == "assistant" and (m.get("content") or "").strip():
                lines.append(m["content"].strip())
                lines.append("")
                lines.append("---")
                lines.append("")

    if artifacts:
        lines.append("## 产出物")
        lines.append("")
        for a in artifacts:
            lines.append(f"### {a.get('artifact_type') or 'artifact'}")
            lines.append("")
            lines.append((a.get("content") or "").strip())
            lines.append("")

    body = "\n".join(lines).strip() + "\n"
    if len(body) < 40:
        raise ValueError("会话暂无可导出内容，请先完成至少一轮对话")
    return body


@router.post("/{session_id}/export")
@limiter.limit("20/hour")
async def export_result(request: Request, session_id: str, req: ExportRequest, user_id: str = Depends(get_user_id)):
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    artifacts = await state_tracker.get_artifacts(session_id)
    messages = await state_tracker.get_messages(session_id)

    try:
        full = _build_markdown(s, messages, artifacts, req.scope or "conversation")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    fid = str(uuid.uuid4())
    stem = _export_stem(session_id, fid)
    safe_title = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (s.get("title") or "ars_export"))[:40]
    base_name = f"{safe_title}_{session_id[:8]}"

    fmt = (req.format or "markdown").lower()
    if fmt in ("md", "markdown"):
        fn, fp = f"{base_name}.md", EXPORT_DIR / f"{stem}.md"
        fp.write_text(full, encoding="utf-8")
        return {"file_id": fid, "filename": fn, "status": "ready", "format": "markdown", "bytes": fp.stat().st_size}

    if fmt == "latex":
        fn, fp = f"{base_name}.tex", EXPORT_DIR / f"{stem}.tex"
        fp.write_text(full, encoding="utf-8")
        return {"file_id": fid, "filename": fn, "status": "ready", "format": "latex", "bytes": fp.stat().st_size}

    if fmt in ("docx", "pdf"):
        tmp = EXPORT_DIR / f"{stem}.md"
        tmp.write_text(full, encoding="utf-8")
        ext = ".docx" if fmt == "docx" else ".pdf"
        fp = EXPORT_DIR / f"{stem}{ext}"
        cmd = ["pandoc", str(tmp), "-o", str(fp)]
        if fmt == "pdf":
            cmd += ["--pdf-engine=xelatex", "-V", "mainfont=Noto Sans CJK SC"]
        try:
            r = subprocess.run(cmd, check=True, capture_output=True, timeout=90)
            tmp.unlink(missing_ok=True)
            return {
                "file_id": fid,
                "filename": f"{base_name}{ext}",
                "status": "ready",
                "format": fmt,
                "bytes": fp.stat().st_size,
            }
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="服务器未安装 pandoc，无法导出该格式；请改用 Markdown")
        except subprocess.CalledProcessError as e:
            err = (e.stderr or e.stdout or b"").decode("utf-8", "replace")[:500]
            # 失败时仍提供 markdown 回退文件
            return {
                "file_id": fid,
                "filename": f"{base_name}.md",
                "status": "fallback_markdown",
                "format": "markdown",
                "bytes": tmp.stat().st_size,
                "warning": f"转换为 {fmt} 失败，已回退为 Markdown。原因：{err or 'unknown'}",
            }
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail=f"导出 {fmt} 超时，请改用 Markdown 或缩短会话")

    raise HTTPException(status_code=400, detail=f"不支持的格式: {req.format}")


@router.get("/{session_id}/exports/{file_id}")
async def download_export(session_id: str, file_id: str, user_id: str = Depends(get_user_id)):
    s = await state_tracker.get_session(session_id)
    if not s or s.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    stem = _export_stem(session_id, file_id)
    for ext in [".md", ".docx", ".pdf", ".tex"]:
        fp = EXPORT_DIR / f"{stem}{ext}"
        if fp.exists():
            mt = {
                ".md": "text/markdown; charset=utf-8",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".pdf": "application/pdf",
                ".tex": "application/x-tex",
            }
            return FileResponse(
                path=str(fp),
                media_type=mt.get(ext, "application/octet-stream"),
                filename=f"ars_export_{session_id[:8]}{ext}",
            )
    raise HTTPException(status_code=404, detail="导出文件不存在或已过期")
