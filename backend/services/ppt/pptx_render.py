"""把 pptx 渲染成 PNG（用 DSH 自带的 LibreOffice Kit），带磁盘缓存。

为什么用它：本机没有 PowerPoint，也没有系统 LibreOffice；
DSH 运行时里带了 libreoffice-kit（node + cli），能 `render` 出每页图片。
拿到真图以后，"模板卡片""生成结果"就不用只画色块示意了。

缓存策略：按"文件指纹（路径+大小+修改时间）"建目录，页图存成 page-<n>.png；
文件一改指纹变，缓存自然失效。渲染很慢（每页约 1–2 秒），所以一定要缓存。

找不到 node/cli 时 `available()` 返回 False，调用方回退到结构预览，不报错。
"""

from __future__ import annotations

import hashlib
import logging
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import uuid

logger = logging.getLogger(__name__)

# 渲染很吃资源：一份 20MB 的设计模板起一次 LibreOffice 要好几秒。
# 界面一口气请求 11 张封面时会并发 11 个进程，互相拖超时、还会让机器卡住——
# 所以这里串行化：一次只跑一个渲染任务，其余排队等。
_RENDER_LOCK = threading.Lock()
_LAST_ERROR = ""

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
CACHE_ROOT = DATA_DIR / "ppt_render"

NODE_CANDIDATES = [
    os.environ.get("ARS_LO_NODE", ""),
    r"D:\deepseek harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe",
    str(pathlib.Path.home() / ".dsh" / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"),
]
CLI_CANDIDATES = [
    os.environ.get("ARS_LO_CLI", ""),
    r"D:\deepseek harness\resources\app.asar.unpacked\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js",
]


def _first_existing(candidates: list[str]) -> str:
    for raw in candidates:
        if raw and pathlib.Path(raw).exists():
            return raw
    return ""


def node_path() -> str:
    return _first_existing(NODE_CANDIDATES)


def cli_path() -> str:
    return _first_existing(CLI_CANDIDATES)


def available() -> bool:
    return bool(node_path() and cli_path())


def _fingerprint(path: pathlib.Path) -> str:
    try:
        st = path.stat()
        raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        raw = str(path)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def cache_dir(path: str | pathlib.Path) -> pathlib.Path:
    folder = CACHE_ROOT / _fingerprint(pathlib.Path(path))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def cached_page(path: str | pathlib.Path, page: int) -> pathlib.Path | None:
    target = cache_dir(path) / f"page-{page}.png"
    return target if target.exists() and target.stat().st_size > 0 else None


def render_pages(path: str | pathlib.Path, pages: list[int], dpi: int = 110) -> dict[int, pathlib.Path]:
    """渲染指定页，返回 {页号: PNG 路径}。已缓存的页不重复渲染。"""
    source = pathlib.Path(path)
    if not source.is_file() or not available():
        return {}

    have: dict[int, pathlib.Path] = {}
    missing: list[int] = []
    for page in pages:
        hit = cached_page(source, page)
        if hit:
            have[page] = hit
        else:
            missing.append(page)

    if missing:
        # 注意：kit 要求输出目录**尚不存在**（它自己创建），所以不能先 mkdtemp
        tmp = pathlib.Path(tempfile.gettempdir()) / f"ppt_render_{uuid.uuid4().hex[:10]}"
        global _LAST_ERROR
        try:
            cmd = [node_path(), cli_path(), "render", "--input", str(source),
                   "--output-dir", str(tmp), "--dpi", str(dpi),
                   "--pages", ",".join(str(p) for p in missing)]
            # 串行执行：并发渲染会把机器压垮（界面里 11 张封面一起请求就会这样）
            with _RENDER_LOCK:
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", timeout=180)
            produced = sorted(tmp.glob("*.png"))
            if not produced:
                _LAST_ERROR = (result.stdout or result.stderr or "")[:300]
                logger.warning("渲染没有产出图片：%s", _LAST_ERROR)
            folder = cache_dir(source)
            # 输出是"请求顺序 + index"命名的，按顺序对应回页号
            for pos, image in enumerate(produced):
                if pos >= len(missing):
                    break
                page = missing[pos]
                dest = folder / f"page-{page}.png"
                shutil.copyfile(image, dest)
                have[page] = dest
        except subprocess.TimeoutExpired:
            _LAST_ERROR = "渲染超时（超过 180 秒）"
            logger.warning("渲染超时：%s", source.name)
        except Exception as exc:
            _LAST_ERROR = f"{type(exc).__name__}: {exc}"
            logger.warning("渲染失败：%s", exc)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return have


def last_error() -> str:
    return _LAST_ERROR


def available_reason() -> str:
    """渲染不可用时的原因，供接口给出准确提示。"""
    if not available():
        return "这台机器上没找到 DSH 自带的 LibreOffice Kit（node / cli）"
    return _LAST_ERROR or "这一页渲染失败或超时，可以重试"


def render_first_page(path: str | pathlib.Path, dpi: int = 90) -> pathlib.Path | None:
    return render_pages(path, [1], dpi=dpi).get(1)


def clear_cache() -> int:
    """清掉渲染缓存，返回删掉的目录数。"""
    count = 0
    if CACHE_ROOT.is_dir():
        for folder in CACHE_ROOT.iterdir():
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
                count += 1
    return count
