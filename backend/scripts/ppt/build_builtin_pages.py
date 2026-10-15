"""给内置模板预置页说明。

在 backend 目录运行：
    python scripts/ppt/build_builtin_pages.py

对 assets/ppt_templates/builtin/*.pptx 逐页看图，再做一次整份归纳，
写成同名的 .pages.json。密钥从管理员账号的设置里读，不打印。
已经有「解析完成」页说明的模板会跳过，避免重复看图。
"""

from __future__ import annotations

import logging
logging.disable(logging.CRITICAL)

import asyncio
import pathlib
import sqlite3
import sys
import time

BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from services.ppt import ppt_template, ppt_vision  # noqa: E402

BUILTIN = BACKEND / "assets" / "ppt_templates" / "builtin"
DB = BACKEND / "data" / "ars.db"


def admin_id() -> str:
    uri = f"file:{DB.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        raise SystemExit("找不到管理员账号，页说明没有生成")
    return str(row[0])


def already_done(pptx: pathlib.Path) -> bool:
    path = pptx.with_suffix(".pages.json")
    if not path.is_file():
        return False
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    parse = data.get("parse") or {}
    return parse.get("status") == "done" and not parse.get("errors") and bool(data.get("pages"))


async def build_one(user_id: str, pptx: pathlib.Path) -> dict:
    analysis = ppt_template.load_analysis(pptx.with_suffix(".analysis.json"))
    if not analysis:
        return {"name": pptx.stem, "error": "没有分析结果"}
    slides = (analysis.get("stats") or {}).get("slides") or len(analysis.get("specimens") or [])
    template = dict(analysis)
    template["file_path"] = str(pptx)
    template["source"] = "build"
    template["id"] = f"builtin-{pptx.stem}"
    template["name"] = analysis.get("name") or pptx.stem
    progress = {"status": "running", "done": 0, "total": slides, "errors": []}
    started = time.time()
    await ppt_vision.run_parse(user_id, template, "", [], False, progress, text_model="")
    return {
        "name": pptx.stem,
        "slides": slides,
        "status": progress.get("status"),
        "done": progress.get("done"),
        "errors": progress.get("errors") or [],
        "seconds": round(time.time() - started, 1),
    }


async def main() -> None:
    user_id = admin_id()
    files = sorted(BUILTIN.glob("*.pptx"))
    if not files:
        raise SystemExit("内置模板目录里没有 pptx")
    for pptx in files:
        if already_done(pptx):
            print(f"{pptx.stem} 已有页说明，跳过", flush=True)
            continue
        print(f"{pptx.stem} 开始", flush=True)
        result = await build_one(user_id, pptx)
        errors = result.get("errors") or []
        print(
            f"{result['name']} {result.get('status')} {result.get('done')}/{result.get('slides')} "
            f"失败 {len(errors)} 用时 {result.get('seconds')} 秒",
            flush=True,
        )
        for item in errors[:5]:
            print(f"  第 {item.get('page')} 页 {item.get('error')}", flush=True)


if __name__ == "__main__":
    import os
    asyncio.run(main())
    sys.stdout.flush()
    os._exit(0)
