"""② 截图变模板：把一张幻灯片截图做成"可用的 PPT 模板"。

为什么要绕一圈：拼接引擎只会克隆 .pptx 里的页（形状 + 文字 + 图片位），
而截图只是一张位图。所以这里做三件事，把它变成真正的模板：

1. **认出文字**：RapidOCR 给出每块文字的框 + 内容（已有能力，中文识别可用）；
2. **擦掉文字**：按框把原文字从图里抹掉（用框周围的中位色填充）→ 得到一张干净的"设计底图"；
   不擦的话，我们填进去的字会和截图里原来的字叠在一起，很难看。
3. **重排**：把底图铺满整页 → 在每个文字原位放一个**空文本框**（字号按框高估、颜色按原文字采样）
   → 大块无文字的高方差区域（原本是照片的地方）抹掉并放一个**图片占位矩形**（图片填充），
   这样拼接时 `_replace_picture` 就能把用户的照片填进去。

产出一份 .pptx（可以多页，一页一图），之后走现有流程：`ppt_template.analyze_pptx` 解析 → 入模板库。
"""

from __future__ import annotations

import pathlib
from typing import Optional

# 幻灯片尺寸：截图是宽屏就按 16:9，否则按 4:3
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5
SLIDE_H_4_3 = 10.0   # 4:3 时的高度（宽度仍是 13.333）
EMU_PER_INCH = 914400
MIN_TEXT_HEIGHT_PX = 9
MIN_OCR_SCORE = 0.55
PHOTO_MIN_AREA = 0.06      # 照片区域至少占页面 6%
PLACEHOLDER_GRAY = "D9D9D9"


def _load(image_path: pathlib.Path):
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    return img


def _slide_size(width_px: int, height_px: int) -> tuple[float, float]:
    ratio = width_px / height_px if height_px else 16 / 9
    if abs(ratio - 16 / 9) < 0.25:
        return SLIDE_W_IN, SLIDE_H_IN
    if abs(ratio - 4 / 3) < 0.25:
        return SLIDE_W_IN, SLIDE_H_4_3
    # 其他比例：按截图比例定高度
    return SLIDE_W_IN, round(SLIDE_W_IN / ratio, 3)


def _ocr_boxes(image_path: pathlib.Path, width_px: int, height_px: int) -> list[dict]:
    """RapidOCR 拿文字框：返回 [{x,y,w,h,text,score,size_px}]（像素坐标）。"""
    try:
        import numpy as np
        from PIL import Image
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return []

    try:
        engine = RapidOCR()
        img = np.array(Image.open(image_path).convert("RGB"))
        result, _ = engine(img)
    except Exception:
        return []

    boxes: list[dict] = []
    for item in result or []:
        try:
            poly, text, score = item[0], str(item[1]), float(item[2])
        except Exception:
            continue
        if score < MIN_OCR_SCORE or not text.strip():
            continue
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        x1, x2 = max(0.0, min(xs)), min(float(width_px), max(xs))
        y1, y2 = max(0.0, min(ys)), min(float(height_px), max(ys))
        height = y2 - y1
        if height < MIN_TEXT_HEIGHT_PX or x2 <= x1:
            continue
        boxes.append({
            "x": x1, "y": y1, "w": x2 - x1, "h": height,
            "text": text.strip(), "score": score, "size_px": height,
        })
    return boxes


