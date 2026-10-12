"""端到端测拼接引擎：解析好的模板 + 一份大纲 → 出片 + 渲染成图。"""
import io
import json
import pathlib
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services import ppt_template, pptx_splice  # noqa: E402

TPL_DIR = BACKEND / "assets" / "ppt_templates" / "builtin"
NODE = pathlib.Path(r"C:\Users\28473\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe")
CLI = pathlib.Path(r"D:\deepseek harness\resources\app.asar.unpacked\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js")

OUTLINE = {
    "title": "中国农村改革：国家与土地所有权关系的变化",
    "subtitle": "周其仁（1995）读书报告 · 汇报人：XXX",
    "slides": [
        {"layout": "cover", "title": "中国农村改革：国家与土地所有权关系的变化",
         "bullets": [], "notes": "开场：交代文章出处、作者与本文要回答的问题。"},
        {"layout": "toc", "title": "汇报框架",
         "bullets": [
             {"text": "一、问题意识：产权与国家的互相塑造", "children": []},
             {"text": "二、已有讨论：所有权悖论与诺斯难题", "children": []},
             {"text": "三、改革前的产权制度及其由来", "children": []},
             {"text": "四、国家控制下的集体经济与政策调整", "children": []},
             {"text": "五、交易产生的所有权与结论", "children": []},
         ], "notes": "先交代全文五部分结构。"},
        {"layout": "content", "title": "一、问题意识：产权与国家的互相塑造",
         "bullets": [
             {"text": "如果不把国家及其代理人的行为引进来，就无法理解产权安排", "children": []},
             {"text": "国家既是产权界定的前提，也是产权被侵蚀的来源", "children": []},
             {"text": "由此形成「所有权悖论」：有效产权需要国家，国家又可能毁掉它", "children": []},
         ], "notes": "这一页是全文的理论起点。"},
        {"layout": "content", "title": "二、已有讨论：两个未解的难题",
         "bullets": [
             {"text": "诺斯难题：为什么有效率的产权制度难以长期维持", "children": []},
             {"text": "所有权的排他性与国家强制力之间的张力", "children": []},
             {"text": "既有研究多把制度变迁归因于外部冲击", "children": []},
             {"text": "较少解释行为主体在约束下的策略选择", "children": []},
             {"text": "本文试图用中国经验回应这两点", "children": []},
         ], "notes": "文献部分，注意与后文经验分析呼应。"},
        {"layout": "two-col", "title": "三、两种解释的对照",
         "bullets": [
             {"text": "既有解释：制度变迁由外部冲击与效率压力驱动", "children": []},
             {"text": "本文解释：国家、集体与农户在约束下互相博弈的结果", "children": []},
         ], "notes": "对照两栏，可口头展开。"},
        {"layout": "big-number", "title": "关键数据",
         "bullets": [
             {"text": "50 年", "children": []},
             {"text": "1949—1999：制度变迁的时间跨度与三个关键节点", "children": []},
         ], "notes": "数字页，讲清节点。"},
        {"layout": "section", "title": "四、结论与讨论",
         "bullets": [], "notes": "转入结论。"},
        {"layout": "end", "title": "谢谢", "bullets": [], "notes": "请老师与同学批评指正。"},
    ],
}

def main() -> None:
    analysis = ppt_template.load_analysis(TPL_DIR / "academic-red.analysis.json")
    assert analysis, "缺少模板解析结果"
    out = BACKEND / "_splice_test.pptx"
    stats = pptx_splice.splice(analysis, OUTLINE, TPL_DIR / "academic-red.pptx", out)
    print(f"拼接完成：{stats['pages']} 页  模板={stats['template']}")
    print("用到的版式：", "、".join(stats["used_tags"]))
    if stats["warnings"]:
        print("提示：")
        for w in stats["warnings"]:
            print("  -", w)
    # 回读确认文字确实进去了
    from services.pptx_edit import read_slides
    slides = read_slides(out)
    print("\n回读逐页：")
    for s in slides:
        first = ""
        if s["bullets"]:
            first = str(s["bullets"][0].get("text") if isinstance(s["bullets"][0], dict) else s["bullets"][0])
        print(f"  第{s['index']}页 [{s['title'][:26]}] 要点{len(s['bullets'])}条 首条={first[:26]!r} 备注{len(s['notes'])}字")

    if NODE.exists() and CLI.exists():
        out_dir = BACKEND / "_render_splice"
        r = subprocess.run([str(NODE), str(CLI), "render", "--input", str(out),
                            "--output-dir", str(out_dir), "--dpi", "110"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        data = json.loads((r.stdout or "{}").strip().splitlines()[-1] or "{}")
        print(f"\n渲染 {len(data.get('images') or [])} 张 → {out_dir}")
        print("缺字体：", data.get("missingFonts") or "无")


if __name__ == "__main__":
    main()
