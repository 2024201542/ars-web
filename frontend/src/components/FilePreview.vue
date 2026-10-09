<script setup lang="ts">
import { ref, watch, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '@/api'
import { toast } from '@/composables/useToast'
import MarkdownIt from 'markdown-it'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { attachPdfTextLayer, detachPdfTextLayers } from '@/utils/pdfTextSelection'
import { renderMermaidBlocks } from '@/utils/mermaidBlocks'
import { File, Download, ExternalLink, Loader2, Columns, Eye } from 'lucide-vue-next'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

// 扫描件常用 JBIG2 / JPEG2000 压缩，pdfjs 解码这些格式需要 WASM 资源。
// 不指定 wasmUrl 时 pdfjs 会退回 nowasm 版本并报 "JBig2 failed to initialize"，
// 结果是整页图片解不出来、预览一片空白。资源由 vite.config.ts 拷到 <base>/pdfjs/wasm/。
const PDFJS_WASM_URL = `${import.meta.env.BASE_URL}pdfjs/wasm/`

const props = defineProps<{
  sessionId: string
  source?: string
  file: { name: string; path: string; ext: string; size_bytes: number; columns?: string[] } | null
}>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const content = ref('')
const pdfHost = ref<HTMLElement | null>(null)
const pdfTotal = ref(0)
const pdfDrawn = ref(0)
// 是否为"可选中文字"的 PDF：扫描件没有文字层，选不中也复制不了
const pdfHasText = ref(false)
// 扫描件的 OCR 进度（已识别页 / 总页）
const pdfOcr = ref<{ done: number; total: number; warming: boolean; needs_ocr: boolean; pending: number } | null>(null)
let ocrTimer: ReturnType<typeof setInterval> | null = null

const pdfOcrLabel = computed(() => {
  const p = pdfOcr.value
  if (!p || !p.needs_ocr) return ''
  if (p.done >= p.total && p.total > 0) return `OCR 已完成 ${p.total} 页`
  if (p.warming) return `OCR 识别中 ${p.done}/${p.total}`
  return `OCR 已识别 ${p.done}/${p.total}`
})

async function refreshPdfOcr() {
  if (!props.file || !isPdf.value) return
  try {
    pdfOcr.value = await api.getPdfOcrProgress(props.sessionId, props.file.path, props.source)
  } catch { /* 进度拿不到就不显示，不影响看图 */ }
}

// 只有"确实是扫描件、且还没识别完"才轮询；文字版 PDF 一次都不请求
async function startOcrPolling() {
  stopOcrPolling()
  await refreshPdfOcr()
  const p = pdfOcr.value
  if (!p?.needs_ocr || (p.total > 0 && p.done >= p.total)) return
  ocrTimer = setInterval(async () => {
    await refreshPdfOcr()
    const cur = pdfOcr.value
    if (!cur?.needs_ocr || (cur.total > 0 && cur.done >= cur.total)) stopOcrPolling()
  }, 5000)
}

function stopOcrPolling() {
  if (ocrTimer) { clearInterval(ocrTimer); ocrTimer = null }
}
let loadToken = 0
let pdfLoadingTask: pdfjs.PDFDocumentLoadingTask | null = null
let pdfDoc: pdfjs.PDFDocumentProxy | null = null
const draft = ref('')
const htmlPreview = ref('')
const mdPreviewHost = ref<HTMLElement | null>(null)
const loading = ref(false)
const saving = ref(false)
const previewing = ref(false)
const error = ref('')
const asTable = ref(true)
const leaveChoice = ref<((choice: boolean | null) => void) | null>(null)

const md = new MarkdownIt({ html: false, breaks: true, linkify: true })

function getAuthHeaders(): Record<string, string> {
  const t = localStorage.getItem('ars_token')
  return t ? { Authorization: `Bearer ${t}` } : {}
}

const ext = computed(() => (props.file?.ext || '').toLowerCase())
const isMarkdown = computed(() => ['.md'].includes(ext.value))
const isCode = computed(() => ['.py', '.r', '.js', '.ts', '.sh', '.txt', '.json', '.yaml', '.yml', '.bib', '.tex'].includes(ext.value))
const isCsv = computed(() => ['.csv', '.tsv'].includes(ext.value))
const isImage = computed(() => ['.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp'].includes(ext.value))
const isPdf = computed(() => ['.pdf'].includes(ext.value))
const isHtml = computed(() => ext.value === '.html')
const isDocx = computed(() => ['.docx'].includes(ext.value))
const isXlsx = computed(() => ['.xlsx', '.xls'].includes(ext.value))
const isArchive = computed(() => ['.zip', '.gz', '.parquet', '.feather'].includes(ext.value))

const downloadUrl = computed(() => props.file ? api.getFileDownloadUrl(props.sessionId, props.file.path, props.source) : '')
const previewUrl = computed(() => props.file ? api.getFilePreviewUrl(props.sessionId, props.file.path, props.source) : '')
const pdfOpenUrl = computed(() => props.file ? api.getPdfOpenUrl(props.sessionId, props.file.path, props.source) : '')
const canPreview = computed(() => isMarkdown.value || isCode.value || isCsv.value || isImage.value || isPdf.value || isDocx.value || isXlsx.value || isHtml.value)
const canEdit = computed(() => ['.md', '.txt', '.bib', '.tex', '.docx'].includes(ext.value))
const dirty = computed(() => canEdit.value && draft.value !== content.value)
watch(dirty, (value) => emit('dirty', value))

const langLabel = computed(() => {
  const map: Record<string, string> = { '.py': 'Python', '.r': 'R', '.js': 'JavaScript', '.ts': 'TypeScript', '.json': 'JSON', '.sh': 'Bash', '.yaml': 'YAML', '.yml': 'YAML', '.txt': 'Text', '.bib': 'BibTeX', '.tex': 'LaTeX' }
  return map[ext.value] || ext.value.replace('.', '')
})

function csvToTable(text: string): string {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return text
  const headers = lines[0].split(',').map(h => h.trim())
  const rows = lines.slice(1, Math.min(lines.length, 501))
  return `<table><thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(line => {
    const cols = line.split(',').map(c => c.trim())
    return `<tr>${cols.map(c => `<td>${c}</td>`).join('')}</tr>`
  }).join('')}</tbody></table>`
}

const pdfSize = computed(() => {
  const n = props.file?.size_bytes || 0
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
})

async function clearPdfUrl() {
  pdfDrawn.value = 0
  pdfTotal.value = 0
  pdfHasText.value = false
  const task = pdfLoadingTask
  pdfLoadingTask = null
  pdfDoc = null
  // pdfjs 6 里 PDFDocumentProxy 没有 destroy()，文档由 loadingTask.destroy() 一并释放
  if (task) {
    try { await task.destroy() } catch { /* 已销毁或加载失败时忽略 */ }
  }
  detachPdfTextLayers(pdfHost.value)
  pdfHost.value?.replaceChildren()
}

const renderedContent = computed(() => {
  const source = canEdit.value ? draft.value : content.value
  if (!source) return ''
  if (isMarkdown.value) return md.render(source)
  if (isCsv.value && asTable.value) return csvToTable(source)
  return ''
})

async function paintMermaid() {
  await nextTick()
  await renderMermaidBlocks(mdPreviewHost.value)
}

watch([previewing, renderedContent], () => {
  if (previewing.value && isMarkdown.value) paintMermaid()
})

async function saveDraft() {
  if (!props.file || saving.value || !dirty.value) return !dirty.value
  saving.value = true
  try {
    await api.saveFileContent(props.sessionId, props.file.path, draft.value, props.source)
    content.value = draft.value
    toast.success('已保存')
    return true
  } catch (e: any) {
    toast.error(e.message || '保存失败')
    return false
  } finally {
    saving.value = false
  }
}

function confirmLeave(): Promise<boolean> {
  if (!dirty.value) return Promise.resolve(true)
  return new Promise((resolve) => {
    leaveChoice.value = async (choice) => {
      leaveChoice.value = null
      if (choice === null) {
        resolve(false)
        return
      }
      if (choice === true) {
        resolve(await saveDraft())
        return
      }
      draft.value = content.value
      resolve(true)
    }
  })
}

async function togglePreview() {
  if (!previewing.value && isDocx.value && !htmlPreview.value && props.file) {
    try {
      const r = await fetch(previewUrl.value)
      if (!r.ok) {
        const e = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }))
        throw new Error(e.detail)
      }
      const data = await r.json()
      htmlPreview.value = data.content || ''
    } catch (e: any) {
      toast.error(e.message || 'Word 预览失败')
      return
    }
  }
  previewing.value = !previewing.value
}

function onEditKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    void saveDraft()
  }
}

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (!dirty.value) return
  e.preventDefault()
  e.returnValue = ''
}

async function reload() {
  if (dirty.value) return
  await loadContent()
}

defineExpose({ confirmLeave, isDirty: () => dirty.value, reload })

async function drawPdfPages(doc: pdfjs.PDFDocumentProxy, token: number) {
  const host = pdfHost.value
  if (!host) return
  host.replaceChildren()
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
  for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber++) {
    if (token !== loadToken) return
    const page = await doc.getPage(pageNumber)
    if (token !== loadToken) return
    const base = page.getViewport({ scale: 1 })
    const width = host.clientWidth || base.width
    const viewport = page.getViewport({ scale: width / base.width })
    const sheet = document.createElement('div')
    sheet.className = 'pdf-sheet'
    sheet.style.setProperty('--scale-factor', String(viewport.scale))
    sheet.style.setProperty('--user-unit', String(viewport.userUnit))
    const canvas = document.createElement('canvas')
    const textLayerDiv = document.createElement('div')
    textLayerDiv.className = 'textLayer'
    sheet.append(canvas, textLayerDiv)
    host.append(sheet)
    // 已经确认可选中文字后，后面的页就不必再铺文字层（省内存），但页面照常画出
    const wantTextLayer = !pdfHasText.value || pageNumber <= 5
    let textLayer: pdfjs.TextLayer | null = null
    if (wantTextLayer) {
      textLayer = new pdfjs.TextLayer({
        textContentSource: page.streamTextContent(),
        container: textLayerDiv,
        viewport,
      })
      sheet.style.width = textLayerDiv.style.width
      sheet.style.height = textLayerDiv.style.height
    } else {
      sheet.style.width = `${viewport.width}px`
      sheet.style.height = `${viewport.height}px`
    }
    canvas.style.width = '100%'
    canvas.style.height = '100%'
    const box = sheet.getBoundingClientRect()
    const bitmapWidth = Math.max(1, Math.floor(box.width * pixelRatio))
    const bitmapHeight = Math.max(1, Math.floor(box.height * pixelRatio))
    canvas.width = bitmapWidth
    canvas.height = bitmapHeight
    const transform = box.width > 0 && box.height > 0
      ? [bitmapWidth / viewport.width, 0, 0, bitmapHeight / viewport.height, 0, 0]
      : undefined
    await page.render({ canvas, viewport, transform }).promise
    if (token !== loadToken) return
    if (textLayer) {
      await textLayer.render()
      attachPdfTextLayer(textLayerDiv)
      // 前几页任一处有文字，就认为这份 PDF 可以选字；扫描件始终为 0
      if (!pdfHasText.value && pageNumber <= 5
        && textLayer.textContentItemsStr?.some((s: string) => s.trim())) {
        pdfHasText.value = true
      }
    }
    pdfDrawn.value = pageNumber
  }
}