def _erase_regions(pil_img, regions: list[tuple[int, int, int, int]], pad: int = 3):
    """把若干矩形区域从图里抹掉：用框四周的中位色填充。"""
    import numpy as np
    from PIL import Image

    arr = np.array(pil_img)
    height, width = arr.shape[:2]
    for (x, y, w, h) in regions:
        x1, y1 = max(0, int(x) - pad), max(0, int(y) - pad)
        x2, y2 = min(width, int(x + w) + pad), min(height, int(y + h) + pad)
        if x2 <= x1 or y2 <= y1:
            continue
        # 取框外一圈像素的中位色当底色（比"框内平均色"稳，框内大部分是文字）
        ring = []
        for rx in range(max(0, x1 - 6), min(width, x2 + 6)):
            for ry in (max(0, y1 - 3), min(height - 1, y2 + 2)):
                ring.append(arr[ry, rx])
        for ry in range(max(0, y1 - 6), min(height, y2 + 6)):
            for rx in (max(0, x1 - 3), min(width - 1, x2 + 2)):
                ring.append(arr[ry, rx])
        fill = np.median(np.array(ring), axis=0) if ring else np.array([255, 255, 255])
        arr[y1:y2, x1:x2] = fill.astype("uint8")
    return Image.fromarray(arr)


def _text_color(pil_img, box: dict) -> str:
    """采样文字颜色（框内偏暗的那部分像素）。"""
    import numpy as np

    arr = np.array(pil_img)
    x1, y1 = int(box["x"]), int(box["y"])
    x2, y2 = int(box["x"] + box["w"]), int(box["y"] + box["h"])
    patch = arr[max(0, y1):max(1, y2), max(0, x1):max(1, x2)].reshape(-1, 3)
    if not len(patch):
        return "262626"
    luma = patch.mean(axis=1)
    dark = patch[luma <= luma.min() + 40]
    color = dark.mean(axis=0) if len(dark) else patch.mean(axis=0)
    return "%02X%02X%02X" % tuple(int(max(0, min(255, c))) for c in color)


def _photo_regions(pil_img, text_boxes: list[dict]) -> list[tuple[int, int, int, int]]:
    """找出"大块、无文字、颜色有变化"的区域（截图里原本是照片/配图的地方）。"""
    import numpy as np

    try:
        import cv2
    except Exception:
        return []

    arr = np.array(pil_img)
    height, width = arr.shape[:2]
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    rows, cols = 10, 14
    cell_h, cell_w = height / rows, width / cols
    mask = np.zeros((height, width), dtype="uint8")

    for r in range(rows):
        for c in range(cols):
            y1, y2 = int(r * cell_h), int((r + 1) * cell_h)
            x1, x2 = int(c * cell_w), int((c + 1) * cell_w)
            patch = gray[y1:y2, x1:x2]
            if patch.size == 0 or float(patch.std()) < 18:
                continue   # 太平：纯色背景/色块
            overlaps = any(
                not (b["x"] + b["w"] < x1 or b["x"] > x2 or b["y"] + b["h"] < y1 or b["y"] > y2)
                for b in text_boxes
            )
            if overlaps:
                continue   # 有文字：不是纯照片区
            mask[y1:y2, x1:x2] = 255

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    total = float(width * height)
    regions: list[tuple[int, int, int, int]] = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area / total < PHOTO_MIN_AREA:
            continue
        ratio = w / h if h else 1
        if not (0.4 <= ratio <= 3.5):
            continue
        regions.append((int(x), int(y), int(w), int(h)))
    # 合并靠得很近的区域（同一张照片被网格切开的情况）
    merged: list[list[int]] = []
    for x, y, w, h in sorted(regions, key=lambda r: -r[2] * r[3]):
        for box in merged:
            if not (x + w < box[0] - 20 or x > box[0] + box[2] + 20
                    or y + h < box[1] - 20 or y > box[1] + box[3] + 20):
                box[0] = min(box[0], x)
                box[1] = min(box[1], y)
                box[2] = max(box[0] + box[2], x + w) - box[0]
                box[3] = max(box[1] + box[3], y + h) - box[1]
                break
        else:
            merged.append([x, y, w, h])
    return [(b[0], b[1], b[2], b[3]) for b in merged]


def _gray_png(path: pathlib.Path) -> pathlib.Path:
    from PIL import Image

    if not path.exists():
        Image.new("RGB", (8, 8), "#" + PLACEHOLDER_GRAY).save(path)
    return path


