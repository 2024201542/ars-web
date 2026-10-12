"""把桌面上的真实模板导入模板库（复制进用户模板目录 + 解析 + 角色映射）。"""
import io
import json
import pathlib
import shutil
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services import ppt_template as t  # noqa: E402

USER_ID = "c46ff668-f8c3-46d9-ba62-7f2c271816d4"
FOLDER = BACKEND / "data" / "workspaces" / USER_ID / "ppt_templates"
DESKTOP = pathlib.Path(r"C:\Users\28473\Desktop")

FOLDER.mkdir(parents=True, exist_ok=True)
import uuid  # noqa: E402

files = sorted(DESKTOP.glob("中国人民大学模板-5*.pptx"))
for path in files:
    tid = uuid.uuid4().hex[:12]
    dest = FOLDER / f"{tid}.pptx"
    t0 = time.time()
    shutil.copyfile(path, dest)
    analysis = t.analyze_pptx(dest, tid=tid, name=path.stem, source="user")
    t.save_analysis(FOLDER / f"{tid}.analysis.json", analysis)
    print(f"导入 {path.stem}  [{path.stat().st_size/1024/1024:.1f} MB]  → {tid}  "
          f"{analysis['stats']['slides']} 页  用时 {time.time()-t0:.1f}s")
    print("     角色：" + json.dumps(analysis["manual_roles"], ensure_ascii=False))

total = sum(f.stat().st_size for f in FOLDER.glob("*.pptx"))
print(f"\n模板库（用户目录）现有 {len(list(FOLDER.glob('*.pptx')))} 套，共 {total/1024/1024:.0f} MB")
