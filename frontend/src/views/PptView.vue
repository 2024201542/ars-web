<template>
  <div class="min-h-screen bg-ruc-cream">
    <!-- 顶栏 -->
    <header class="sticky top-0 z-20 bg-white border-b border-ruc-divider">
      <div class="max-w-7xl mx-auto px-5 py-3 flex items-center gap-3">
        <button class="p-1.5 rounded-lg hover:bg-ruc-warm text-ruc-text-dim" title="返回" @click="goBack">
          <ChevronLeft class="w-4 h-4" />
        </button>
        <ListChecks class="w-5 h-5 text-ruc-red" />
        <div class="min-w-0">
          <h1 class="text-sm font-display font-semibold text-ruc-text">PPT 计划</h1>
          <p class="text-[11px] font-ui text-ruc-text-light truncate">
            {{ plan?.title || '未命名' }}
            <template v-if="plan"> · {{ plan.slides?.length || 0 }} 页</template>
            <template v-if="planPath"> · {{ planPath }}</template>
          </p>
        </div>
        <div class="ml-auto flex items-center gap-2">
          <button
            v-if="canUndo"
            type="button"
            class="px-3 py-1.5 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red disabled:opacity-50"
            :disabled="pageBusy !== 0"
            @click="undoLast"
          >{{ pageBusy === -1 ? '撤销中…' : '撤销' }}</button>
          <select
            v-model="templateId"
            class="text-[11px] font-ui border border-ruc-divider rounded-lg px-2 py-1 bg-white text-ruc-text max-w-[220px]"
          >
            <option value="">按主题（内置版式）</option>
            <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <label class="flex items-center gap-1 text-[11px] font-ui text-ruc-text-dim whitespace-nowrap">
            <input v-model="saveToLocal" type="checkbox" class="accent-ruc-red" />
            存到我打开的文件夹
          </label>
          <button
            class="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-ruc-red text-white text-[11px] font-ui disabled:opacity-50"
            :disabled="composing || !plan"
            @click="compose"
          >
            <Loader2 v-if="composing" class="w-3.5 h-3.5 animate-spin" />
            <Sparkles v-else class="w-3.5 h-3.5" />
            {{ composing ? '出片中…' : '生成 PPT' }}
          </button>
        </div>
      </div>
    </header>

    <main class="max-w-7xl mx-auto px-5 py-5 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_400px] gap-5">
      <!-- 左：逐页计划 -->
      <section class="space-y-3">
        <div v-if="loading" class="bg-white rounded-2xl border border-ruc-divider p-6 text-center text-[12px] font-ui text-ruc-text-light">
          正在读计划…
        </div>
        <div v-else-if="!plan" class="bg-white rounded-2xl border border-ruc-divider p-6 space-y-3">
          <p class="text-[12px] font-ui text-ruc-text-dim">
            没有找到计划。可以在对话里说「根据这篇材料做个 PPT」，也可以在这里直接贴素材出一版计划。
          </p>
          <textarea
            v-model="material"
            rows="6"
            class="w-full rounded-xl border border-ruc-divider px-3 py-2 text-[12px] font-ui"
            placeholder="把要讲的文字贴在这里……"
          ></textarea>
          <button
            class="px-3 py-1.5 rounded-lg bg-ruc-red text-white text-[11px] font-ui disabled:opacity-50"
            :disabled="making || !material.trim()"
            @click="makePlan"
          >{{ making ? '正在读材料、列计划…' : '出一版计划' }}</button>
        </div>

        <template v-else>
          <div class="bg-white rounded-2xl border border-ruc-divider p-3 flex items-center gap-2">
            <input
              v-model="instruction"
              class="flex-1 rounded-lg border border-ruc-divider px-2.5 py-1.5 text-[11px] font-ui"
              placeholder="用一句话改计划，比如「第 6 页改成时间轴」「整体压到 10 页」"
              @keyup.enter="revise"
            />
            <button
              class="px-3 py-1.5 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red disabled:opacity-50"
              :disabled="revising || !instruction.trim()"
              @click="revise"
            >{{ revising ? '改中…' : '让它改' }}</button>
          </div>

          <p v-if="reviewLine" class="text-[11px] font-ui text-ruc-text-dim px-1">{{ reviewLine }}</p>
          <div v-if="storyIssues.length" class="bg-white rounded-2xl border border-ruc-divider p-3 space-y-1">
            <p class="text-[11px] font-ui text-amber-800">讲法检查：{{ storyIssues.length }} 个问题</p>
            <p v-for="(issue, issueIndex) in storyIssues" :key="issue.code + '-' + issue.page + '-' + issueIndex" class="text-[11px] font-ui text-ruc-text-dim">
              <button type="button" class="text-ruc-red" @click="jumpPage(issue.page)">第 {{ issue.page }} 页</button>
              {{ issue.detail }}
            </p>
          </div>

          <article
            v-for="(slide, i) in plan.slides"
            :key="i"
            :id="'slide-' + (i + 1)"
            class="bg-white rounded-2xl border border-ruc-divider p-3"
          >
            <div v-if="pickOpen === i" class="mb-2 rounded-lg border border-ruc-divider bg-ruc-cream/60 p-2">
              <p v-if="pickBusy" class="text-[10px] font-ui text-ruc-text-light">正在列候选页…</p>
              <div v-else class="flex gap-2 overflow-x-auto">
                <button
                  v-for="choice in pickChoices"
                  :key="'pick-' + i + '-' + choice.page"
                  type="button"
                  class="flex-shrink-0 w-28 text-left"
                  @click="choosePick(i, choice.page)"
                >
                  <img
                    :src="api.getPptTemplateThumbUrl(templateId, choice.page)"
                    class="w-full rounded border border-ruc-divider bg-white"
                    style="aspect-ratio: 16 / 9"
                    alt=""
                  />
                  <span class="mt-0.5 block text-[10px] font-ui text-ruc-text-dim">
                    第 {{ choice.page }} 页 · {{ choice.score }} 分
                  </span>
                </button>
              </div>
            </div>
            <div class="flex items-center gap-2 mb-2">
              <span class="text-[11px] font-ui font-semibold text-ruc-text">{{ i + 1 }}</span>
              <span class="text-[10px] font-ui px-1.5 py-0.5 rounded bg-ruc-warm text-ruc-text-dim">
                {{ layoutName(slide.layout) }}
              </span>
              <span class="text-[10px] font-ui text-ruc-text-light">{{ slide.layout }}</span>
              <button
                v-if="slide.template_page || slide.pick_fallback"
                type="button"
                class="text-[10px] font-ui px-1.5 py-0.5 rounded border border-ruc-divider text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red"
                :title="(slide.pick_reason || []).join('；')"
                @click="openPick(i)"
              >{{ pickLabel(slide) }}</button>
              <span v-if="(plan.quality?.thin_pages || []).includes(i + 1)"
                    class="text-[10px] font-ui px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">偏薄</span>
              <span v-if="slide.from" class="text-[10px] font-ui text-ruc-text-light truncate">· 来自 {{ slide.from }}</span>
            </div>

            <!-- 标题 -->
            <div v-if="hasField(slide.layout, 'title')" class="mb-2">
              <input
                v-model="slide.title"
                class="w-full rounded-lg border px-2 py-1 text-[12px] font-ui"
                :class="over('title', slide.title, slide.layout) ? 'border-ruc-error text-ruc-error' : 'border-ruc-divider'"
                placeholder="这张的标题（写成一句结论）"
              />
              <p class="mt-0.5 text-[10px] font-ui" :class="over('title', slide.title, slide.layout) ? 'text-ruc-error' : 'text-ruc-text-light'">
                {{ count(slide.title) }}/{{ limitOf(slide.layout, 'title') }} 字
              </p>
            </div>

            <!-- 简单字段：金句 / 出处 / 解读 / 小结 / 序号 / 图片序号 -->
            <div v-for="key in scalarKeys(slide.layout)" :key="key" class="mb-2">
              <label class="text-[10px] font-ui text-ruc-text-light">{{ fieldLabel(slide.layout, key) }}</label>
              <textarea
                v-if="key === 'quote' || key === 'note' || key === 'takeaway'"
                v-model="slide[key]"
                rows="2"
                class="w-full rounded-lg border px-2 py-1 text-[11px] font-ui"
                :class="over(key, slide[key], slide.layout) ? 'border-ruc-error text-ruc-error' : 'border-ruc-divider'"
              ></textarea>
              <input
                v-else
                v-model="slide[key]"
                class="w-full rounded-lg border px-2 py-1 text-[11px] font-ui"
                :class="over(key, slide[key], slide.layout) ? 'border-ruc-error text-ruc-error' : 'border-ruc-divider'"
              />
              <p class="mt-0.5 text-[10px] font-ui" :class="over(key, slide[key], slide.layout) ? 'text-ruc-error' : 'text-ruc-text-light'">
                {{ count(slide[key]) }}/{{ limitOf(slide.layout, key) }}
              </p>
            </div>

            <!-- 字符串数组：points / info / subs -->
            <div v-for="key in stringArrayKeys(slide.layout)" :key="key" class="mb-2">
              <label class="text-[10px] font-ui text-ruc-text-light">{{ fieldLabel(slide.layout, key) }}</label>
              <div v-for="(_, j) in (slide[key] || [])" :key="j" class="flex items-start gap-1 mt-1">
                <textarea
                  v-model="slide[key][j]"
                  rows="1"
                  class="flex-1 rounded-lg border px-2 py-1 text-[11px] font-ui"
                  :class="over(key, slide[key][j], slide.layout) ? 'border-ruc-error text-ruc-error' : 'border-ruc-divider'"
                ></textarea>
                <span class="text-[10px] font-ui pt-1.5 w-10 text-right"
                      :class="over(key, slide[key][j], slide.layout) ? 'text-ruc-error' : 'text-ruc-text-light'">
                  {{ count(slide[key][j]) }}/{{ limitOf(slide.layout, key) }}
                </span>
                <button class="text-ruc-text-light hover:text-ruc-error pt-1" title="删掉这条" @click="removeAt(slide, key, j)">✕</button>
              </div>
              <button class="mt-1 text-[10px] font-ui text-ruc-red" @click="addTo(slide, key)">+ 加一条</button>
            </div>

            <!-- 对象数组：items / cards / nodes / rows / stats -->
            <div v-for="key in objectArrayKeys(slide.layout)" :key="key" class="mb-2">
              <label class="text-[10px] font-ui text-ruc-text-light">{{ fieldLabel(slide.layout, key) }}</label>
              <div
                v-for="(row, j) in (slide[key] || [])"
                :key="j"
                class="mt-1 rounded-lg border border-ruc-divider p-2 space-y-1"
              >
                <div v-for="sub in subFields(slide.layout, key)" :key="sub.key" class="flex items-start gap-1">
                  <span class="text-[10px] font-ui text-ruc-text-light pt-1.5 w-12 flex-shrink-0">{{ sub.label }}</span>
                  <textarea
                    v-model="row[sub.key]"
                    rows="1"
                    class="flex-1 rounded-lg border px-2 py-1 text-[11px] font-ui"
                    :class="over(key + '.' + sub.key, row[sub.key], slide.layout) ? 'border-ruc-error text-ruc-error' : 'border-ruc-divider'"
                  ></textarea>
                  <span class="text-[10px] font-ui pt-1.5 w-10 text-right"
                        :class="over(key + '.' + sub.key, row[sub.key], slide.layout) ? 'text-ruc-error' : 'text-ruc-text-light'">
                    {{ count(row[sub.key]) }}/{{ limitOf(slide.layout, key + '.' + sub.key) }}
                  </span>
                </div>
                <button class="text-[10px] font-ui text-ruc-text-light hover:text-ruc-error" @click="slide[key].splice(j, 1)">删掉这一项</button>
              </div>
              <button class="mt-1 text-[10px] font-ui text-ruc-red" @click="addObject(slide, key)">+ 加一项</button>
            </div>

            <!-- 对比页的两栏 -->
            <div v-for="side in groupKeys(slide.layout)" :key="side" class="mb-2 rounded-lg border border-ruc-divider p-2">
              <label class="text-[10px] font-ui text-ruc-text-dim">{{ fieldLabel(slide.layout, side) }}</label>
              <div class="flex items-start gap-1 mt-1">
                <span class="text-[10px] font-ui text-ruc-text-light pt-1.5 w-12">栏标题</span>
                <input
                  v-model="slide[side].head"
                  class="flex-1 rounded-lg border px-2 py-1 text-[11px] font-ui"
                  :class="over(side + '.head', slide[side]?.head, slide.layout) ? 'border-ruc-error text-ruc-error' : 'border-ruc-divider'"
                />
                <span class="text-[10px] font-ui pt-1.5 w-10 text-right text-ruc-text-light">
                  {{ count(slide[side]?.head) }}/{{ limitOf(slide.layout, side + '.head') }}
                </span>
              </div>
              <div v-for="(_, j) in (slide[side]?.points || [])" :key="j" class="flex items-start gap-1 mt-1">
                <textarea
                  v-model="slide[side].points[j]"
                  rows="1"
                  class="flex-1 rounded-lg border px-2 py-1 text-[11px] font-ui"
                  :class="over(side + '.points', slide[side].points[j], slide.layout) ? 'border-ruc-error text-ruc-error' : 'border-ruc-divider'"
                ></textarea>
                <span class="text-[10px] font-ui pt-1.5 w-10 text-right text-ruc-text-light">
                  {{ count(slide[side].points[j]) }}/{{ limitOf(slide.layout, side + '.points') }}
                </span>
              </div>
            </div>

            <!-- 讲稿 -->
            <div v-if="'notes' in slide" class="mt-1">
              <label class="text-[10px] font-ui text-ruc-text-light">讲稿（写进备注）</label>
              <textarea v-model="slide.notes" rows="2"
                        class="w-full rounded-lg border border-ruc-divider px-2 py-1 text-[11px] font-ui text-ruc-text-dim"></textarea>
            </div>
          </article>

          <p v-if="overCount" class="text-[11px] font-ui text-ruc-error">
            有 {{ overCount }} 个字段超出上限，出片时会被自动截短——建议先手动改短。
          </p>
        </template>
      </section>

      <!-- 右：缩略图与问题 -->
      <aside class="space-y-3">
        <section v-if="result" class="bg-white rounded-2xl border border-ruc-divider p-3">
          <div class="flex items-center gap-2 mb-2">
            <CheckCircle2 class="w-4 h-4 text-green-600" />
            <span class="text-[11px] font-ui text-ruc-text truncate">{{ result.name }}</span>
            <span class="text-[10px] font-ui text-ruc-text-light">{{ result.pages }} 页</span>
            <a class="ml-auto text-[10px] font-ui text-ruc-red" :href="api.getPptFileUrl(result.path, result.source || '')" target="_blank" rel="noreferrer">下载</a>
          </div>
          <p class="text-[10px] font-ui text-ruc-text-light break-all">{{ result.dir }}</p>
          <div class="mt-2 grid grid-cols-2 gap-2 max-h-[60vh] overflow-auto">
            <div v-for="t in result.thumbs" :key="t.page" class="space-y-1">
              <a
                :href="api.getPptPageImageUrl(result.path, t.page, result.source || '', result.rev || '')"
                target="_blank"
                rel="noreferrer"
                class="relative block rounded-lg border border-ruc-divider overflow-hidden bg-ruc-warm/40"
                style="aspect-ratio: 16 / 9"
              >
                <img :src="api.getPptPageImageUrl(result.path, t.page, result.source || '', result.rev || '')" class="absolute inset-0 w-full h-full object-cover" alt="" />
                <span class="absolute left-1 bottom-1 text-[9px] font-ui text-ruc-text-dim bg-white/85 rounded px-1">{{ t.page }}</span>
              </a>
              <input
                class="w-full rounded border border-ruc-divider px-1.5 py-1 text-[10px] font-ui"
                placeholder="这页哪里不好？"
                :disabled="pageBusy === t.page"
                @keyup.enter="editThisPage(t.page, $event)"
              />
            </div>
          </div>
        </section>

        <section v-if="result" class="bg-white rounded-2xl border border-ruc-divider p-3">
          <h2 class="text-[11px] font-ui font-semibold text-ruc-text mb-1">自检</h2>
          <p v-if="result.base_confirmed === false" class="mb-1 text-[10px] font-ui text-amber-800">
            这套模板的底板是自动猜的，可能留下示例字。回到对话里点「模板 → 设置底板」。
          </p>
          <p v-if="result.template_pages?.length" class="mb-1 text-[10px] font-ui text-ruc-text-dim">
            内容用了模板第 {{ result.template_pages.join('、') }} 页。
          </p>
          <p v-if="!result.issues?.length" class="text-[11px] font-ui text-green-700">没有发现问题。</p>
          <ul v-else class="space-y-1">
            <li v-for="group in issueGroups(result.issues)" :key="group.kind" class="text-[10px] font-ui text-amber-700">
              {{ group.kind }} {{ group.count }} 项。{{ group.hint }}
            </li>
          </ul>
          <button
            v-if="issueGroups(result.issues).some((g) => g.kind === 'offslide' || g.kind === 'overlap')"
            type="button"
            class="mt-2 px-2 py-1 rounded bg-ruc-red text-white text-[10px] font-ui disabled:opacity-50"
            :disabled="repairing"
            @click="repairDeck"
          >{{ repairing ? '正在修…' : '一键修掉' }}</button>
          <p v-if="result.warnings?.length" class="mt-2 text-[10px] font-ui text-amber-600">
            提示：{{ result.warnings.map((w: any) => w.detail || w).join('；') }}
          </p>
          <p v-if="result.overflow?.length" class="mt-1 text-[10px] font-ui text-amber-600">
            超限截短：{{ result.overflow.length }} 处
          </p>
        </section>

        <section v-if="plan" class="bg-white rounded-2xl border border-ruc-divider p-3">
          <h2 class="text-[11px] font-ui font-semibold text-ruc-text mb-1">出片说明</h2>
          <p class="text-[10px] font-ui text-ruc-text-light leading-relaxed">
            内容按计划画进模板的安全区，模板原有的页眉、校徽、页码保留。
            改完字段点右上「生成 PPT」整份重出（本地操作，几秒到十几秒）。
          </p>
          <button
            class="mt-2 w-full px-3 py-1.5 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red"
            @click="openLibrary"
          >去模板库设置底板</button>
        </section>
      </aside>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { toast } from '@/composables/useToast'
