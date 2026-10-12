"""验证"图片位自动填充"：图片位识别 → 挑图 → 按位裁剪 → 替换 → 渲染看效果。"""
import io
import json
import pathlib
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services import ppt_image, ppt_template, pptx_splice  # noqa: E402

TPL_DIR = BACKEND / "assets" / "ppt_templates" / "builtin"
REAL_DIR = BACKEND / "data" / "workspaces" / "c46ff668-f8c3-46d9-ba62-7f2c271816d4" / "ppt_templates"
NODE = pathlib.Path(r"C:\Users\28473\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe")
CLI = pathlib.Path(r"D:\deepseek harness\resources\app.asar.unpacked\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js")

OUTLINE = {
    "title": "中国农村改革：国家与土地所有权关系的变化",
    "subtitle": "读书报告 · 汇报人：XXX",
    "slides": [
        {"layout": "cover", "title": "中国农村改革：国家与土地所有权关系的变化", "bullets": []},
        {"layout": "toc", "title": "汇报框架", "bullets": [
            {"text": "一、问题意识：所有权悖论"}, {"text": "二、诺斯难题"},
            {"text": "三、改革前的产权制度"}, {"text": "四、1978 年后的制度变迁"},
            {"text": "五、结论与讨论"}]},
        {"layout": "content", "title": "一、问题意识：所有权悖论", "bullets": [
            {"text": "国家既是产权界定的前提"}, {"text": "也可能成为产权被侵蚀的来源"},
            {"text": "由此形成所有权悖论"}]},
        {"layout": "image+text", "title": "二、诺斯难题", "bullets": [
            {"text": "有效率的产权制度为何难以长期维持"}, {"text": "制度变迁并非简单的效率选择"}]},
        {"layout": "image+text", "title": "三、改革前的产权制度", "bullets": [
            {"text": "集体所有与统购统销"}, {"text": "土地的排他性权利受到严格限制"}]},
        {"layout": "end", "title": "谢谢", "bullets": []},
    ],
}


def make_images() -> list[pathlib.Path]:
    from PIL import Image, ImageDraw

    folder = BACKEND / "_img_test"
    folder.mkdir(exist_ok=True)
    made = []
    for name, size, color in [("竖图.png", (900, 1400), (60, 90, 140)),
                              ("横图.png", (1600, 800), (140, 90, 60))]:
        img = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(img)
        draw.ellipse([size[0] * 0.3, size[1] * 0.25, size[0] * 0.7, size[1] * 0.6], fill=(240, 220, 180))
        draw.text((size[0] * 0.1, size[1] * 0.85), f"TEST {size[0]}x{size[1]}", fill="white")
        path = folder / name
        img.save(path)
        made.append(path)
    return made


def main() -> None:
    print("=== 内置模板的图片位 ===")
    analysis = ppt_template.load_analysis(TPL_DIR / "academic-red.analysis.json")
    for spec in analysis["specimens"]:
        print(f"  {spec['index']:>2} {spec['tag']:12s} 图片位={len(spec.get('images') or [])} 主图位={spec.get('image_i')}")

    real_files = sorted(REAL_DIR.glob("*.analysis.json"))
    real_path = REAL_DIR / "7acd6eb053b2.pptx"
    real = None
    real_json = next((f for f in real_files if "50" in json.loads(f.read_text(encoding="utf-8"))["name"]), None)
    if real_path.exists():
        # 现场重新解析（不要用旧 JSON：图片位是后加的能力）
        real = ppt_template.analyze_pptx(real_path, tid="7acd6eb053b2", name="中国人民大学模板-50", source="user")
        print(f"\n=== 人大模板-50 重新解析：{real['stats']['slides']} 页 ===")
        for spec in real["specimens"][:10]:
            slots = spec.get("images") or []
            info = "、".join(f"#{s['i']} {s['kind']} {s['w']}x{s['h']}in 比例{s['ratio']} 面积{s['area']}" for s in slots)
            print(f"  {spec['index']:>2} {spec['tag']:12s} 主图位={spec.get('image_i')}  {info or '（本页无图）'}")
        print("  版式分布：" + "、".join(f"{k}×{v}" for k, v in real["stats"]["tags"].items()))

    images = make_images()
    print(f"\n=== 测试图 ===")
    for info in ppt_image.collect([str(p) for p in images]):
        print(f"  {info['name']}  {info['width']}x{info['height']}  比例{info['ratio']}  方位={info['orient']}")

    target_tpl = real_path if real_path.exists() else (TPL_DIR / "academic-red.pptx")
    target_analysis = real if real and real_path.exists() else analysis
    out = BACKEND / "_splice_images.pptx"
    stats = pptx_splice.splice(target_analysis, OUTLINE, target_tpl, out, images=[str(p) for p in images])
    print(f"\n=== 拼接结果 ===")
    print(f"  页数 {stats['pages']}  模板 {stats['template']}")
    print(f"  可用图 {stats['images_available']} 张  已填入 {stats['images_used']}")
    print(f"  版式 {'、'.join(stats['used_tags'])}")
    if stats["warnings"]:
        print("  提示：" + "；".join(stats["warnings"][:3]))

    if NODE.exists() and CLI.exists() and out.exists():
        out_dir = BACKEND / "_render_images"
        if out_dir.exists():
            import shutil
            shutil.rmtree(out_dir)
        r = subprocess.run([str(NODE), str(CLI), "render", "--input", str(out),
                            "--output-dir", str(out_dir), "--pages", "4,5", "--dpi", "90"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            data = json.loads((r.stdout or "{}").strip().splitlines()[-1])
            print(f"  渲染 {len(data.get('images') or [])} 张 → {out_dir}")
        except Exception:
            print("  渲染失败: " + (r.stdout or r.stderr or "")[:160])


main()
