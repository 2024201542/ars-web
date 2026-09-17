/** 所有共享常量，原在 HomeView/WorkSessionView 中各自重复定义。 */

export const SKILL_LABELS: Record<string, string> = {
  'deep-research': '深度研究',
  'academic-paper': '论文撰写',
  'academic-paper-reviewer': '同行评审',
  'academic-pipeline': '全流程管线',
  'kimi-cnki-search': '知网/CSSCI检索',
}

export const SKILL_ROUTES: Record<string, string> = {
  'deep-research': 'research',
  'academic-paper': 'paper',
  'academic-paper-reviewer': 'reviewer',
  'academic-pipeline': 'pipeline',
  'kimi-cnki-search': 'kimi',
}

export const SKILL_DESCRIPTIONS: Record<string, string> = {
  'deep-research': '通用深度研究智能体团队，13 个专业 Agent 协作，7 种模式：完整研究、快速简报、叙述性综述、文献综述、事实核查、苏格拉底式引导、系统综述。覆盖研究问题构思、方法论设计、系统文献检索、来源验证、跨源综合分析、偏倚风险评估、元分析、APA 7.0 报告编写、编辑审查、魔鬼代言人挑战和伦理审查',
  'academic-paper': '12 个 Agent 的学术论文撰写管线，10 种模式：完整撰写、写作规划、大纲模式、论文修改、修改指导、摘要模式、文献综述论文、格式转换、引用检查、声明生成。支持 6 种论文类型、5 种引用格式、中英双语摘要，可输出 Markdown / DOCX / LaTeX / PDF 格式',
  'academic-paper-reviewer': '多视角学术论文同行评审，模拟 5 位独立审稿人（主编 + 3 位同行评审 + 魔鬼代言人），支持领域自适应评审配置。6 种模式：完整审稿、再审稿、快速评审、方法论聚焦、定向审稿、审稿校准',
  'academic-pipeline': '全流程学术管线编排器，10 阶段端到端流程：研究 → 撰写 → 完整性验证 → 审稿 → 修订 → 再审 → 再修订 → 终审 → 定稿 → 流程总结。自动协调深度研究、论文撰写、同行评审三大技能，含强制完整性门控和双阶段同行评审',
  'kimi-cnki-search': '基于月之暗面 Kimi AI 的中文学术文献检索，支持 CNKI 和 CSSCI 来源期刊检索。3 种模式：知网检索、CSSCI 检索、语料构建',
}

/** 将技能名简称为最大 4 字的标签 */
export function skillShortLabel(name: string): string {
  return SKILL_LABELS[name]?.slice(0, 4) || name.slice(0, 4)
}
