"""全流程管线：按论文写作顺序，一次只做现有功能里的一步。"""

STEPS = [
    {"group": "深度研究", "label": "快速简报", "file": "01-研究简报.txt", "task": "先把题目摸清，写成一份研究简报。"},
    {"group": "深度研究", "label": "文献综述", "file": "02-文献综述.txt", "task": "按主题整理文献，写成一篇文献综述。"},
    {"group": "论文撰写", "label": "写作规划", "file": "03-写作规划.txt", "task": "把题目收成大纲和写作计划。"},
    {"group": "论文撰写", "label": "大纲", "file": "04-论文大纲.txt", "task": "只做章节大纲。"},
    {"group": "论文撰写", "label": "结构图", "file": "论文结构图.html", "task": "只根据论文大纲画出结构。页面白底，每一章一个方框，箭头表示先后。样式写在这一个 HTML 里。不要用图片，不要写脚本，不要改大纲和其他文稿。"},
    {"group": "论文撰写", "label": "完整撰写", "file": "05-论文初稿.txt", "task": "按文件夹里已有的简报、综述、规划和大纲，写成一版完整论文。"},
    {"group": "同行评审", "label": "快速评审", "file": "06-审稿意见.txt", "task": "对照论文初稿快速过一遍，列出要改的问题。"},
    {"group": "论文撰写", "label": "论文修改", "file": "07-论文修改稿.txt", "task": "对照审稿意见改论文初稿，写成修改稿。"},
    {"group": "论文撰写", "label": "摘要", "file": "08-摘要.txt", "task": "为修改稿写中英文摘要和关键词。"},
    {"group": "论文撰写", "label": "引用检查", "file": "09-引用检查.txt", "task": "检查修改稿里的引用是否齐全、格式是否统一，写出检查结果。"},
    {"group": "论文撰写", "label": "声明", "file": "10-声明.txt", "task": "写伦理、利益冲突和数据可用性声明。"},
    {"group": "论文撰写", "label": "终稿", "file": "11-论文终稿.txt", "task": "综合文件夹里前面各步已经写好的文稿，整理成一篇可以交出去的论文终稿。摘要、正文、参考文献和声明放在同一篇里。"},
]

ASK_FOLDER = "请在消息里 @ 一个文件夹。每一步生成的文件都会放进这个文件夹，确认之后才进行下一步。"


def _pipeline_of(message: dict) -> dict | None:
    raw = message.get("metadata")
    if not raw:
        return None
    try:
        import json
        meta = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    found = meta.get("pipeline") if isinstance(meta, dict) else None
    return found if isinstance(found, dict) else None


def last_pipeline(messages: list[dict]) -> dict | None:
    for message in reversed(messages or []):
        if message.get("role") != "assistant":
            continue
        found = _pipeline_of(message)
        if found:
            return found
    return None


def mentioned_folder(text: str, directories: list[dict]) -> str:
    raw = text or ""
    paths = [item.get("path") or "" for item in directories if item.get("is_dir") and item.get("path")]
    for path in sorted(paths, key=len, reverse=True):
        name = path.split("/")[-1]
        if f"@{path}" in raw or f"@{name}" in raw or f'@"{name}"' in raw:
            return path
    return ""


def _wants_final(text: str) -> bool:
    raw = text or ""
    return any(word in raw for word in ("终稿", "定稿", "综合上面", "最后一份", "最后一步"))


def _stored_index(prior: dict | None) -> int:
    if not prior or "index" not in prior:
        return -1
    return int(prior["index"])


def _step_index(prior: dict | None) -> int:
    """按已经写好的文件名对齐步骤。中途加了结构图时，旧进度不会串到别的文稿上。"""
    stored = _stored_index(prior)
    if not prior:
        return stored
    file = str(prior.get("file") or "").replace("\\", "/").split("/")[-1]
    label = str(prior.get("label") or "").strip()
    if file:
        for i, step in enumerate(STEPS):
            if step["file"] == file:
                return i
    if label and label != "待开始":
        for i, step in enumerate(STEPS):
            if step["label"] == label:
                return i
    return stored


def _clean_topic(text: str, folder: str) -> str:
    raw = text or ""
    name = folder.split("/")[-1] if folder else ""
    for token in (
        f"@{folder}" if folder else "",
        f"@{name}" if name else "",
        f'@"{name}"' if name else "",
        f"[文件夹: {folder}]" if folder else "",
        "用户问题:",
        "请分析以上文件内容",
        "---",
    ):
        if token:
            raw = raw.replace(token, " ")
    return " ".join(raw.split()).strip()


