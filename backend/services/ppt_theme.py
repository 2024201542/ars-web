"""PPT 主题注册表：配色 + 字体 + 标题/正文规格。

内置模板（`assets/ppt_templates/builtin/`）用这些主题生成；
用户没选模板时，生成也按其中一个主题出片（M2 会在此基础上扩版式）。
"""

from __future__ import annotations

THEMES: dict[str, dict] = {
    "academic-red": {
        "name": "学术红",
        "accent": "9E1B32",
        "secondary": "C9A227",
        "text": "262626",
        "muted": "595959",
        "font": "微软雅黑",
        "title_size": 30,
        "body_size": 17,
    },
    "academy-blue": {
        "name": "学院蓝",
        "accent": "1F4E79",
        "secondary": "2E75B6",
        "text": "1F2937",
        "muted": "5B6B7C",
        "font": "微软雅黑",
        "title_size": 30,
        "body_size": 17,
    },
    "forest-green": {
        "name": "松墨绿",
        "accent": "2F5D50",
        "secondary": "7FA88F",
        "text": "22302B",
        "muted": "5C6E66",
        "font": "微软雅黑",
        "title_size": 30,
        "body_size": 17,
    },
    "minimal-black": {
        "name": "极简黑白",
        "accent": "1A1A1A",
        "secondary": "8C8C8C",
        "text": "1A1A1A",
        "muted": "6B6B6B",
        "font": "思源黑体",
        "title_size": 30,
        "body_size": 17,
    },
    "warm-orange": {
        "name": "暖橙",
        "accent": "C05621",
        "secondary": "E8A33D",
        "text": "2D2119",
        "muted": "6B5A4C",
        "font": "微软雅黑",
        "title_size": 30,
        "body_size": 17,
    },
    "grey-violet": {
        "name": "灰紫",
        "accent": "5B4B8A",
        "secondary": "9C8CC4",
        "text": "2A2438",
        "muted": "615A73",
        "font": "微软雅黑",
        "title_size": 30,
        "body_size": 17,
    },
}

DEFAULT_THEME = "academic-red"


def list_themes() -> list[dict]:
    return [{"id": tid, **cfg} for tid, cfg in THEMES.items()]


def get_theme(theme_id: str = "") -> dict:
    return THEMES.get((theme_id or "").strip(), THEMES[DEFAULT_THEME])


def outline_theme(theme_id: str = "") -> dict:
    """转成大纲里的 theme 字段（pptx_builder 读的是 accent / font）。"""
    cfg = get_theme(theme_id)
    return {"accent": f"#{cfg['accent']}", "font": cfg["font"]}
