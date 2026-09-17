<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { api } from '@/api'
import { FileText, FileCode, Table2, Image, File, Loader2 } from 'lucide-vue-next'

const props = defineProps<{
  sessionId: string
  query: string
}>()
const emit = defineEmits<{ select: [file: any]; close: [] }>()

const files = ref<any[]>([])
const loading = ref(false)
const selectedIdx = ref(0)

watch(() => props.query, async (q) => {
  if (!props.sessionId) return
  loading.value = true
  selectedIdx.value = 0
  try {
    const d = await api.get(`/workspace/search?session_id=${encodeURIComponent(props.sessionId)}&q=${encodeURIComponent(q)}`)
    files.value = d.data || []
  } catch { files.value = [] }
  finally { loading.value = false }
}, { immediate: true })

function fileIcon(ext: string) {
  const e = (ext || '').toLowerCase()
  if (['.md', '.txt'].includes(e)) return FileText
  if (['.py', '.r', '.js', '.ts', '.sh'].includes(e)) return FileCode
  if (['.csv', '.tsv', '.xlsx', '.xls'].includes(e)) return Table2
  if (['.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp'].includes(e)) return Image
  return File
}

function handleSelect(file: any) {
  emit('select', file)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') { e.preventDefault(); selectedIdx.value = Math.min(selectedIdx.value + 1, files.value.length - 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); selectedIdx.value = Math.max(selectedIdx.value - 1, 0) }
  else if (e.key === 'Enter' && files.value[selectedIdx.value]) {
    e.preventDefault()
    handleSelect(files.value[selectedIdx.value])
  }
  else if (e.key === 'Escape') { emit('close') }
}

function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024*1024)).toFixed(1)} MB`
}

defineExpose({ handleKeydown })
</script>

<template>
  <div
    v-if="files.length > 0 || loading"
    class="absolute bottom-full left-0 right-0 mb-2 bg-white border border-ruc-divider rounded-xl shadow-elevated overflow-hidden z-50 max-h-[240px] overflow-y-auto"
  >
    <div v-if="loading" class="flex items-center justify-center py-6">
      <Loader2 class="w-4 h-4 animate-spin text-ruc-red/50" />
    </div>
    <div
      v-for="(f, i) in files"
      :key="f.path"
      @click="handleSelect(f)"
      @mouseenter="selectedIdx = i"
      class="flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-colors"
      :class="i === selectedIdx ? 'bg-ruc-red-pale' : 'hover:bg-ruc-warm'"
    >
      <component :is="fileIcon(f.ext)" class="w-4 h-4 flex-shrink-0" :class="i === selectedIdx ? 'text-ruc-red' : 'text-ruc-text-dim'" />
      <div class="flex-1 min-w-0">
        <p class="text-sm font-ui text-ruc-text truncate">{{ f.name }}</p>
        <p class="text-[10px] font-ui text-ruc-text-light">{{ f.dir || '根目录' }} · {{ fmtSize(f.size_bytes) }}</p>
      </div>
      <span class="text-[10px] font-ui text-ruc-text-light flex-shrink-0">{{ f.ext.replace('.', '').toUpperCase() }}</span>
    </div>
    <div v-if="!loading && files.length === 0 && query" class="px-3 py-6 text-center">
      <p class="text-xs font-ui text-ruc-text-light">未找到匹配 "{{ query }}" 的文件</p>
    </div>
  </div>
</template>
