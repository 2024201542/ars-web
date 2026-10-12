<template>
  <!-- 模板选择面板：左边列表（真封面图），右边整页预览，可上传自己的模板 -->
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" @click.self="$emit('close')">
    <div class="w-full max-w-5xl max-h-[86vh] bg-white rounded-2xl border border-ruc-divider shadow-modal flex flex-col overflow-hidden">
      <header class="flex items-center gap-2 px-4 py-3 border-b border-ruc-divider">
        <LayoutTemplate class="w-4 h-4 text-ruc-red" />
        <h3 class="text-sm font-ui font-semibold text-ruc-text">选择 PPT 模板</h3>
        <span class="text-[10px] font-ui text-ruc-text-light">
          {{ templates.length }} 套（内置 {{ builtin }} / 我的 {{ mine }}）· 点一下看预览，满意就「用这套」
        </span>
        <button
          class="ml-auto px-2.5 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red"
          :disabled="uploading"
          @click="pickFile"
        >{{ uploading ? '解析中…' : '上传 .pptx 模板' }}</button>
        <button
          class="px-2.5 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red"
          :disabled="shotBusy"
          @click="shotInput?.click()"
        >{{ shotBusy ? '识别中…' : '从截图建模板' }}</button>
        <button
          v-if="current && current.source === 'user'"
          class="px-2.5 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red"
          :disabled="refining"
          :title="'让 qwen-vl 看一遍这张模板，校正标题/正文/配图位（约 30 秒）'"
          @click="runVisionRefine"
        >{{ refining ? '校正中…' : '视觉校正' }}</button>
        <button
          v-if="current && current.source === 'user'"
          class="px-2.5 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red"
          :disabled="rebuilding"
          title="把「整页导出成图片、字改不了」的页重建成可编辑页（每页约 5 秒）"
          @click="runRebuild"
        >{{ rebuilding ? '重建中…' : '重建图片页' }}</button>
        <a
          class="px-2.5 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red"
          href="#/ppt"
          @click="$emit('close')"
        >模板库管理</a>
        <button class="p-1 rounded hover:bg-ruc-warm text-ruc-text-light" @click="$emit('close')"><X class="w-4 h-4" /></button>
        <input ref="fileInput" type="file" accept=".pptx" class="hidden" @change="onFile" />
        <input ref="shotInput" type="file" accept="image/*" multiple class="hidden" @change="onShots" />
      </header>

      <div class="flex-1 min-h-0 flex">
        <!-- 左：模板列表 -->
        <div class="w-72 border-r border-ruc-divider overflow-y-auto p-3 space-y-2">
          <button
            class="w-full text-left rounded-xl border px-3 py-2"
            :class="!selectedId ? 'border-ruc-red bg-ruc-red-pale/50' : 'border-ruc-divider hover:border-ruc-red/40'"
            @click="selectedId = ''; previewPage = 1"
          >
            <span class="text-[12px] font-ui text-ruc-text">不用模板（按主题）</span>
            <span class="block text-[10px] font-ui text-ruc-text-light mt-0.5">用内置版式库，换主题即可换配色</span>
          </button>
          <button
            v-for="tpl in templates"
            :key="tpl.id"
            class="w-full text-left rounded-xl border p-2 flex gap-2"
            :class="selectedId === tpl.id ? 'border-ruc-red bg-ruc-red-pale/40' : 'border-ruc-divider hover:border-ruc-red/40'"
            @click="select(tpl)"
          >
            <span class="relative w-24 flex-shrink-0 rounded-md bg-ruc-warm/60 overflow-hidden" style="aspect-ratio: 16 / 9">
              <!-- 只给"当前选中"的那套拉真封面：一次只渲染一张，否则 11 套同时渲染会把机器压垮 -->
              <img
                v-if="selectedId === tpl.id && thumbs[tpl.id] !== 'failed'"
                :src="api.getPptTemplateThumbUrl(tpl.id, 1)"
                class="absolute inset-0 w-full h-full object-cover"
                :class="thumbs[tpl.id] === 'ok' ? 'opacity-100' : 'opacity-0'"
                alt=""
                @load="thumbs[tpl.id] = 'ok'"
                @error="thumbs[tpl.id] = 'failed'"
              />
              <span class="absolute inset-0 flex items-center justify-center text-[9px] font-ui text-ruc-text-light">
                {{ tpl.slides }} 页
              </span>
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-[11px] font-ui text-ruc-text truncate">{{ tpl.name }}</span>
              <span class="block text-[9px] font-ui text-ruc-text-light mt-0.5">
                {{ tpl.source === 'builtin' ? '内置' : '我的' }} · {{ tpl.slides }} 页
              </span>
              <span class="block text-[9px] font-ui text-ruc-text-light truncate mt-0.5">
                {{ Object.keys(tpl.tags || {}).slice(0, 4).join(' · ') }}
              </span>
            </span>
            <span
              v-if="tpl.source === 'user'"
              class="self-start text-ruc-text-light hover:text-ruc-error"
              title="删除这个模板"
              @click.stop="remove(tpl)"
            ><Trash2 class="w-3 h-3" /></span>
          </button>
        </div>

        <!-- 右：整页预览 -->
        <div class="flex-1 min-w-0 overflow-y-auto p-3">
          <div v-if="!selectedId" class="h-full flex flex-col items-center justify-center text-center gap-2">
            <Presentation class="w-8 h-8 text-ruc-divider" />
            <p class="text-[11px] font-ui text-ruc-text-dim">没有选模板：会用内置版式库 + 你在顶栏选的主题出片。</p>
            <p class="text-[10px] font-ui text-ruc-text-light">也可以左边挑一套看看效果。</p>
          </div>
          <div v-else>
            <div class="flex items-center gap-2 mb-2">
              <span class="text-[11px] font-ui text-ruc-text-dim">第 {{ previewPage }} / {{ currentSlides }} 页</span>
              <input
                v-model.number="previewPage"
                type="range" min="1" :max="Math.max(1, currentSlides)"
                class="flex-1 accent-ruc-red"
              />
              <span class="text-[10px] font-ui text-ruc-text-light">{{ currentName }}</span>
            </div>
            <div class="rounded-xl border border-ruc-divider overflow-hidden bg-ruc-warm/40 relative" style="aspect-ratio: 16 / 9">
              <img
                v-if="previewOk !== 'failed'"
                :key="previewSrc"
                :src="previewSrc"
                class="w-full h-full object-contain"
                :class="previewOk === 'ok' ? 'opacity-100' : 'opacity-0'"
                alt=""
                @load="previewOk = 'ok'"
                @error="previewOk = 'failed'"
              />
              <div v-if="previewOk !== 'ok'" class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center px-4">
                <template v-if="previewOk === 'failed'">
                  <p class="text-[11px] font-ui text-ruc-text-dim">{{ previewError || '这一页渲染失败或太慢' }}</p>
                  <button class="px-2.5 py-1 rounded-lg border border-ruc-divider text-[11px] font-ui text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red" @click="retryPreview">
                    重试
                  </button>
                </template>
                <p v-else class="text-[11px] font-ui text-ruc-text-light">
                  正在渲染第 {{ previewPage }} 页…（真实模板第一次要几秒，之后有缓存）
                </p>
              </div>
            </div>
            <div class="mt-2 flex flex-wrap gap-1">
              <button
                v-for="p in pageButtons"
                :key="'pg' + p"
                class="text-[10px] font-ui px-2 py-0.5 rounded border"
                :class="p === previewPage ? 'border-ruc-red text-ruc-red bg-ruc-red-pale/60' : 'border-ruc-divider text-ruc-text-dim'"
                @click="previewPage = p"
              >{{ p }}</button>
            </div>
          </div>
        </div>
      </div>

      <footer class="flex items-center gap-3 px-4 py-3 border-t border-ruc-divider">
        <label class="flex items-center gap-1.5 text-[11px] font-ui text-ruc-text-dim">
          页数
          <select v-model.number="pages" class="rounded-lg border border-ruc-divider px-2 py-1 text-[11px] font-ui bg-white">
            <option :value="0">按内容自定</option>
            <option :value="8">约 8 页</option>
            <option :value="12">约 12 页</option>
            <option :value="16">约 16 页</option>
          </select>
        </label>
        <label class="flex items-center gap-1.5 text-[11px] font-ui text-ruc-text-dim" title="没配图素材时，用通义万相按内容生成一张插图（要花几十秒）">
          <input v-model="autoImage" type="checkbox" class="accent-ruc-red" />
          没配图时自动生成配图
        </label>
        <span class="text-[10px] font-ui text-ruc-text-light">
          选好后在对话框里正常说话（比如“@这份文件 做个汇报 PPT”），生成时会用这套模板。
        </span>
        <button class="ml-auto px-3 py-1.5 rounded-lg bg-ruc-red text-white text-[11px] font-ui" @click="confirm">
          {{ selectedId ? '用这套模板' : '不用模板' }}
        </button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { toast } from '@/composables/useToast'
