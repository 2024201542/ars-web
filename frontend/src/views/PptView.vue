<template>
  <div class="min-h-screen bg-ruc-cream">
    <!-- 顶栏 -->
    <header class="sticky top-0 z-20 bg-white border-b border-ruc-divider">
      <div class="max-w-6xl mx-auto px-5 py-3 flex items-center gap-3">
        <button class="p-1.5 rounded-lg hover:bg-ruc-warm text-ruc-text-dim" title="返回" @click="goBack">
          <ChevronLeft class="w-4 h-4" />
        </button>
        <Presentation class="w-5 h-5 text-ruc-red" />
        <div class="min-w-0">
          <h1 class="text-sm font-display font-semibold text-ruc-text">PPT 生成</h1>
          <p class="text-[11px] font-ui text-ruc-text-light truncate">
            选一套模板（或主题）→ 粘贴素材 → 生成可编辑的 .pptx
          </p>
        </div>
        <div class="ml-auto flex items-center gap-2">
          <select v-model="theme" class="text-[11px] font-ui border border-ruc-divider rounded-lg px-2 py-1 bg-white text-ruc-text">
            <option v-for="t in themes" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <button
            class="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-ruc-red text-white text-[11px] font-ui disabled:opacity-50"
            :disabled="generating || !material.trim()"
            @click="generate"
          >
            <Loader2 v-if="generating" class="w-3.5 h-3.5 animate-spin" />
            <Sparkles v-else class="w-3.5 h-3.5" />
            {{ generating ? '生成中…' : '生成 PPT' }}
          </button>
        </div>
      </div>
    </header>

    <main class="max-w-6xl mx-auto px-5 py-5 space-y-5">
      <!-- 模板库 -->
      <section class="bg-white rounded-2xl border border-ruc-divider p-4">
        <div class="flex items-center gap-2 mb-3">
          <Layers class="w-4 h-4 text-ruc-red/70" />
          <h2 class="text-xs font-ui font-semibold text-ruc-text">模板库</h2>
          <span class="text-[10px] font-ui text-ruc-text-light">
            共 {{ templates.length }} 套（内置 {{ builtinCount }} / 我的 {{ userCount }}）
          </span>
          <div class="ml-auto flex items-center gap-2">
            <button
              class="px-2.5 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red"
              :disabled="uploading"
              @click="pickFile"
            >
              {{ uploading ? '解析中…' : '上传我的模板' }}
            </button>
            <button
              class="px-2.5 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red"
              :class="!selectedId ? 'bg-ruc-red-pale border-ruc-red/40 text-ruc-red' : ''"
              @click="selectedId = ''"
            >
              不用模板（按主题）
            </button>
          </div>
          <input ref="fileInput" type="file" accept=".pptx" class="hidden" @change="onFile" />
        </div>

        <div v-if="loading" class="text-[11px] font-ui text-ruc-text-light py-6 text-center">正在读取模板库…</div>
        <div v-else class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          <button
            v-for="tpl in templates"
            :key="tpl.id"
            class="text-left rounded-xl border p-2 transition-all hover:shadow-sm"
            :class="selectedId === tpl.id ? 'border-ruc-red ring-2 ring-ruc-red/20' : 'border-ruc-divider'"
            @click="selectedId = tpl.id"
          >
            <!-- 真实缩略图（有渲染器时）；拿不到就退回结构预览 -->
            <div class="relative w-full rounded-md bg-ruc-warm/60 overflow-hidden" style="aspect-ratio: 16 / 9">
              <img
                v-if="thumbs[tpl.id] !== 'failed'"
                :src="api.getPptTemplateThumbUrl(tpl.id, 1)"
                class="absolute inset-0 w-full h-full object-cover"
                :class="thumbs[tpl.id] === 'ok' ? 'opacity-100' : 'opacity-0'"
                alt=""
                @load="thumbs[tpl.id] = 'ok'"
                @error="thumbs[tpl.id] = 'failed'"
              />
              <template v-if="thumbs[tpl.id] !== 'ok'">
                <template v-for="(card, ci) in (tpl.preview || []).slice(0, 1)" :key="ci">
                  <div
                    v-for="(box, bi) in card.boxes"
                    :key="bi"
                    class="absolute rounded-[2px]"
                    :class="box.kind === 'title' ? 'bg-ruc-red/70' : 'bg-ruc-text-dim/30'"
                    :style="{
                      left: (box.x * 100) + '%',
                      top: (box.y * 100) + '%',
                      width: Math.max(4, box.w * 100) + '%',
                      height: Math.max(3, box.h * 100) + '%',
                    }"
                  />
                </template>
              </template>
              <span class="absolute right-1 top-1 text-[9px] font-ui text-ruc-text-dim bg-white/80 rounded px-1">
                {{ tpl.slides }} 页
              </span>
            </div>
            <div class="mt-2 flex items-center gap-1.5">
              <span class="text-[11px] font-ui text-ruc-text truncate">{{ tpl.name }}</span>
              <span
                class="text-[9px] font-ui px-1 rounded flex-shrink-0"
                :class="tpl.source === 'builtin' ? 'bg-ruc-warm text-ruc-text-dim' : 'bg-ruc-red-pale text-ruc-red'"
              >
                {{ tpl.source === 'builtin' ? '内置' : '我的' }}
              </span>
              <button
                v-if="tpl.source === 'user'"
                class="ml-auto text-ruc-text-light hover:text-ruc-error"
                title="删除这个模板"
                @click.stop="removeTemplate(tpl)"
              >
                <Trash2 class="w-3 h-3" />
              </button>
            </div>
            <p class="mt-1 text-[9px] font-ui text-ruc-text-light truncate">
              {{ Object.keys(tpl.tags || {}).join(' · ') }}
            </p>
          </button>
        </div>
      </section>

      <!-- 素材 -->
      <section class="bg-white rounded-2xl border border-ruc-divider p-4">
        <div class="flex items-center gap-2 mb-3">
          <FileText class="w-4 h-4 text-ruc-red/70" />
          <h2 class="text-xs font-ui font-semibold text-ruc-text">素材</h2>
          <span class="text-[10px] font-ui text-ruc-text-light">
            粘贴要讲的文字（论文段落、笔记、要点都行），或从会话里复制过来
          </span>
        </div>
        <textarea
          v-model="material"
          rows="9"
          class="w-full rounded-xl border border-ruc-divider px-3 py-2 text-[12px] font-ui text-ruc-text leading-relaxed resize-y"
          placeholder="把要做的内容贴在这里……"
        ></textarea>
        <div class="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
          <label class="text-[11px] font-ui text-ruc-text-dim">
            文件名
            <input v-model="filename" class="mt-1 w-full rounded-lg border border-ruc-divider px-2 py-1 text-[11px] font-ui" placeholder="不填就按标题" />
          </label>
          <label class="text-[11px] font-ui text-ruc-text-dim">
            页数
            <select v-model.number="pages" class="mt-1 w-full rounded-lg border border-ruc-divider px-2 py-1 text-[11px] font-ui bg-white">
              <option :value="0">按内容自定</option>
              <option :value="8">约 8 页</option>
              <option :value="12">约 12 页</option>
              <option :value="16">约 16 页</option>
            </select>
          </label>
          <label class="text-[11px] font-ui text-ruc-text-dim">
            补充要求
            <input v-model="guidance" class="mt-1 w-full rounded-lg border border-ruc-divider px-2 py-1 text-[11px] font-ui" placeholder="如：面向组会，突出结论" />
          </label>
          <label class="flex items-end gap-1.5 text-[11px] font-ui text-ruc-text-dim pb-1">
            <input v-model="saveToLocal" type="checkbox" class="accent-ruc-red" />
            存到我打开的文件夹
          </label>
        </div>
      </section>

      <!-- 结果 -->
      <section v-if="result" class="bg-white rounded-2xl border border-ruc-divider p-4">
        <div class="flex items-center gap-2 mb-2">
          <CheckCircle2 class="w-4 h-4 text-green-600" />
          <h2 class="text-xs font-ui font-semibold text-ruc-text">已生成</h2>
          <span class="text-[11px] font-ui text-ruc-text-dim">
            {{ result.file.name }} · {{ result.pages }} 页 · {{ result.model }}
            <template v-if="result.template"> · 模板 {{ result.template }}</template>
          </span>
          <a
            class="ml-auto px-2.5 py-1 rounded-lg bg-ruc-red text-white text-[11px] font-ui"
            :href="downloadUrl"
            target="_blank"
            rel="noreferrer"
          >下载</a>
        </div>
        <p class="text-[10px] font-ui text-ruc-text-light">
          保存在 {{ result.file.path }}（左侧文件栏可见；在会话里打开它就能逐页改文字并写回）
        </p>
        <p v-if="result.used_tags?.length" class="mt-1 text-[10px] font-ui text-ruc-text-light">
          用到的版式：{{ result.used_tags.join('、') }}
        </p>
        <p v-if="result.warnings?.length" class="mt-1 text-[10px] font-ui text-amber-600">
          提示：{{ result.warnings.join('；') }}
        </p>
        <!-- 真实逐页图（有渲染器时） -->
        <div v-if="result.preview_pages" class="mt-3 grid grid-cols-2 md:grid-cols-3 gap-2">
          <a
            v-for="p in result.preview_pages"
            :key="'pp' + p"
            :href="api.getPptPageImageUrl(result.file.path, p)"
            target="_blank"
            rel="noreferrer"
            class="relative block rounded-lg border border-ruc-divider overflow-hidden bg-ruc-warm/40"
            style="aspect-ratio: 16 / 9"
          >
            <img
              v-if="pagesOk[p] !== 'failed'"
              :src="api.getPptPageImageUrl(result.file.path, p)"
              class="absolute inset-0 w-full h-full object-cover"
              :class="pagesOk[p] === 'ok' ? 'opacity-100' : 'opacity-0'"
              alt=""
              @load="pagesOk[p] = 'ok'"
              @error="pagesOk[p] = 'failed'"
            />
            <span class="absolute left-1 bottom-1 text-[9px] font-ui text-ruc-text-dim bg-white/85 rounded px-1">
              第 {{ p }} 页
            </span>
          </a>
        </div>
        <p v-if="!renderOk" class="mt-2 text-[10px] font-ui text-ruc-text-light">
          （这台机器上没找到渲染器，所以只能看大纲；装了 DSH 自带的 LibreOffice Kit 就能出真图）
        </p>
        <div class="mt-3 space-y-1.5 max-h-72 overflow-auto">
          <div
            v-for="(s, i) in (result.outline?.slides || [])"
            :key="i"
            class="rounded-lg border border-ruc-divider px-2.5 py-1.5"
          >
            <p class="text-[11px] font-ui text-ruc-text">
              {{ i + 1 }}. {{ s.title }}
              <span v-if="s.layout" class="text-[9px] text-ruc-text-light">[{{ s.layout }}]</span>
            </p>
            <p v-if="s.bullets?.length" class="text-[10px] font-ui text-ruc-text-dim mt-0.5">
              {{ slideBullets(s) }}
            </p>
          </div>
        </div>
      </section>

      <p class="text-[10px] font-ui text-ruc-text-light pb-6">
        提示：上传的模板会被解析成"版式样本"（封面/目录/要点页/两栏/大数字/引用/分节/结尾），生成时按内容形状自动挑选并替换文字，模板的配色与版式保持不变。
      </p>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { toast } from '@/composables/useToast'
