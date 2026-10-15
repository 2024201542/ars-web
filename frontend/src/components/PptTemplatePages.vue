<template>
  <div class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" @click.self="emit('close')">
    <div class="w-full max-w-5xl max-h-[88vh] bg-white rounded-2xl border border-ruc-divider shadow-modal flex flex-col overflow-hidden">
      <header class="flex items-center gap-2 px-4 py-3 border-b border-ruc-divider">
        <h3 class="text-sm font-ui font-semibold text-ruc-text">页说明</h3>
        <span class="text-[10px] font-ui text-ruc-text-light truncate">{{ doc?.template_name || '' }}</span>
        <button class="ml-auto p-1 rounded hover:bg-ruc-warm text-ruc-text-light" @click="emit('close')"><X class="w-4 h-4" /></button>
      </header>

      <div v-if="loading" class="p-6 text-[12px] font-ui text-ruc-text-dim">正在读页说明…</div>
      <div v-else-if="error" class="p-6 text-[12px] font-ui text-ruc-error">{{ error }}</div>
      <div v-else class="flex-1 min-h-0 overflow-auto p-4 space-y-3">
        <p v-if="readonly" class="text-[11px] font-ui text-amber-800">内置模板的页说明随程序提供，不能改。</p>
        <textarea
          v-model="summary"
          rows="2"
          class="w-full rounded-lg border border-ruc-divider px-3 py-2 text-[12px] font-ui text-ruc-text"
          :disabled="readonly"
          placeholder="这套模板适合什么场合"
          @blur="saveSummary"
        />
        <ul v-if="story.length" class="text-[11px] font-ui text-ruc-text-dim space-y-0.5">
          <li v-for="(line, index) in story" :key="index">{{ line }}</li>
        </ul>
        <div class="flex flex-wrap gap-2">
          <a class="px-2 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:text-ruc-red" :href="api.getPptTemplatePagesExportUrl(templateId, 'json')">导出 JSON</a>
          <a class="px-2 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:text-ruc-red" :href="api.getPptTemplatePagesExportUrl(templateId, 'md')">导出 Markdown</a>
          <button type="button" class="px-2 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:text-ruc-red" :disabled="savingLocal" @click="saveLocal">{{ savingLocal ? '保存中…' : '存到本机文件夹' }}</button>
          <button type="button" class="px-2 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:text-ruc-red" :disabled="readonly" @click="importInput?.click()">导入页说明</button>
          <input ref="importInput" type="file" accept="application/json,.json" class="hidden" @change="onImport" />
        </div>

        <article v-for="page in pages" :key="page.page" class="rounded-xl border border-ruc-divider p-3 flex gap-3">
          <button type="button" class="relative w-36 flex-shrink-0 rounded-md bg-ruc-warm/50 overflow-hidden" style="aspect-ratio: 16 / 9" @click="zoom = page">
            <img :src="api.getPptTemplateThumbUrl(templateId, page.page)" class="absolute inset-0 w-full h-full object-contain" alt="" />
          </button>
          <div class="min-w-0 flex-1 space-y-2">
            <div class="flex items-center gap-2">
              <span class="text-[12px] font-ui text-ruc-text">第 {{ page.page }} 页</span>
              <span v-if="saved[page.page]" class="ml-auto text-[10px] font-ui text-emerald-700">已改</span>
            </div>
            <div class="flex flex-wrap gap-2">
              <label class="text-[10px] font-ui text-ruc-text-dim">角色
                <select v-model="page.role" class="ml-1 rounded border border-ruc-divider px-1 py-0.5 text-[11px]" :disabled="readonly" @change="schedule(page)">
                  <option v-for="(label, key) in ROLES" :key="key" :value="key">{{ label }}</option>
                </select>
              </label>
              <label class="text-[10px] font-ui text-ruc-text-dim">形态
                <select v-model="page.form" class="ml-1 rounded border border-ruc-divider px-1 py-0.5 text-[11px]" :disabled="readonly" @change="schedule(page)">
                  <option v-for="(label, key) in FORMS" :key="key" :value="key">{{ label }}</option>
                </select>
              </label>
              <label class="text-[10px] font-ui text-ruc-text-dim inline-flex items-center gap-1">
                <input type="checkbox" :checked="page.usable === false" :disabled="readonly" @change="toggleUnused(page, $event)" />
                不用这页
              </label>
            </div>
            <details class="text-[10px] font-ui text-ruc-text-dim">
              <summary>适合讲：{{ fitText(page) || '未选' }}</summary>
              <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                <label v-for="(label, key) in NARRATIVE" :key="key" class="inline-flex items-center gap-1">
                  <input type="checkbox" :checked="(page.narrative_fit || []).includes(key)" :disabled="readonly" @change="toggleFit(page, key, $event)" />
                  {{ label }}
                </label>
              </div>
            </details>
            <input
              v-model="page.description"
              class="w-full rounded border border-ruc-divider px-2 py-1 text-[11px] font-ui"
              :disabled="readonly"
              placeholder="一句话说明"
              @input="schedule(page)"
            />
            <p class="text-[10px] font-ui text-ruc-text-light">{{ slotText(page) }}</p>
            <p v-for="(warn, index) in page.parse_warnings || []" :key="index" class="text-[10px] font-ui text-amber-700">{{ warn }}</p>
          </div>
        </article>
      </div>
    </div>

    <div v-if="zoom" class="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-6" @click.self="zoom = null">
      <div class="relative w-full max-w-4xl bg-white rounded-xl overflow-hidden" style="aspect-ratio: 16 / 9">
        <img :src="api.getPptTemplateThumbUrl(templateId, zoom.page)" class="absolute inset-0 w-full h-full object-contain" alt="" />
        <svg class="absolute inset-0 w-full h-full" :viewBox="`0 0 ${slideW} ${slideH}`" preserveAspectRatio="xMidYMid meet">
          <g v-for="slot in zoom.slots || []" :key="slot.name + '-' + slot.frame">
            <rect v-if="slot.box" :x="slot.box[0]" :y="slot.box[1]" :width="slot.box[2]" :height="slot.box[3]" fill="none" stroke="#b91c1c" stroke-width="0.04" />
            <text v-if="slot.box" :x="slot.box[0]" :y="Math.max(0.2, slot.box[1] - 0.05)" fill="#b91c1c" font-size="0.28">{{ slot.name }}</text>
          </g>
        </svg>
        <button type="button" class="absolute top-2 right-2 p-1 rounded bg-white/80" @click="zoom = null"><X class="w-4 h-4" /></button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { X } from 'lucide-vue-next'
