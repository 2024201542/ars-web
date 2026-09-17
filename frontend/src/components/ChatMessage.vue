<script setup lang="ts">
import { ref, computed } from 'vue'
import MarkdownIt from 'markdown-it'
import { Copy, Check, Circle, CheckCircle, Loader2 } from 'lucide-vue-next'

const props = defineProps<{
  message: any
  isSelected: boolean
}>()

const emit = defineEmits<{
  copy: [content: string, id: number]
  select: [id: number]
}>()

const md = new MarkdownIt({ html: false, breaks: true, linkify: true })
const copied = ref(false)

const renderedContent = computed(() => {
  return props.message.content ? md.render(props.message.content) : ''
})

function handleCopy() {
  emit('copy', props.message.content, props.message.id)
  copied.value = true
  setTimeout(() => copied.value = false, 2000)
}

function handleSelect() {
  emit('select', props.message.id)
}
</script>

<template>
  <div class="flex items-start gap-2 animate-fade-in" :class="message.role==='user'?'justify-end':'justify-start'">
    <button 
      v-if="message.role==='assistant' && message.content" 
      @click="handleSelect" 
      class="flex-shrink-0 mt-3 p-0.5 rounded-full transition-all" 
      :class="isSelected?'text-ruc-red opacity-100':'text-ruc-text-light opacity-0 group-hover:opacity-100'"
    >
      <CheckCircle v-if="isSelected" class="w-4 h-4" />
      <Circle v-else class="w-4 h-4" />
    </button>
    
    <div 
      class="max-w-[80%] sm:max-w-[72%] rounded-2xl px-4 py-3 relative group" 
      :class="message.role==='user'?'bg-ruc-warm border border-ruc-divider':'bg-white border border-ruc-divider shadow-sm'"
    >
      <button 
        v-if="message.role==='assistant' && message.content" 
        @click="handleCopy" 
        class="absolute -top-1.5 -right-1.5 opacity-0 group-hover:opacity-100 transition-all p-1.5 rounded-lg bg-white border border-ruc-divider shadow-elevated hover:border-ruc-red/30" 
        title="复制"
      >
        <Check v-if="copied" class="w-3 h-3 text-ruc-success" />
        <Copy v-else class="w-3 h-3 text-ruc-text-dim" />
      </button>
      
      <div 
        v-if="message.role==='user'" 
        class="text-ruc-text font-ui text-sm whitespace-pre-wrap leading-relaxed"
      >
        {{ message.content }}
      </div>
      
      <div 
        v-else-if="message._streaming && message.content" 
        class="text-ruc-text font-ui text-sm whitespace-pre-wrap leading-relaxed"
      >
        {{ message.content }}<span class="inline-block w-0.5 h-4 bg-ruc-red ml-0.5 animate-pulse align-middle" />
      </div>
      
      <div 
        v-else-if="message.content" 
        class="markdown-body text-sm" 
        :class="{'ring-2 ring-ruc-red/20 rounded-lg':isSelected}" 
        v-html="renderedContent" 
      />
      
      <div v-else class="py-1">
        <div class="flex items-center gap-2.5 text-ruc-text-dim font-ui text-sm">
          <Loader2 class="w-4 h-4 animate-spin text-ruc-red/50" />
          <span class="animate-pulse-soft">正在思考...</span>
        </div>
      </div>
    </div>
  </div>
</template>