import type { PptTemplate } from '@/types'
import { LayoutTemplate, Presentation, X, Trash2 } from 'lucide-vue-next'

const props = defineProps<{
  templateId?: string
  pages?: number
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm', payload: { templateId: string; pages: number; name: string }): void
}>()

const templates = ref<PptTemplate[]>([])
const selectedId = ref(props.templateId || '')
const pages = ref(props.pages ?? 12)
const previewPage = ref(1)
const previewOk = ref<'ok' | 'failed' | ''>('')
const previewError = ref('')
const previewNonce = ref(0)
const thumbs = ref<Record<string, 'ok' | 'failed'>>({})
const uploading = ref(false)
const shotBusy = ref(false)
const refining = ref(false)
const rebuilding = ref(false)
const autoImage = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const shotInput = ref<HTMLInputElement | null>(null)

const builtin = computed(() => templates.value.filter((t) => t.source === 'builtin').length)
const mine = computed(() => templates.value.filter((t) => t.source === 'user').length)
const current = computed(() => templates.value.find((t) => t.id === selectedId.value))
const currentSlides = computed(() => current.value?.slides || 0)
const currentName = computed(() => current.value?.name || '（不用模板）')
const previewSrc = computed(() =>
  selectedId.value
    ? `${api.getPptTemplateThumbUrl(selectedId.value, previewPage.value)}${previewNonce.value ? `&r=${previewNonce.value}` : ''}`
    : '')

