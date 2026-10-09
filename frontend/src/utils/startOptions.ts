/** 首页输入框上的入口。默认是论文撰写 · 写作规划。 */

export interface StartOption {
  id: string
  group: '工作流' | '工具'
  skill: string
  mode: string
  label: string
  modeLabel: string
  hint: string
  trial?: boolean
}

export const START_OPTIONS: StartOption[] = [
  {
    id: 'paper-plan',
    group: '工作流',
    skill: 'academic-paper',
    mode: 'plan',
    label: '论文撰写',
    modeLabel: '写作规划',
    hint: '先把题目收成大纲和写作计划',
  },
  {
    id: 'paper-full',
    group: '工作流',
    skill: 'academic-paper',
    mode: 'full',
    label: '论文撰写',
    modeLabel: '完整撰写',
    hint: '从问题写到一版草稿',
  },
  {
    id: 'research-full',
    group: '工作流',
    skill: 'deep-research',
    mode: 'full',
    label: '深度研究',
    modeLabel: '完整研究',
    hint: '检索、核对，整理成研究简报',
  },
  {
    id: 'review-full',
    group: '工作流',
    skill: 'academic-paper-reviewer',
    mode: 'full',
    label: '同行评审',
    modeLabel: '完整审稿',
    hint: '从几个角度挑问题，给出修改清单',
  },
  {
    id: 'pipeline-full',
    group: '工作流',
    skill: 'academic-pipeline',
    mode: 'full',
    label: '全流程管线',
    modeLabel: '从头到定稿',
    hint: '先列出步骤，点开始才写；最后收成终稿',
    trial: true,
  },
  {
    id: 'paper-lit',
    group: '工具',
    skill: 'academic-paper',
    mode: 'lit-review',
    label: '文献综述',
    modeLabel: '文献综述',
    hint: '把书目收成有论点的综述',
  },
  {
    id: 'paper-revision',
    group: '工具',
    skill: 'academic-paper',
    mode: 'revision',
    label: '按意见修改',
    modeLabel: '论文修改',
    hint: '对照导师或审稿意见逐条改',
  },
  {
    id: 'cite',
    group: '工具',
    skill: 'academic-paper',
    mode: 'citation-check',
    label: '引用检查',
    modeLabel: '引用检查',
    hint: '查引用是否完整、格式是否统一',
  },
  {
    id: 'abstract',
    group: '工具',
    skill: 'academic-paper',
    mode: 'abstract-only',
    label: '摘要',
    modeLabel: '摘要',
    hint: '写中英文摘要和关键词',
  },
  {
    id: 'format',
    group: '工具',
    skill: 'academic-paper',
    mode: 'format-convert',
    label: '格式转换',
    modeLabel: '格式转换',
    hint: '转换引用格式或稿件格式',
  },
  {
    id: 'review-quick',
    group: '工具',
    skill: 'academic-paper-reviewer',
    mode: 'quick',
    label: '投稿前自查',
    modeLabel: '快速评审',
    hint: '交稿前从审稿人角度过一遍',
  },
  {
    id: 'socratic',
    group: '工具',
    skill: 'deep-research',
    mode: 'socratic',
    label: '苏格拉底式引导',
    modeLabel: '引导',
    hint: '题目还没定时，用提问帮你收拢',
  },
]

export const DEFAULT_START_ID = 'paper-plan'

export const QUICK_STARTS = [
  { id: 'paper-plan', label: '写作规划' },
  { id: 'paper-lit', label: '文献综述' },
  { id: 'review-quick', label: '投稿前自查' },
]

export const SUGGESTIONS = [
  {
    startId: 'paper-plan',
    text: '帮我把「晚清报刊里的女性形象」收成一个可以写的论文问题，并列出章节大纲。',
  },
  {
    startId: 'paper-lit',
    text: '这篇论文的文献综述只是在罗列书目。请改成有论点的综述结构，并指出还缺哪几类材料。',
  },
  {
    startId: 'paper-revision',
    text: '我收到导师意见：论证有跳跃，引文格式不统一。请逐条说明该怎么改。',
  },
]

const EXTRA_MODE_LABELS: Record<string, string> = {
  full: '完整',
  plan: '写作规划',
  'outline-only': '大纲',
  revision: '论文修改',
  'revision-coach': '修改指导',
  'abstract-only': '摘要',
  'lit-review': '文献综述',
  'format-convert': '格式转换',
  'structure-map': '结构图',
  'citation-check': '引用检查',
  disclosure: '声明',
  quick: '快速',
  socratic: '引导',
  search: '开放检索',
  passage: '按文段',
  files: '查找文件',
  'lit-search': '查文献',
  review: '叙述性综述',
  'fact-check': '事实核查',
  'systematic-review': '系统综述',
  're-review': '再审稿',
  'methodology-focus': '方法论',
  guided: '定向审稿',
}

export function startTitle(option: StartOption) {
  if (option.label === option.modeLabel) return option.label
  return `${option.label} · ${option.modeLabel}`
}

export function findStart(id: string) {
  return START_OPTIONS.find((item) => item.id === id) || START_OPTIONS[0]
}

export function describeSession(skill: string, mode: string) {
  const hit = START_OPTIONS.find((item) => item.skill === skill && item.mode === mode)
  if (hit) return hit.modeLabel
  return EXTRA_MODE_LABELS[mode] || mode
}