import type { PptTemplate } from '@/types'
import { ChevronLeft, ListChecks, Sparkles, Loader2, CheckCircle2 } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()

const planPath = ref('')
const planSource = ref('')
const plan = ref<any>(null)
const specs = ref<Record<string, any>>({})
const limits = ref<Record<string, Record<string, number>>>({})
const templates = ref<PptTemplate[]>([])
const templateId = ref('')
const saveToLocal = ref(false)
const material = ref('')
const instruction = ref('')
const loading = ref(false)
const making = ref(false)
const revising = ref(false)
const composing = ref(false)
const repairing = ref(false)
const result = ref<any>(null)
const canUndo = ref(false)
const pageBusy = ref(0)
const pickOpen = ref(-1)
const pickChoices = ref<any[]>([])
const pickBusy = ref(false)
const storyIssues = computed(() => {
  const items = plan.value?.story_issues
  return Array.isArray(items) ? items : []
})
const reviewLine = computed(() => {
  const review = plan.value?.review
  if (!review) return ''
  const scores = review.scores_after && Object.keys(review.scores_after).length
    ? review.scores_after
    : review.scores_before
  if (!scores || typeof scores !== 'object') return ''
  const nums = Object.values(scores).map(item => Number(item)).filter(item => !Number.isNaN(item))
  if (!nums.length) return ''
  const avg = nums.reduce((sum, item) => sum + item, 0) / nums.length
  const fixed = Array.isArray(review.fixed_pages) ? review.fixed_pages.length : 0
  const same = review.same_model ? '。评委和写稿是同一个模型' : ''
  return `衔接评分 ${avg.toFixed(1)} / 5，修了 ${fixed} 页${same}`
})

