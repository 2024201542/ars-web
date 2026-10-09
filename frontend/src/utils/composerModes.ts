/** 对话框底部的入口。四大功能点进去再选细项。 */

export interface ComposerMode {
  mode: string
  label: string
  hint: string
}

export interface FunctionGroup {
  skill: string
  label: string
  trial?: boolean
  planned?: boolean
  modes: ComposerMode[]
}

export const DIRECT_ENTRIES = [
  { skill: 'agent', mode: 'agent', label: 'Agent', hint: '按你的话来做，需要时可以改左侧文稿' },
  { skill: 'chat', mode: 'chat', label: '聊天', hint: '只和已接入的模型说话' },
]

export const FUNCTION_GROUPS: FunctionGroup[] = [
  {
    skill: 'academic-pipeline',
    label: '全流程管线',
    trial: true,
    modes: [
      { mode: 'full', label: '从头到定稿', hint: '先列出步骤，点开始才写；最后收成终稿' },
    ],
  },
  {
    skill: 'idea-debate',
    label: '想法深入',
    modes: [
      { mode: 'socratic', label: '苏格拉底式提问', hint: '写下主题和看法，用一问一答引导思考' },
      { mode: 'contrast', label: '多模型辩论', hint: '给每个模型一个看法，一次一位发言' },
      { mode: 'custom', label: '自己定问法', hint: '问法由你写，可选一个或多个模型' },
    ],
  },
  {
    skill: 'literature-find',
    label: '文献查找',
    modes: [
      { mode: 'search', label: '开放检索', hint: '向 OpenAlex 要真实记录。关键词检索受限时先用 Crossref 定位 DOI。知网仍未接通，不会编造文献' },
      { mode: 'passage', label: '按文段', hint: '贴一段正在写的文字。当前模型先拟检索词，再向 OpenAlex 检索。不会编造文献' },
      { mode: 'files', label: '查找文件', hint: '找出带公开 PDF 的论文，勾选后放到左侧文件夹。没有公开全文的不会下载' },
    ],
  },
  {
    skill: 'deep-research',
    label: '深度研究',
    modes: [
      { mode: 'full', label: '完整研究', hint: '检索、核对，整理成研究简报' },
      { mode: 'quick', label: '快速简报', hint: '先把这个题目摸清' },
      { mode: 'review', label: '叙述性综述', hint: '写成有结构的综述' },
      { mode: 'lit-review', label: '文献综述', hint: '按主题整理文献' },
      { mode: 'fact-check', label: '事实核查', hint: '核对一句话或一组数据' },
      { mode: 'socratic', label: '苏格拉底式引导', hint: '题目还没定时，用提问帮你收拢' },
      { mode: 'systematic-review', label: '系统综述', hint: '按系统综述的步骤来做' },
    ],
  },
  {
    skill: 'academic-paper',
    label: '论文撰写',
    modes: [
      { mode: 'plan', label: '写作规划', hint: '先把题目收成大纲和写作计划' },
      { mode: 'outline-only', label: '大纲', hint: '只做章节大纲' },
      { mode: 'full', label: '完整撰写', hint: '按已有的大纲、笔记和材料写成一版论文' },
      { mode: 'revision', label: '论文修改', hint: '对照审稿或导师意见改' },
      { mode: 'revision-coach', label: '修改指导', hint: '先指出该改哪里' },
      { mode: 'abstract-only', label: '摘要', hint: '写中英文摘要和关键词' },
      { mode: 'lit-review', label: '文献综述', hint: '写成一篇有论点的综述' },
      { mode: 'lit-search', label: '查文献', hint: '知网检索还没接通，接口先留在这里' },
      { mode: 'format-convert', label: '格式转换', hint: '转换引用或稿件格式' },
      { mode: 'structure-map', label: '结构图', hint: '按已有文稿另存一份 HTML 结构图，不改原文' },
      { mode: 'citation-check', label: '引用检查', hint: '查引用是否齐全、格式是否统一' },
      { mode: 'disclosure', label: '声明', hint: '写伦理、利益冲突、数据可用性声明' },
    ],
  },
  {
    skill: 'academic-paper-reviewer',
    label: '同行评审',
    modes: [
      { mode: 'full', label: '完整审稿', hint: '从几个角度挑问题，给出修改清单' },
      { mode: 're-review', label: '再审稿', hint: '看改过的稿还剩什么问题' },
      { mode: 'quick', label: '快速评审', hint: '交稿前快速过一遍' },
      { mode: 'methodology-focus', label: '方法论', hint: '专看研究方法' },
      { mode: 'guided', label: '定向审稿', hint: '按你指定的标准来审' },
      { mode: 'calibration', label: '审稿校准', hint: '看几份意见是否互相矛盾' },
    ],
  },
  {
    skill: 'word-draft',
    label: 'Word 文档撰写',
    planned: true,
    modes: [],
  },
]

export function entryButtonLabel(skill?: string, mode?: string) {
  const direct = DIRECT_ENTRIES.find((item) => item.skill === skill && item.mode === mode)
  if (direct) return direct.label
  for (const group of FUNCTION_GROUPS) {
    if (group.skill !== skill) continue
    const hit = group.modes.find((item) => item.mode === mode)
    if (hit) return hit.label
  }
  return 'Agent'
}

export function entryTitle(skill?: string, mode?: string) {
  const direct = DIRECT_ENTRIES.find((item) => item.skill === skill && item.mode === mode)
  if (direct) return direct.label
  for (const group of FUNCTION_GROUPS) {
    if (group.skill !== skill) continue
    const hit = group.modes.find((item) => item.mode === mode)
    if (hit) return `${group.label} · ${hit.label}`
  }
  return ''
}
