"""PPT 模板库的服务层：内置模板 + 用户上传模板。

抽出来的原因：**两处都要用**——
1. `routers/template_library.py`（模板库管理接口）；
2. `services/ppt/ppt_chat.py`（对话框里一句"生成 PPT"时按选中的模板拼接）。
放在服务层，两边就不会各写一套逻辑。

目录约定：
- 内置：`backend/assets/ppt_templates/builtin/<theme>.pptx` + `<theme>.analysis.json`（随代码提交）
- 用户：`data/workspaces/<uid>/ppt_templates/<tid>.pptx` + `<tid>.analysis.json`
"""

from __future__ import annotations

import pathlib
from typing import Optional

from services.ppt import ppt_template, ppt_theme
from services.workspace_manager import user_dir

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
BUILTIN_DIR = BACKEND_DIR / "assets" / "ppt_templates" / "builtin"
MAX_TEMPLATE_BYTES = 40 * 1024 * 1024

LAYOUT_HINT = (
    "每一页可以带 layout 字段，从这些里挑最合适的："
    "cover（封面，只在第一页）、toc（目录）、section（章节分隔，没有要点的过渡页）、"
    "content（普通要点页）、two-col（两点对照，正好两条要点时用）、"
    "cards-3（三个并列要点，正好三条且互不从属时用）、"
    "timeline（有 3–4 个时间节点时用，每条要点以年份开头）、"
    "big-number（有一个关键数字时用，第一条要点写这个数字，第二条写解释）、"
    "quote（引用原文金句，只有一句时用）、end（结尾页）。"
    "不要写 title 或 bullets 之外的内容。"
)


def user_tpl_dir(user_id: str) -> pathlib.Path:
    folder = user_dir(user_id) / "ppt_templates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _fresh(path: pathlib.Path, analysis: Optional[dict], *, tid: str, name: str, source: str) -> Optional[dict]:
    """解析结果太旧（缺新字段）就现场重新解析并写回。"""
    if analysis and analysis.get("version") == ppt_template.ANALYSIS_VERSION:
        return analysis
    try:
        refreshed = ppt_template.analyze_pptx(path, tid=tid, name=name or path.stem, source=source)
        ppt_template.save_analysis(path.with_suffix(".analysis.json"), refreshed)
        return refreshed
    except Exception:
        return analysis


def load_builtin() -> list[dict]:
    items: list[dict] = []
    if not BUILTIN_DIR.is_dir():
        return items
    for pptx in sorted(BUILTIN_DIR.glob("*.pptx")):
        analysis = ppt_template.load_analysis(BUILTIN_DIR / f"{pptx.stem}.analysis.json")
        analysis = _fresh(pptx, analysis, tid=f"builtin-{pptx.stem}", name=pptx.stem, source="builtin")
        if not analysis:
            continue
        analysis["id"] = f"builtin-{pptx.stem}"
        analysis["source"] = "builtin"
        analysis["file_path"] = str(pptx)
        items.append(analysis)
    return items


def load_user(user_id: str) -> list[dict]:
    items: list[dict] = []
    folder = user_tpl_dir(user_id)
    for pptx in sorted(folder.glob("*.pptx")):
        if ".backup" in pptx.name.lower():
            continue
        analysis = ppt_template.load_analysis(folder / f"{pptx.stem}.analysis.json")
        analysis = _fresh(pptx, analysis, tid=pptx.stem,
                          name=(analysis or {}).get("name") or pptx.stem, source="user")
        if not analysis:
            continue
        analysis["source"] = "user"
        analysis["file_path"] = str(pptx)
        items.append(analysis)
    return items


def find(user_id: str, template_id: str) -> Optional[dict]:
    tid = (template_id or "").strip()
    if not tid or tid == "none":
        return None
    for item in load_builtin():
        if item.get("id") == tid:
            return item
    for item in load_user(user_id):
        if item.get("id") == tid:
            return item
    return None


def builtin_for_theme(theme: str) -> Optional[dict]:
    """某主题对应的内置模板——它就是那套"版式库"；找不到就退回默认主题。"""
    items = load_builtin()
    wanted = f"builtin-{(theme or '').strip()}"
    for item in items:
        if item.get("id") == wanted:
            return item
    for item in items:
        if item.get("id") == f"builtin-{ppt_theme.DEFAULT_THEME}":
            return item
    return items[0] if items else None


def _pages_status(analysis: dict) -> str:
    if not analysis.get("file_path"):
        return "none"
    from services.ppt import ppt_pages
    try:
        return ppt_pages.pages_status(analysis)
    except Exception:
        return "none"


def summary(analysis: dict, with_preview: bool = True) -> dict:
    out = {
        "id": analysis.get("id"),
        "name": analysis.get("name"),
        "source": analysis.get("source", "user"),
        "slides": (analysis.get("stats") or {}).get("slides", 0),
        "tags": (analysis.get("stats") or {}).get("tags", {}),
        "theme": analysis.get("theme", {}),
        "slide_width": analysis.get("slide_width"),
        "slide_height": analysis.get("slide_height"),
        "roles": analysis.get("manual_roles") or {},
        "pages_status": _pages_status(analysis),
    }
    if with_preview:
        out["preview"] = ppt_template.structure_preview(analysis, max_slides=10)
    return out