function jumpPage(page: number) {
  document.getElementById('slide-' + page)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const FORM_NAMES: Record<string, string> = {
  bullets: '要点', numbered: '编号结论', cards: '并列卡片', compare: '左右对比',
  timeline: '时间轴', process: '流程步骤', quote: '金句', bignum: '大数字',
  image_text: '图文', table: '表格', chart: '图表', text: '大段文字', none: '无',
}
const ROLE_NAMES: Record<string, string> = {
  cover: '封面', toc: '目录', section: '章节过渡', content: '内容', summary: '总结', end: '结尾',
}

function pickLabel(slide: any): string {
  if (!slide?.template_page) return '没有合适的模板页'
  const kind = FORM_NAMES[slide.template_form] || ROLE_NAMES[slide.template_role] || '模板页'
  const shown = slide.template_form && slide.template_form !== 'none' ? kind : (ROLE_NAMES[slide.template_role] || kind)
  return `模板第 ${slide.template_page} 页 · ${shown}`
}

const PUNCT = /[，。、；：？！“”‘’（）《》〈〉【】—…·,.;:?!'"()\[\]{}<>~`\-—_/\\|\s]/g

function count(text: any): number {
  return String(text ?? '').replace(PUNCT, '').length
}

function limitOf(layout: string, key: string): number {
  const table = limits.value[layout] || {}
  const dot = key.lastIndexOf('.')
  const candidates = [key, key + '[]']
  if (dot > 0) {
    const head = key.slice(0, dot)
    const tail = key.slice(dot + 1)
    candidates.push(`${head}[].${tail}`, `${head}.${tail}[]`)
  }
  for (const candidate of candidates) {
    if (typeof table[candidate] === 'number') return table[candidate]
  }
  return 0
}

function issueGroups(issues: any[]) {
  const groups: Record<string, { kind: string; count: number; hint: string }> = {}
  for (const issue of issues || []) {
    const kind = String(issue?.kind || 'other')
    if (!groups[kind]) groups[kind] = { kind, count: 0, hint: issue?.hint || '' }
    groups[kind].count += 1
  }
  return Object.values(groups)
}

function over(key: string, value: any, layout: string): boolean {
  const cap = limitOf(layout, key)
  return cap > 0 && count(value) > cap
}

const overCount = computed(() => {
  if (!plan.value) return 0
  let n = 0
  for (const slide of plan.value.slides || []) {
    const fields = limits.value[slide.layout] || {}
    for (const key of Object.keys(fields)) {
      if (!key.includes('[]') && !key.includes('.')) {
        if (count(slide[key]) > fields[key]) n += 1
      }
    }
  }
  return n
})

function specFields(layout: string): any[] {
  return specs.value[layout]?.fields || []
}

function layoutName(layout: string): string {
  return specs.value[layout]?.name || layout
}

function hasField(layout: string, key: string): boolean {
  return specFields(layout).some((f) => f.key === key)
}

function fieldLabel(layout: string, key: string): string {
  const field = specFields(layout).find((f) => f.key === key)
  return field?.label || key
}

function scalarKeys(layout: string): string[] {
  return specFields(layout)
    .filter((f) => !f.item && !f.group && f.key !== 'title' && !f.min)
    .map((f) => f.key)
}

function stringArrayKeys(layout: string): string[] {
  return specFields(layout).filter((f) => !f.item && !f.group && f.min).map((f) => f.key)
}

function objectArrayKeys(layout: string): string[] {
  return specFields(layout).filter((f) => f.item).map((f) => f.key)
}

function groupKeys(layout: string): string[] {
  return specFields(layout).filter((f) => f.group).map((f) => f.key)
}

function subFields(layout: string, key: string): any[] {
  return specFields(layout).find((f) => f.key === key)?.item || []
}

function addTo(slide: any, key: string) {
  if (!Array.isArray(slide[key])) slide[key] = []
  slide[key].push('')
}

function removeAt(slide: any, key: string, index: number) {
  slide[key].splice(index, 1)
}

function addObject(slide: any, key: string) {
  const subs = subFields(slide.layout, key)
  if (!Array.isArray(slide[key])) slide[key] = []
  slide[key].push(Object.fromEntries(subs.map((s: any) => [s.key, ''])))
}

async function openPick(index: number) {
  if (pickOpen.value === index) {
    pickOpen.value = -1
    return
  }
  if (!templateId.value) {
    toast.error('先在右上角选一套模板')
    return
  }
  pickOpen.value = index
  pickBusy.value = true
  pickChoices.value = []
  try {
    const data = await api.repickPptPlan({
      plan_path: planPath.value,
      source: planSource.value,
      slide: index + 1,
      template_id: templateId.value,
    })
    pickChoices.value = data.candidates || []
  } catch (e: any) {
    pickOpen.value = -1
    toast.error(e?.message || '候选页读不到')
  } finally {
    pickBusy.value = false
  }
}

async function choosePick(index: number, page: number) {
  pickBusy.value = true
  try {
    const data = await api.repickPptPlan({
      plan_path: planPath.value,
      source: planSource.value,
      slide: index + 1,
      page,
      template_id: templateId.value,
    })
    if (data.plan) plan.value = data.plan
    pickOpen.value = -1
    await loadPlan()
  } catch (e: any) {
    toast.error(e?.message || '没换成这一页')
  } finally {
    pickBusy.value = false
  }
}

function goBack() { router.push('/ppt') }
function openLibrary() { router.push('/ppt') }

async function loadLayouts() {
  try {
    const data = await api.listPptLayouts()
    specs.value = data.specs || {}
    limits.value = data.limits || {}
  } catch (e: any) {
    toast.error('版式清单读不到：' + (e.message || e))
  }
}

async function loadTemplates() {
  try {
    const data = await api.listPptTemplates()
    templates.value = data.templates || []
  } catch { /* 模板库读不到就先按主题 */ }
}

async function loadPlan() {
  const path = String(route.query.plan || '')
  if (!path) return
  loading.value = true
  try {
    const data = await api.readPptPlan(path, String(route.query.source || ''))
    plan.value = data.plan
    planPath.value = data.plan_path || path
    planSource.value = data.source || String(route.query.source || '')
    if (route.query.template) templateId.value = String(route.query.template)
    else if (data.plan?.template_id) templateId.value = String(data.plan.template_id)
    applyOutput(data.plan)
  } catch (e: any) {
    toast.error('计划读不出来：' + (e.message || e))
  } finally {
    loading.value = false
  }
}

async function makePlan() {
  if (making.value || !material.value.trim()) return
  making.value = true
  try {
    const data = await api.makePptPlan({ material_text: material.value, pages: 0 })
    plan.value = data.plan
    planPath.value = ''
    toast.success(`已列出 ${data.plan?.slides?.length || 0} 页计划（还没存盘，生成时会存）`)
  } catch (e: any) {
    toast.error(e.message || '出计划失败')
  } finally {
    making.value = false
  }
}

async function revise() {
  if (revising.value || !instruction.value.trim()) return
  if (!planPath.value) {
    toast.warning('这份计划还没存盘，先在对话里生成一份再改')
    return
  }
  revising.value = true
  try {
    const data = await api.revisePptPlan({
      plan_path: planPath.value,
      source: planSource.value,
      instruction: instruction.value,
    })
    plan.value = data.plan
    instruction.value = ''
    toast.success('计划已更新')
  } catch (e: any) {
    toast.error(e.message || '改计划失败')
  } finally {
    revising.value = false
  }
}

function applyOutput(doc: any) {
  const output = doc?.output
  if (!output?.path) return
  const pages = Array.isArray(doc.slides) ? doc.slides.length : 0
  const same = result.value?.path === output.path
  result.value = {
    ...(result.value || {}),
    path: output.path,
    source: output.source || planSource.value,
    name: String(output.path).split('/').pop() || 'PPT',
    pages,
    rev: same && result.value?.rev ? result.value.rev : (output.rev || ''),
    thumbs: Array.from({ length: pages }, (_, index) => ({ page: index + 1 })),
    issues: same ? (result.value?.issues || []) : [],
  }
}

async function editThisPage(page: number, event: KeyboardEvent) {
  const input = event.target as HTMLInputElement
  const text = input.value.trim()
  if (!text || pageBusy.value || !planPath.value) return
  pageBusy.value = page
  canUndo.value = false
  try {
    const data = await api.editPpt({
      plan_path: planPath.value,
      source: planSource.value,
      instruction: text,
      page,
    })
    input.value = ''
    await loadPlan()
    if (result.value) {
      result.value = { ...result.value, rev: data.rev || result.value.rev, issues: data.issues || [] }
    }
    canUndo.value = Boolean(data.path || result.value?.path)
    toast.success(data.reply || '已改这一页')
  } catch (e: any) {
    toast.error(e.message || '没改成')
  } finally {
    pageBusy.value = 0
  }
}

async function undoLast() {
  const path = result.value?.path
  if (!path || pageBusy.value) return
  pageBusy.value = -1
  try {
    const data = await api.undoPptEdit({ path, source: result.value?.source || planSource.value })
    await loadPlan()
    if (result.value) result.value = { ...result.value, rev: data.rev, issues: data.issues || [] }
    canUndo.value = false
    toast.success('已撤回到上一版')
  } catch (e: any) {
    toast.error(e.message || '撤销失败')
  } finally {
    pageBusy.value = 0
  }
}

async function repairDeck() {
  if (repairing.value || !result.value?.path) return
  repairing.value = true
  try {
    const fixed = await api.repairPpt({ path: result.value.path, source: result.value.source || '' })
    result.value = { ...result.value, issues: fixed.issues, repaired: fixed.repaired, rev: fixed.rev }
    const left = fixed.issues?.length || 0
    toast.success(left ? `已修，还剩 ${left} 项` : '已修，自检没问题了')
  } catch (e: any) {
    toast.error(e.message || '修改失败')
  } finally {
    repairing.value = false
  }
}

async function compose() {
  if (composing.value || !plan.value) return
  if (!planPath.value) {
    toast.warning('这份计划还没存盘：先在对话里生成，或点「出一版计划」后从对话里走一遍')
    return
  }
  composing.value = true
  result.value = null
  try {
    const data = await api.composePpt({
      plan_path: planPath.value,
      source: planSource.value,
      template_id: templateId.value,
      save_to_local: saveToLocal.value,
      plan: plan.value,
    })
    result.value = data
    const issues = data.issues?.length || 0
    toast.success(`已出片：${data.name}（${data.pages} 页${issues ? `，自检 ${issues} 项` : '，自检没问题'}）`)
  } catch (e: any) {
    toast.error(e.message || '出片失败')
  } finally {
    composing.value = false
  }
}

onMounted(async () => {
  await loadLayouts()
  void loadTemplates()
  await loadPlan()
  const page = Number(route.query.page || 0)
  if (page) {
    await nextTick()
    jumpPage(page)
  }
})
</script>