async function loadContent() {
  if (!props.file) return
  const token = ++loadToken
  clearPdfUrl()
  loading.value = true; error.value = ''; content.value = ''; draft.value = ''; htmlPreview.value = ''
  previewing.value = false
  try {
    if (isPdf.value) {
      const response = await fetch(pdfOpenUrl.value)
      if (!response.ok) {
        const failed = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
        throw new Error(failed.detail || `HTTP ${response.status}`)
      }
      const data = await response.arrayBuffer()
      if (token !== loadToken) return
      const task = pdfjs.getDocument({ data, wasmUrl: PDFJS_WASM_URL })
      pdfLoadingTask = task
      const doc = await task.promise
      if (token !== loadToken) {
        // 这次加载已被后续操作取代：连同 loadingTask 一起释放（doc 本身没有 destroy）
        try { await task.destroy() } catch { /* ignore */ }
        return
      }
      pdfDoc = doc
      pdfTotal.value = doc.numPages
      content.value = 'pdf'
      loading.value = false
      // 扫描件会边看边 OCR，这里轮询显示进度
      startOcrPolling()
      await nextTick()
      await drawPdfPages(doc, token)
    } else if (isXlsx.value) {
      // previewUrl.value 已经通过 withAuthToken 添加了 token，不需要再重复加 headers
      const r = await fetch(previewUrl.value)
      if (!r.ok) { const e = await r.json().catch(()=>({detail:`HTTP ${r.status}`})); throw new Error(e.detail) }
      const j = await r.json()
      htmlPreview.value = j.content
    } else if (!isImage.value) {
      const result = await api.getFileContent(props.sessionId, props.file.path, props.source)
      content.value = result.content
      draft.value = result.content
      if (isMarkdown.value && props.file.name === '论文结构图.md') previewing.value = true
    }
  } catch (e: any) {
    if (token !== loadToken) return
    const message = e.message || String(e) || '未知错误'
    if (pdfDrawn.value) toast.error('后面的页面没有打开: ' + message)
    else error.value = '加载失败: ' + message
  } finally {
    if (token === loadToken) loading.value = false
  }
}