import { api } from '@/api'
import { toast } from '@/composables/useToast'

const props = defineProps<{ templateId: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved-local'): void }>()

const ROLES: Record<string, string> = {
  cover: '封面', toc: '目录', section: '章节过渡', content: '内容',
  summary: '总结', end: '结尾', qa: '提问', blank: '空白',
}
const FORMS: Record<string, string> = {
  bullets: '要点', numbered: '编号结论', cards: '并列卡片', compare: '左右对比',
  timeline: '时间轴', process: '流程步骤', quote: '金句', bignum: '大数字',
  image_text: '图文', table: '表格', chart: '图表', text: '大段文字', none: '无',
}
const NARRATIVE: Record<string, string> = {
  hook: '开场引子', background: '背景', significance: '意义', question: '研究问题',
  literature: '已有研究', theory: '理论框架', method: '方法与设计', data: '数据与材料',
  concept: '概念界定', principle: '原理机制', finding: '主要发现', case: '案例',
  comparison: '对比', example: '举例', misconception: '常见误区', discussion: '讨论',
  recommendation: '建议', conclusion: '结论', limitation: '不足', outlook: '展望',
  innovation: '创新点', schedule: '进度安排', takeaway: '启发', summary: '小结',
}
const SLOT_LABEL: Record<string, string> = {
  title: '标题', subtitle: '副标题', lead: '导语', body: '正文',
  section_title: '章节标题', section_index: '章节序号', section_question: '章节问题',
  quote: '金句', source: '出处', caption: '图注',
}

const doc = ref<any>(null)
const pages = ref<any[]>([])
const summary = ref('')
const loading = ref(true)
const error = ref('')
const readonly = ref(false)
const saved = ref<Record<number, boolean>>({})
const savingLocal = ref(false)
const zoom = ref<any>(null)
const importInput = ref<HTMLInputElement | null>(null)
const timers = new Map<number, number>()

const slideW = computed(() => Number(doc.value?.slide_size?.[0]) || 13.33)
const slideH = computed(() => Number(doc.value?.slide_size?.[1]) || 7.5)
const story = computed(() => ((doc.value?.deck?.template_storyline) || []).map((item: any) => {
  const heading = item.heading || '（无标题）'
  return `${heading} → ${pageSpan(item.pages || [])}`
}))

function pageSpan(list: number[]) {
  const sorted = [...list].filter((n) => Number.isFinite(n)).sort((a, b) => a - b)
  if (!sorted.length) return ''
  const ranges: string[] = []
  let start = sorted[0]
  let prev = sorted[0]
  for (const n of sorted.slice(1)) {
    if (n === prev + 1) { prev = n; continue }
    ranges.push(start === prev ? `第 ${start} 页` : `第 ${start}–${prev} 页`)
    start = prev = n
  }
  ranges.push(start === prev ? `第 ${start} 页` : `第 ${start}–${prev} 页`)
  return ranges.join('、')
}

function fitText(page: any) {
  return (page.narrative_fit || []).map((key: string) => NARRATIVE[key] || key).join('、')
}

function slotLabel(name: string) {
  if (name.endsWith('.head')) return '卡片小标题'
  if (name.endsWith('.body')) return '卡片正文'
  return SLOT_LABEL[name] || name
}

function slotText(page: any) {
  const groups = new Map<string, number>()
  for (const slot of page.slots || []) {
    const key = `${slotLabel(slot.name)} ${slot.max_chars || 0} 字`
    groups.set(key, (groups.get(key) || 0) + 1)
  }
  return [...groups.entries()].map(([key, count]) => (count > 1 ? `${key} ×${count}` : key)).join('，')
}

function applyDoc(data: any) {
  doc.value = data
  pages.value = data.pages || []
  summary.value = data.deck?.summary || ''
  readonly.value = data.source === 'builtin' || String(props.templateId).startsWith('builtin-')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    applyDoc(await api.getPptTemplatePages(props.templateId))
  } catch (e: any) {
    error.value = e.message || '页说明读不到'
  } finally {
    loading.value = false
  }
}