def prepare_page(image_path: str | pathlib.Path, work_dir: str | pathlib.Path, index: int) -> dict:
    """把一张幻灯片截图拆成"可重建的零件"：干净底图 + 文字位 + 照片位。

    `screenshot_to_pptx` 与"救活整页图片化的模板页"共用它。
    """
    source = pathlib.Path(image_path)
    work = pathlib.Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    pil = _load(source)
    width_px, height_px = pil.size
    boxes = _ocr_boxes(source, width_px, height_px)
    photos = _photo_regions(pil, boxes)
    cleaned = _erase_regions(pil, photos, pad=0)
    cleaned = _erase_regions(cleaned, [(b["x"], b["y"], b["w"], b["h"]) for b in boxes])
    bg = work / f"bg_{index}.png"
    cleaned.save(bg)
    return {
        "bg": bg,
        "boxes": boxes,
        "photos": photos,
        "px": (width_px, height_px),
        "slide": _slide_size(width_px, height_px),
    }


def rebuild_image_only_pages(source_pptx: str | pathlib.Path, out_pptx: str | pathlib.Path,
                             pages_1based: list[int], work_dir: str | pathlib.Path | None = None,
                             dpi: int = 110) -> dict:
    """救活"整页导出成图片"的模板页：渲染 → 擦字 → 用干净底图 + 可编辑文本框重建该页。

    这些页原本一个字都改不了（设计稿被导成一张大图）。重建后：
    - 图上的文字被擦掉，换成**我们自己的文本框**（位置、字号、颜色按原样估）；
    - 原本是照片的区域换成**图片占位矩形**，拼接时可以填用户的图；
    - 原页从模板里删掉，新页追加在后面 → 模板整体仍是同一套风格。
    """
    from pptx import Presentation
    from pptx.util import Inches, Pt

    from services import pptx_render

    src = pathlib.Path(source_pptx)
    out = pathlib.Path(out_pptx)
    work = pathlib.Path(work_dir) if work_dir else out.parent / f"{out.stem}_rebuild"
    work.mkdir(parents=True, exist_ok=True)

    images = pptx_render.render_pages(src, sorted(set(pages_1based)), dpi=dpi)
    missing = [p for p in pages_1based if p not in images]
    if not images:
        return {"ok": False, "error": pptx_render.available_reason(), "rebuilt": 0}

    prs = Presentation(str(src))
    placeholder = _gray_png(work / "_placeholder.png")
    report = {"rebuilt": 0, "texts": 0, "photos": 0, "missing": missing, "pages": []}

    for page in sorted(images.keys()):
        image_path = images[page]
        parts = prepare_page(image_path, work, page)
        width_px, height_px = parts["px"]
        slide_w, slide_h = parts["slide"]
        # 用源文件自己的空白版式，避免跨文件版式错乱
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_picture(str(parts["bg"]), 0, 0, Inches(slide_w), Inches(slide_h))

        for (x, y, w, h) in parts["photos"]:
            shape = slide.shapes.add_picture(
                str(placeholder), Inches(x / width_px * slide_w), Inches(y / height_px * slide_h),
                Inches(w / width_px * slide_w), Inches(h / height_px * slide_h))
            shape.name = "PPT_PHOTO_SLOT"
            report["photos"] += 1

        for box in sorted(parts["boxes"], key=lambda b: (b["y"], b["x"])):
            shape = slide.shapes.add_textbox(
                Inches(box["x"] / width_px * slide_w), Inches(box["y"] / height_px * slide_h),
                Inches(max(0.6, box["w"] / width_px * slide_w * 1.06)),
                Inches(max(0.28, box["h"] / height_px * slide_h * 1.5)))
            shape.text_frame.word_wrap = True
            run = shape.text_frame.paragraphs[0].add_run()
            run.text = box["text"]
            run.font.size = Pt(max(9, min(54, round(box["h"] / height_px * slide_h * 72 * 0.75))))
            try:
                from pptx.dml.color import RGBColor

                run.font.color.rgb = RGBColor.from_string(_text_color(_load(image_path), box))
            except Exception:
                pass
            report["texts"] += 1

        report["rebuilt"] += 1
        report["pages"].append(page)

    # 删掉原来的"整页图片化"页（索引从 0 起）
    drop = [p - 1 for p in report["pages"]]
    sld_id_lst = prs.slides._sldIdLst
    elements = list(sld_id_lst)
    for index in sorted(drop, reverse=True):
        if 0 <= index < len(elements):
            element = elements[index]
            try:
                prs.part.drop_rel(element.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"))
            except Exception:
                pass
            sld_id_lst.remove(element)

    prs.save(str(out))
    report["ok"] = True
    report["file"] = str(out)
    return report


def screenshot_to_pptx(images: list[str | pathlib.Path], out_pptx: str | pathlib.Path,
                       work_dir: str | pathlib.Path | None = None) -> dict:
    """把一张或多张幻灯片截图做成一份 pptx（每张截图一页）。"""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    out = pathlib.Path(out_pptx)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(work_dir) if work_dir else out.parent / f"{out.stem}_assets"
    work.mkdir(parents=True, exist_ok=True)
    placeholder = _gray_png(work / "_placeholder.png")

    prs = Presentation()
    first = _load(pathlib.Path(images[0]))
    slide_w, slide_h = _slide_size(*first.size)
    prs.slide_width = Inches(slide_w)
    prs.slide_height = Inches(slide_h)

    report = {"pages": 0, "texts": 0, "photos": 0, "slide_w": slide_w, "slide_h": slide_h}

    for page_index, raw in enumerate(images):
        source = pathlib.Path(raw)
        pil = _load(source)
        width_px, height_px = pil.size
        scale_x = slide_w / width_px
        scale_y = slide_h / height_px

        boxes = _ocr_boxes(source, width_px, height_px)
        photos = _photo_regions(pil, boxes)

        # 擦掉文字与照片 → 干净的底图
        cleaned = _erase_regions(pil, photos, pad=0)
        cleaned = _erase_regions(cleaned, [(b["x"], b["y"], b["w"], b["h"]) for b in boxes])
        bg_path = work / f"bg_{page_index + 1}.png"
        cleaned.save(bg_path)

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_picture(str(bg_path), 0, 0, Inches(slide_w), Inches(slide_h))

        # 照片位：图片填充的矩形（拼接时按 blip 替换）
        for (x, y, w, h) in photos:
            shape = slide.shapes.add_picture(
                str(placeholder),
                Inches(x * scale_x), Inches(y * scale_y), Inches(w * scale_x), Inches(h * scale_y),
            )
            shape.name = "PPT_PHOTO_SLOT"
            report["photos"] += 1

        # 文字位：空文本框（字号按框高估，颜色采样原文字）
        for box in sorted(boxes, key=lambda b: (b["y"], b["x"])):
            frame_shape = slide.shapes.add_textbox(
                Inches(box["x"] * scale_x), Inches(box["y"] * scale_y),
                Inches(max(0.6, box["w"] * scale_x * 1.06)),
                Inches(max(0.28, box["h"] * scale_y * 1.5)),
            )
            tf = frame_shape.text_frame
            tf.word_wrap = True
            size_pt = max(9, min(54, round(box["size_px"] * scale_y * 72 * 0.75)))
            para = tf.paragraphs[0]
            run = para.add_run()
            run.text = box["text"]
            run.font.size = Pt(size_pt)
            try:
                from pptx.dml.color import RGBColor

                run.font.color.rgb = RGBColor.from_string(_text_color(pil, box))
            except Exception:
                pass
            # 居中的框（左右留白差不多）保持居中
            if box["x"] > width_px * 0.18 and abs((box["x"]) - (width_px - box["x"] - box["w"])) < width_px * 0.08:
                from pptx.enum.text import PP_ALIGN

                para.alignment = PP_ALIGN.CENTER
            report["texts"] += 1

        report["pages"] += 1

    prs.save(str(out))
    report["file"] = str(out)
    report["assets"] = str(work)
    return report
