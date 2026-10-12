"""把最近的对话导出成 Markdown，供界面卡住时直接阅读。"""
import io
import json
import os
import pathlib
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from compression import zstd

SRC = pathlib.Path(
    r"C:\Users\28473\.dsh\sessions\--D-academic-research-skills-main--"
    r"\session-480eb54d-9f78-4186-bd68-fb445aa650d3\session.v4.jsonl.zstd"
)
OUT = pathlib.Path(r"D:\academic-research-skills-main\最近对话记录.md")

TURNS = 16          # 导出最近多少个回合
MAX_CHARS = 4000    # 单条消息最多保留多少字


def text_of_user(d: dict) -> str:
    c = d.get("content")
    if isinstance(c, list):
        parts = []
        for x in c:
            if not isinstance(x, dict):
                continue
            if x.get("type") == "text":
                parts.append(str(x.get("text") or ""))
            elif x.get("type") == "image":
                parts.append("［图片］")
        return "\n".join(p for p in parts if p)
    return str(c or "")


def text_of_assistant(d: dict) -> str:
    """assistant 记录的真实结构是 data.message.content[]，每项含 type=text 的 text 字段。"""
    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
    blocks = msg.get("content") or d.get("content") or []
    if isinstance(blocks, str):
        return blocks
    parts = []
    if isinstance(blocks, list):
        for b in blocks:
            if isinstance(b, dict) and (b.get("type") in (None, "text")) and b.get("text"):
                parts.append(str(b.get("text")))
    return "\n".join(parts)


def clip(text: str, limit: int = MAX_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + f"\n\n…（本条还有 {len(text)-limit} 字，完整内容在会话文件里）"


records = []
for line in zstd.decompress(SRC.read_bytes()).decode("utf-8", "replace").splitlines():
    try:
        records.append(json.loads(line))
    except Exception:
        continue

# 按 user/message 切回合
items: list[tuple[str, str, str]] = []   # (role, when, text)
for rec in records:
    t = rec.get("type")
    d = rec.get("data") or {}
    when = ""
    try:
        when = time.strftime("%m-%d %H:%M", time.localtime(int(rec.get("time") or 0) / 1000))
    except Exception:
        pass
    if t == "user/message":
        text = text_of_user(d)
        if text.strip():
            items.append(("user", when, text))
    elif t == "assistant/message":
        text = text_of_assistant(d)
        if text.strip():
            items.append(("assistant", when, text))

# 取最近 TURNS 个 user 消息之后的全部内容
user_idx = [i for i, it in enumerate(items) if it[0] == "user"]
start = user_idx[-TURNS] if len(user_idx) > TURNS else 0
recent = items[start:]

lines = [
    "# 最近对话记录（界面卡住时的备用阅读）",
    "",
    f"> 由会话文件导出：{time.strftime('%Y-%m-%d %H:%M:%S')}　共 {len(recent)} 条"
    f"（最近 {min(TURNS, len(user_idx))} 个回合）",
    "",
    "---",
    "",
]
for role, when, text in recent:
    who = "**你**" if role == "user" else "**AI**"
    lines.append(f"### {who}　{when}")
    lines.append("")
    lines.append(clip(text))
    lines.append("")
    lines.append("---")
    lines.append("")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"已导出 {len(recent)} 条 → {OUT}")
print(f"文件大小 {OUT.stat().st_size/1024:.1f} KB")
