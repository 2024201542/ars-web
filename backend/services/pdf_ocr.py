"""扫描件 PDF 的文字提取（OCR）。

pdftotext 只能取 PDF 里已有的文字层；纯扫描件（每页一张图）取出来是空的。
这里用 RapidOCR（onnxruntime，纯 CPU，无需额外安装 Tesseract）把页面渲染成图再识别。

两个关键取舍：
1. **逐页缓存**：OCR 约 5 秒/页，同一份文件绝不重复识别。缓存落在 data/ocr_cache/。
2. **按需扩页**：先只识别前 N 页（够摘要、引言、辩题用），需要更多时再往上加页，
   已识别的页直接从缓存读。整份 50 页第一次跑要几分钟，所以不放在同步请求里死等。
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 单页渲染分辨率；实测 150/200/禁检测三种配置耗时接近（5.5–6.1s），取 200 保清晰度
RENDER_DPI = 200
# 单次同步请求最多识别多少页（新页），避免一个请求挂几分钟
SYNC_MAX_NEW_PAGES = 4
# 后台预热一次最多识别多少页
WARM_MAX_PAGES = 12
# pdftotext 取到的文字少于此值，就认为没有文字层、需要 OCR
TEXT_LAYER_MIN_CHARS = 120

_CACHE_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "ocr_cache"
_ENGINE = None
_ENGINE_LOCK = threading.Lock()

# 正在预热的文件（绝对路径），避免重复起线程
_WARMING: set[str] = set()
_OCR_SEMAPHORE = threading.Semaphore(1)  # RapidOCR 引擎不是线程安全的，串行使用


def _cache_dir() -> pathlib.Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _build_result(pages: dict, total: int, limit: int) -> dict:
    """按页码顺序拼出文字，并算出识别情况。"""
    got = sorted(int(k) for k, v in pages.items() if (v or "").strip())
    text = "\n\n".join((pages[str(i)] or "").strip() for i in got)
    # 还没有文字的页（没识别过或识别为空）
    pending = len([i for i in range(limit) if not (pages.get(str(i)) or "").strip()])
    source = "empty" if not text.strip() else ("ocr" if pending == 0 else "ocr-partial")
    return {"text": text, "total_pages": total, "ocr_pages": got,
            "source": source, "pending_pages": pending}


def _fingerprint(path: pathlib.Path) -> str:
    """按路径+大小+修改时间做指纹，文件变了缓存自然失效。"""
    st = path.stat()
    raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _cache_file(path: pathlib.Path) -> pathlib.Path:
    return _cache_dir() / f"{_fingerprint(path)}.json"


def read_cache(path: pathlib.Path) -> Optional[dict]:
    fp = _cache_file(path)
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_cache(path: pathlib.Path, data: dict) -> None:
    fp = _cache_file(path)
    try:
        data = {**data, "file": str(path), "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        tmp = fp.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(fp)
    except Exception as exc:  # 缓存写不了不该影响主流程
        logger.warning("OCR 缓存写入失败: %s", exc)


def _engine():
    """懒加载 OCR 引擎（首次约 1 秒）。"""
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                from rapidocr_onnxruntime import RapidOCR

                _ENGINE = RapidOCR()
    return _ENGINE


def ocr_page(doc, page_index: int) -> str:
    """识别单页，返回按行拼接的文本。"""
    import numpy as np
    import pymupdf  # noqa: F401  (doc 由调用方用 pymupdf 打开)
    from PIL import Image

    page = doc.load_page(page_index)
    pix = page.get_pixmap(dpi=RENDER_DPI)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    arr = np.array(img)
    with _OCR_SEMAPHORE:
        result, _ = _engine()(arr)
    lines = [item[1] for item in (result or []) if len(item) > 1 and item[1]]
    return "\n".join(lines)


def extract_text(path: str | pathlib.Path, max_pages: Optional[int] = None,
                 max_new_pages: int = SYNC_MAX_NEW_PAGES,
                 min_chars: int = TEXT_LAYER_MIN_CHARS) -> dict:
    """取 PDF 文字：优先文字层，必要时 OCR。

    返回 {text, total_pages, ocr_pages, source, pending_pages}
      source: "text-layer" | "ocr" | "ocr-partial" | "empty"
      pending_pages: 还没识别、需要再调一次才能补齐的页数
    """
    import pymupdf

    fp = pathlib.Path(path)
    doc = pymupdf.open(fp)
    try:
        total = doc.page_count
        limit = total if max_pages is None else min(total, max_pages)

        # 1. 先试文字层
        layer = "\n".join(doc.load_page(i).get_text() for i in range(limit)).strip()
        if len(layer) >= min_chars:
            return {"text": layer, "total_pages": total, "ocr_pages": [],
                    "source": "text-layer", "pending_pages": 0}

        # 2. 文字层不够 → OCR，先看缓存
        cache = read_cache(fp) or {"pages": {}}
        pages: dict = cache.get("pages") or {}
        remaining = limit - len(pages)
        new_budget = max(0, min(max_new_pages, remaining))
        done_new = 0
        for i in range(limit):
            key = str(i)
            if key in pages:
                continue
            if done_new >= new_budget:
                break
            try:
                pages[key] = ocr_page(doc, i)
            except Exception as exc:
                logger.warning("第 %d 页 OCR 失败: %s", i + 1, exc)
                pages[key] = ""
            done_new += 1

        if done_new:
            write_cache(fp, {"pages": pages, "total_pages": total})

        result = _build_result(pages, total, limit)
        # 已经确认是扫描件：后台把后面的页慢慢识别完，用户下次读就是现成的
        if result["source"] in ("ocr", "ocr-partial"):
            warm_pages(fp, WARM_MAX_PAGES)
        return result
    finally:
        doc.close()


def progress(path: str | pathlib.Path) -> dict:
    """查一份 PDF 的 OCR 进度：已识别多少页 / 共多少页。

    没有缓存且文字层够用时，直接报"不需要 OCR"，避免为了显示进度去开一次 PDF。
    """
    fp = pathlib.Path(path)
    cache = read_cache(fp)
    pages = (cache or {}).get("pages") or {}
    done = len([k for k, v in pages.items() if (v or "").strip()])
    total = (cache or {}).get("total_pages") or 0
    if not total:
        try:
            import pymupdf

            doc = pymupdf.open(fp)
            try:
                total = doc.page_count
            finally:
                doc.close()
        except Exception:
            total = 0
    warming = str(fp.resolve()) in _WARMING
    return {
        "done": done,
        "total": total,
        "warming": warming,
        "needs_ocr": needs_ocr(fp) if total else False,
        "pending": max(0, total - done),
    }


def warm_pages(path: str | pathlib.Path, pages: int = WARM_MAX_PAGES) -> None:
    """后台把前 pages 页识别完并写入缓存；已在预热或已达页数则直接返回。"""
    fp = pathlib.Path(path)
    key = str(fp.resolve())
    if key in _WARMING:
        return
    cache = read_cache(fp)
    have = len([k for k, v in ((cache or {}).get("pages") or {}).items() if v])
    if have >= pages:
        return

    _WARMING.add(key)

    def run():
        try:
            import pymupdf

            doc = pymupdf.open(fp)
            try:
                total = doc.page_count
                data = read_cache(fp) or {"pages": {}}
                store: dict = data.get("pages") or {}
                for i in range(min(pages, total)):
                    if store.get(str(i)):
                        continue
                    try:
                        store[str(i)] = ocr_page(doc, i)
                    except Exception as exc:
                        logger.warning("预热第 %d 页失败: %s", i + 1, exc)
                    write_cache(fp, {"pages": store, "total_pages": total})
                logger.info("OCR 预热完成: %s 前 %d 页", fp.name, min(pages, total))
            finally:
                doc.close()
        except Exception as exc:
            logger.warning("OCR 预热失败 %s: %s", fp, exc)
        finally:
            _WARMING.discard(key)

    threading.Thread(target=run, name="ocr-warm", daemon=True).start()


def needs_ocr(path: str | pathlib.Path) -> bool:
    """快速判断是否属于"文字层几乎没有"的扫描件。"""
    import pymupdf

    try:
        doc = pymupdf.open(pathlib.Path(path))
    except Exception:
        return False
    try:
        probe = min(3, doc.page_count)
        chars = sum(len(doc.load_page(i).get_text().strip()) for i in range(probe))
        return chars < TEXT_LAYER_MIN_CHARS
    finally:
        doc.close()
