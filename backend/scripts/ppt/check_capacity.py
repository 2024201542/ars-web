"""看"容量感知挑页"的效果：同一套模板，长内容会挑到装得下的页。"""
import io
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from services.ppt import ppt_template as t  # noqa: E402

TPL = BACKEND / "data" / "workspaces" / "c46ff668-f8c3-46d9-ba62-7f2c271816d4" / "ppt_templates" / "7acd6eb053b2.pptx"
analysis = t.analyze_pptx(TPL, tid="7acd6eb053b2", name="人大模板-50", source="user")

print("=== 各页的文字容量（正文框能装多少字 / 碎片小框数）===")
specs = sorted(analysis["specimens"], key=lambda s: -(s.get("capacity_chars") or 0))
for spec in specs[:8]:
    title = next((f["text"] for f in spec["frames"] if f["i"] == spec["title_i"]), "")
    print(f"  第{spec['index']+1:>2}页 {spec['tag']:11s} 容量{spec.get('capacity_chars'):>4}字  "
          f"碎片{spec.get('fragmented')}个  「{title[:20]}」")

print("\n=== 挑页结果（needed = 内容大概多少字）===")
for needed in (60, 120, 220):
    row = []
    for tag in ["toc", "bullets-4", "bullets-5", "cards-3"]:
        spec = t.pick_specimen(analysis, tag, needed_chars=needed)
        row.append(f"{tag}→第{spec['index']+1}页(容量{spec.get('capacity_chars')})")
    print(f"  需要 {needed:>3} 字： " + "  ".join(row))
