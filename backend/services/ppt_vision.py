"""③ 视觉排版：让看图模型（qwen-vl）判断"哪块是标题、哪块是正文、哪块是配图位"。

为什么需要它：设计型模板（人大那几套）每页构图都不一样，我用几何启发式猜"标题框"
经常猜偏——结果就是有的页留着"添加标题内容"这种占位文字，我们的字跑到别处去了。
让模型看一眼渲染出来的页面，直接给出三个区域集合，比我猜准得多。

流程：pptx 某页 → 渲染成 PNG（LibreOffice Kit，已有）→ qwen-vl 返回归一化坐标
→ 与解析出来的文本框做重叠匹配 → 改写该页的 title_i / bodies_i。
结果按"文件指纹 + 页码"缓存，避免重复花钱。
"""

from __future__ import annotations

import asyncio
import base64
import json
import pathlib
from typing import Optional

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
CACHE_DIR = BACKEND_DIR / "data" / "ppt_vision"

VISION_MODELS = {
    "qwen-vl-max": "qwen",
    "qwen3-vl-plus": "qwen",
    "qwen-vl-plus": "qwen",
}
DEFAULT_VISION_MODEL = "qwen-vl-max"

PROMPT = (
    "这是一张幻灯片页面。请只输出 JSON（不要解释、不要代码块标记），字段为：\n"
    '{"title_boxes": [[x,y,w,h]], "body_boxes": [[x,y,w,h]], "photo_boxes": [[x,y,w,h]], "note": "一句话"}\n'
    "坐标是相对整页的归一化值（0~1，左上为原点）。"
    "title_boxes：页面标题所在区域（通常 1 个，最多 2 个）；"
    "body_boxes：正文内容区域（要点列表、段落、表格文字），按从上到下、从左到右排序；"
    "photo_boxes：照片/插图/图表所在区域（没有就给空数组）。"
    "只框真正的内容区，不要把校徽、页眉导航条、页码算进去。"
)


def _fingerprint(path: pathlib.Path) -> str:
    import hashlib

    try:
        st = path.stat()
        raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        raw = str(path)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(template_path: pathlib.Path, page: int) -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{_fingerprint(template_path)}_p{page}.json"


async def _vision_call(user_id: str, image_path: pathlib.Path, model_id: str) -> tuple[dict, str]:
    """调视觉模型。返回 (解析出的 dict, 错误信息)。"""
    import httpx

    from providers import PROVIDERS
    from services.state_tracker import tracker

    provider_key = VISION_MODELS.get(model_id, "qwen")
    provider = PROVIDERS[provider_key]
    key = (await tracker.get_setting(provider["key_setting"], user_id) or "").strip()
    if not key:
        return {}, f"{provider['display_name']} 还没配 API Key"
    base = (await tracker.get_setting(provider["base_url_setting"], user_id) or "").strip() \
        or (provider.get("default_base_url") or "")

    data_url = "data:image/png;base64," + base64.b64encode(image_path.read_bytes()).decode()
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
        "max_tokens": 900,
        "temperature": 0.1,
    }
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(f"{base.rstrip('/')}/chat/completions", json=body,
                                     headers={"Authorization": f"Bearer {key}"})
        if resp.status_code != 200:
            return {}, f"HTTP {resp.status_code}: {resp.text[:160]}"
        content = resp.json()["choices"][0]["message"].get("content") or ""
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"

    text = str(content).strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}, f"模型没给出 JSON：{text[:120]}"
    try:
        return json.loads(text[start:end + 1]), ""
    except Exception as exc:
        return {}, f"JSON 解析失败：{exc}"


def normalize_boxes(regions: dict, image_w: int, image_h: int) -> dict:
    """把模型返回的坐标统一成 0~1。

    实测：即使提示里明确要求归一化，qwen-vl 仍常返回**像素坐标**（例如 x=1472 就是图宽），
    所以这里自动判定——只要有任何一个值 > 1.5，就按像素处理并除以图片尺寸。
    """
    out: dict = {}
    for key in ("title_boxes", "body_boxes", "photo_boxes"):
        boxes = regions.get(key) or []
        fixed = []
        for box in boxes:
            try:
                x, y, w, h = (float(v) for v in list(box)[:4])
            except Exception:
                continue
            if max(abs(x), abs(y), abs(w), abs(h)) > 1.5:
                x, y, w, h = x / image_w, y / image_h, w / image_w, h / image_h
            fixed.append([round(x, 4), round(y, 4), round(max(0.0, w), 4), round(max(0.0, h), 4)])
        out[key] = fixed
    if regions.get("note"):
        out["note"] = regions["note"]
    return out


def _overlap(a: dict, box: list[float]) -> float:
    """文本框与视觉区域的交并比（都是归一化坐标）。"""
    try:
        ax1, ay1 = float(a["x"]), float(a["y"])
        ax2, ay2 = ax1 + float(a["w"]), ay1 + float(a["h"])
        bx1, by1, bw, bh = (float(v) for v in box[:4])
        bx2, by2 = bx1 + bw, by1 + bh
    except Exception:
        return 0.0
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = (ax2 - ax1) * (ay2 - ay1) + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _to_normalized(frame: dict, slide_w: float, slide_h: float) -> dict:
    return {
        "x": (frame.get("x") or 0) / (slide_w or 1),
        "y": (frame.get("y") or 0) / (slide_h or 1),
        "w": (frame.get("w") or 0) / (slide_w or 1),
        "h": (frame.get("h") or 0) / (slide_h or 1),
        "i": frame["i"],
    }


