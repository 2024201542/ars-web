"""完整跑一套：论文 PDF → 选人大模板 → 重建不可编辑页 → 生成讲解 PPT → 渲染预览。

用运行中的后端接口（走真实链路，不绕过任何一层）。
"""
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

PDF_REL = "土地改革论文写作/6 周其仁，中国农村改革：国家与土地所有权关系的变化.pdf"
NODE = pathlib.Path(r"C:\Users\28473\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe")
CLI = pathlib.Path(r"D:\deepseek harness\resources\app.asar.unpacked\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js")
LOCAL_ROOT = pathlib.Path(r"C:\Users\28473\Desktop\学术写作工具测试")


async def main() -> None:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=1800) as c:
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        h = {"Authorization": "Bearer " + r.json()["token"]}

        # ① 读论文正文（走附件读取接口，扫描件会走 OCR 缓存）
        import urllib.parse

        t0 = time.time()
        q = urllib.parse.urlencode({"session_id": "", "path": PDF_REL, "source": "local"})
        # 需要 session 才能读文件，先建一个会话
        created = await c.post("/api/sessions", headers=h,
                               json={"skill_name": "ppt-maker", "mode_name": "make", "title": "论文讲解 PPT"})
        sid = created.json()["id"]
        q = urllib.parse.urlencode({"session_id": sid, "path": PDF_REL, "source": "local"})
        body = await c.get(f"/api/workspace/files/content?{q}", headers=h)
        if body.status_code != 200:
            say(f"读论文失败：{body.status_code} {body.text[:200]}")
            return
        text = body.json()["content"]
        say(f"① 论文正文：{len(text)} 字（{time.time()-t0:.1f}s）")

        # ② 选模板：人大模板-50，并先把"整页图片化"的页重建掉
        items = (await c.get("/api/ppt/templates", headers=h)).json()["templates"]
        tpl = next(t for t in items if t["name"].endswith("50"))
        say(f"② 选定模板：{tpl['name']}（{tpl['slides']} 页）")

        real = BACKEND / "data" / "workspaces" / "c46ff668-f8c3-46d9-ba62-7f2c271816d4" / "ppt_templates" / f"{tpl['id']}.pptx"
        backup = real.with_suffix(".backup.pptx")
        if not backup.exists():
            shutil.copyfile(real, backup)
            say(f"   已备份原模板 → {backup.name}")

        t1 = time.time()
        rebuilt = await c.post(f"/api/ppt/templates/{tpl['id']}/rebuild-image-pages", headers=h)
        if rebuilt.status_code == 200:
            info = rebuilt.json()
            say(f"   重建图片页：{info.get('rebuilt')} 页，新增文字位 {info.get('texts')}、图片位 {info.get('photos')}（{time.time()-t1:.1f}s）")
        else:
            say(f"   重建跳过：{rebuilt.status_code} {rebuilt.text[:120]}")

        # ③ 生成：套这套模板，12 页左右
        say("③ 正在生成（模型出大纲 → 套模板拼版）…")
        t2 = time.time()
        gen = await c.post("/api/ppt/generate", headers=h, json={
            "material_text": text,
            "template_id": tpl["id"],
            "pages": 12,
            "filename": "中国农村改革：国家与土地产权关系的变化（讲解稿）",
            "save_to_local": True,
            "auto_image": False,
        })
        if gen.status_code != 200:
            say(f"   生成失败：{gen.status_code} {gen.text[:300]}")
            return
        data = gen.json()
        say(f"   完成：{data['pages']} 页（{time.time()-t2:.1f}s）")
        say(f"   用到的版式：{'、'.join(data.get('used_tags') or [])}")
        say(f"   文件：{data['file']['name']}  →  {data['file']['path']}（source={data['file'].get('source')}）")
        if data.get("warnings"):
            say("   提示：" + "；".join(data["warnings"][:3]))

        # ④ 渲染预览图
        local_file = LOCAL_ROOT / data["file"]["path"]
        if not local_file.exists():
            local_file = BACKEND / "data" / "workspaces" / "c46ff668-f8c3-46d9-ba62-7f2c271816d4" / data["file"]["path"]
        say(f"④ 产物位置：{local_file}  存在={local_file.exists()}")
        if local_file.exists() and NODE.exists() and CLI.exists():
            out_dir = BACKEND / "_final_preview"
            shutil.rmtree(out_dir, ignore_errors=True)
            r2 = subprocess.run([str(NODE), str(CLI), "render", "--input", str(local_file),
                                 "--output-dir", str(out_dir), "--pages", "1,3,5,7", "--dpi", "100"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
            try:
                meta = json.loads((r2.stdout or "{}").strip().splitlines()[-1])
                say(f"   渲染 {len(meta.get('images') or [])} 张 → {out_dir}")
            except Exception:
                say("   渲染失败：" + (r2.stdout or r2.stderr or "")[:160])

        # ⑤ 大纲摘要
        slides = (data.get("outline") or {}).get("slides") or []
        say("\n⑤ 逐页提纲：")
        for i, s in enumerate(slides, 1):
            bullets = "；".join(str(b.get("text") if isinstance(b, dict) else b)[:18] for b in (s.get("bullets") or [])[:3])
            say(f"   {i:>2}. [{s.get('layout')}] {str(s.get('title'))[:28]}  {bullets[:60]}")


try:
    asyncio.run(main())
except Exception as exc:
    say(f"异常 {type(exc).__name__}: {exc}")
say("=== 结束 ===")
sys.stdout.flush()
os._exit(0)
