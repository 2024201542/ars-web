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
import logging
import pathlib
from typing import Optional

logger = logging.getLogger(__name__)

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
CACHE_DIR = BACKEND_DIR / "data" / "ppt_vision"

VISION_MODELS = {
    "qwen-vl-max": "qwen",
    "qwen3-vl-plus": "qwen",
    "qwen-vl-plus": "qwen",
}
DEFAULT_VISION_MODEL = "qwen3-vl-plus"

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


PROMPT_VERSION = 4
SUMMARY_TIMEOUT = 180

PARSE_PROMPT = """这是一套 PPT 模板中的一页，图上用红框和 F 编号标出了每个文本框，蓝框和 P 编号标出了图片位。下面是每个框的位置和原文。
请判断这一页怎么用，只输出 JSON，不要解释：
{
  "role": "页面角色，取值：cover/toc/section/content/summary/end/qa/blank",
  "form": "内容形态，取值：bullets/numbered/cards/compare/timeline/process/quote/bignum/image_text/table/chart/text/none",
  "narrative_fit": ["这页适合讲的叙事角色，0 到 4 个，取值见下表"],
  "description": "一句话说明这页的版面和适合讲什么，不超过 60 字",
  "sample_heading": "这页模板原来的标题原文，没有就空",
  "repeat": 并列的格子有几组，没有就 0,
  "frames": [{"id": "F3", "slot": "格子名"}],
  "missing": [{"slot": "格子名", "box": [x, y, w, h]}],
  "usable": true,
  "unusable_reason": ""
}
格子名只能用：title、subtitle、lead（标题下的导语或承接句）、section_index、section_title、section_question、
item1.head、item1.body、item2.head……（并列格子按从左到右、从上到下编号）、stat1.value、stat1.label、quote、source、
left.head、left.body、right.head、right.body、caption、info1、info2、body、decor_keep（校名、页码、导航条，出片保留）、
decor_clear（示例英文、装饰口号、水印、「点击输入」占位，出片清空）。
每个 F 编号都要给一个格子名。只能使用框清单里出现过的 F 编号，不要自己编编号。清单里没有文本框时，frames 给空数组。
并列格子从左到右、从上到下编号，同一个 item 编号不要用两次。圆圈或药丸里单独的数字不是正文，标成 decor_keep。示例英文、装饰口号标成 decor_clear，不要标成 subtitle。
目录里「-01-」「-02-」这种序号标成 decor_keep，不要标成 title 或 itemN.head。序号旁边的章节名标成 itemN.head，序号下面的英文占位标成 decor_clear。
一页如果没有能写下章节名的框（没有 section_title，也没有单独的大标题），role 不能是 section，标成 content。
missing 只填图上看得到文字区域、但没有红框的地方，坐标是相对整页的 0 到 1。
整页是一张图片、没有可写字的地方，usable 填 false。
叙事角色取值：__NARRATIVE_ROLES__
"""


def friendly_vision_error(raw: str) -> str:
    text = raw or ""
    if "invalid_api_key" in text or "Incorrect API key" in text:
        return "通义千问的密钥不被阿里云接受。到设置里换成百炼的 Key 后再校正。"
    if "model_not_found" in text or "Model not exist" in text:
        return "看图模型在这个接口上不存在。当前账号可用的是 qwen3-vl-plus。"
    return text


def _fatal_vision_error(raw: str) -> bool:
    text = raw or ""
    return any(word in text for word in (
        "密钥", "API Key", "invalid_api_key", "Incorrect API key",
        "看图模型", "model_not_found", "Model not exist",
    ))


async def _vision_call(user_id: str, image_path: pathlib.Path, model_id: str,
                       prompt: str = PROMPT, max_tokens: int = 900) -> tuple[dict, str]:
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
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
        "max_tokens": max_tokens,
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


def _parse_cache_path(template_path: pathlib.Path, page: int) -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{_fingerprint(template_path)}_p{page}_parse_v{PROMPT_VERSION}.json"


def _norm_box(frame: dict, slide_w: float, slide_h: float) -> tuple[float, float, float, float]:
    sw = slide_w or 1
    sh = slide_h or 1
    return (
        float(frame.get("x") or 0) / sw,
        float(frame.get("y") or 0) / sh,
        float(frame.get("w") or 0) / sw,
        float(frame.get("h") or 0) / sh,
    )


