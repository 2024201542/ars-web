"""工作区管理器 — 会话级项目目录管理

每个会话一个 workspace 目录，模仿 Claude Code 项目文件管理：
- 用户上传的文件存放在 {session_dir}/uploads/
- ARS agent 生成的产出物也可写入此目录
- 文件树直接扫描目录（非护照模式），简单直接
"""

import asyncio
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import WORKSPACE_DIR
from logging_config import get_logger

logger = get_logger(__name__)

ALLOWED_FILE_EXTS = {
    ".csv", ".tsv", ".json", ".txt", ".md", ".yaml", ".yml",
    ".py", ".r", ".rmd", ".ipynb",
    ".pdf", ".xlsx", ".xls",
    ".zip", ".tar.gz", ".gz",
    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp",
    ".parquet", ".feather",
    ".bib", ".tex", ".docx",
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def user_dir(user_id: str) -> Path:
    """用户工作区根目录：WORKSPACE_DIR / {user_id}。一个用户的所有文件在此。"""
    return WORKSPACE_DIR / user_id


def session_dir(session_id: str) -> Path:
    """会话工作区（legacy）。"""
    return WORKSPACE_DIR / session_id


class WorkspaceManager:
    """按会话隔离的工作区管理器。"""

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}

    def _base_dir(self, user_id: str = "default") -> Path:
        return WORKSPACE_DIR / user_id

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    # ── 文件扫描 ──

    def _scan_dir(self, base: Path, root: Path, files: list, prefix: str = "") -> list:
        """递归扫描目录，返回文件列表。"""
        try:
            for entry in sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                rel = str(entry.relative_to(base))
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    self._scan_dir(base, entry, files, prefix)
                elif entry.is_file():
                    stat = entry.stat()
                    ext = entry.suffix.lower()
                    info = {
                        "id": uuid.uuid4().hex[:12],
                        "name": entry.name,
                        "path": rel,
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        "ext": ext,
                        "dir": str(entry.parent.relative_to(base)) if entry.parent != base else "",
                    }
                    # CSV 列名探测
                    if ext == ".csv":
                        try:
                            import csv as _csv
                            with open(entry, encoding="utf-8", errors="replace") as f:
                                reader = _csv.reader(f)
                                info["columns"] = next(reader, [])
                                if info["columns"]:
                                    info["columns"] = [c for c in info["columns"] if c]
                        except Exception:
                            pass
                    files.append(info)
        except PermissionError:
            pass
        return files

    async def list_files(self, session_id: str) -> list[dict]:
        """列出会话工作区的所有文件。"""
        base = session_dir(session_id)
        base.mkdir(parents=True, exist_ok=True)

        def _do_scan():
            files = []
            self._scan_dir(base, base, files)
            return files

        return await asyncio.to_thread(_do_scan)

    async def list_user_files(self, user_id: str) -> list[dict]:
        """列出用户工作区的所有文件。"""
        base = user_dir(user_id)
        base.mkdir(parents=True, exist_ok=True)
        def _do_scan():
            files = []
            self._scan_dir(base, base, files)
            return files
        return await asyncio.to_thread(_do_scan)

    async def get_user_file_path(self, user_id: str, file_path: str) -> Optional[Path]:
        """获取用户工作区文件的绝对路径。"""
        base = user_dir(user_id)
        resolved = (base / file_path).resolve()
        if not str(resolved).startswith(str(base.resolve())):
            return None
        return resolved if resolved.exists() else None

    async def get_file_path(self, session_id: str, file_path: str) -> Optional[Path]:
        """获取文件的绝对路径（安全检查：必须在 session_dir 内）。"""
        base = session_dir(session_id)
        # 兼容旧格式 {id}_{filename} 和新格式 relative_path
        if "/" in file_path or "\\" in file_path:
            resolved = (base / file_path).resolve()
            if not str(resolved).startswith(str(base.resolve())):
                return None
            return resolved if resolved.exists() else None
        # 旧格式：按文件名匹配
        for f in base.rglob("**/*"):
            if f.is_file() and not f.name.startswith(".") and f.name == file_path:
                return f
        return None

    async def save_user_file(self, user_id: str, filename: str, content: bytes, mime_type: str = "") -> dict:
        """上传文件到用户工作区。"""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_FILE_EXTS:
            raise ValueError(f"不支持的文件类型: {ext}")
        if len(content) > MAX_FILE_SIZE:
            raise ValueError("文件过大，最大 50MB")
        base = user_dir(user_id)
        uploads = base / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in filename if c.isalnum() or c in "._- ")[:120]
        dest = uploads / safe
        if dest.exists():
            import os as _os
            stem, e = _os.path.splitext(safe)
            dest = uploads / f"{stem}_{uuid.uuid4().hex[:6]}{e}"
        await asyncio.to_thread(dest.write_bytes, content)
        return {"id": uuid.uuid4().hex[:12], "name": dest.name, "path": str(dest.relative_to(base)),
                "size_bytes": len(content), "modified_at": _now(), "ext": ext, "dir": "uploads"}

    async def delete_user_file(self, user_id: str, path: str):
        """删除用户工作区文件。"""
        fp = await self.get_user_file_path(user_id, path)
        if fp and fp.is_file():
            fp.unlink()

    # ── 上传 ──

    async def save_file(self, session_id: str, filename: str, content: bytes, mime_type: str = "") -> dict:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_FILE_EXTS:
            raise ValueError(f"不支持的文件类型: {ext}")
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"文件过大，最大 50MB")

        base = session_dir(session_id)
        uploads = base / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)

        # sanitize + 避免覆盖
        safe = "".join(c for c in filename if c.isalnum() or c in "._- ")[:120]
        dest = uploads / safe
        if dest.exists():
            stem, e = os.path.splitext(safe)
            dest = uploads / f"{stem}_{uuid.uuid4().hex[:6]}{e}"

        await asyncio.to_thread(dest.write_bytes, content)

        info = {
            "id": uuid.uuid4().hex[:12],
            "name": dest.name,
            "path": str(dest.relative_to(base)),
            "size_bytes": len(content),
            "modified_at": _now(),
            "ext": ext,
            "dir": "uploads",
        }
        return info

    async def delete_file(self, session_id: str, file_path: str):
        """安全删除文件。"""
        file = await self.get_file_path(session_id, file_path)
        if file and file.is_file():
            file.unlink()

    async def get_content(self, session_id: str, file_path: str) -> Optional[str]:
        """读取文件文本内容（支持纯文本 + DOCX/XLSX 转换）。"""
        file = await self.get_file_path(session_id, file_path)
        if not file:
            return None
        ext = file.suffix.lower()
        # 纯二进制文件不读文本
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".parquet", ".feather"}:
            return None

        # DOCX → 通过 mammoth 提取纯文本
        if ext == ".docx":
            try:
                import mammoth
                with open(file, "rb") as f:
                    result = mammoth.extract_raw_text(f)
                return result.value
            except Exception:
                return None

        # PDF → 尝试 pdftotext（如有则用），否则返回提示
        if ext == ".pdf":
            try:
                import subprocess
                r = subprocess.run(["pdftotext", str(file), "-"], capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    return r.stdout
            except Exception:
                pass
            return None

        # XLSX → openpyxl 提取为 CSV-like 文本
        if ext in (".xlsx", ".xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
                lines = []
                for name in wb.sheetnames[:3]:
                    ws = wb[name]
                    lines.append(f"[{name}]")
                    for row in ws.iter_rows(values_only=True):
                        lines.append(",".join(str(c or "") for c in row))
                wb.close()
                return "\n".join(lines)
            except Exception:
                return None

        # 其余纯文本格式
        try:
            return file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    async def refresh(self, session_id: str):
        """刷新工作区（chat 完成后调用，重新扫描文件）。"""
        return await self.list_files(session_id)


workspace_manager = WorkspaceManager()