watch(() => props.file, (newFile, oldFile) => {
  // 文件引用变化时强制重新加载
  if (newFile && newFile.path !== oldFile?.path) { loadContent() }
}, { immediate: true })

watch(() => props.sessionId, () => { if (props.file) loadContent() })
watch(() => props.source, () => { if (props.file) loadContent() })

onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  stopOcrPolling()
  clearPdfUrl()
  detachPdfTextLayers()
})
</script>

<template>
  <div class="relative flex flex-col h-full" @keydown="onEditKeydown">
    <!-- Toolbar -->
    <div v-if="file" class="flex items-center justify-between px-3 py-1.5 border-b border-ruc-divider bg-ruc-card/70 flex-shrink-0">
      <span class="text-xs font-ui text-ruc-text truncate flex items-center gap-1.5 min-w-0">
        <span v-if="dirty" class="w-1.5 h-1.5 rounded-full bg-ruc-text flex-shrink-0" title="未保存" />
        <File class="w-3 h-3 text-ruc-red/50 flex-shrink-0" />
        {{ file.name }}
      </span>
      <div class="flex items-center gap-1 flex-shrink-0">
        <button
          v-if="canEdit && (isMarkdown || isDocx) && !loading && !error"
          class="px-2 py-0.5 text-[11px] font-ui rounded-lg text-ruc-text-dim hover:text-ruc-red hover:bg-ruc-warm"
          :title="previewing ? '回到编辑' : '预览排版'"
          @click="togglePreview"
        >{{ previewing ? '编辑' : '预览' }}</button>
        <button
          v-if="canEdit && !loading && !error"
          class="px-2 py-0.5 text-[11px] font-ui rounded-lg bg-ruc-red text-white disabled:opacity-40"
          :disabled="!dirty || saving"
          title="保存 (Ctrl+S)"
          @click="saveDraft"
        >{{ saving ? '保存中' : '保存' }}</button>
        <button v-if="isCsv" @click="asTable = !asTable" class="p-1 rounded transition-colors"
          :class="asTable ? 'text-ruc-red' : 'text-ruc-text-dim hover:text-ruc-red'" title="表格视图">
          <Columns class="w-3.5 h-3.5" />
        </button>
        <a :href="downloadUrl" :download="file.name" class="p-1 text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="下载">
          <Download class="w-3.5 h-3.5" />
        </a>
        <a :href="isPdf ? pdfOpenUrl : downloadUrl" target="_blank" class="p-1 text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="新标签页打开">
          <ExternalLink class="w-3.5 h-3.5" />
        </a>
      </div>
    </div>

    <!-- Content -->
    <div
      class="flex-1 min-h-0"
      :class="((canEdit && !previewing) || isPdf || isHtml) && !loading && !error && file ? 'overflow-hidden flex flex-col' : 'overflow-auto'"
    >
      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center h-full">
        <Loader2 class="w-5 h-5 text-ruc-red/40 animate-spin" />
      </div>

      <!-- Error -->
      <div v-else-if="error" class="flex items-center justify-center h-full">
        <p class="text-ruc-error text-sm font-ui">{{ error }}</p>
      </div>

      <!-- Empty -->
      <div v-else-if="!file" class="flex items-center justify-center h-full">
        <div class="text-center">
          <File class="w-10 h-10 mx-auto text-ruc-divider mb-3" />
          <p class="text-ruc-text-light text-sm font-ui">选择文件以预览</p>
          <p class="text-ruc-text-light/50 text-xs font-ui mt-1">支持 Markdown / CSV / PDF / DOCX / Excel / 图片 / 代码</p>
        </div>
      </div>

      <textarea
        v-else-if="canEdit && !previewing"
        v-model="draft"
        class="editor-body select-text flex-1 min-h-0 w-full resize-none px-8 py-6 text-sm text-ruc-text leading-relaxed bg-white focus:outline-none"
        spellcheck="true"
        @keydown="onEditKeydown"
      />
      <div v-else-if="canEdit && previewing" ref="mdPreviewHost" class="editor-body flex-1 overflow-auto p-8">
        <div v-if="isDocx" class="markdown-body text-sm" v-html="htmlPreview" />
        <div v-else class="markdown-body text-sm" v-html="renderedContent" />
      </div>

      <div v-else-if="isPdf" class="flex-1 min-h-0 overflow-auto bg-[#e7e5e4] px-4 py-4 select-text">
        <div ref="pdfHost" class="pdf-reader mx-auto w-full max-w-3xl"></div>
        <p v-if="pdfDrawn < pdfTotal" class="text-center text-[11px] font-ui text-ruc-text-dim py-2">正在打开第 {{ pdfDrawn + 1 }} 页</p>
      </div>

      <!-- XLSX: HTML。Word 走上面的编辑区。 -->
      <div v-else-if="isXlsx" class="p-4">
        <div class="flex items-center gap-2 mb-3">
          <Eye class="w-4 h-4 text-ruc-red/60" />
          <span class="text-xs font-ui text-ruc-text-dim">Excel 表格预览</span>
        </div>
        <div class="markdown-body text-sm" v-html="htmlPreview" />
      </div>

      <!-- CSV -->
      <div v-else-if="isCsv && asTable" class="p-3 overflow-auto">
        <div class="markdown-body text-xs" v-html="renderedContent" />
      </div>
      <div v-else-if="isCsv" class="p-3">
        <pre class="text-xs font-mono text-ruc-text whitespace-pre-wrap">{{ content }}</pre>
      </div>

      <!-- Code -->
      <div v-else-if="isCode" class="p-3">
        <span class="text-[10px] px-1.5 py-0.5 rounded-lg font-ui bg-ruc-red/10 text-ruc-red/60">{{ langLabel }}</span>
        <pre class="mt-2 text-xs font-mono text-ruc-text whitespace-pre-wrap leading-relaxed">{{ content }}</pre>
      </div>

      <div v-else-if="isHtml" class="flex-1 min-h-0 overflow-hidden bg-white">
        <iframe class="w-full h-full border-0 bg-white" sandbox="" :srcdoc="content" title="论文结构图"></iframe>
      </div>

      <!-- Image -->
      <div v-else-if="isImage" class="p-3 flex items-center justify-center">
        <img :src="downloadUrl" :alt="file.name" class="max-w-full max-h-full object-contain rounded-lg" />
      </div>

      <!-- Archive / binary -->
      <div v-else class="flex items-center justify-center h-full">
        <div class="text-center">
          <File class="w-12 h-12 mx-auto text-ruc-divider mb-3" />
          <p class="text-ruc-text-light text-sm font-ui mb-2">此格式无法在线预览</p>
          <a :href="downloadUrl" :download="file.name" class="btn-secondary text-xs">{{ file.name }}</a>
        </div>
      </div>
    </div>

    <!-- Status bar -->
    <div v-if="file" class="px-3 py-1 border-t border-ruc-divider flex-shrink-0 flex items-center gap-3 text-[10px] font-ui text-ruc-text-light">
      <span>{{ ext.replace('.', '').toUpperCase() || 'FILE' }}</span>
      <span v-if="file.columns?.length">{{ file.columns.length }} 列</span>
      <span v-if="isPdf">{{ pdfTotal ? pdfTotal + ' 页 · ' : '' }}{{ pdfSize }} · {{ pdfHasText ? '文字可以选中' : '扫描图片，无法选中文字' }}<template v-if="pdfOcrLabel"> · {{ pdfOcrLabel }}</template></span>
      <span v-else>{{ ((canEdit ? draft.length : content.length) || htmlPreview.length || file.size_bytes).toLocaleString() }} 字符</span>
      <span v-if="isDocx">保存写回 Word，表格和图片仍留着</span>
      <span v-if="dirty" class="text-ruc-red">未保存</span>
    </div>

    <div v-if="leaveChoice" class="absolute inset-0 z-40 bg-white/85 flex items-center justify-center p-6">
      <div class="bg-white border border-ruc-divider rounded-xl shadow-modal p-4 w-full max-w-xs">
        <p class="text-sm font-ui font-medium text-ruc-text">是否保存更改</p>
        <p class="text-xs font-ui text-ruc-text-dim mt-1 leading-relaxed">是否保存对「{{ file?.name }}」的更改？</p>
        <div class="mt-3 flex flex-col gap-1.5">
          <button class="px-3 py-1.5 rounded-lg bg-ruc-red text-white text-xs font-ui hover:bg-ruc-red-dark" @click="leaveChoice?.(true)">保存</button>
          <button class="px-3 py-1.5 rounded-lg border border-ruc-border text-xs font-ui text-ruc-text hover:bg-ruc-warm" @click="leaveChoice?.(false)">不保存</button>
          <button class="px-3 py-1.5 rounded-lg text-xs font-ui text-ruc-text-dim hover:bg-ruc-warm" @click="leaveChoice?.(null)">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