function retryPreview() {
  previewNonce.value = Date.now()
  previewOk.value = ''
  previewError.value = ''
}

async function loadPreviewError() {
  // 渲染失败时后端会带具体原因（503），拿它显示出来，避免"没有渲染器"这种误导文案
  if (!selectedId.value) return
  try {
    const res = await fetch(api.getPptTemplateThumbUrl(selectedId.value, previewPage.value))
    if (!res.ok) previewError.value = '渲染失败' // 具体原因在响应体里，界面只给一句人话
  } catch {
    previewError.value = '网络或渲染服务没响应'
  }
}
const pageButtons = computed(() => {
  const total = currentSlides.value
  if (!total) return []
  const step = Math.max(1, Math.ceil(total / 12))
  const list: number[] = []
  for (let p = 1; p <= total; p += step) list.push(p)
  return list.slice(0, 14)
})

function select(tpl: PptTemplate) {
  selectedId.value = tpl.id
  previewPage.value = 1
  previewOk.value = ''
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
    select(item)
    toast.success(`已加入模板：${item.name}（${item.slides} 页）`)
  } catch (e: any) {
    toast.error(e.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function onShots(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) return
  shotBusy.value = true
  try {
    const name = prompt('给这份截图模板起个名字', '截图模板') || '截图模板'
    const item = await api.createPptTemplateFromScreenshot(files, name)
    templates.value = [item, ...templates.value.filter((t) => t.id !== item.id)]
    select(item)
    const r = item.report || {}
    toast.success(`已建模板：${item.name}（${r.pages || item.slides} 页，${r.texts || 0} 个文字位、${r.photos || 0} 个照片位）`)
  } catch (e: any) {
    toast.error(e.message || '截图识别失败')
  } finally {
    shotBusy.value = false
  }
}

async function runVisionRefine() {
  const tpl = current.value
  if (!tpl || refining.value) return
  refining.value = true
  toast.info('正在让 qwen-vl 看这张模板的版面，约 30 秒…')
  try {
    const res = await api.visionRefineTemplate(tpl.id)
    if (!res.refined) {
      toast.error('没校正成功：' + (res.results?.[0]?.error || '未知原因'))
    } else {
      toast.success(`视觉校正完成：看了 ${res.refined} 页，改动了 ${res.changed} 页`)
    }
    // 角色/框位变了，让外面按新映射重挑样本
    thumbs.value = { ...thumbs.value }
  } catch (e: any) {
    toast.error(e.message || '视觉校正失败')
  } finally {
    refining.value = false
  }
}

async function runRebuild() {
  const tpl = current.value
  if (!tpl || rebuilding.value) return
  rebuilding.value = true
  toast.info('正在把「整页图片化」的页重建成可编辑页，每页约 5 秒…')
  try {
    const res = await api.rebuildTemplateImagePages(tpl.id)
    if (!res.rebuilt) {
      toast.info(res.message || '这份模板没有需要重建的页')
    } else {
      toast.success(`重建完成：${res.rebuilt} 页，新增 ${res.texts || 0} 个可编辑文字位、${res.photos || 0} 个图片位`)
    }
    await onMountedLoad()
  } catch (e: any) {
    toast.error(e.message || '重建失败')
  } finally {
    rebuilding.value = false
  }
}

async function remove(tpl: PptTemplate) {
  try {
    await api.deletePptTemplate(tpl.id)
    templates.value = templates.value.filter((t) => t.id !== tpl.id)
    if (selectedId.value === tpl.id) selectedId.value = ''
    toast.success('已删除模板')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

function confirm() {
  emit('confirm', {
    templateId: selectedId.value,
    pages: pages.value,
    name: selectedId.value ? currentName.value : '按主题（内置版式）',
    autoImage: autoImage.value,
  })
  emit('close')
}

async function onMountedLoad() {
  try {
    const data = await api.listPptTemplates()
    templates.value = data.templates || []
    if (selectedId.value) {
      const hit = templates.value.find((t) => t.id === selectedId.value)
      if (!hit) selectedId.value = ''
    }
  } catch (e: any) {
    toast.error('模板库读不到：' + (e.message || e))
  }
}

onMounted(() => {
  void onMountedLoad()
})
</script>
