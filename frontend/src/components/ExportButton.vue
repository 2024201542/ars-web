<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { toast } from '@/composables/useToast'
import { api } from '@/api'
import { Download, Loader2, FileText, FileType, FileBox } from 'lucide-vue-next'

const props = defineProps<{ sessionId: string; disabled?: boolean }>()

const exporting = ref(false)
const showMenu = ref(false)
const rootRef = ref<HTMLElement | null>(null)

const FORMATS = [
  { id: 'markdown', label: 'Markdown (.md)', desc: '完整问答记录，推荐' },
  { id: 'docx', label: 'Word (.docx)', desc: '适合提交/打印' },
  { id: 'pdf', label: 'PDF', desc: '适合归档分享' },
  { id: 'latex', label: 'LaTeX (.tex)', desc: '适合学术排版' },
]

function onDocClick(e: MouseEvent) {
  if (rootRef.value && !rootRef.value.contains(e.target as Node)) showMenu.value = false
}
onMounted(() => document.addEventListener('click', onDocClick, true))
onUnmounted(() => document.removeEventListener('click', onDocClick, true))

async function handleExport(format: string) {
  if (!props.sessionId || props.disabled) return
  exporting.value = true
  try {
    const result = await api.exportResult(props.sessionId, format, 'conversation')
    if (result.warning) toast.warning(result.warning)
    else toast.success(`已导出 ${result.filename || format}`)
    const url = api.getExportUrl(props.sessionId, result.file_id)
    // 触发下载而不是新标签打开
    const a = document.createElement('a')
    a.href = url
    a.download = result.filename || `ars_export.${format === 'markdown' ? 'md' : format}`
    document.body.appendChild(a)
    a.click()
    a.remove()
  } catch (e: any) {
    toast.error('导出失败：' + (e.message || '未知错误'))
  } finally {
    exporting.value = false
    showMenu.value = false
  }
}
</script>

<template>
  <div ref="rootRef" class="relative">
    <button
      @click="showMenu = !showMenu"
      class="btn-secondary text-sm flex items-center gap-2"
      :disabled="exporting || disabled"
      title="导出当前会话"
    >
      <Loader2 v-if="exporting" class="w-4 h-4 animate-spin" />
      <Download v-else class="w-4 h-4" />
      {{ exporting ? '导出中…' : '导出会话' }}
    </button>

    <div
      v-if="showMenu"
      class="absolute bottom-full right-0 mb-2 bg-ruc-card border border-ruc-divider rounded-lg py-1 w-64 shadow-modal z-30"
    >
      <div class="px-3 py-2 text-[11px] font-ui text-ruc-text-light border-b border-ruc-divider">导出完整问答（含提问与回答）</div>
      <button
        v-for="fmt in FORMATS"
        :key="fmt.id"
        @click="handleExport(fmt.id)"
        class="w-full text-left px-4 py-2.5 flex items-start gap-3 hover:bg-ruc-red/5 transition-colors group"
      >
        <FileText class="w-4 h-4 text-ruc-red/70 mt-0.5 flex-shrink-0" />
        <div>
          <div class="text-sm font-ui text-ruc-text group-hover:text-ruc-red transition-colors">{{ fmt.label }}</div>
          <div class="text-xs font-ui text-ruc-text-dim mt-0.5">{{ fmt.desc }}</div>
        </div>
      </button>
    </div>
  </div>
</template>