import type { PptTemplate } from '@/types'
import {
  ChevronLeft, Presentation, Layers, FileText, Sparkles, Loader2, Trash2, CheckCircle2,
} from 'lucide-vue-next'

const router = useRouter()
const templates = ref<PptTemplate[]>([])
const themes = ref<{ id: string; name: string }[]>([])
const theme = ref('academic-red')
const selectedId = ref('')
const material = ref('')
const filename = ref('')
const pages = ref(12)
const guidance = ref('')
const saveToLocal = ref(false)
const loading = ref(false)
const uploading = ref(false)
const generating = ref(false)
const result = ref<any>(null)
const fileInput = ref<HTMLInputElement | null>(null)
// 'ok' = 真图加载成功；'failed' = 没渲染器/渲染失败 → 保留结构预览
const thumbs = ref<Record<string, 'ok' | 'failed'>>({})
const pagesOk = ref<Record<number, 'ok' | 'failed'>>({})
const renderOk = ref(true)

const builtinCount = computed(() => templates.value.filter((t) => t.source === 'builtin').length)
const userCount = computed(() => templates.value.filter((t) => t.source === 'user').length)
const downloadUrl = computed(() => {
  const f = result.value?.file
  return f ? api.getPptFileUrl(f.path) : '#'
})

function bulletText(line: any): string {
  return Array.isArray(line) ? line.join('　·　') : String(line || '')
}

