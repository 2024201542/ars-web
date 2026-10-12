"""看会话文件尾部：我的最新消息是否真的写进去了（判断是"没保存"还是"界面没显示"）。"""
import io
import json
import os
import pathlib
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from compression import zstd

src = pathlib.Path(
    r"C:\Users\28473\.dsh\sessions\--D-academic-research-skills-main--"
    r"\session-480eb54d-9f78-4186-bd68-fb445aa650d3\session.v4.jsonl.zstd"
)
st = src.stat()
print(f"文件: {st.st_size/1024/1024:.2f} MB  最后写入: "
      f"{time.strftime('%H:%M:%S', time.localtime(st.st_mtime))}  现在: {time.strftime('%H:%M:%S')}")

raw = zstd.decompress(src.read_bytes()).decode("utf-8", "replace")
lines = raw.splitlines()
print(f"记录 {len(lines)} 条\n")

print("最后 14 条记录：")
for line in lines[-14:]:
    try:
        rec = json.loads(line)
    except Exception:
        continue
    t = rec.get("type")
    ts = rec.get("time")
    when = ""
    try:
        when = time.strftime("%H:%M:%S", time.localtime(int(ts) / 1000))
    except Exception:
        pass
    d = rec.get("data") or {}
    extra = ""
    if t == "assistant/message":
        blocks = d.get("content") or d.get("blocks") or []
        text = ""
        if isinstance(blocks, list):
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text":
                    text = str(b.get("text") or "")
                    break
        elif isinstance(blocks, str):
            text = blocks
        extra = text.replace("\n", " ")[:70]
    elif t == "user/message":
        c = d.get("content")
        if isinstance(c, list):
            extra = " ".join(str(x.get("text") or x.get("type") or "") for x in c if isinstance(x, dict))[:70]
        else:
            extra = str(c)[:70]
    elif t == "tool/result":
        extra = str((d.get("message") or {}).get("name") or "")[:40]
    print(f"  {when}  {t:28s} {extra}")
