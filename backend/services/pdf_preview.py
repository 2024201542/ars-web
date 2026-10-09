"""把 PDF 画成页面图片。浏览器自带阅读器嵌在页面里时会一片黑。"""

import threading
from pathlib import Path

_LOCK = threading.Lock()
_CACHE: dict[tuple, list[bytes | None]] = {}


def _key(path: Path) -> tuple:
    stat = path.stat()
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def pdf_page_count(path: Path) -> int:
    import pymupdf

    doc = pymupdf.open(path)
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def render_pdf_page(path: Path, index: int) -> bytes:
    key = _key(path)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and 0 <= index < len(cached) and cached[index] is not None:
            return cached[index]
    import pymupdf

    doc = pymupdf.open(path)
    count = 0
    try:
        count = int(doc.page_count)
        if index < 0 or index >= count:
            raise ValueError("没有这一页")
        pix = doc[index].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        data = pix.tobytes("png")
    finally:
        doc.close()
    with _LOCK:
        bucket = _CACHE.get(key)
        if bucket is None or len(bucket) != count:
            if len(_CACHE) > 2:
                _CACHE.clear()
            bucket = [None] * count
            _CACHE[key] = bucket
        if 0 <= index < len(bucket):
            bucket[index] = data
    return data
