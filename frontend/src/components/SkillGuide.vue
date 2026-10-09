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
    'academic-paper': props.mode === 'structure-map'
      ? {
          steps: ['打开已经写好的大纲或正文', '点结构图，直接发送或点名那一篇', '左侧多出「论文结构图.html」', '中间能看到章节方框和箭头'],
          tips: ['不改原来的文稿', '格式转换仍用来改引用格式', '图只反映现在的结构'],
        }
      : {
          steps: ['输入论文主题或已有结果', 'AI 依次：大纲→论证→草稿→引用检查', '支持中英双语摘要、多种引用格式', '完成后可导出 MD / Word / PDF / LaTeX'],
          tips: ['有明确研究问题时质量更高', '引用格式可随时切换', '支持上传参考文献'],
        },
    'academic-paper-reviewer': {
      steps: ['粘贴或上传需要评审的论文', 'AI 模拟 5 位独立审稿人评审', '涵盖方法论、领域、跨学科、魔鬼代言人', '生成含修改建议和总体评价的报告'],
      tips: ['论文越完整评审越准', '可选不同模式：快速/方法论/完整', '报告可直接用于投稿前修改'],
    },
    'academic-pipeline': {
      steps: ['先 @ 一个文件夹，再输入题目', '发出去只列出步骤，点「开始」才写第一步', '大纲确认后会另存一份 HTML 结构图，再写初稿', '简报、综述、规划、大纲、结构图、初稿、审稿、修改、摘要、引用、声明，最后综合成终稿'],
      tips: ['选中这个入口不会马上开写', '对这一步不满意，可以直接补充后再做一次', '确认之后才会往下走'],
    },
    'literature-find': props.mode === 'files'
      ? {
          steps: ['输入检索词', '向 OpenAlex 要一小页真实记录，并标出公开 PDF', '勾选其中一部分', '放到左侧当前打开的文件夹'],
          tips: ['没有公开全文的留空，不会下载收费论文', '知网接口还留着，尚未接通', '不会编造文献'],
        }
      : props.mode === 'passage'
        ? {
            steps: ['贴一段正在写的文字', '当前模型从这段文字拟出检索词', '再向 OpenAlex 要真实记录', '对话里列出题名、作者、年份、来源和 DOI'],
            tips: ['文段涉及 Transformer 或注意力时，会去找 Attention Is All You Need', '缺的字段留空', '不会编造文献'],
          }
        : {
            steps: ['输入检索词', '向 OpenAlex 要一小页真实记录', '关键词检索受限时，先用 Crossref 定位 DOI，再向 OpenAlex 读取', '对话里列出题名、作者、年份、来源和 DOI', '缺的字段留空，不写进文件夹'],
            tips: ['知网接口还留着，尚未接通', '不会编造文献'],
          },
    'idea-debate': props.mode === 'socratic'
      ? {
          steps: ['在右边选一个模型', '写下主题和你的看法', '它会用一问一答引导你思考，一次只问一个问题', '你回答之后，它再接着问下一句'],
          tips: ['不替你下结论', '打开的文稿只带入前 2400 字'],
        }
      : props.mode === 'custom'
        ? {
            steps: ['在右边选一个模型', '问法由你写在输入框里', '思考和结果会分开'],
            tips: ['打开的文稿只带入前 2400 字'],
          }
        : {
            steps: ['点开「辩论设置」，先选要辩论的模型', '辩题可以自己写，也可以写下看法后生成，再给每位分配辩题', '对话里会标出每位的名称和辩题', '一轮说完你写意见，再开始下一轮'],
            tips: ['每位只看见辩题、看法、前面的结果和你插入的提示', '不会自动读完左侧整篇论文，程序也没有把窗口裁成 54', '可以标选轮次再整理，也可以分开整理某一位的观点。法官单独选模型'],
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