.pdf-sheet {
  position: relative;
  margin: 0 auto 12px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(28, 25, 23, 0.08);
  --user-unit: 1;
  --scale-factor: 1;
  --total-scale-factor: calc(var(--scale-factor) * var(--user-unit));
  --scale-round-x: 1px;
  --scale-round-y: 1px;
}
.pdf-sheet canvas {
  display: block;
}
.pdf-sheet .textLayer {
  position: absolute;
  top: 0;
  left: 0;
  overflow: clip;
  line-height: 1;
  transform-origin: 0 0;
  z-index: 1;
  --min-font-size: 1;
  --text-scale-factor: calc(var(--total-scale-factor) * var(--min-font-size));
  --min-font-size-inv: calc(1 / var(--min-font-size));
}
.pdf-sheet .textLayer :is(span, br) {
  color: transparent;
  position: absolute;
  white-space: pre;
  cursor: text;
  transform-origin: 0% 0%;
  user-select: text;
}
.pdf-sheet .textLayer > :not(.markedContent),
.pdf-sheet .textLayer .markedContent span:not(.markedContent) {
  z-index: 1;
  font-size: calc(var(--text-scale-factor) * var(--font-height));
  transform: rotate(var(--rotate, 0deg)) scaleX(var(--scale-x, 1)) scale(var(--min-font-size-inv));
}
.pdf-sheet .textLayer .markedContent {
  display: contents;
}
.pdf-sheet .textLayer ::selection {
  background: rgba(190, 40, 45, 0.28);
  color: transparent;
}
.pdf-sheet .textLayer .endOfContent {
  display: block;
  position: absolute;
  inset: 100% 0 0;
  z-index: 0;
  cursor: default;
  user-select: none;
}
.pdf-sheet .textLayer.selecting .endOfContent {
  top: 0;
}
</style>