function slideBullets(slide: any): string {
  const list = (slide?.bullets || []).map((b: any) => (typeof b === 'string' ? b : b?.text || ''))
  return list.filter(Boolean).join('　·　')
}

function goBack() {
  router.push('/')
}

async function load() {
  loading.value = true
  try {
    const data = await api.listPptTemplates()
    templates.value = data.templates || []
    if (!selectedId.value && templates.value.length) selectedId.value = templates.value[0].id
  } catch (e: any) {
    toast.error('模板库读不到：' + (e.message || e))
  } finally {
    loading.value = false
  }
}

async function loadThemes() {
  try {
    const data = await api.listPptThemes()
    themes.value = data.themes || []
    theme.value = data.default || 'academic-red'
  } catch { /* 主题取不到就用默认 */ }
}

function pickFile() {
  fileInput.value?.click()
}

async function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  try {
    const item = await api.uploadPptTemplate(file)
    templates.value = [item, ...templates.value.filter((t) => t.id !== item.id)]
    selectedId.value = item.id
    toast.success(`已加入模板：${item.name}（${item.slides} 页）`)
  } catch (e: any) {
    toast.error(e.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function removeTemplate(tpl: PptTemplate) {
  try {
    await api.deletePptTemplate(tpl.id)
    templates.value = templates.value.filter((t) => t.id !== tpl.id)
    if (selectedId.value === tpl.id) selectedId.value = ''
    toast.success('已删除模板')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

async function generate() {
  if (generating.value || !material.value.trim()) return
  generating.value = true
  result.value = null
  pagesOk.value = {}
  try {
    const data = await api.generatePpt({
      material_text: material.value,
      template_id: selectedId.value,
      theme: theme.value,
      pages: pages.value,
      guidance: guidance.value,
      filename: filename.value,
      save_to_local: saveToLocal.value,
    })
    result.value = data
    toast.success(`已生成：${data.file.name}（${data.pages} 页）`)
  } catch (e: any) {
    toast.error(e.message || '生成失败')
  } finally {
    generating.value = false
  }
}

onMounted(async () => {
  try {
    const s = await api.getPptRenderStatus()
    renderOk.value = Boolean(s.available)
  } catch {
    renderOk.value = false
  }
  void load()
  void loadThemes()
})
</script>
