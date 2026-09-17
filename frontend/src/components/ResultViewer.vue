<script setup lang="ts">
import { ref, computed } from 'vue'
import { ChevronRight, Copy, Check } from 'lucide-vue-next'

const props = defineProps<{ content: string; title?: string }>()

const show = ref(false)
const copied = ref(false)

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.content)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch { /* ignore */ }
}
</script>

<template>
  <div>
    <button
      @click="show = !show"
      class="text-ruc-red hover:text-ruc-red-light font-ui text-sm flex items-center gap-1.5 transition-colors"
    >
      <ChevronRight class="w-4 h-4 transition-transform" :class="{ 'rotate-90': show }" />
      {{ show ? '收起完整结果' : `查看完整结果 (${content.length} 字符)` }}
    </button>

    <div
      v-if="show"
      class="mt-3 bg-ruc-bg/50 border border-ruc-divider rounded-lg overflow-hidden"
    >
      <div class="flex items-center justify-between px-4 py-2 border-b border-ruc-divider bg-ruc-card/80">
        <span class="text-ruc-text-dim text-xs font-ui">{{ title || '研究结果' }}</span>
        <button
          @click="copyContent"
          class="flex items-center gap-1 text-xs font-ui text-ruc-text-dim hover:text-ruc-red transition-colors"
        >
          <Check v-if="copied" class="w-3.5 h-3.5 text-ruc-success" />
          <Copy v-else class="w-3.5 h-3.5" />
          {{ copied ? '已复制' : '复制全文' }}
        </button>
      </div>
      <div class="p-4 max-h-96 overflow-y-auto">
        <div class="markdown-body text-sm" v-html="content" />
      </div>
    </div>
  </div>
</template>
