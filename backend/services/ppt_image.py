"""PPT 图像素材：盘点、分类、按框裁剪、从 PDF 抽图。

配图能做到什么程度，取决于"图从哪来"和"图往哪放"：
- 来源：用户 @ 进来的图片、左侧文件夹里的图片、**论文 PDF 里抽出来的图表**；
- 放置：模板解析出的"图片位"（`ppt_template` 记为 specimen.images）；按位的比例裁剪后替换，
  所以图不会被拉变形。

方位分类很简单但够用：横图（宽高比 >1.25）、竖图（<0.8）、方图（其间）、超宽（>2.2）、超长（<0.45）。
版式选择就按这个来：竖图配"左图右文/两栏"，横图配"整页大图/图文页"，方图配"卡片页"。
"""

from __future__ import annotations

import pathlib
from typing import Optional

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def is_image(path: str | pathlib.Path) -> bool:
    return pathlib.Path(str(path)).suffix.lower() in IMAGE_EXTS


def describe(path: str | pathlib.Path) -> Optional[dict]:
    """读一张图的元信息（尺寸、比例、方位、主色）。读不了就返回 None。"""
    target = pathlib.Path(path)
    if not target.is_file():
        return None
    try:
        from PIL import Image

        with Image.open(target) as img:
            width, height = img.size
            if width <= 0 or height <= 0:
                return None
            ratio = round(width / height, 3)
            small = img.convert("RGB").resize((24, 24))
            pixels = list(small.getdata())
            avg = tuple(sum(c[i] for c in pixels) // len(pixels) for i in range(3))
            dominant = "#%02X%02X%02X" % avg
    except Exception:
        return None

    if ratio >= 2.2:
        orient = "ultrawide"
    elif ratio > 1.25:
        orient = "landscape"
    elif ratio >= 0.8:
        orient = "square"
    elif ratio >= 0.45:
        orient = "portrait"
    else:
        orient = "tall"
    return {
        "path": str(target),
        "name": target.name,
        "width": width,
        "height": height,
        "ratio": ratio,
        "orient": orient,
        "dominant": dominant,
    }


def collect(paths: list[str], limit: int = 12) -> list[dict]:
    """把一堆路径里"确实是图片"的挑出来并描述。"""
    out: list[dict] = []
    for raw in paths:
        if not raw:
            continue
        info = describe(raw)
        if info:
            out.append(info)
        if len(out) >= limit:
            break
    return out


def orient_rank(orient: str, want: str) -> int:
    """给方位打分（越小越合适），want 是"这一页想要什么形状的图"。"""
    order = {
        "portrait": ["portrait", "tall", "square"],
        "landscape": ["landscape", "ultrawide", "square"],
        "square": ["square", "landscape", "portrait"],
        "any": ["landscape", "square", "portrait", "ultrawide", "tall"],
    }
    seq = order.get(want, order["any"])
    return seq.index(orient) if orient in seq else len(seq) + 1


def pick_for_slot(assets: list[dict], slot_ratio: float, used: set[str]) -> Optional[dict]:
    """按图片位的比例挑最合适的一张（还没用过的、比例接近优先）。"""
    candidates = [a for a in assets if a["path"] not in used]
    if not candidates:
        return None
    return min(candidates, key=lambda a: abs(a["ratio"] - (slot_ratio or 1.0)))


def fit_to_slot(image_path: str | pathlib.Path, slot_ratio: float, out_path: str | pathlib.Path,
                max_px: int = 1600) -> Optional[pathlib.Path]:
    """把图裁成图片位的比例（不拉伸），输出到 out_path。"""
    if not slot_ratio or slot_ratio <= 0:
        return None
    try:
        from PIL import Image, ImageOps

        target = pathlib.Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            if slot_ratio >= 1:
                width = min(max_px, img.width)
                height = max(1, int(width / slot_ratio))
            else:
                height = min(max_px, img.height)
                width = max(1, int(height * slot_ratio))
            # centering 稍微偏上一点：人像/建筑主体通常在上半部
            fitted = ImageOps.fit(img, (width, height), method=Image.LANCZOS, centering=(0.5, 0.42))
            fitted.save(target, format="PNG" if target.suffix.lower() == ".png" else "JPEG", quality=90)
        return target
    except Exception:
        return None


def extract_from_pdf(pdf_path: str | pathlib.Path, out_dir: str | pathlib.Path,
                     min_px: int = 200, limit: int = 8) -> list[dict]:
    """从 PDF 里抽出内嵌图片（论文里的图表/示意图）。

    过滤掉太小的（图标、公式碎片）与几乎一样大的重复图（同一张图在多页重复）。
    """
    import hashlib

    import pymupdf

    source = pathlib.Path(pdf_path)
    folder = pathlib.Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    found: list[dict] = []

    try:
        doc = pymupdf.open(source)
    except Exception:
        return found

    try:
        for page_index in range(min(doc.page_count, 40)):
            if len(found) >= limit:
                break
            page = doc.load_page(page_index)
            for img_index, meta in enumerate(page.get_images(full=True)):
                if len(found) >= limit:
                    break
                xref = meta[0]
                try:
                    data = doc.extract_image(xref)
                except Exception:
                    continue
                width, height = data.get("width") or 0, data.get("height") or 0
                if width < min_px or height < min_px:
                    continue
                digest = hashlib.sha1(data["image"]).hexdigest()[:12]
                if digest in seen:
                    continue
                seen.add(digest)
                ext = data.get("ext") or "png"
                target = folder / f"{source.stem}_p{page_index + 1}_{img_index}.{ext}"
                try:
                    target.write_bytes(data["image"])
                except Exception:
                    continue
                info = describe(target)
                if info:
                    info["from_pdf"] = source.name
                    info["page"] = page_index + 1
                    found.append(info)
    finally:
        doc.close()
    return found
