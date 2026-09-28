<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/api'
import { toast } from '@/composables/useToast'
import { useWorkspaceStore } from '@/stores/workspace'
import { FilePlus, Loader2, FileText } from 'lucide-vue-next'

const props = defineProps<{ sessionId: string; selectedIds?: number[]; disabled?: boolean }>()
const emit = defineEmits<{ created: [file: any] }>()

const store = useWorkspaceStore()
const open = ref(false)
const acting = ref(false)
const rootRef = ref<HTMLElement | null>(null)

function onDocClick(e: MouseEvent) {
  if (rootRef.value && !rootRef.value.contains(e.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('click', onDocClick, true))
onUnmounted(() => document.removeEventListener('click', onDocClick, true))

async function generate(format: 'markdown' | 'docx') {
  if (!props.sessionId || props.disabled) return
  acting.value = true
  try {
    const file = await api.generateWorkspaceDoc(props.sessionId, {
      format,
      message_ids: props.selectedIds || [],
    })
    await store.loadFiles(props.sessionId)
    const label = format === 'docx' ? 'Word' : 'Markdown'
    const from = file.source === 'selected' ? '已勾选的回复' : '最近一条回复'
    toast.success(`已生成${label}：${file.name}（${from}）`)
    emit('created', file)
    open.value = false
  } catch (e: any) {
    toast.error(e.message || '生成失败')
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <div ref="rootRef" class="relative">
    <button
      class="btn-secondary text-sm flex items-center gap-2"
      :disabled="disabled || acting"
      title="把回复写成文件，出现在左侧文件栏"
      @click="open = !open"
    >
      <Loader2 v-if="acting" class="w-4 h-4 animate-spin" />
      <FilePlus v-else class="w-4 h-4" />
      生成文档
    </button>
    <div
      v-if="open"
      class="absolute bottom-full left-0 mb-2 w-64 bg-white border border-ruc-divider rounded-xl shadow-modal z-40 py-1"
    >
      <p class="px-3 py-2 text-[11px] font-ui text-ruc-text-light border-b border-ruc-divider">
        {{ selectedIds?.length ? `使用已勾选的 ${selectedIds.length} 条` : '未勾选时使用最近一条回复' }}
      </p>
      <button class="w-full text-left px-3 py-2 hover:bg-ruc-warm flex items-start gap-2" @click="generate('markdown')">
        <FileText class="w-4 h-4 text-ruc-red mt-0.5" />
        <span>
          <span class="block text-sm font-ui text-ruc-text">Markdown</span>
          <span class="block text-[11px] text-ruc-text-dim">写入左侧「generated」</span>
        </span>
      </button>
      <button class="w-full text-left px-3 py-2 hover:bg-ruc-warm flex items-start gap-2" @click="generate('docx')">
        <FileText class="w-4 h-4 text-ruc-red mt-0.5" />
        <span>
          <span class="block text-sm font-ui text-ruc-text">Word（普通样式）</span>
          <span class="block text-[11px] text-ruc-text-dim">直接生成，无需另装软件</span>
        </span>
      </button>
    </div>
  </div>
</template>