def _contains(a: dict, box: list[float]) -> float:
    """文本框有多大比例落在视觉区域内（比 IoU 宽容：框被大区域包住也算命中）。"""
    try:
        ax1, ay1 = float(a["x"]), float(a["y"])
        ax2, ay2 = ax1 + float(a["w"]), ay1 + float(a["h"])
        bx1, by1, bw, bh = (float(v) for v in box[:4])
        bx2, by2 = bx1 + bw, by1 + bh
    except Exception:
        return 0.0
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    area = max(1e-6, (ax2 - ax1) * (ay2 - ay1))
    return inter / area


def _apply_regions(spec: dict, regions: dict, slide_w: float, slide_h: float) -> dict:
    """把视觉区域映射回该页已有的文本框，改写 title_i / bodies_i。"""
    frames = spec.get("frames") or []
    if not frames:
        return {"changed": False, "reason": "这页没有文本框"}
    norm = [_to_normalized(f, slide_w, slide_h) for f in frames]
    changed: list[str] = []

    title_boxes = regions.get("title_boxes") or []
    if title_boxes:
        best, best_score = None, 0.18      # 低于这个重叠就不动，避免乱改
        for frame in norm:
            score = max((_overlap(frame, box) for box in title_boxes), default=0.0)
            if score > best_score:
                best, best_score = frame, score
        if best is not None and best["i"] != spec.get("title_i"):
            spec["title_i"] = best["i"]
            changed.append("title")

    body_boxes = regions.get("body_boxes") or []
    if body_boxes:
        hits: list[tuple[float, float, int]] = []
        for box in body_boxes:
            for frame in norm:
                # 用"包含度"而不是 IoU：文本框通常小于模型画的内容区，IoU 会偏小导致漏配
                score = max(_contains(frame, box), _overlap(frame, box))
                if score >= 0.35:
                    hits.append((float(box[1]), float(box[0]), frame["i"]))
        hits.sort()
        ordered = [i for _, _, i in hits if i != spec.get("title_i")]
        if ordered and ordered != (spec.get("bodies_i") or []):
            spec["bodies_i"] = ordered
            spec["body_i"] = ordered[0]
            spec["capacity"] = max(1, len(ordered))
            changed.append("body")

    photo_boxes = regions.get("photo_boxes") or []
    if photo_boxes and (spec.get("images") or []):
        best, best_score = None, 0.2
        for slot in spec["images"]:
            slot_norm = _to_normalized({k: slot.get(k) for k in ("x", "y", "w", "h")} | {"i": slot["i"]},
                                       slide_w, slide_h)
            score = max((_overlap(slot_norm, box) for box in photo_boxes), default=0.0)
            if score > best_score and not slot.get("full_bleed"):
                best, best_score = slot, score
        if best is not None and best["i"] != spec.get("image_i"):
            spec["image_i"] = best["i"]
            spec["image_ratio"] = best.get("ratio")
            spec["image_usable"] = True
            changed.append("image")

    return {"changed": bool(changed), "fields": changed}


async def refine_page(user_id: str, analysis: dict, template_path: str | pathlib.Path,
                      page: int, model_id: str = DEFAULT_VISION_MODEL,
                      use_cache: bool = True) -> dict:
    """用视觉模型校正模板某页的"标题/正文/配图位"。page 从 1 起。"""
    from services import pptx_render

    source = pathlib.Path(template_path)
    specs = analysis.get("specimens") or []
    spec = next((s for s in specs if s["index"] == page - 1), None)
    if spec is None:
        return {"ok": False, "error": f"模板没有第 {page} 页"}

    cache = _cache_path(source, page)
    regions: dict = {}
    error = ""
    image_size = (1280, 720)
    if use_cache and cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            regions = cached.get("regions") or {}
            image_size = tuple(cached.get("image_size") or image_size)
        except Exception:
            regions = {}
    if not regions:
        images = await asyncio.to_thread(pptx_render.render_pages, source, [page], 110)
        image = images.get(page)
        if not image:
            return {"ok": False, "error": pptx_render.available_reason()}
        try:
            from PIL import Image

            with Image.open(image) as img:
                image_size = img.size
        except Exception:
            pass
        regions, error = await _vision_call(user_id, pathlib.Path(image), model_id)
        if error or not regions:
            return {"ok": False, "error": error or "模型没有返回区域"}
        regions = normalize_boxes(regions, image_size[0], image_size[1])
        try:
            cache.write_text(json.dumps({"regions": regions, "image_size": list(image_size)},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    applied = _apply_regions(spec, regions, analysis.get("slide_width") or 13.333,
                             analysis.get("slide_height") or 7.5)
    return {
        "ok": True,
        "page": page,
        "model": model_id,
        "image_size": list(image_size),
        "regions": {k: regions.get(k) for k in ("title_boxes", "body_boxes", "photo_boxes", "note")},
        **applied,
    }
