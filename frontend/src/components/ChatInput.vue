<script setup lang="ts">
import { ref, computed } from 'vue'
import { ArrowUp, Square, FileText, X } from 'lucide-vue-next'

const props = defineProps<{
  isStreaming: boolean
  attachedFiles: any[]
}>()

const emit = defineEmits<{
  send: [message: string]
  stop: []
  fileRemove: [file: any]
}>()

const inputMessage = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const charCount = computed(() => inputMessage.value.length)
const isCharLimitExceeded = computed(() => charCount.value > 50000)
const canSend = computed(() => (inputMessage.value.trim() || props.attachedFiles.length) && !isCharLimitExceeded.value)

function handleInput(e: Event) {
  const t = e.target as HTMLTextAreaElement
  inputMessage.value = t.value
  t.style.height = 'auto'
  t.style.height = Math.min(t.scrollHeight, 160) + 'px'
}

function handleSend() {
  if (!canSend.value || props.isStreaming) return
  emit('send', inputMessage.value.trim())
  inputMessage.value = ''
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function removeFile(f: any) {
  emit('fileRemove', f)
}

defineExpose({
  focus: () => textareaRef.value?.focus()
})
</script>

<template>
  <div class="flex-shrink-0 border-t border-ruc-divider bg-white/80 backdrop-blur-md px-4 sm:px-6 py-3">
    <div v-if="attachedFiles.length>0" class="flex flex-wrap gap-1.5 mb-2">
      <span 
        v-for="f in attachedFiles" 
        :key="f.path" 
        class="inline-flex items-center gap-1 text-xs font-ui bg-ruc-red-pale border border-ruc-red/15 text-ruc-red px-2 py-1 rounded-lg"
      >
        <FileText class="w-3 h-3" />
        {{ f.name }}
        <button @click="removeFile(f)" class="ml-0.5 hover:text-ruc-error">
          <X class="w-3 h-3" />
        </button>
      </span>
    </div>
    
    <div class="flex gap-2.5 items-end relative">
      <div class="flex-1 relative">
        <textarea 
          ref="textareaRef"
          v-model="inputMessage" 
          @keydown="handleKeydown" 
          @input="handleInput" 
          :disabled="isStreaming" 
          :placeholder="attachedFiles.length?'输入消息或 Enter 发送':'输入研究主题… Enter 发送'" 
          rows="1" 
          class="w-full resize-none font-ui text-sm bg-white border border-ruc-border rounded-2xl px-4 py-3 placeholder:text-ruc-text-light focus:outline-none focus:border-ruc-red/40 focus:ring-2 focus:ring-ruc-red/15 transition-all duration-150 disabled:bg-ruc-bg disabled:text-ruc-text-light" 
          :class="{'!border-ruc-error/50 !ring-ruc-error/20':isCharLimitExceeded}" 
          style="min-height:44px;max-height:160px" 
        />
      </div>
      
      <button 
        v-if="!isStreaming" 
        @click="handleSend" 
        :disabled="!canSend" 
        class="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 transition-all duration-200" 
        :class="canSend?'bg-ruc-red text-white shadow-sm shadow-ruc-red/20 hover:bg-ruc-red-light hover:shadow-md hover:-translate-y-0.5 active:translate-y-0 active:shadow-none':'bg-ruc-bg text-ruc-text-light cursor-not-allowed'"
      >
        <ArrowUp class="w-5 h-5" />
      </button>
      
      <button 
        v-else 
        @click="$emit('stop')" 
        class="w-10 h-10 rounded-xl bg-ruc-error-soft border border-ruc-error/20 flex items-center justify-center flex-shrink-0 hover:bg-ruc-error/10 hover:border-ruc-error/40 transition-all duration-200" 
        title="停止生成"
      >
        <Square class="w-4 h-4 text-ruc-error" />
      </button>
    </div>
  </div>
</template>
