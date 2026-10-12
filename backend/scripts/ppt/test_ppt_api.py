"""ASGI 直连验证 PPT 模块接口：模板列表 / 详情 / 生成。"""
import asyncio
import io
import os
import pathlib
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

_LOG = BACKEND / "_ppt_api.log"
_LINES: list[str] = []


def say(m: str) -> None:
    print(m, flush=True)
    _LINES.append(str(m))
    _LOG.write_text("\n".join(_LINES), encoding="utf-8")


from httpx import ASGITransport, AsyncClient  # noqa: E402

from main import app  # noqa: E402

MATERIAL = """周其仁《中国农村改革：国家与土地所有权关系的变化》一文回顾了 1949—1999 年
中国农村产权制度的变迁。文章指出，国家既是产权界定的前提，也可能成为产权被侵蚀的来源，
由此形成"所有权悖论"。作者梳理了诺斯难题，说明有效率的产权制度为何难以长期维持。
改革前，农村产权制度以集体所有和统购统销为特征，土地的排他性权利受到严格限制。
1978 年以后，包产到户在地方试验中出现，交易产生的所有权逐步被国家承认，形成新的制度均衡。
文章的结论是：制度变迁不是简单的效率选择，而是国家、集体与农户在约束条件下互相博弈的结果。
"""


async def main():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=600) as c:
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        h = {"Authorization": "Bearer " + r.json()["token"]}

        t0 = time.time()
        r1 = await c.get("/api/ppt/templates", headers=h)
        say(f"GET /api/ppt/templates → {r1.status_code}  {time.time()-t0:.1f}s")
        if r1.status_code != 200:
            say(r1.text[:300])
            return
        items = r1.json()["templates"]
        say(f"  模板 {len(items)} 套")
        for it in items[:3]:
            say(f"   · {it['name']:14s} {it['source']:7s} {it['slides']} 页  标签 {list(it['tags'].keys())}")
        first = items[0]

        r2 = await c.get(f"/api/ppt/templates/{first['id']}", headers=h)
        say(f"GET 详情 → {r2.status_code}  样本 {len(r2.json().get('specimens') or [])} 个  预览卡 {len(r2.json().get('preview') or [])} 张")

        r3 = await c.get("/api/ppt/themes", headers=h)
        say(f"GET /api/ppt/themes → {r3.status_code}  {len(r3.json()['themes'])} 套主题")

        say("\n生成（选内置模板 academic-red，DeepSeek）…")
        t1 = time.time()
        r4 = await c.post("/api/ppt/generate", headers=h, json={
            "material_text": MATERIAL,
            "template_id": first["id"],
            "theme": "academic-red",
            "pages": 6,
            "filename": "农村改革汇报",
            "model": "",
        })
        say(f"POST /api/ppt/generate → {r4.status_code}  {time.time()-t1:.1f}s")
        if r4.status_code != 200:
            say("  " + r4.text[:300])
            return
        d = r4.json()
        say(f"  文件 {d['file']['name']}  {d['file']['path']}  来源 {d['file'].get('source')}")
        say(f"  {d['pages']} 页  模板={d['template']}  模型={d['model']}")
        say(f"  用到的版式：{'、'.join(d['used_tags'])}")
        if d["warnings"]:
            say("  提示：" + "；".join(d["warnings"][:3]))

        # M2：不用模板（按主题）也要走版式库
        say("\n生成（不选模板，只用主题 academy-blue）…")
        t2 = time.time()
        r5 = await c.post("/api/ppt/generate", headers=h, json={
            "material_text": MATERIAL,
            "template_id": "",
            "theme": "academy-blue",
            "pages": 8,
            "filename": "只按主题生成",
            "model": "",
        })
        say(f"POST /api/ppt/generate（无模板）→ {r5.status_code}  {time.time()-t2:.1f}s")
        if r5.status_code == 200:
            e = r5.json()
            say(f"  {e['pages']} 页  用的模板={e['template']}（theme_template={e.get('theme_template')}）")
            say(f"  用到的版式：{'、'.join(e['used_tags'])}")
        else:
            say("  " + r5.text[:200])

        # M3：真实缩略图与结果页图
        r6 = await c.get("/api/ppt/render/status", headers=h)
        say(f"\nGET render/status → {r6.status_code} {r6.json()}")
        t3 = time.time()
        r7 = await c.get(f"/api/ppt/templates/{first['id']}/thumb.png?page=1", headers=h)
        say(f"GET 模板缩略图 → {r7.status_code}  {len(r7.content)/1024:.1f} KB  {time.time()-t3:.1f}s  {r7.headers.get('content-type')}")
        t4 = time.time()
        r8 = await c.get(f"/api/ppt/preview.png?page=1&path={d['file']['path']}", headers=h)
        say(f"GET 结果页图 → {r8.status_code}  {len(r8.content)/1024:.1f} KB  {time.time()-t4:.1f}s")


try:
    asyncio.run(main())
except Exception as exc:
    say(f"异常 {type(exc).__name__}: {exc}")
say("=== 结束 ===")
sys.stdout.flush()
os._exit(0)
