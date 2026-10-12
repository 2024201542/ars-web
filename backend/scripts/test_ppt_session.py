"""会话级端到端：PPT 生成入口 + 选模板 → 对话框一句话 → 出片（落到工作区）。"""
import asyncio
import io
import json
import os
import pathlib
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_LOG = BACKEND / "_ppt_session.log"
_LINES: list[str] = []


def say(m: str) -> None:
    print(m, flush=True)
    _LINES.append(str(m))
    _LOG.write_text("\n".join(_LINES), encoding="utf-8")


from httpx import ASGITransport, AsyncClient  # noqa: E402

from main import app  # noqa: E402

MATERIAL = """周其仁《中国农村改革：国家与土地所有权关系的变化》回顾了 1949—1999 年中国农村产权制度变迁。
文章指出国家既是产权界定的前提，也可能成为产权被侵蚀的来源，由此形成所有权悖论。
作者梳理诺斯难题，说明有效率的产权制度为何难以长期维持。
改革前农村产权以集体所有与统购统销为特征，土地排他性权利受到严格限制。
1978 年以后包产到户在地方试验中出现，交易产生的所有权逐步被国家承认，形成新的制度均衡。
结论：制度变迁不是简单的效率选择，而是国家、集体与农户在约束条件下互相博弈的结果。
"""


async def main():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=900) as c:
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        h = {"Authorization": "Bearer " + r.json()["token"]}

        # 1) 新建会话并切到 PPT 生成入口
        created = await c.post("/api/sessions", headers=h,
                               json={"skill_name": "ppt-maker", "mode_name": "make", "title": "PPT 测试"})
        say(f"新建会话（skill=ppt-maker/make）→ {created.status_code}")
        if created.status_code not in (200, 201):
            say("  " + created.text[:200])
            return
        sid = created.json()["id"]
        patched = await c.patch(f"/api/sessions/{sid}", headers=h,
                                json={"skill_name": "ppt-maker", "mode_name": "make"})
        say(f"切换入口 → {patched.status_code}")

        # 2) 模板库：选一套用户的真实模板
        items = (await c.get("/api/ppt/templates", headers=h)).json()["templates"]
        real = next((t for t in items if t["source"] == "user" and "50" in t["name"]), None)
        say(f"模板库 {len(items)} 套；将使用：{real['name'] if real else '（无，用内置主题）'}")
        if real:
            detail = await c.get(f"/api/ppt/templates/{real['id']}", headers=h)
            say(f"  角色映射：{json.dumps(detail.json().get('roles'), ensure_ascii=False)}")

        # 3) 对话框一句话 + 带上所选模板与页数
        message = f"[文件: 中国农村改革.pdf]\n{MATERIAL}\n---\n用户问题: 根据这个做一个汇报 PPT"
        payload = {
            "message": message,
            "user_text": "根据这个做一个汇报 PPT，配图用我给的图片",
            "attach_paths": ["_测试配图.png"],
            "attach_source": "local",
            "ppt_template_id": real["id"] if real else "",
            "ppt_pages": 10,
        }
        say("\n发送（SSE）：")
        events = []
        async with c.stream("POST", f"/api/sessions/{sid}/chat", headers=h, json=payload) as resp:
            say(f"  HTTP {resp.status_code}")
            cur = ""
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    cur = line[7:].strip()
                elif line.startswith("data: ") and cur:
                    try:
                        data = json.loads(line[6:])
                    except Exception:
                        continue
                    events.append((cur, data))
                    if cur in ("ppt_created", "message", "error"):
                        if cur == "ppt_created":
                            say("  [ppt_created] " + json.dumps(
                                {k: data.get(k) for k in ("name", "path", "source", "pages", "model",
                                                          "template", "used_tags", "images_used",
                                                          "images_available", "warnings")},
                                ensure_ascii=False))
                        else:
                            say(f"  [{cur}] {str(data)[:200]}")
                    cur = ""

        ppt = next((d for e, d in events if e == "ppt_created"), None)
        if not ppt:
            say("\n没有生成 ppt_created 事件")
            return
        root = BACKEND / "data" / "workspaces" / "c46ff668-f8c3-46d9-ba62-7f2c271816d4"
        f = root / ppt["path"]
        say(f"\n文件落地: {f.exists()}  {f}")
        if f.exists():
            from services.pptx_edit import read_slides
            slides = read_slides(f)
            say(f"回读 {len(slides)} 页：" + " / ".join(s["title"][:14] for s in slides[:8]))


try:
    asyncio.run(main())
except Exception as exc:
    say(f"异常 {type(exc).__name__}: {exc}")
say("=== 结束 ===")
sys.stdout.flush()
os._exit(0)