def _frame_line(frame: dict, slide_w: float, slide_h: float) -> str:
    x, y, w, h = _norm_box(frame, slide_w, slide_h)
    try:
        size = int(frame.get("size") or 18)
    except (TypeError, ValueError):
        size = 18
    text = str(frame.get("text") or "").replace("\n", " ").replace("」", "")
    return f"F{frame.get('i')}｜位置 左{x:.2f} 上{y:.2f} 宽{w:.2f} 高{h:.2f}｜字号 {size}｜原文「{text}」"


def _label_font(image_width: int):
    from PIL import ImageFont

    size = max(8, int(image_width * 0.016))
    for name in ("arial.ttf", r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _draw_tag(draw, x: int, y: int, text: str, color: str, font) -> None:
    try:
        box = draw.textbbox((x, y), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
    except Exception:
        tw, th = 8 * len(text), 12
    draw.rectangle([x, y, x + tw + 4, y + th + 2], fill="white")
    draw.text((x + 2, y), text, fill=color, font=font)


def mark_frames(png_path, frames, slide_w, slide_h, images=None,
                template_path=None, page: int | None = None) -> pathlib.Path:
    """在渲染图上给文本框画红框、给图片位画蓝框。输出尺寸与原图一致。"""
    from PIL import Image, ImageDraw

    source = pathlib.Path(png_path)
    with Image.open(source) as raw:
        img = raw.convert("RGB")
    width, height = img.size
    draw = ImageDraw.Draw(img)
    font = _label_font(width)
    for frame in frames or []:
        x, y, w, h = _norm_box(frame, slide_w, slide_h)
        left, top = int(round(x * width)), int(round(y * height))
        right = int(round((x + w) * width))
        bottom = int(round((y + h) * height))
        if right <= left:
            right = left + 2
        if bottom <= top:
            bottom = top + 2
        draw.rectangle([left, top, right, bottom], outline="red", width=2)
        _draw_tag(draw, left, top, f"F{frame.get('i')}", "red", font)
    for slot in images or []:
        x, y, w, h = _norm_box(slot, slide_w, slide_h)
        left, top = int(round(x * width)), int(round(y * height))
        right = int(round((x + w) * width))
        bottom = int(round((y + h) * height))
        draw.rectangle([left, top, right, bottom], outline="blue", width=2)
        _draw_tag(draw, left, top, f"P{slot.get('i')}", "blue", font)

    if page is None:
        name = source.name
        page = 1
        marker = "page-"
        if marker in name:
            digits = name.split(marker, 1)[1].split(".", 1)[0]
            if digits.isdigit():
                page = int(digits)
    finger = _fingerprint(pathlib.Path(template_path) if template_path else source)
    dest_dir = CACHE_DIR / "marked"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{finger}_p{page}.png"
    img.save(dest)
    return dest


def _parse_prompt(lines: list[str]) -> str:
    from services.ppt import ppt_roles

    roles = "、".join(f"{key} {label}" for key, label in ppt_roles.NARRATIVE_ROLES.items())
    body = PARSE_PROMPT.replace("__NARRATIVE_ROLES__", roles)
    listing = "\n".join(lines) if lines else "（这一页没有文本框）"
    return body + "\n\n框清单：\n" + listing


async def parse_page(user_id: str, analysis: dict, template_path: str | pathlib.Path,
                     page: int, model: str = DEFAULT_VISION_MODEL,
                     force: bool = False) -> dict:
    """看图判断模板的一页。命中缓存且 force 不为真时不调模型。"""
    from services.ppt import pptx_render

    source = pathlib.Path(template_path)
    spec = next((item for item in (analysis or {}).get("specimens") or []
                 if item.get("index") == page - 1), None)
    cache = _parse_cache_path(source, page)
    if not force and cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(cached.get("result"), dict):
                return {"ok": True, "page": page, "result": cached["result"], "cached": True}
        except Exception:
            pass
    if spec is None:
        return {"ok": False, "error": f"模板没有第 {page} 页"}

    images = await asyncio.to_thread(pptx_render.render_pages, source, [page], 110)
    image = images.get(page)
    if not image:
        return {"ok": False, "error": pptx_render.available_reason() or "这一页没有渲染出图片"}
    slide_w = (analysis or {}).get("slide_width") or 13.333
    slide_h = (analysis or {}).get("slide_height") or 7.5
    marked = await asyncio.to_thread(
        mark_frames, image, spec.get("frames") or [], slide_w, slide_h,
        spec.get("images") or [], source, page,
    )
    lines = [_frame_line(frame, slide_w, slide_h) for frame in (spec.get("frames") or [])]
    for index, slot in enumerate(spec.get("images") or []):
        x, y, w, h = _norm_box(slot, slide_w, slide_h)
        lines.append(
            f"P{slot.get('i', index)}｜位置 左{x:.2f} 上{y:.2f} 宽{w:.2f} 高{h:.2f}｜图片位"
        )
    payload, error = await _vision_call(
        user_id, marked, model or DEFAULT_VISION_MODEL,
        prompt=_parse_prompt(lines), max_tokens=1600,
    )
    if error or not payload:
        return {"ok": False, "error": error or "模型没有返回"}
    try:
        cache.write_text(json.dumps({"result": payload, "model": model or DEFAULT_VISION_MODEL},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {"ok": True, "page": page, "result": payload, "cached": False}


async def refine_page(user_id: str, analysis: dict, template_path: str | pathlib.Path,
                      page: int, model_id: str = DEFAULT_VISION_MODEL,
                      use_cache: bool = True) -> dict:
    """旧的单页校正。内部改走逐页解析，仍把格子写回这一页的 title_i / bodies_i。"""
    from services.ppt import ppt_pages

    parsed = await parse_page(user_id, analysis, template_path, page, model_id, force=not use_cache)
    if not parsed.get("ok"):
        return {"ok": False, "page": page, "error": parsed.get("error") or "解析失败"}
    pages = ppt_pages.empty_pages({}, analysis)
    ppt_pages.apply_page_parse(pages, analysis, page, parsed.get("result") or {})
    return {"ok": True, "page": page, "model": model_id, "changed": True, "parse": parsed.get("result")}


def _guess_page_back(template: dict, analysis: dict, page: int, pages_data: dict) -> None:
    from services.ppt import ppt_pages

    fresh = ppt_pages.empty_pages(template, analysis)
    guessed = next((item for item in fresh.get("pages") or [] if item.get("page") == page), None)
    if guessed is None:
        return
    pages = pages_data.setdefault("pages", [])
    current = next((item for item in pages if item.get("page") == page), None)
    if current and current.get("user_edited"):
        merged = ppt_pages.merge_user_edits({"pages": [dict(current)]}, {"pages": [guessed]})
        guessed = merged["pages"][0]
    if current is None:
        pages.append(guessed)
    else:
        current.clear()
        current.update(guessed)


async def run_parse(user_id: str, template: dict, model: str, pages: list[int],
                    force: bool, progress: dict, text_model: str = "") -> dict:
    """逐页解析。单页失败重试 1 次；密钥或模型不存在则整任务停下。全部试完后做一次整份归纳。"""
    from services.ppt import ppt_pages, ppt_template

    progress = progress if isinstance(progress, dict) else {}
    template = template or {}
    if template.get("source") == "builtin":
        progress["status"] = "failed"
        progress["errors"] = [{"page": 0, "error": "内置模板不能解析"}]
        return progress
    analysis = template
    specs = analysis.get("specimens") or []
    page_list = [int(p) for p in (pages or []) if 1 <= int(p) <= max(len(specs), 0)]
    if not page_list:
        page_list = [int(item.get("index") or 0) + 1 for item in specs]
    progress["status"] = "running"
    progress["total"] = len(page_list)
    progress["done"] = 0
    progress["errors"] = []
    progress["current_page"] = page_list[0] if page_list else 0

    pages_data = ppt_pages.load_pages(template) or ppt_pages.empty_pages(template, analysis)
    source = template.get("file_path") or ""
    if source and not pages_data.get("template_sha1") and pathlib.Path(source).is_file():
        try:
            pages_data["template_sha1"] = ppt_pages.template_sha1(source)
        except Exception:
            pass
    pages_data["models"] = {
        "vision": model or DEFAULT_VISION_MODEL,
        "text": text_model or "",
    }
    pages_data["parse"] = {
        "status": "running",
        "done": 0,
        "total": len(page_list),
        "current_page": progress["current_page"],
        "errors": [],
    }
    _persist_parse(template, pages_data, analysis, save_analysis=False)

    for index, page in enumerate(page_list):
        progress["current_page"] = page
        pages_data["parse"]["current_page"] = page
        pages_data["parse"]["status"] = "running"
        _persist_parse(template, pages_data, analysis, save_analysis=False)
        outcome = await _parse_with_retry(user_id, analysis, source, page, model, force)
        if outcome.get("fatal"):
            err = {"page": page, "error": outcome.get("error") or "解析失败"}
            progress["status"] = "failed"
            progress["errors"].append(err)
            pages_data["parse"]["status"] = "failed"
            pages_data["parse"]["errors"] = list(progress["errors"])
            _persist_parse(template, pages_data, analysis, save_analysis=False)
            return pages_data
        if not outcome.get("ok"):
            err = {"page": page, "error": outcome.get("error") or "解析失败"}
            progress["errors"].append(err)
            _guess_page_back(template, analysis, page, pages_data)
            progress["done"] = index + 1
            pages_data["parse"]["done"] = progress["done"]
            pages_data["parse"]["errors"] = list(progress["errors"])
            _persist_parse(template, pages_data, analysis, save_analysis=False)
            continue
        ppt_pages.apply_page_parse(pages_data, analysis, page, outcome.get("result") or {})
        progress["done"] = index + 1
        pages_data["parse"]["done"] = progress["done"]
        pages_data["parse"]["errors"] = list(progress["errors"])
        _persist_parse(template, pages_data, analysis, save_analysis=True)

    progress["status"] = "partial" if progress["errors"] else "done"
    pages_data["parse"]["status"] = progress["status"]
    pages_data["parsed_at"] = time_now()
    await _finish_deck(user_id, pages_data, analysis, text_model)
    _persist_parse(template, pages_data, analysis, save_analysis=True)
    return pages_data


async def _finish_deck(user_id: str, pages_data: dict, analysis: dict, text_model: str) -> None:
    """逐页都试过之后归纳整份。归纳失败或超过时限，不推翻已经写好的逐页结果。"""
    try:
        from services.ppt import ppt_deck_parse, ppt_pages

        facts = ppt_deck_parse.deck_facts(pages_data, analysis)
        try:
            story = await asyncio.wait_for(
                ppt_deck_parse.deck_story(pages_data, text_model, user_id),
                timeout=SUMMARY_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("整份归纳超过 %s 秒，简介留空", SUMMARY_TIMEOUT)
            story = {
                "summary": "",
                "deck_type_hint": "",
                "template_storyline": ppt_deck_parse.fallback_storyline(pages_data),
            }
        ppt_pages.write_deck(pages_data, facts, story)
    except Exception as exc:
        logger.warning("整份归纳没有写上：%s", exc)


def time_now() -> str:
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _persist_parse(template: dict, pages_data: dict, analysis: dict, save_analysis: bool) -> None:
    from services.ppt import ppt_pages, ppt_template

    if not template.get("file_path"):
        return
    ppt_pages.save_pages(template, pages_data)
    if not save_analysis:
        return
    path = pathlib.Path(template["file_path"]).with_suffix(".analysis.json")
    clean = dict(analysis)
    clean.pop("file_path", None)
    ppt_template.save_analysis(path, clean)


async def _parse_with_retry(user_id: str, analysis: dict, template_path: str,
                            page: int, model: str, force: bool) -> dict:
    last = {"ok": False, "error": "没有调用"}
    for _attempt in range(2):
        try:
            last = await parse_page(user_id, analysis, template_path, page, model, force=force)
        except Exception as exc:
            last = {"ok": False, "error": friendly_vision_error(f"{type(exc).__name__}: {exc}")}
        else:
            if not last.get("ok"):
                last = dict(last)
                last["error"] = friendly_vision_error(str(last.get("error") or "解析失败"))[:160]
        if last.get("ok"):
            return last
        if _fatal_vision_error(str(last.get("error") or "")):
            last = dict(last)
            last["fatal"] = True
            last["error"] = str(last.get("error") or "")[:160]
            return last
    last = dict(last)
    last["error"] = str(last.get("error") or "解析失败")[:160]
    return last
