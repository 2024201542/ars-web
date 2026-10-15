"""pptx_render 整页渲染：convert 转 PDF 再出图，右侧和底部不能被裁掉。"""

import pathlib

import pytest
from PIL import Image

from services.ppt import pptx_render

# 样片在仓库外的开发笔记里，本机没有就跳过
SAMPLE = (pathlib.Path(__file__).resolve().parents[3]
          / "开发笔记" / "截图" / "ppt-新方案" / "样片-人大模板53.pptx")


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    """覆盖 conftest 的同名 fixture。

    DSH 沙箱里 pytest 用 0o700 建的临时目录（basetemp/tmp_path）受限令牌
    进不去，tmp_path 一实例化就 PermissionError；本模块的测试不碰数据库，
    环境变量指到一个普通目录拼路径即可。
    """
    sandbox = pathlib.Path(__file__).resolve().parents[3] / ".tmp" / "pytest-env"
    monkeypatch.setenv("ARS_WEB_DB_PATH", str(sandbox / "test_ars.db"))
    monkeypatch.setenv("ARS_SKILLS_PATH", str(sandbox / "fake_skills"))
    monkeypatch.setenv("ARS_WORKSPACE_DIR", str(sandbox / "workspaces"))
    # 渲染缓存也指到沙箱可写处，不污染 data\ppt_render
    monkeypatch.setenv("ARS_PPT_RENDER_CACHE", str(sandbox / "ppt_render"))

pytestmark = pytest.mark.skipif(
    not pptx_render.available() or not SAMPLE.is_file(),
    reason="没有 LibreOffice Kit 或样片不在本机",
)


def _right_strip_has_ink(png: pathlib.Path) -> bool:
    """右侧 15% 区域里有非白像素（校徽/水印所在的位置）。"""
    img = Image.open(png).convert("L")
    w, h = img.size
    strip = img.crop((int(w * 0.85), 0, w, h))
    return strip.getextrema()[0] < 240


def test_render_page4_is_full_width():
    out = pptx_render.render_pages(SAMPLE, [4], dpi=110)
    assert 4 in out, f"第 4 页没渲染出来：{pptx_render.last_error()}"
    img = Image.open(out[4])
    w, h = img.size
    assert abs(w / h - 16 / 9) < 0.02, f"宽高比 {w}x{h} 不是 16:9"
    assert _right_strip_has_ink(out[4]), "右侧 15% 区域全白，右侧内容被裁掉了"


def test_deck_pdf_is_reused_across_pages():
    """同一文件请求不同页时，deck.pdf 不重复转换（mtime 不变）。"""
    first = pptx_render.render_pages(SAMPLE, [4], dpi=110)
    assert 4 in first
    pdf = pptx_render.cache_dir(SAMPLE) / "deck.pdf"
    assert pdf.is_file(), "deck.pdf 没有缓存下来"
    mtime = pdf.stat().st_mtime
    second = pptx_render.render_pages(SAMPLE, [5], dpi=110)
    assert 5 in second, f"第 5 页没渲染出来：{pptx_render.last_error()}"
    assert pdf.stat().st_mtime == mtime, "请求新页时 deck.pdf 被重新转换了"
