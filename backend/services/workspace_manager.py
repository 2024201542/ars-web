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
from services.state_tracker import tracker as state_tracker

logger = get_logger(__name__)

TEXT_EDIT_EXTS = {".md", ".txt", ".bib", ".tex"}
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
LOCAL_PROJECT_KEY = "local_project_path"
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", ".idea"}
MAX_LISTED_FILES = 800
FILE_KINDS = {
    "draft": ("文稿.md", "# 文稿\n\n"),
    "outline": ("大纲.md", "# 大纲\n\n"),
    "notes": ("读书笔记.md", "# 读书笔记\n\n## 书目\n\n## 摘录\n\n## 想法\n\n"),
    "bib": ("参考文献.bib", ""),
    "text": ("笔记.txt", ""),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_upload_ext(ext: str) -> None:
    if ext == ".doc":
        raise ValueError("这是旧版 Word（.doc）。请在 Word 里另存为 .docx 后再上传。")
    if ext not in ALLOWED_FILE_EXTS:
        raise ValueError(f"不支持的文件类型: {ext}")


def _safe_upload_rel(filename: str) -> Path:
    """把浏览器传来的相对路径收成 uploads 下的安全路径，丢掉 .. 和隐藏段。"""
    raw = (filename or "").replace("\\", "/").strip().lstrip("/")
    parts: list[str] = []
    for part in raw.split("/"):
        if not part or part in {".", ".."} or part.startswith("."):
            continue
        clean = "".join(c for c in part if c.isalnum() or c in "._- （）()【】").strip().strip(".")
        if not clean or clean in {".", ".."}:
            continue
        parts.append(clean[:80])
    if not parts:
        raise ValueError("文件名为空")
    if len(parts) > 8:
        parts = parts[-8:]
    return Path(*parts)


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
                if entry.name.startswith("."):
                    continue
                if entry.name in SKIP_DIRS:
                    continue
                if entry.is_dir():
                    rel = str(entry.relative_to(base)).replace("\\", "/")
                    parent = "" if entry.parent == base else str(entry.parent.relative_to(base)).replace("\\", "/")
                    files.append({
                        "id": uuid.uuid4().hex[:12],
                        "name": entry.name,
                        "path": rel,
                        "size_bytes": 0,
                        "modified_at": datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc).isoformat(),
                        "ext": "",
                        "dir": parent,
                        "is_dir": True,
                    })
                    self._scan_dir(base, entry, files, prefix)
                elif entry.is_file():
                    stat = entry.stat()
                    ext = entry.suffix.lower()
                    rel = str(entry.relative_to(base)).replace("\\", "/")
                    parent = "" if entry.parent == base else str(entry.parent.relative_to(base)).replace("\\", "/")
                    info = {
                        "id": uuid.uuid4().hex[:12],
                        "name": entry.name,
                        "path": rel,
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        "ext": ext,
                        "dir": parent,
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

    async def save_generated_file(self, user_id: str, filename: str, content: bytes) -> dict:
        """把生成的文档写入用户工作区 generated/，供左侧文件栏预览和下载。"""
        ext = Path(filename).suffix.lower()
        _check_upload_ext(ext)
        if len(content) > MAX_FILE_SIZE:
            raise ValueError("文件过大，最大 50MB")
        base = user_dir(user_id)
        folder = base / "generated"
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in Path(filename).name if c.isalnum() or c in "._- （）()【】")[:120]
        if not safe.lower().endswith(ext):
            safe = (safe or "论文稿") + ext
        dest = folder / safe
        if dest.exists():
            stem, e = os.path.splitext(safe)
            dest = folder / f"{stem}_{uuid.uuid4().hex[:6]}{e}"
        await asyncio.to_thread(dest.write_bytes, content)
        return {
            "id": uuid.uuid4().hex[:12],
            "name": dest.name,
            "path": str(dest.relative_to(base)).replace("\\", "/"),
            "size_bytes": len(content),
            "modified_at": _now(),
            "ext": ext,
            "dir": "generated",
        }

    async def save_user_file(self, user_id: str, filename: str, content: bytes, mime_type: str = "") -> dict:
        """上传文件到用户工作区。filename 可以是「文件夹/子目录/文件名」。"""
        rel = _safe_upload_rel(filename)
        ext = rel.suffix.lower()
        _check_upload_ext(ext)
        if len(content) > MAX_FILE_SIZE:
            raise ValueError("文件过大，最大 50MB")
        base = user_dir(user_id)
        dest = base / "uploads" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}_{uuid.uuid4().hex[:6]}{dest.suffix}")
        await asyncio.to_thread(dest.write_bytes, content)
        parent = dest.parent.relative_to(base)
        return {
            "id": uuid.uuid4().hex[:12],
            "name": dest.name,
            "path": str(dest.relative_to(base)).replace("\\", "/"),
            "size_bytes": len(content),
            "modified_at": _now(),
            "ext": ext,
            "dir": str(parent).replace("\\", "/"),
        }

    async def delete_user_file(self, user_id: str, path: str):
        """删除用户工作区文件。"""
        fp = await self.get_user_file_path(user_id, path)
        if fp and fp.is_file():
            fp.unlink()

    # ── 上传 ──

    async def save_file(self, session_id: str, filename: str, content: bytes, mime_type: str = "") -> dict:
        ext = Path(filename).suffix.lower()
        _check_upload_ext(ext)
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

    async def get_content(self, session_id: str, file_path: str, user_id: Optional[str] = None, source: str = "site") -> Optional[str]:
        """读取文件文本内容（优先用户工作区或已打开的本机文件夹）。"""
        file = None
        if user_id:
            file = await self.resolve_file(user_id, file_path, source)
        if not file and source != "local":
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
                from services.docx_text import extract_docx_text
                return extract_docx_text(file)
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

    def _is_inside(self, path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False

    def _resolve_inside(self, base: Path, rel: str, must_exist: bool = True) -> Optional[Path]:
        raw = (rel or "").replace("\\", "/").strip()
        if not raw:
            candidate = base.resolve()
            return candidate if (not must_exist or candidate.exists()) else None
        if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
            return None
        parts: list[str] = []
        for part in raw.split("/"):
            if part in {"", "."}:
                continue
            if part == ".." or part.startswith("."):
                return None
            parts.append(part)
        candidate = base.joinpath(*parts).resolve()
        if not self._is_inside(candidate, base):
            return None
        if must_exist and not candidate.exists():
            return None
        return candidate

    async def get_local_root(self, user_id: str) -> Optional[Path]:
        raw = await state_tracker.get_setting(LOCAL_PROJECT_KEY, user_id)
        if not raw or not str(raw).strip():
            return None
        path = Path(str(raw).strip())
        if not path.is_dir():
            await state_tracker.set_setting(LOCAL_PROJECT_KEY, "", user_id)
            return None
        return path.resolve()

    async def set_local_root(self, user_id: str, raw: str) -> dict:
        path = Path((raw or "").strip()).expanduser()
        if not path.is_absolute():
            raise ValueError("请选择一个完整的文件夹路径")
        resolved = path.resolve()
        if not resolved.is_dir():
            raise ValueError("这不是一个文件夹")
        if resolved.parent == resolved:
            raise ValueError("请选一个具体的文件夹，不要选整个磁盘")
        windir = os.environ.get("WINDIR")
        if windir and self._is_inside(resolved, Path(windir)):
            raise ValueError("不能打开系统目录")
        await state_tracker.set_setting(LOCAL_PROJECT_KEY, str(resolved), user_id)
        return {"cancelled": False, "source": "local", "label": resolved.name, "path": str(resolved)}

    async def clear_local_root(self, user_id: str):
        await state_tracker.set_setting(LOCAL_PROJECT_KEY, "", user_id)

    def _scan_limited(self, base: Path, root: Path, files: list, depth: int) -> bool:
        if depth > 8 or len(files) >= MAX_LISTED_FILES:
            return True
        truncated = False
        try:
            entries = sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except (PermissionError, OSError):
            return False
        for entry in entries:
            if len(files) >= MAX_LISTED_FILES:
                return True
            if entry.name.startswith(".") or entry.name in SKIP_DIRS or entry.is_symlink():
                continue
            if entry.is_dir():
                rel = str(entry.relative_to(base)).replace("\\", "/")
                parent = "" if entry.parent == base else str(entry.parent.relative_to(base)).replace("\\", "/")
                files.append({
                    "id": uuid.uuid4().hex[:12],
                    "name": entry.name,
                    "path": rel,
                    "size_bytes": 0,
                    "modified_at": _now(),
                    "ext": "",
                    "dir": parent,
                    "is_dir": True,
                })
                if self._scan_limited(base, entry, files, depth + 1):
                    truncated = True
                continue
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            rel = str(entry.relative_to(base)).replace("\\", "/")
            parent = "" if entry.parent == base else str(entry.parent.relative_to(base)).replace("\\", "/")
            files.append({
                "id": uuid.uuid4().hex[:12],
                "name": entry.name,
                "path": rel,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "ext": entry.suffix.lower(),
                "dir": parent,
            })
        return truncated

    async def list_active(self, user_id: str) -> dict:
        root = await self.get_local_root(user_id)
        if root:
            files: list = []
            truncated = await asyncio.to_thread(self._scan_limited, root, root, files, 0)
            return {
                "data": files,
                "root": {"source": "local", "label": root.name, "path": str(root), "truncated": truncated},
            }
        return {
            "data": await self.list_user_files(user_id),
            "root": {"source": "site", "label": "项目文件", "path": "", "truncated": False},
        }

    async def resolve_file(self, user_id: str, rel: str, source: str = "site") -> Optional[Path]:
        if source == "local":
            base = await self.get_local_root(user_id)
            if not base:
                return None
            found = self._resolve_inside(base, rel, must_exist=True)
            return found if found and found.is_file() else None
        return await self.get_user_file_path(user_id, rel)

    async def save_text(self, user_id: str, rel: str, text: str, source: str = "site") -> dict:
        """覆盖保存一篇已有的文稿。只接受纯文本格式。"""
        if text is None:
            raise ValueError("内容为空")
        raw = text.encode("utf-8")
        if len(raw) > MAX_FILE_SIZE:
            raise ValueError("文件过大，最大 50MB")
        if source == "local":
            base = await self.get_local_root(user_id)
            if not base:
                raise ValueError("还没有打开本机文件夹")
        else:
            base = user_dir(user_id)
        found = self._resolve_inside(base, rel, must_exist=True)
        if not found or not found.is_file():
            raise ValueError("文件不存在")
        if found.suffix.lower() == ".docx":
            from services.docx_text import apply_docx_text
            await asyncio.to_thread(apply_docx_text, found, text)
            dir_label = "" if found.parent == base else str(found.parent.relative_to(base)).replace("\\", "/")
            return self._file_info(base, found, dir_label)
        if found.suffix.lower() not in TEXT_EDIT_EXTS:
            raise ValueError("这个格式不能在这里改，请下载后用别的软件打开")
        await asyncio.to_thread(found.write_text, text, encoding="utf-8")
        dir_label = "" if found.parent == base else str(found.parent.relative_to(base)).replace("\\", "/")
        return self._file_info(base, found, dir_label)

    def _file_info(self, base: Path, dest: Path, dir_label: str) -> dict:
        return {
            "id": uuid.uuid4().hex[:12],
            "name": dest.name,
            "path": str(dest.relative_to(base)).replace("\\", "/"),
            "size_bytes": dest.stat().st_size,
            "modified_at": _now(),
            "ext": dest.suffix.lower(),
            "dir": dir_label,
        }

    async def create_file(self, user_id: str, kind: str, directory: str = "", name: str = "", source: str = "site") -> dict:
        spec = FILE_KINDS.get(kind)
        if not spec:
            raise ValueError("请选择文稿、大纲、读书笔记、参考文献或纯文本")
        default_name, body = spec
        filename = (name or default_name).strip() or default_name
        filename = "".join(c for c in Path(filename).name if c.isalnum() or c in "._- （）()【】").strip().strip(".")
        if not filename:
            raise ValueError("文件名为空")
        ext = Path(default_name).suffix.lower()
        if not filename.lower().endswith(ext):
            filename = f"{Path(filename).stem}{ext}"
        if source == "local":
            base = await self.get_local_root(user_id)
            if not base:
                raise ValueError("还没有打开本机文件夹")
            rel_dir = (directory or "").strip()
        else:
            base = user_dir(user_id)
            rel_dir = (directory or "").replace("\\", "/").strip("/")
            if not rel_dir or rel_dir == "generated" or not rel_dir.startswith("uploads"):
                rel_dir = "uploads"
        parent = self._resolve_inside(base, rel_dir, must_exist=False) if rel_dir else base.resolve()
        if parent is None or not self._is_inside(parent, base):
            raise ValueError("不能建到这个位置")
        if rel_dir and parent.exists() and not parent.is_dir():
            raise ValueError("请先选一个文件夹")
        parent.mkdir(parents=True, exist_ok=True)
        dest = parent / filename
        if dest.exists():
            dest = parent / f"{dest.stem}-{uuid.uuid4().hex[:4]}{dest.suffix}"
        await asyncio.to_thread(dest.write_text, body, encoding="utf-8")
        dir_label = "" if dest.parent == base else str(dest.parent.relative_to(base)).replace("\\", "/")
        return self._file_info(base, dest, dir_label)

    async def _placement(self, user_id: str, directory: str, source: str) -> tuple[Path, Path]:
        if source == "local":
            base = await self.get_local_root(user_id)
            if not base:
                raise ValueError("还没有打开本机文件夹")
            rel_dir = (directory or "").strip()
        else:
            base = user_dir(user_id)
            rel_dir = (directory or "").replace("\\", "/").strip("/")
            if not rel_dir or rel_dir == "generated" or not rel_dir.startswith("uploads"):
                rel_dir = "uploads"
        parent = self._resolve_inside(base, rel_dir, must_exist=False) if rel_dir else base.resolve()
        if parent is None or not self._is_inside(parent, base):
            raise ValueError("不能建到这个位置")
        if rel_dir and parent.exists() and not parent.is_dir():
            raise ValueError("请先选一个文件夹")
        parent.mkdir(parents=True, exist_ok=True)
        return base, parent

    async def create_directory(self, user_id: str, name: str, directory: str = "", source: str = "site") -> dict:
        clean = "".join(c for c in Path(name or "").name if c.isalnum() or c in "._- （）()【】").strip().strip(".")
        if not clean or clean.startswith("."):
            raise ValueError("文件夹名为空")
        base, parent = await self._placement(user_id, directory, source)
        dest = parent / clean
        if dest.exists():
            raise ValueError("已经有同名文件夹或文件")
        await asyncio.to_thread(dest.mkdir)
        rel = str(dest.relative_to(base)).replace("\\", "/")
        dir_label = "" if dest.parent == base else str(dest.parent.relative_to(base)).replace("\\", "/")
        return {
            "id": uuid.uuid4().hex[:12],
            "name": dest.name,
            "path": rel,
            "size_bytes": 0,
            "modified_at": _now(),
            "ext": "",
            "dir": dir_label,
            "is_dir": True,
        }

    async def rename_file(self, user_id: str, rel: str, new_name: str, source: str = "site") -> dict:
        found = await self.resolve_file(user_id, rel, source)
        if not found:
            raise ValueError("文件不存在")
        clean = "".join(c for c in Path(new_name).name if c.isalnum() or c in "._- （）()【】").strip().strip(".")
        if not clean:
            raise ValueError("文件名为空")
        if Path(clean).suffix.lower() not in ALLOWED_FILE_EXTS:
            clean = f"{Path(clean).stem}{found.suffix}"
        dest = found.with_name(clean)
        if dest != found and dest.exists():
            raise ValueError("已经有同名文件")
        await asyncio.to_thread(found.rename, dest)
        if source == "local":
            base = await self.get_local_root(user_id)
        else:
            base = user_dir(user_id)
        if not base:
            raise ValueError("文件不存在")
        dir_label = "" if dest.parent == base else str(dest.parent.relative_to(base)).replace("\\", "/")
        return self._file_info(base, dest, dir_label)

    async def save_local_file(self, user_id: str, filename: str, content: bytes) -> dict:
        base = await self.get_local_root(user_id)
        if not base:
            raise ValueError("还没有打开本机文件夹")
        rel = _safe_upload_rel(filename)
        ext = rel.suffix.lower()
        _check_upload_ext(ext)
        if len(content) > MAX_FILE_SIZE:
            raise ValueError("文件过大，最大 50MB")
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}_{uuid.uuid4().hex[:6]}{dest.suffix}")
        await asyncio.to_thread(dest.write_bytes, content)
        dir_label = "" if dest.parent == base else str(dest.parent.relative_to(base)).replace("\\", "/")
        return self._file_info(base, dest, dir_label)

    async def delete_project_file(self, user_id: str, rel: str, source: str = "site"):
        base = await self.get_local_root(user_id) if source == "local" else user_dir(user_id)
        if not base:
            return
        found = self._resolve_inside(base, rel, must_exist=True)
        if not found:
            return
        if found.resolve() == base.resolve():
            raise ValueError("不能删除打开的这个文件夹本身")
        if found.is_dir():
            await asyncio.to_thread(shutil.rmtree, found)
        elif found.is_file():
            found.unlink()


workspace_manager = WorkspaceManager()
