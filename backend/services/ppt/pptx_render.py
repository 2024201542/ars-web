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


def _cache_root() -> pathlib.Path:
    # 测试和 DSH 沙箱里 data\ 目录不一定可写，用环境变量把缓存指到可写处
    override = os.environ.get("ARS_PPT_RENDER_CACHE", "")
    return pathlib.Path(override) if override else CACHE_ROOT


def cache_dir(path: str | pathlib.Path) -> pathlib.Path:
    folder = _cache_root() / _fingerprint(pathlib.Path(path))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def cached_page(path: str | pathlib.Path, page: int) -> pathlib.Path | None:
    target = cache_dir(path) / f"page-{page}.png"
    return target if target.exists() and target.stat().st_size > 0 else None


def _render_via_pdf(source: pathlib.Path, pages: list[int], dpi: int) -> dict[int, pathlib.Path]:
    """先 convert 成 PDF 再用 PyMuPDF 出整页图。

    kit 的 render 命令对宽模板只画左上约 75%（右侧和底部被裁掉），
    convert 转 PDF 不走那套裁剪逻辑，出来的是整页。
    PDF 缓存成 deck.pdf：同一文件再请求别的页时直接翻 PDF，不重复转换。
    """
    global _LAST_ERROR
    try:
        import pymupdf
    except ImportError:
        _LAST_ERROR = "没有安装 pymupdf，无法走 PDF 渲染"
        return {}

    folder = cache_dir(source)
    pdf = folder / "deck.pdf"
    have: dict[int, pathlib.Path] = {}
    # convert 和出图都在串行锁里：出图很快，锁里一起做完能避免
    # "一个线程在写 deck.pdf、另一个线程同时在读" 的半截文件。
    with _RENDER_LOCK:
        if not pdf.exists() or pdf.stat().st_size == 0:
            tmp_pdf = pathlib.Path(tempfile.gettempdir()) / f"ppt_convert_{uuid.uuid4().hex[:10]}.pdf"
            try:
                cmd = [node_path(), cli_path(), "convert", "--input", str(source),
                       "--output", str(tmp_pdf)]
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", timeout=300)
                if not tmp_pdf.exists() or tmp_pdf.stat().st_size == 0:
                    _LAST_ERROR = (result.stdout or result.stderr or "convert 没有产出 PDF")[:300]
                    logger.warning("convert 没有产出 PDF：%s", _LAST_ERROR)
                    return {}
                shutil.copyfile(tmp_pdf, pdf)
            except subprocess.TimeoutExpired:
                _LAST_ERROR = "convert 超时（超过 300 秒）"
                logger.warning("convert 超时：%s", source.name)
                return {}
            except Exception as exc:
                _LAST_ERROR = f"{type(exc).__name__}: {exc}"
                logger.warning("convert 失败：%s", exc)
                return {}
            finally:
                tmp_pdf.unlink(missing_ok=True)
        try:
            doc = pymupdf.open(pdf)
            for page in pages:
                idx = page - 1  # pptx 页号从 1 起，PyMuPDF 从 0 起
                if idx < 0 or idx >= doc.page_count:
                    continue
                dest = folder / f"page-{page}.png"
                doc.load_page(idx).get_pixmap(dpi=dpi).save(dest)
                have[page] = dest
            doc.close()
        except Exception as exc:
            _LAST_ERROR = f"PDF 出图失败：{type(exc).__name__}: {exc}"
            logger.warning("PDF 出图失败：%s", exc)
            # deck.pdf 损坏时删掉，下次请求重新 convert
            if not have:
                pdf.unlink(missing_ok=True)
    return have


def _render_via_kit(source: pathlib.Path, pages: list[int], dpi: int) -> dict[int, pathlib.Path]:
    """老路径：kit render 命令直接出 PNG。宽模板会被裁掉右侧和底部，只作兜底。"""
    global _LAST_ERROR
    have: dict[int, pathlib.Path] = {}
    # 注意：kit 要求输出目录**尚不存在**（它自己创建），所以不能先 mkdtemp
    tmp = pathlib.Path(tempfile.gettempdir()) / f"ppt_render_{uuid.uuid4().hex[:10]}"
    try:
        cmd = [node_path(), cli_path(), "render", "--input", str(source),
               "--output-dir", str(tmp), "--dpi", str(dpi),
               "--pages", ",".join(str(p) for p in pages)]
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
            if pos >= len(pages):
                break
            page = pages[pos]
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


def render_pages(path: str | pathlib.Path, pages: list[int], dpi: int = 110) -> dict[int, pathlib.Path]:
    """渲染指定页，返回 {页号: PNG 路径}。已缓存的页不重复渲染。

    先走 convert+PDF 出整页图；失败的页再退回 kit render 老路径。
    """
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
        have.update(_render_via_pdf(source, missing, dpi))
        still = [p for p in missing if p not in have]
        if still:
            have.update(_render_via_kit(source, still, dpi))

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
    root = _cache_root()
    if root.is_dir():
        for folder in root.iterdir():
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
                count += 1
    return count