def _preview(folder: str, topic: str) -> dict:
    lines = [f"{i + 1}. {step['label']} → {step['file']}" for i, step in enumerate(STEPS)]
    text = (
        "步骤先列在这里，还没有开始写。\n\n"
        f"文件夹：{folder}\n"
        f"题目：{topic or '（还没写题目）'}\n\n"
        + "\n".join(lines)
        + "\n\n点下面的「开始」才做第一步。想改题目，直接再发一句。"
    )
    return {
        "skip_model": True,
        "text": text,
        "model_prompt": "",
        "mode_line": "",
        "pipeline": {
            "index": -1,
            "total": len(STEPS),
            "group": "",
            "label": "待开始",
            "file": "",
            "folder": folder,
            "awaiting": True,
            "done": False,
            "need_folder": False,
            "next_label": STEPS[0]["label"],
            "topic": topic,
        },
    }


def resolve_pipeline(messages: list[dict], user_message: str, action: str, directories: list[dict]) -> dict:
    """决定这一轮做哪一步。发出题目只列出步骤；点开始之后才调用模型。"""
    prior = last_pipeline(messages)
    folder = ((prior or {}).get("folder") or "").strip()
    mentioned = mentioned_folder(user_message, directories)
    if mentioned:
        folder = mentioned
    topic = ((prior or {}).get("topic") or "").strip()
    continuing = (action or "") == "continue" and bool(prior and prior.get("awaiting"))
    fresh = _clean_topic(user_message, folder)
    revising_plan = not continuing and (
        not prior or prior.get("done") or prior.get("need_folder") or _stored_index(prior) < 0
    )
    if revising_plan and fresh:
        topic = fresh
    if continuing:
        index = _step_index(prior) + 1
    elif prior and prior.get("awaiting"):
        index = _step_index(prior)
    elif prior and prior.get("done") and _wants_final(user_message):
        index = len(STEPS) - 1
    else:
        index = -1

    if index >= len(STEPS):
        rel = f"{folder}/{STEPS[-1]['file']}" if folder else STEPS[-1]["file"]
        return {
            "skip_model": True,
            "text": "全流程已经做完。各步文件都在这个文件夹里。",
            "model_prompt": "",
            "mode_line": "",
            "pipeline": {
                "index": len(STEPS) - 1,
                "total": len(STEPS),
                "folder": folder,
                "awaiting": False,
                "done": True,
                "label": STEPS[-1]["label"],
                "group": STEPS[-1]["group"],
                "file": rel,
                "next_label": "",
                "topic": topic,
            },
        }
    if not folder:
        return {
            "skip_model": True,
            "text": ASK_FOLDER,
            "model_prompt": "",
            "mode_line": "",
            "pipeline": {
                "index": -1,
                "total": len(STEPS),
                "folder": "",
                "awaiting": False,
                "done": False,
                "need_folder": True,
                "label": "",
                "group": "",
                "file": "",
                "next_label": STEPS[0]["label"],
                "topic": topic,
            },
        }
    if index < 0:
        return _preview(folder, topic)

    step = STEPS[index]
    last = index == len(STEPS) - 1
    rel = f"{folder}/{step['file']}"
    next_label = "" if last else STEPS[index + 1]["label"]
    note = ""
    if prior and prior.get("awaiting") and not continuing and fresh:
        note = f"用户对这一步的补充：{fresh}。"
    html_step = step["file"].lower().endswith(".html")
    kind = (
        "这是 HTML。用方框和箭头画出结构，样式写在这个文件里，不要用图片，不要写脚本，不要改已有文稿。"
        if html_step
        else "这是 txt，不要另存成 md。"
    )
    mode_line = (
        f"当前是全流程第 {index + 1}/{len(STEPS)} 步：{step['group']} · {step['label']}。"
        f"这一步只做这件事：{step['task']}{note}"
        f"先阅读文件夹「{folder}」里已经有的文件，不要改那些旧文件。"
        f"本步必须用 Write 把全文保存为「{rel}」，这是用户点名要留下的文稿。{kind}"
        "这一轮只能写这一个文件。不要提前做后面的步骤，也不要把后面的步骤写进同一个文件。"
        "写完用两三句话说明这一步做了什么、文件在哪，然后停下来等用户确认。"
    )
    model_prompt = (
        f"论文题目和用户要求：\n{topic or user_message}\n\n"
        f"现在只做第 {index + 1}/{len(STEPS)} 步：{step['group']} · {step['label']}。\n"
        f"{step['task']}\n"
        f"只把这一步的全文写入「{rel}」。{kind}先看文件夹「{folder}」里已有的文件。写完就停。"
    )
    return {
        "skip_model": False,
        "text": "",
        "model_prompt": model_prompt,
        "mode_line": mode_line,
        "pipeline": {
            "index": index,
            "total": len(STEPS),
            "group": step["group"],
            "label": step["label"],
            "file": rel,
            "folder": folder,
            "awaiting": not last,
            "done": last,
            "need_folder": False,
            "next_label": next_label,
            "topic": topic,
        },
    }