function schedule(page: any) {
  if (readonly.value) return
  const prev = timers.get(page.page)
  if (prev) window.clearTimeout(prev)
  timers.set(page.page, window.setTimeout(() => savePage(page), 800))
}

async function savePage(page: any) {
  try {
    const data = await api.putPptTemplatePages(props.templateId, {
      pages: [{
        page: page.page,
        role: page.role,
        form: page.form,
        narrative_fit: page.narrative_fit || [],
        description: page.description || '',
        usable: page.usable !== false,
      }],
    })
    applyDoc(data)
    saved.value = { ...saved.value, [page.page]: true }
  } catch (e: any) {
    toast.error(e.message || '这一页没有保存')
  }
}

function toggleUnused(page: any, event: Event) {
  page.usable = !(event.target as HTMLInputElement).checked
  schedule(page)
}

function toggleFit(page: any, key: string, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const current = new Set(page.narrative_fit || [])
  if (checked) {
    if (current.size >= 4) {
      (event.target as HTMLInputElement).checked = false
      toast.error('一页最多选 4 个叙事角色')
      return
    }
    current.add(key)
  } else {
    current.delete(key)
  }
  page.narrative_fit = [...current]
  schedule(page)
}

async function saveSummary() {
  if (readonly.value || summary.value === (doc.value?.deck?.summary || '')) return
  try {
    applyDoc(await api.putPptTemplatePages(props.templateId, { deck: { summary: summary.value } }))
  } catch (e: any) {
    toast.error(e.message || '简介没有保存')
  }
}

async function saveLocal() {
  if (savingLocal.value) return
  savingLocal.value = true
  try {
    const res = await api.savePptTemplatePagesLocal(props.templateId)
    toast.success(`已存到本机文件夹：${res.json}、${res.markdown}`)
    emit('saved-local')
  } catch (e: any) {
    toast.error(e.message || '没有存到本机文件夹')
  } finally {
    savingLocal.value = false
  }
}

async function onImport(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || readonly.value) return
  try {
    const res = await api.importPptTemplatePages(props.templateId, file)
    if (res.warnings?.length) toast.error(res.warnings[0])
    toast.success(`导入了 ${res.imported} 页`)
    await load()
  } catch (e: any) {
    toast.error(e.message || '导入失败')
  }
}

onMounted(load)
</script>
