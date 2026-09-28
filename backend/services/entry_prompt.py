"""对话框入口：聊天只说话，其余入口可以改左侧文稿。"""

from config import PROXY_BASE_URL
from providers import PROVIDERS

# 和前端 composerModes 的一句用途对齐。只放进提示，不塞整套技能文档。
MODE_LINES = {
    ("academic-paper", "plan"): "当前任务是写作规划：先把题目收成大纲和写作计划。",
    ("academic-paper", "full"): "当前任务是完整撰写：读取文件夹里已有的大纲、写作计划和材料，写成一版完整论文。",
    ("academic-paper", "outline-only"): "当前任务是大纲：只做章节大纲。",
    ("academic-paper", "revision"): "当前任务是论文修改：对照审稿或导师意见改。",
    ("academic-paper", "revision-coach"): "当前任务是修改指导：先指出该改哪里。",
    ("academic-paper", "abstract-only"): "当前任务是摘要：写中英文摘要和关键词。",
    ("academic-paper", "lit-review"): "当前任务是文献综述：写成一篇有论点的综述。",
    ("academic-paper", "lit-search"): "当前任务是查文献：知网接口尚未接通，不要编造文献。",
    ("literature-find", "search"): "当前任务是开放检索：只列出 OpenAlex 返回的记录，缺的字段留空，不要编造文献。",
    ("idea-debate", "socratic"): "当前任务是苏格拉底式提问：用户给出主题和看法，用一问一答引导思考，一次只问一个问题。",
    ("idea-debate", "contrast"): "当前任务是多模型辩论：按指定看法一次一位发言，思考和结果分开。",
    ("idea-debate", "custom"): "当前任务是自己定问法：按用户写的角度深入。",
    ("academic-paper", "format-convert"): "当前任务是格式转换：转换引用或稿件格式。",
    ("academic-paper", "citation-check"): "当前任务是引用检查：查引用是否齐全、格式是否统一。",
    ("academic-paper", "disclosure"): "当前任务是声明：写伦理、利益冲突、数据可用性声明。",
    ("deep-research", "full"): "当前任务是完整研究：检索、核对，整理成研究简报。",
    ("deep-research", "quick"): "当前任务是快速简报：先把这个题目摸清。",
    ("deep-research", "review"): "当前任务是叙述性综述：写成有结构的综述。",
    ("deep-research", "lit-review"): "当前任务是文献综述：按主题整理文献。",
    ("deep-research", "fact-check"): "当前任务是事实核查：核对一句话或一组数据。",
    ("deep-research", "socratic"): "当前任务是苏格拉底式引导：题目还没定时，用提问帮用户收拢。",
    ("deep-research", "systematic-review"): "当前任务是系统综述：按系统综述的步骤来做。",
    ("academic-paper-reviewer", "full"): "当前任务是完整审稿：从几个角度挑问题，给出修改清单。",
    ("academic-paper-reviewer", "re-review"): "当前任务是再审稿：看改过的稿还剩什么问题。",
    ("academic-paper-reviewer", "quick"): "当前任务是快速评审：交稿前快速过一遍。",
    ("academic-paper-reviewer", "methodology-focus"): "当前任务是方法论审稿：专看研究方法。",
    ("academic-paper-reviewer", "guided"): "当前任务是定向审稿：按用户指定的标准来审。",
    ("academic-paper-reviewer", "calibration"): "当前任务是审稿校准：看几份意见是否互相矛盾。",
    ("academic-pipeline", "full"): "当前任务是全流程管线：先列出步骤，用户点开始才写；一次只做一步，最后把前面的文稿收成终稿，文件写进用户 @ 的文件夹。",
}

FILE_TOOLS = "Read,Edit,Write,WebSearch,WebFetch"


def mode_instruction(skill_name: str, mode_name: str) -> str:
    return MODE_LINES.get(((skill_name or "").strip(), (mode_name or "").strip()), "")


def resolve_chat_route(provider_id: str, custom_base: str, skill_name: str) -> tuple[bool, str]:
    """返回 (是否允许改文件, 传给 Claude CLI 的 ANTHROPIC_BASE_URL)。

    空字符串表示使用 Anthropic 官方地址。聊天入口不带改文件工具。
    DeepSeek 的改文件走官方 Anthropic 兼容地址，本机转接层会丢掉工具调用。
    """
    provider = PROVIDERS.get(provider_id) or PROVIDERS["anthropic"]
    text_only = (skill_name or "") == "chat"
    custom = (custom_base or "").strip().rstrip("/")
    if provider.get("protocol") == "anthropic":
        return (not text_only), custom

    tool_url = (provider.get("tool_base_url") or "").strip().rstrip("/")
    default = (provider.get("default_base_url") or "").rstrip("/")
    if text_only or not tool_url:
        return False, PROXY_BASE_URL
    if custom.endswith("/anthropic"):
        return True, custom
    if not custom or custom == default:
        return True, tool_url
    return False, PROXY_BASE_URL
