"""模板解析：把一份 .pptx 拆成"版式样本"（specimen）并打标签。

产出的 analysis.json 是"拼接引擎"（pptx_splice）与"模板库界面"的共同契约：

    {
      "id": "builtin-academic-red", "name": "...", "source": "builtin",
      "slide_width": 13.333, "slide_height": 7.5,
      "theme": {"accent": "9E1B32", "fonts": ["微软雅黑"], "text_color": "262626"},
      "specimens": [
        {"index": 0, "tag": "cover",
         "frames": [{"i":0,"kind":"title","x":0.9,"y":1.6,"w":11.5,"h":1.6,
                     "size":30,"chars":18,"bullets":0,"text":"示例标题"}],
         "title_i": 0, "body_i": 1, "body2_i": null,
         "capacity": 0, "has_image": false, "lines": 1},
        ...
      ],
      "stats": {"slides": 6, "tags": {"cover": 1, "bullets-3": 2, ...}}
    }

坐标一律换算成英寸；`frames[].i` 是"该页第几个文本框"的序号——克隆页里顺序一致，
所以拼接时仍按这个序号去找同一个文本框。
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Optional

from pptx import Presentation
from pptx.util import Emu

# 版式标签
TAG_COVER = "cover"
TAG_TOC = "toc"
TAG_SECTION = "section"
TAG_TWO_COL = "two-col"
TAG_IMAGE_TEXT = "image+text"
TAG_QUOTE = "quote"
TAG_BIG_NUMBER = "big-number"
TAG_END = "end"
TAG_BULLETS = "bullets"          # bullets-1 … bullets-7
TAG_CARDS = "cards-3"            # 三张并列卡片
TAG_TIMELINE = "timeline"        # 时间线（4–6 个节点，横向）
TAG_CONTENT = "content"          # 认不出具体形状的普通正文页（拼接时的通用兜底）

TOC_WORDS = ("目录", "框架", "提纲", "内容提要", "汇报框架")
END_WORDS = ("谢谢", "感謝", "感谢", "致谢", "敬请", "谢谢聆听", "thank", "thanks")
# 目录页判断用"去掉编号标点后的短标题"，避免"…理论框架"这种正文章节被误判
TOC_EXACT = ("目录", "汇报框架", "框架", "提纲", "内容提要", "目录与框架", "汇报提纲")

EMU_PER_INCH = 914400

# 解析结果的版本号：新增字段（如"图片位"）时 +1。
# 读取时会检查，旧版本自动重新解析——避免"老模板缺新字段"导致功能悄悄失效（踩过一次：
# 图片位功能上了以后，模板库里已有的 analysis.json 没有 image_i，配图一直不生效）。
ANALYSIS_VERSION = 3


def iter_text_shapes(container) -> list:
    """先取顶层文本框，再补组合内部的。

    顶层序号保持不变，旧的 title_i 仍然指向同一个框。组合里的框排在后面。
    子形状的坐标用 python-pptx 给出的值，不再叠加组合原点。
    """
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    top: list = []
    nested: list = []

    def walk(shape) -> None:
        try:
            grouped = shape.shape_type == MSO_SHAPE_TYPE.GROUP
        except Exception:
            grouped = False
        if grouped:
            for child in shape.shapes:
                walk(child)
            return
        if is_text_candidate(shape):
            nested.append(shape)

    for shape in container.shapes:
        try:
            grouped = shape.shape_type == MSO_SHAPE_TYPE.GROUP
        except Exception:
            grouped = False
        if grouped:
            walk(shape)
        elif is_text_candidate(shape):
            top.append(shape)
    return top + nested


def is_text_candidate(shape) -> bool:
    """是不是"该被当作文本框"的形状。

    装饰用的矩形/线条也是 has_text_frame=True 但里面没字，必须排除——
    否则解析出来的"第 0 个文本框"是个空矩形，填字就会填错地方。
    占位符即使暂时为空也保留（用户模板里常见空的内容占位符）。
    解析与拼接必须用同一条规则，索引才对得上。
    """
    if not shape.has_text_frame:
        return False
    try:
        if shape.is_placeholder:
            return True
    except Exception:
        pass
    return bool(shape.text_frame.text.strip())


def _normalize_title(text: str) -> str:
    raw = re.sub(r"[\s　、，。：:·\-—()（）]", "", str(text or ""))
    raw = re.sub(r"^[一二三四五六七八九十0-9]+[.、]?", "", raw)
    return raw


def is_toc_title(text: str) -> bool:
    norm = _normalize_title(text)
    if not norm or len(norm) > 8:
        return False
    return any(norm == w or norm == _normalize_title(w) for w in TOC_EXACT)


def _inches(value) -> float:
    try:
        return round(int(value) / EMU_PER_INCH, 2)
    except Exception:
        return 0.0


def _font_size(run) -> Optional[int]:
    try:
        if run.font.size is not None:
            return int(run.font.size.pt)
    except Exception:
        pass
    return None


def _frame_info(shape, order: int) -> Optional[dict]:
    if not is_text_candidate(shape):
        return None
    tf = shape.text_frame
    paragraphs = [p for p in tf.paragraphs]
    texts = ["".join(r.text for r in p.runs).strip() or (p.text or "").strip() for p in paragraphs]
    non_empty = [t for t in texts if t]
    first_run = None
    for p in paragraphs:
        for r in p.runs:
            if (r.text or "").strip():
                first_run = r
                break
        if first_run is not None:
            break
    is_title = False
    try:
        is_title = shape.is_placeholder and shape.placeholder_format.idx == 0
    except Exception:
        is_title = False
    return {
        "i": order,
        "kind": "title" if is_title else "body",
        "x": _inches(shape.left), "y": _inches(shape.top),
        "w": _inches(shape.width), "h": _inches(shape.height),
        "size": _font_size(first_run) if first_run is not None else None,
        "chars": sum(len(t) for t in non_empty),
        "bullets": len([t for t in non_empty]),
        "lines": len(non_empty),
        "text": (non_empty[0] if non_empty else "")[:40],
        "shape_id": getattr(shape, "shape_id", None),
    }


def _blips(slide) -> list[dict]:
    """按 XML 顺序找出这一页**所有**图片引用。

    为什么不用 python-pptx 的 shape_type：设计模板里的照片常常
    "包在组合里""做成矩形的图片填充""当页面底图"，这三种都不是顶层 PICTURE 形状，
    用 shape_type 找一张都找不到（实测人大模板 35 页全是 0 个图片位）。
    直接扫 `a:blip` 就能全部覆盖，而且顺序稳定，替换时按同一个序号找回来。

    kind: picture（图片形状）/ shape-fill（形状的图片填充）/ background（页面底图）
    """
    from pptx.oxml.ns import qn

    try:
        prs = slide.part.package.presentation_part.presentation
        slide_w = prs.slide_width or 1
        slide_h = prs.slide_height or 1
    except Exception:
        slide_w = slide_h = 1
    total = slide_w * slide_h

    out: list[dict] = []
    order = 0
    for blip in slide._element.iter(qn("a:blip")):
        if not blip.get(qn("r:embed")):
            continue
        node = blip.getparent()
        owner = None
        kind = "picture"
        while node is not None:
            if node.tag == qn("p:pic"):
                owner, kind = node, "picture"
                break
            if node.tag == qn("p:sp"):
                owner, kind = node, "shape-fill"
                break
            if node.tag == qn("p:bg"):
                kind = "background"
                break
            node = node.getparent()

        ratio, width_emu, height_emu = None, 0, 0
        if kind == "background":
            ratio, width_emu, height_emu = (slide_w / slide_h if slide_h else 1.0), slide_w, slide_h
        elif owner is not None:
            sp_pr = owner.find(qn("p:spPr"))
            xfrm = sp_pr.find(qn("a:xfrm")) if sp_pr is not None else None
            ext = xfrm.find(qn("a:ext")) if xfrm is not None else None
            if ext is not None:
                try:
                    width_emu = int(ext.get("cx") or 0)
                    height_emu = int(ext.get("cy") or 0)
                except Exception:
                    width_emu = height_emu = 0
            if width_emu and height_emu:
                ratio = width_emu / height_emu
        area = (width_emu * height_emu / total) if (total and width_emu and height_emu) else 0.0

        out.append({
            "i": order,
            "kind": kind,
            "w": _inches(width_emu),
            "h": _inches(height_emu),
            "ratio": round(ratio, 3) if ratio else 1.0,
            "area": round(area, 3),
            "full_bleed": area > 0.78 or kind == "background",
        })
        order += 1
    return out


def _usable_slot(slot: dict) -> bool:
    """这个图片位能不能放"用户的配图"。

    排除两类：
    - 满幅底图（面积 >78%）：那是背景，换掉会把整页设计毁了；
    - 装饰小图 / 长条（面积 <6% 或 极端长宽比）：学校 logo、色带、页码装饰。
    """
    if slot.get("full_bleed") or slot.get("kind") == "background":
        return False
    area = slot.get("area") or 0
    ratio = slot.get("ratio") or 1.0
    if area < 0.06 or area > 0.78:
        return False
    return 0.3 <= ratio <= 3.5


def _image_slots(slide) -> list[dict]:
    """这一页的"图片位"（用 _blips 的结果，含组合内图片/图片填充/底图）。"""
    return _blips(slide)


def _has_image(slide) -> bool:
    return bool(_blips(slide))


def _image_stats(slide) -> dict:
    """图片面积情况（决定这页算不算"图文页"）。

    content：面积在 12%–78% 之间的图（像一张配图/照片）；
    bleed：面积 > 78%（或页面底图），那是背景，不算内容图。
    """
    blips = _blips(slide)
    if not blips:
        return {"max_area": 0.0, "bleed": False, "content": False}
    best = max(b["area"] for b in blips)
    bleed = any(b["full_bleed"] for b in blips)
    content = any(0.12 <= b["area"] <= 0.78 and not b["full_bleed"] for b in blips)
    return {"max_area": round(best, 3), "bleed": bleed, "content": content}


def _meaningful_title(text: str) -> bool:
    """这条文字像不像"标题"（排除 01 / 2025/5/23 / ? 这类装饰文字）。"""
    raw = (text or "").strip()
    if len(raw) < 3:
        return False
    if re.fullmatch(r"[\d\W_]+", raw):
        return False
    if re.fullmatch(r"\d{4}\s*[/\-年.]\s*\d{1,2}\s*[/\-月.]?\s*\d{0,2}\s*日?", raw):
        return False
    # 校名/机构名/栏目名这类"品牌文字"不该当标题（校徽上的"中国人民大学"就踩过这个坑）
    if len(raw) <= 12 and re.search(r"(大学|学院|学校|校徽|校训|logo|版权所有|汇报人|答辩人|指导教师)", raw):
        return False
    return True


def _side_by_side(a: dict, b: dict) -> bool:
    """两个文本框是不是左右并排（水平方向几乎不重叠）。"""
    return (a["x"] + a["w"] <= b["x"] + 0.25) or (b["x"] + b["w"] <= a["x"] + 0.25)


def _vertical_list(bodies: list[dict]) -> list[dict]:
    """把"左对齐、从上到下排列、每框一两行"的文本框认成一份列表。

    中文模板很常见：5 条要点 = 5 个独立文本框（不是一个大文本框里的 5 段），
    所以"容量"不能只看第一个框里有几段，而要看这种竖排的一串框。
    """
    if len(bodies) < 2:
        return []
    first = bodies[0]
    group = [first]
    for frame in bodies[1:]:
        prev = group[-1]
        same_x = abs((frame["x"] or 0) - (first["x"] or 0)) <= 0.35
        below = (frame["y"] or 0) >= (prev["y"] or 0) + 0.15
        if same_x and below and frame["lines"] <= 2 and prev["lines"] <= 2:
            group.append(frame)
        else:
            break
    return group if len(group) >= 2 else []


def _classify(index: int, total: int, frames: list[dict], has_image: bool,
              slide_height: float = 7.5, image_stats: dict | None = None) -> tuple[str, int, Optional[int], Optional[int]]:
    """返回 (tag, title_i, body_i, body2_i)。

    判断顺序很重要：
    1. 标题先认（占位符 → 上部最靠上的"像标题"的大字，跳过 01 / 日期 / 符号）；
    2. 大数字页（超大字号短文本框）在几何上很像两栏，所以先看字号；
    3. 竖排一串文本框 = 列表页（中文模板的常见做法），容量按框数算；
    4. 再看左右并排（两栏 / 三卡片 / 时间线）。
    """
    titles = [f for f in frames if f["kind"] == "title"]
    if not titles and frames:
        upper_limit = slide_height * (0.55 if index == 0 else 0.26)
        upper = [f for f in frames if (f["y"] or 0) <= upper_limit and (f["size"] or 0) >= 16]
        good = [f for f in upper if _meaningful_title(f["text"])]
        if not good:
            # 设计模板的标题常常排在页面中部（大字号），上部只有装饰数字/日期
            mid = [f for f in frames
                   if (f["y"] or 0) <= slide_height * 0.62
                   and (f["size"] or 0) >= 24
                   and _meaningful_title(f["text"])]
            good = mid
        if not good and len(frames) <= 2:
            good = [f for f in frames if (f["size"] or 0) >= 20]
        if good:
            top = sorted(good, key=lambda f: ((f["y"] or 0), -(f["size"] or 0)))[0]
            top["kind"] = "title"
            titles = [top]

    bodies = [f for f in frames if f["kind"] != "title"]
    title_i = titles[0]["i"] if titles else (frames[0]["i"] if frames else None)
    body_i = bodies[0]["i"] if bodies else None
    body2_i = bodies[1]["i"] if len(bodies) > 1 else None
    title_text = (titles[0]["text"] if titles else "") or ""

    def has_word(words) -> bool:
        low = title_text.lower()
        return any(w.lower() in low for w in words)

    if index == total - 1 and total > 1 or has_word(END_WORDS):
        return TAG_END, title_i, body_i, body2_i
    if index == 0:
        return TAG_COVER, title_i, body_i, body2_i
    if is_toc_title(title_text):
        return TAG_TOC, title_i, body_i, body2_i
    stats = image_stats or {}
    if stats.get("content") and bodies:
        return TAG_IMAGE_TEXT, title_i, body_i, body2_i

    # 竖排一串文本框 → 列表页，容量按框数算
    vlist = _vertical_list(bodies)
    if len(vlist) >= 2:
        n = max(2, min(7, len(vlist)))
        return f"{TAG_BULLETS}-{n}", title_i, vlist[0]["i"], (vlist[1]["i"] if len(vlist) > 1 else None)

    # 大数字页：明显更大的短文本框，而且里面得真有数字/单位（否则那是装饰文字）
    for pos, frame in enumerate(bodies):
        size = frame.get("size") or 0
        text = frame.get("text") or ""
        if size >= 36 and 0 < frame["chars"] <= 16 and re.search(r"\d|%|年|万|亿|倍|个|项|篇", text):
            caption = bodies[1]["i"] if len(bodies) > 1 and bodies[1]["i"] != frame["i"] else None
            return TAG_BIG_NUMBER, title_i, frame["i"], caption

    if len(bodies) >= 3 and all(b["chars"] > 0 for b in bodies[:3]) and _side_by_side(bodies[0], bodies[1]) and _side_by_side(bodies[1], bodies[2]):
        # 并列的几块里有两块带年份 → 认定是时间线，而不是普通三卡片
        year_like = sum(1 for b in bodies[:4] if re.search(r"(19|20)\d{2}", b.get("text") or ""))
        if year_like >= 2:
            return TAG_TIMELINE, title_i, body_i, body2_i
        return TAG_CARDS, title_i, body_i, body2_i
    if len(bodies) >= 2 and all(b["chars"] > 0 for b in bodies[:2]) and _side_by_side(bodies[0], bodies[1]):
        return TAG_TWO_COL, title_i, body_i, body2_i
    if not bodies or bodies[0]["chars"] == 0:
        return TAG_SECTION, title_i, body_i, body2_i

    body = bodies[0]
    n = max(1, min(7, body["bullets"]))
    if body["bullets"] <= 1:
        text = body["text"]
        if len(text) >= 28:
            return TAG_QUOTE, title_i, body_i, body2_i
        # 一个字少的孤立文本框：当通用正文页更好用（拼接时优先被挑中）
        return TAG_CONTENT, title_i, body_i, body2_i
    return f"{TAG_BULLETS}-{n}", title_i, body_i, body2_i


def analyze_pptx(path: str | pathlib.Path, *, tid: str = "", name: str = "", source: str = "user") -> dict:
    """解析一份 pptx，返回 analysis dict（可直接存成 json）。"""
    target = pathlib.Path(path)
    prs = Presentation(str(target))

    fonts: list[str] = []
    accent = ""
    text_color = ""
    specimens: list[dict] = []
    total = len(prs.slides)

    for index, slide in enumerate(prs.slides):
        frames: list[dict] = []
        order = 0
        for shape in iter_text_shapes(slide):
            info = _frame_info(shape, order)
            if info is not None:
                frames.append(info)
                order += 1
                # 顺手收集字体/颜色线索（主题识别用）
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        try:
                            if run.font.name and run.font.name not in fonts:
                                fonts.append(run.font.name)
                            if run.font.color and run.font.color.rgb:
                                if not accent:
                                    accent = str(run.font.color.rgb)
                                if not text_color:
                                    text_color = str(run.font.color.rgb)
                        except Exception:
                            continue
        image_stats = _image_stats(slide)
        tag, title_i, body_i, body2_i = _classify(
            index, total, frames, _has_image(slide),
            slide_height=prs.slide_height / EMU_PER_INCH,
            image_stats=image_stats,
        )
        bodies_i = [f["i"] for f in frames if f["i"] != title_i]
        body_frame = next((f for f in frames if f["i"] == body_i), None)
        capacity = (body_frame["bullets"] if body_frame else 0)
        if tag.startswith(TAG_BULLETS):
            # 列表页把竖排的那一串框按顺序全记下来，拼接时一条要点填一个框
            vlist = _vertical_list([f for f in frames if f["i"] != title_i])
            if len(vlist) >= 2:
                bodies_i = [f["i"] for f in vlist]
                capacity = len(vlist)
            else:
                # 设计模板里"第一个正文框"常常是装饰小字；改成挑**面积最大**的那个当正文区
                candidates = [f for f in frames
                              if f["i"] != title_i and f["i"] != body_i and f["chars"] >= 2
                              and (f["w"] or 0) * (f["h"] or 0) > 0]
                if body_frame is not None:
                    candidates.append(body_frame)
                if candidates:
                    best = max(candidates, key=lambda f: (f["w"] or 0) * (f["h"] or 0))
                    if best["i"] != body_i:
                        body_i = best["i"]
                        bodies_i = [best["i"]]
                        capacity = best["bullets"]
        image_slots = _image_slots(slide)
        for slot in image_slots:
            slot["usable"] = _usable_slot(slot)
        # 整页图片化的模板页：设计稿被导成一张大图，里面的字**改不了**。
        # 这种页不能拿来当"文字版式样本"，否则成品里会留着图上的"添加标题内容"。
        full_bleed_area = max([s["area"] for s in image_slots] + [0.0])
        image_only = full_bleed_area >= 0.9 and len(frames) <= 4
        # 主图位：只认"能放配图"的位（不是底图、不是 logo），取面积最大的
        usable = [s for s in image_slots if s["usable"]]
        main_slot = max(usable, key=lambda s: s["area"]) if usable else None
        specimens.append({
            "index": index,
            "tag": tag,
            "frames": frames,
            "title_i": title_i,
            "body_i": body_i,
            "body2_i": body2_i,
            "bodies_i": bodies_i,
            "capacity": capacity,
            "has_image": bool(image_slots),
            "images": image_slots,
            "image_i": main_slot["i"] if main_slot else None,
            "image_ratio": main_slot["ratio"] if main_slot else None,
            "image_usable": main_slot is not None,
            "image_only": image_only,
            "capacity_chars": _text_capacity({"frames": frames, "title_i": title_i})[0],
            "fragmented": _text_capacity({"frames": frames, "title_i": title_i})[1],
            "vector_shapes": _vector_shapes(slide),
            "lines": (body_frame["lines"] if body_frame else 0),
        })

    tags: dict[str, int] = {}
    for spec in specimens:
        tags[spec["tag"]] = tags.get(spec["tag"], 0) + 1

    return {
        "id": tid or target.stem,
        "name": name or target.stem,
        "version": ANALYSIS_VERSION,
        "source": source,
        "file": target.name,
        "slide_width": round(prs.slide_width / EMU_PER_INCH, 3),
        "slide_height": round(prs.slide_height / EMU_PER_INCH, 3),
        "theme": {"accent": accent or "", "text_color": text_color or "", "fonts": fonts[:4]},
        "specimens": specimens,
        "manual_roles": suggest_roles(specimens),
        "stats": {"slides": total, "tags": tags},
    }


def save_analysis(path: str | pathlib.Path, analysis: dict) -> None:
    pathlib.Path(path).write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_analysis(path: str | pathlib.Path) -> Optional[dict]:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


ROLE_KEYS = ("cover", "toc", "section", "content", "two-col", "cards-3", "big-number", "quote", "end")


def suggest_roles(specimens: list[dict]) -> dict:
    """给一份模板猜一套"版式角色 → 第几页"的映射（1 起）。

    设计型模板每页构图都不一样，纯自动分类难免有噪声；
    所以除了分类结果，再给出一套"角色映射"，用户可以覆盖它。
    生成时优先按角色映射取页，取不到才回退到按标签挑。
    """
    roles: dict[str, int] = {}
    if not specimens:
        return roles
    roles["cover"] = specimens[0]["index"] + 1
    roles["end"] = specimens[-1]["index"] + 1
    for spec in specimens[1:-1]:
        if spec["tag"] == TAG_TOC and "toc" not in roles:
            roles["toc"] = spec["index"] + 1
        elif spec["tag"] == TAG_SECTION and "section" not in roles:
            roles["section"] = spec["index"] + 1
        elif spec["tag"] == TAG_TWO_COL and "two-col" not in roles:
            roles["two-col"] = spec["index"] + 1
        elif spec["tag"] == TAG_CARDS and "cards-3" not in roles:
            roles["cards-3"] = spec["index"] + 1
        elif spec["tag"] == TAG_BIG_NUMBER and "big-number" not in roles:
            roles["big-number"] = spec["index"] + 1
        elif spec["tag"] == TAG_QUOTE and "quote" not in roles:
            roles["quote"] = spec["index"] + 1

    # 内容页：优先"正文框最多"的中间页（信息容量大，填出来最像正式页）
    middle = [s for s in specimens[1:-1]
              if s["tag"] not in (TAG_TOC, TAG_SECTION, TAG_COVER, TAG_END)]
    if not middle:
        middle = specimens[1:-1]
    if middle:
        def score(spec: dict) -> tuple:
            body_count = len([f for f in spec["frames"] if f["i"] != spec["title_i"]])
            listed = 1 if spec.get("bodies_i") and len(spec["bodies_i"]) >= 2 else 0
            return (listed, body_count, spec.get("capacity") or 0)
        best = max(middle, key=score)
        roles["content"] = best["index"] + 1
    return roles


def apply_manual_roles(analysis: dict, roles: dict) -> dict:
    """把用户的角色映射写回 analysis（并顺手保证 cover/end 已指定）。"""
    clean: dict[str, int] = {}
    for key, value in (roles or {}).items():
        if key not in ROLE_KEYS:
            continue
        try:
            page = int(value)
        except Exception:
            continue
        if page > 0:
            clean[key] = page
    analysis["manual_roles"] = clean
    return analysis


def _role_page(analysis: dict, want_tag: str) -> Optional[dict]:
    """按角色映射找页；want_tag 是 bullets-N 时对应 content 角色。"""
    roles = analysis.get("manual_roles") or {}
    if not roles:
        return None
    keys = [want_tag]
    if want_tag.startswith(TAG_BULLETS):
        keys.append("content")
    if want_tag == TAG_CARDS:
        keys.append("cards")
    for key in keys:
        page = roles.get(key)
        if not page:
            continue
        spec = next((s for s in (analysis.get("specimens") or []) if s["index"] == int(page) - 1), None)
        if spec and not spec.get("image_only"):
            return spec
        if spec:
            # 角色映射指到了"整页图片化"的页（字改不了）→ 放弃它，回退到按标签挑
            continue
    return None


def _capacity_chars(frame: dict) -> int:
    """估算一个文本框能装多少个字（按它的尺寸和字号）。

    中文按"一个字约等于字号宽度"估：每行字数 = 框宽(in) / (字号pt/72)，
    行数 = 框高(in) / (字号pt/72 * 1.45)。字号缺失时按 16pt 估。
    """
    width = frame.get("w") or 0
    height = frame.get("h") or 0
    size = frame.get("size") or 16
    if width <= 0 or height <= 0 or size <= 0:
        return 0
    char_w = size / 72.0
    per_line = max(1, int(width / char_w))
    lines = max(1, int(height / (char_w * 1.45)))
    return per_line * lines


def _vector_shapes(slide) -> int:
    """这一页有多少"矢量装饰形状"（圆/箭头/连接线/任意多边形）。

    这是区分"图示页"和"文字页"最可靠的信号：
    五角星、六边形、流程箭头这类页面有一堆形状，文字框只是贴在形状上的小标签，
    把成段的要点灌进去必然挤成一团（实测目录页两次都栽在这类页上）。
    """
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    count = 0
    try:
        for shape in slide.shapes:
            try:
                if shape.shape_type in (MSO_SHAPE_TYPE.AUTO_SHAPE, MSO_SHAPE_TYPE.FREEFORM,
                                        MSO_SHAPE_TYPE.LINE, MSO_SHAPE_TYPE.TEXT_BOX):
                    if shape.shape_type != MSO_SHAPE_TYPE.TEXT_BOX:
                        count += 1
            except Exception:
                continue
    except Exception:
        return 0
    return count


def _text_capacity(spec: dict) -> tuple[int, int]:
    """这一页正文区能装多少字，以及有多少"碎片小框"（图示页的特征）。

    这是为了治"把长要点塞进装饰卡片页、字挤成一团"的问题：
    图示页的正文框又小又碎，容量分很低，挑样本时就会被排到后面。
    """
    total = 0
    fragmented = 0
    for frame in spec.get("frames") or []:
        if frame["i"] == spec.get("title_i"):
            continue
        cap = _capacity_chars(frame)
        total += cap
        if (frame.get("size") or 16) < 13 or (frame.get("w") or 0) * (frame.get("h") or 0) < 0.35:
            fragmented += 1
    return total, fragmented


def pick_specimen(analysis: dict, want_tag: str, needed_chars: int = 0) -> Optional[dict]:
    """按想要的标签挑样本页：用户角色映射 → 精确标签 → 容量够用的 → 通用正文页。

    `needed_chars` 给了就优先挑"装得下这次内容"的页，并避开碎片小框多的图示页。
    """
    specs = analysis.get("specimens") or []
    if not specs:
        return None

    manual = _role_page(analysis, want_tag)
    if manual is not None:
        cap = manual.get("capacity_chars") or 0
        special = want_tag in (TAG_COVER, TAG_TOC, TAG_SECTION, TAG_END)
        # 用户指定的页装不下这次的内容（比如"目录"指到了 4 个装饰卡片页）→ 不用它，
        # 回退到按标签挑一个容量够的；封面/分节/结尾不受此限（它们本来就字少）。
        if not needed_chars or cap >= needed_chars * 0.7 or (special and want_tag != TAG_TOC):
            return {**manual, "tag": want_tag}
        if cap >= needed_chars:
            return {**manual, "tag": want_tag}
        analysis.setdefault("_role_overflow", []).append({"tag": want_tag, "page": manual["index"] + 1, "cap": cap})

    def by_tag(tag: str):
        pool = [s for s in specs if s["tag"] == tag and not s.get("image_only")]
        if pool:
            return pool
        return [s for s in specs if s["tag"] == tag]

    def best_of(pool: list[dict]) -> Optional[dict]:
        """容量够的里挑最小的；都不够挑容量最大的（碎片多的扣分）。"""
        if not pool:
            return None
        def score(spec: dict) -> tuple:
            cap = spec.get("capacity_chars") or 0
            frag = spec.get("fragmented") or 0
            # 正文框越少越好：一页塞十几个小框（卡片/图示页）会把字挤成一片
            frames_used = len(spec.get("bodies_i") or [])
            vectors = spec.get("vector_shapes") or 0
            enough = 1 if (not needed_chars or cap >= needed_chars) else 0
            simple = 1 if frames_used <= 2 else 0
            # 图示页（一堆圆/箭头）优先级最低：成段文字进去必然挤成一团
            plain = 0 if vectors >= 5 else 1
            return (plain, enough, simple, -frag, -abs(cap - (needed_chars or cap)) if enough else cap)
        return max(pool, key=score)

    hit = by_tag(want_tag)
    if hit:
        return best_of(hit)
    if want_tag.startswith(TAG_BULLETS):
        try:
            want_n = int(want_tag.split("-", 1)[1])
        except Exception:
            want_n = 3
        pool = [s for s in specs if s["tag"].startswith(TAG_BULLETS) and not s.get("image_only")]
        enough = [s for s in pool if s.get("capacity", 0) >= want_n]
        if enough:
            return best_of(enough)
        if pool:
            return best_of(pool)
        generic = by_tag("content")
        if generic:
            return best_of(generic)
    for tag in (TAG_BULLETS + "-3", TAG_CARDS, TAG_TWO_COL, "content", TAG_SECTION):
        hit = by_tag(tag)
        if hit:
            return hit[0]
    return next((s for s in specs if s["tag"] not in (TAG_COVER, TAG_END)), specs[0])


def structure_preview(analysis: dict, max_slides: int = 12) -> list[dict]:
    """给界面用的"结构卡片"：归一化坐标，前端按 16:9 画色块示意。"""
    width = analysis.get("slide_width") or 13.333
    height = analysis.get("slide_height") or 7.5
    cards: list[dict] = []
    for spec in (analysis.get("specimens") or [])[:max_slides]:
        boxes = []
        for f in spec["frames"]:
            boxes.append({
                "kind": f["kind"],
                "x": round((f["x"] or 0) / width, 4),
                "y": round((f["y"] or 0) / height, 4),
                "w": round((f["w"] or 0) / width, 4),
                "h": round((f["h"] or 0) / height, 4),
                "size": f["size"],
                "text": f["text"],
                "chars": f["chars"],
            })
        cards.append({"index": spec["index"], "tag": spec["tag"], "boxes": boxes,
                      "has_image": spec["has_image"]})
    return cards


def _iter_text_shapes(slide):
    """按解析时的同一顺序遍历文本框形状（占位文字清洗等复用）。"""
    return [s for s in slide.shapes if is_text_candidate(s)]
