"""ARS SKILL.md 文件解析器。

从上游 academic-research-skills 项目中读取和解析技能定义。
"""

import re
import yaml
import pathlib
from typing import Optional

from config import ARS_SKILLS_PATH


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 Markdown 文件的 YAML frontmatter 和正文。"""
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if fm_match:
        try:
            metadata = yaml.safe_load(fm_match.group(1)) or {}
        except yaml.YAMLError:
            metadata = {}
        body = content[fm_match.end() :]
    else:
        metadata = {}
        body = content
    return metadata, body


def _read_md_file(path: pathlib.Path) -> str:
    """安全读取 Markdown 文件。"""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


class SkillLoader:
    """技能加载器 —— 解析 ARS SKILL.md 及其关联文件。"""

    # 技能显示名称映射
    DISPLAY_NAMES = {
        "deep-research": "深度研究",
        "academic-paper": "论文撰写",
        "academic-paper-reviewer": "同行评审",
        "academic-pipeline": "全流程管线",
        "kimi-cnki-search": "知网/CSSCI检索",
    }

    # 技能图标映射 (emoji)
    ICONS = {
        "deep-research": "search",
        "academic-paper": "edit",
        "academic-paper-reviewer": "clipboard",
        "academic-pipeline": "rocket",
        "kimi-cnki-search": "database",
    }

    # 各技能的模式定义（覆盖全部 25 种核心模式）
    MODES = {
        "deep-research": [
            {
                "name": "full",
                "display_name": "完整研究",
                "description": "执行完整的深度研究流程，依次启动 14 个专业 Agent，覆盖研究问题构思、方法论、文献检索、来源验证、综合分析、报告编写、编辑审查、偏差评估和伦理审查",
                "phases": ["研究问题", "方法论", "文献检索", "来源验证", "综合分析", "报告编写", "编辑审查", "魔鬼代言人", "偏倚评估", "伦理审查"],
                "estimated_time": "15-30分钟",
            },
            {
                "name": "quick",
                "display_name": "快速简报",
                "description": "快速生成研究主题简报，适合初步了解一个领域",
                "phases": ["研究问题", "文献检索", "简报编写"],
                "estimated_time": "5-10分钟",
            },
            {
                "name": "review",
                "display_name": "叙述性综述",
                "description": "系统检索 + 综合分析，生成结构化叙述性文献综述",
                "phases": ["研究问题", "文献检索", "来源验证", "综合分析"],
                "estimated_time": "10-20分钟",
            },
            {
                "name": "lit-review",
                "display_name": "文献综述",
                "description": "系统性地检索和分析特定主题的文献，生成带注释书目的综述报告",
                "phases": ["研究问题", "文献检索", "来源验证", "综述编写"],
                "estimated_time": "10-20分钟",
            },
            {
                "name": "fact-check",
                "display_name": "事实核查",
                "description": "验证特定声明或数据的准确性",
                "phases": ["声明分析", "来源验证", "核查报告"],
                "estimated_time": "5-10分钟",
            },
            {
                "name": "socratic",
                "display_name": "苏格拉底式引导",
                "description": "通过 5 层对话引导帮助您理清研究思路和方向",
                "phases": ["问题探索", "思路梳理", "方向确认"],
                "estimated_time": "10-20分钟",
            },
            {
                "name": "systematic-review",
                "display_name": "系统综述",
                "description": "PRISMA-compliant 系统综述，包含偏倚风险评估和元分析设计",
                "phases": ["研究问题", "PRISMA检索", "偏倚评估", "元分析设计", "系统综述报告"],
                "estimated_time": "30-60分钟",
            },
        ],
        "academic-paper": [
            {
                "name": "full",
                "display_name": "完整撰写",
                "description": "12 代理论文撰写管线，从零撰写完整学术论文（IMRaD结构），支持中英双语摘要",
                "phases": ["配置访谈", "文献策略", "大纲设计", "论证构建", "全文草稿", "引用合规", "双语摘要", "格式输出"],
                "estimated_time": "30-60分钟",
                "paper_types": ["original_research", "literature_review", "case_study", "methodology", "theoretical", "position_paper"],
            },
            {
                "name": "plan",
                "display_name": "写作规划",
                "description": "制定完整的论文写作计划和策略",
                "phases": ["配置访谈", "文献策略", "写作规划"],
                "estimated_time": "10-15分钟",
            },
            {
                "name": "outline-only",
                "display_name": "大纲模式",
                "description": "为论文设计和优化大纲结构（IMRaD格式）",
                "phases": ["配置访谈", "大纲设计"],
                "estimated_time": "5-10分钟",
                "paper_types": ["original_research", "literature_review", "case_study", "methodology", "theoretical", "position_paper"],
            },
            {
                "name": "revision",
                "display_name": "论文修改",
                "description": "根据审稿意见完善和修改论文",
                "phases": ["意见分析", "逐条回应", "论文修订"],
                "estimated_time": "15-30分钟",
            },
            {
                "name": "revision-coach",
                "display_name": "修改指导",
                "description": "AI 修改教练提供个性化论文修改建议",
                "phases": ["论文分析", "问题诊断", "改进建议"],
                "estimated_time": "10-20分钟",
            },
            {
                "name": "abstract-only",
                "display_name": "摘要模式",
                "description": "生成中英双语学术摘要 + 关键词",
                "phases": ["内容分析", "摘要生成"],
                "estimated_time": "3-5分钟",
            },
            {
                "name": "lit-review",
                "display_name": "文献综述论文",
                "description": "专为文献综述论文设计的撰写流程",
                "phases": ["领域界定", "文献检索策略", "综合分析", "综述撰写"],
                "estimated_time": "20-40分钟",
            },
            {
                "name": "format-convert",
                "display_name": "格式转换",
                "description": "在不同引用格式之间转换（APA/MLA/Chicago/IEEE/Vancouver）",
                "phases": ["格式识别", "字段提取", "格式转换"],
                "estimated_time": "3-5分钟",
            },
            {
                "name": "citation-check",
                "display_name": "引用检查",
                "description": "验证论文中的引用合规性和完整性",
                "phases": ["引用审计", "合规检查", "修正建议"],
                "estimated_time": "5-10分钟",
            },
            {
                "name": "disclosure",
                "display_name": "声明生成",
                "description": "生成伦理声明、利益冲突声明、数据可用性声明等",
                "phases": ["声明识别", "内容生成", "格式输出"],
                "estimated_time": "3-5分钟",
            },
        ],
        "academic-paper-reviewer": [
            {
                "name": "full",
                "display_name": "完整审稿",
                "description": "5 位独立审稿人（EIC + 3 位同行审稿 + 魔鬼代言人）对论文进行全面评审",
                "phases": ["领域分析", "EIC初审", "方法论审稿", "领域专家审稿", "交叉视角审稿", "魔鬼代言人挑战", "综合意见"],
                "estimated_time": "20-40分钟",
            },
            {
                "name": "re-review",
                "display_name": "再审稿",
                "description": "对修改后的论文进行第二轮审稿",
                "phases": ["差异分析", "修改验证", "再审意见"],
                "estimated_time": "15-25分钟",
            },
            {
                "name": "quick",
                "display_name": "快速评审",
                "description": "精简版 3 人审稿：EIC + 1 位领域专家 + 魔鬼代言人",
                "phases": ["EIC初审", "领域审稿", "魔鬼代言人"],
                "estimated_time": "10-15分钟",
            },
            {
                "name": "methodology-focus",
                "display_name": "方法论聚焦",
                "description": "专门审查论文的研究方法设计和实施",
                "phases": ["方法设计评估", "实施有效性", "局限性分析"],
                "estimated_time": "10-20分钟",
            },
            {
                "name": "guided",
                "display_name": "定向审稿",
                "description": "根据用户指定的审稿准则进行针对性评审",
                "phases": ["准则理解", "定向审查", "准则对照报告"],
                "estimated_time": "10-20分钟",
            },
            {
                "name": "calibration",
                "display_name": "审稿校准",
                "description": "多审稿人评分校准，检测评分偏差和不一致",
                "phases": ["独立评分", "偏差检测", "校准报告"],
                "estimated_time": "10-15分钟",
            },
        ],
        "academic-pipeline": [
            {
                "name": "full",
                "display_name": "全流程管线",
                "description": "10 阶段全流程学术管线：研究→撰写→完整性验证→审稿→修订→再审→终审→最终确认→定稿→流程总结。包含强制完整性验证和双阶段审稿",
                "phases": ["Stage1研究", "Stage2撰写", "Stage2.5完整性验证", "Stage3审稿", "Stage4修订", "Stage3'再审", "Stage4'再修订", "Stage4.5终审", "Stage5定稿", "Stage6流程总结"],
                "estimated_time": "60-120分钟",
                "paper_types": ["original_research", "literature_review", "case_study", "methodology", "theoretical", "position_paper"],
            },
        ],
        "kimi-cnki-search": [
            {
                "name": "search",
                "display_name": "知网检索",
                "description": "使用 Kimi AI 检索 CNKI 中文学术期刊文献",
                "phases": ["检索策略", "文献筛选", "结果整理"],
                "estimated_time": "3-5分钟",
            },
            {
                "name": "cssci-search",
                "display_name": "CSSCI检索",
                "description": "专门检索 CSSCI（中文社会科学引文索引）来源期刊",
                "phases": ["期刊限定", "精确检索", "结果导出"],
                "estimated_time": "3-5分钟",
            },
            {
                "name": "corpus-build",
                "display_name": "语料构建",
                "description": "批量检索并构建中文文献语料库",
                "phases": ["检索条件设计", "批量检索", "语料整理"],
                "estimated_time": "5-15分钟",
            },
        ],
    }

    # 论文类型配置
    PAPER_TYPES = [
        {"id": "original_research", "name": "原创研究", "description": "报告原创实验或研究结果"},
        {"id": "literature_review", "name": "文献综述", "description": "系统性地回顾和综合现有研究"},
        {"id": "case_study", "name": "案例研究", "description": "深入分析特定案例或实例"},
        {"id": "methodology", "name": "方法学论文", "description": "提出或评估研究方法"},
        {"id": "theoretical", "name": "理论论文", "description": "发展和阐述理论框架"},
    ]

    # 引用格式配置
    CITATION_FORMATS = [
        {"id": "apa", "name": "APA 7th Edition", "description": "美国心理学会第7版格式"},
        {"id": "chicago", "name": "Chicago Manual of Style", "description": "芝加哥格式手册"},
        {"id": "ieee", "name": "IEEE", "description": "电气电子工程师学会格式"},
        {"id": "mla", "name": "MLA 9th Edition", "description": "现代语言协会第9版格式"},
        {"id": "vancouver", "name": "Vancouver", "description": "温哥华格式（生物医学）"},
    ]

    def __init__(self, skills_path: Optional[pathlib.Path] = None):
        self.skills_path = skills_path or ARS_SKILLS_PATH

    def get_skills(self) -> list[dict]:
        """获取所有可用技能列表。"""
        skills = []
        for name in ["deep-research", "academic-paper", "academic-paper-reviewer", "academic-pipeline", "kimi-cnki-search"]:
            skill_dir = self.skills_path / name
            if not skill_dir.exists():
                continue

            skill_md = _read_md_file(skill_dir / "SKILL.md")
            metadata, _ = _parse_frontmatter(skill_md) if skill_md else ({}, "")

            modes = self.MODES.get(name, [])
            skills.append({
                "name": name,
                "display_name": self.DISPLAY_NAMES.get(name, name),
                "description": metadata.get("description", ""),
                "modes": len(modes),
                "icon": self.ICONS.get(name),
            })
        return skills

    def get_skill_modes(self, skill_name: str) -> list[dict]:
        """获取指定技能的所有模式。"""
        return self.MODES.get(skill_name, [])

    def get_skill_config(self, skill_name: str) -> dict:
        """获取技能的配置选项。"""
        if skill_name == "academic-paper":
            return {
                "paper_types": self.PAPER_TYPES,
                "citation_formats": self.CITATION_FORMATS,
                "output_formats": ["markdown", "docx", "pdf", "latex"],
            }
        if skill_name == "academic-pipeline":
            return {
                "paper_types": self.PAPER_TYPES,
                "citation_formats": self.CITATION_FORMATS,
                "output_formats": ["markdown", "docx", "pdf", "latex"],
            }
        if skill_name == "academic-paper-reviewer":
            return {"output_formats": ["markdown", "docx", "pdf"]}
        if skill_name == "kimi-cnki-search":
            return {"output_formats": ["markdown"]}
        return {"paper_types": [], "citation_formats": [], "output_formats": ["markdown"]}

    def get_agent_system_prompt(self, skill_name: str) -> str:
        """获取技能的完整 Agent 系统提示词。"""
        skill_dir = self.skills_path / skill_name
        if not skill_dir.exists():
            return f"你是一个{self.DISPLAY_NAMES.get(skill_name, skill_name)}研究助手。"

        skill_md = _read_md_file(skill_dir / "SKILL.md")
        _, body = _parse_frontmatter(skill_md)

        # 读取 Agent 定义
        agents_dir = skill_dir / "agents"
        agent_content = ""
        if agents_dir.exists():
            for agent_file in sorted(agents_dir.glob("*.md")):
                agent_md = _read_md_file(agent_file)
                _, agent_body = _parse_frontmatter(agent_md)
                agent_content += f"\n\n---\n{agent_body}"

        return body + agent_content

    def get_phase_prompt(self, skill_name: str, phase_name: str) -> str:
        """获取特定阶段的简化提示词。"""
        full_prompt = self.get_agent_system_prompt(skill_name)

        # 根据阶段名称截取相关提示
        phase_keywords = {
            "研究问题": "research question",
            "方法论": "methodology",
            "文献检索": "literature search",
            "来源验证": "source verification",
            "综合分析": "synthesis",
            "报告编写": "report compile",
            "编辑审查": "editorial review",
            "伦理审查": "ethics review",
            "简报编写": "brief report",
            "综述编写": "literature review report",
            "声明分析": "claim analysis",
            "核查报告": "verification report",
            "问题探索": "question exploration",
            "思路梳理": "idea clarification",
            "方向确认": "direction confirmation",
            "配置访谈": "configuration interview",
            "文献策略": "literature strategy",
            "大纲设计": "outline design",
            "论证构建": "argument construction",
            "全文草稿": "full draft",
            "引用合规": "citation compliance",
            "双语摘要": "bilingual abstract",
            "格式输出": "format output",
            "摘要生成": "abstract generation",
            "内容分析": "content analysis",
        }

        keyword = phase_keywords.get(phase_name, "")
        if keyword and keyword in full_prompt.lower():
            idx = full_prompt.lower().find(keyword)
            start = max(0, idx - 500)
            end = min(len(full_prompt), idx + 2000)
            return full_prompt[start:end]

        return full_prompt[:2000]


# 进程内共享单例
skill_loader = SkillLoader()
