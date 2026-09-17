<script setup lang="ts">
import { computed } from 'vue'
import { SKILL_LABELS, SKILL_DESCRIPTIONS } from '@/utils/constants'
import { Sparkles, MessageCircle, BookOpen, Lightbulb } from 'lucide-vue-next'

const props = defineProps<{ skill: string; mode: string }>()
const emit = defineEmits<{ send: [text: string] }>()

const name = computed(() => SKILL_LABELS[props.skill] || props.skill)

type Guide = { steps: string[]; tips: string[] }
const guide = computed<Guide>(() => {
  const m: Record<string, Guide> = {
    'deep-research': {
      steps: ['在下方输入研究主题', 'AI 依次执行：问题构思→文献检索→来源验证→综合分析', '每个阶段可确认或提出修改', '最终生成结构化研究简报'],
      tips: ['主题越具体越精准', '可上传 PDF 作为参考', '中途可随时追问'],
    },
    'academic-paper': {
      steps: ['输入论文主题或已有结果', 'AI 依次：大纲→论证→草稿→引用检查', '支持中英双语摘要、多种引用格式', '完成后可导出 MD / Word / PDF / LaTeX'],
      tips: ['有明确研究问题时质量更高', '引用格式可随时切换', '支持上传参考文献'],
    },
    'academic-paper-reviewer': {
      steps: ['粘贴或上传需要评审的论文', 'AI 模拟 5 位独立审稿人评审', '涵盖方法论、领域、跨学科、魔鬼代言人', '生成含修改建议和总体评价的报告'],
      tips: ['论文越完整评审越准', '可选不同模式：快速/方法论/完整', '报告可直接用于投稿前修改'],
    },
    'academic-pipeline': {
      steps: ['输入研究主题启动全流程', '自动执行：研究→撰写→验证→审稿→修订→终审', '每阶段有检查点可确认', '最终输出完整论文 + 过程记录'],
      tips: ['全流程约 1-2 小时', '适合一次性完成论文', '材料越完整质量越高'],
    },
    'kimi-cnki-search': {
      steps: ['输入中文学术关键词或短语', 'Kimi 引擎检索 CNKI / CSSCI', '输出文献列表（标题/作者/期刊/年份/摘要）', '可构建中文文献语料库'],
      tips: ['支持精确和模糊检索', '结果自动保存到左侧文件区', '多次检索自动去重'],
    },
  }
  return m[props.skill] || { steps: ['输入问题，AI 协助完成学术工作'], tips: [] }
})
</script>

<template>
  <div class="animate-fade-in w-full max-w-2xl mx-auto px-4">
    <div class="text-center mb-6">
      <div class="w-14 h-14 mx-auto mb-3 rounded-2xl bg-ruc-red-pale flex items-center justify-center">
        <Sparkles class="w-7 h-7 text-ruc-red" />
      </div>
      <h2 class="text-lg font-display font-semibold text-ruc-red mb-1">{{ name }}</h2>
      <p class="text-ruc-text-light text-sm font-ui max-w-lg mx-auto leading-relaxed">
        {{ SKILL_DESCRIPTIONS[skill] || '' }}
      </p>
    </div>

    <div class="mb-5">
      <h3 class="flex items-center gap-2 text-sm font-ui font-medium text-ruc-text mb-2">
        <BookOpen class="w-4 h-4 text-ruc-red/60" /> 使用步骤
      </h3>
      <div class="space-y-1.5">
        <div v-for="(step, i) in guide.steps" :key="i" class="flex items-start gap-3 px-4 py-2.5 rounded-xl bg-ruc-warm/60">
          <span class="w-5 h-5 rounded-full bg-ruc-red text-white text-[10px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">{{ i + 1 }}</span>
          <p class="text-sm font-ui text-ruc-text leading-relaxed">{{ step }}</p>
        </div>
      </div>
    </div>

    <div v-if="guide.tips.length" class="mb-5">
      <h3 class="flex items-center gap-2 text-sm font-ui font-medium text-ruc-text mb-2">
        <Lightbulb class="w-4 h-4 text-ruc-gold" /> 使用技巧
      </h3>
      <div class="flex flex-wrap gap-1.5">
        <span v-for="(tip, i) in guide.tips" :key="i" class="text-xs font-ui text-ruc-text-dim bg-white border border-ruc-divider px-3 py-1.5 rounded-full">
          💡 {{ tip }}
        </span>
      </div>
    </div>

    <p class="text-xs text-ruc-text-light text-center font-ui">在下方输入框开始对话</p>
  </div>
</template>
