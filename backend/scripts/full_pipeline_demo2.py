"""完整跑一套（修正版）：论文 → 重建不可编辑页 → 套人大模板生成 → 渲染预览。"""
import asyncio
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_LOG = BACKEND / "_full_run.log"
_LINES: list[str] = []


def say(text: str) -> None:
    print(text, flush=True)
    _LINES.append(str(text))
    _LOG.write_text("\n".join(_LINES), encoding="utf-8")


from httpx import ASGITransport, AsyncClient  # noqa: E402

from main import app  # noqa: E402
from services import ppt_template  # noqa: E402

USER_ID = "c46ff668-f8c3-46d9-ba62-7f2c271816d4"
PDF_REL = "土地改革论文写作/6 周其仁，中国农村改革：国家与土地所有权关系的变化.pdf"
NODE = pathlib.Path(r"C:\Users\28473\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe")
CLI = pathlib.Path(r"D:\deepseek harness\resources\app.asar.unpacked\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js")
LOCAL_ROOT = pathlib.Path(r"C:\Users\28473\Desktop\学术写作工具测试")
TPL_DIR = BACKEND / "data" / "workspaces" / USER_ID / "ppt_templates"


async def main() -> None:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=1800) as c:
        h = {"Authorization": "Bearer " + (await c.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"})).json()["token"]}

        items = (await c.get("/api/ppt/templates", headers=h)).json()["templates"]
        tpl = next(t for t in items if t["name"].endswith("50"))
        tpl_file = TPL_DIR / f"{tpl['id']}.pptx"
        tpl_json = TPL_DIR / f"{tpl['id']}.analysis.json"

        # ① 确保解析是最新的，并看清"整页图片化"的页
        analysis = ppt_template.analyze_pptx(tpl_file, tid=tpl["id"], name=tpl["name"], source="user")
        ppt_template.save_analysis(tpl_json, analysis)
        image_only = [s["index"] + 1 for s in analysis["specimens"] if s.get("image_only")]
        say(f"① 模板 {tpl['name']}：{analysis['stats']['slides']} 页；整页图片化 {len(image_only)} 页 {image_only}")

        # ② 重建这些页（渲染→擦字→可编辑文本框）
        if image_only:
            t0 = time.time()
            res = await c.post(f"/api/ppt/templates/{tpl['id']}/rebuild-image-pages", headers=h)
            if res.status_code == 200:
                info = res.json()
                say(f"② 重建完成：{info.get('rebuilt')} 页，新增文字位 {info.get('texts')}、图片位 {info.get('photos')}（{time.time()-t0:.1f}s）")
            else:
                say(f"② 重建失败：{res.status_code} {res.text[:160]}")

        # ③ 读论文 + 生成（套这套模板）
        created = await c.post("/api/sessions", headers=h,
                               json={"skill_name": "ppt-maker", "mode_name": "make", "title": "论文讲解 PPT"})
        sid = created.json()["id"]
        import urllib.parse

        q = urllib.parse.urlencode({"session_id": sid, "path": PDF_REL, "source": "local"})
        text = (await c.get(f"/api/workspace/files/content?{q}", headers=h)).json()["content"]
        say(f"③ 论文正文 {len(text)} 字，开始生成…")
        t1 = time.time()
        gen = await c.post("/api/ppt/generate", headers=h, json={
            "material_text": text,
            "template_id": tpl["id"],
            "pages": 12,
            "filename": "中国农村改革：国家与土地产权关系的变化（讲解稿）",
            "save_to_local": True,
        })
        if gen.status_code != 200:
            say(f"   生成失败：{gen.status_code} {gen.text[:300]}")
            return
        data = gen.json()
        say(f"   完成：{data.get('pages')} 页（{time.time()-t1:.1f}s）  模板={data.get('template')}")
        say(f"   版式：{'、'.join(data.get('used_tags') or [])}")
        say(f"   文件：{data.get('name')}  →  {data.get('path')}（source={data.get('source')}）")
        if data.get("warnings"):
            say("   提示：" + "；".join(data["warnings"][:3]))

        target = LOCAL_ROOT / str(data.get("path"))
        if not target.exists():
            target = BACKEND / "data" / "workspaces" / USER_ID / str(data.get("path"))
        say(f"④ 产物：{target}  存在={target.exists()}  {target.stat().st_size/1024/1024:.1f} MB" if target.exists() else f"④ 产物不存在：{target}")

        if target.exists() and NODE.exists() and CLI.exists():
            out_dir = BACKEND / "_final_preview"
            shutil.rmtree(out_dir, ignore_errors=True)
            r2 = subprocess.run([str(NODE), str(CLI), "render", "--input", str(target),
                                 "--output-dir", str(out_dir), "--pages", "1,3,6,9,14", "--dpi", "100"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
            try:
                meta = json.loads((r2.stdout or "{}").strip().splitlines()[-1])
                say(f"   渲染 {len(meta.get('images') or [])} 张 → {out_dir}")
            except Exception:
                say("   渲染失败：" + (r2.stdout or r2.stderr or "")[:200])

        say("\n⑤ 逐页提纲：")
        for i, s in enumerate((data.get("outline") or {}).get("slides") or [], 1):
            bullets = "；".join(str(b.get("text") if isinstance(b, dict) else b)[:16] for b in (s.get("bullets") or [])[:2])
            say(f"   {i:>2}. [{str(s.get('layout')):10s}] {str(s.get('title'))[:26]:28s} {bullets[:52]}")


try:
    asyncio.run(main())
except Exception as exc:
    say(f"异常 {type(exc).__name__}: {exc}")
say("=== 结束 ===")
sys.stdout.flush()
os._exit(0)
