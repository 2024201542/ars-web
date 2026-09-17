<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'
import { toast } from '@/composables/useToast'

const hasError = ref(false)
const errorMessage = ref('')

// 全局错误捕获
onErrorCaptured((error, instance, info) => {
  console.error('全局错误:', error, info)
  
  // 记录错误信息
  errorMessage.value = error.message || '应用发生错误'
  hasError.value = true
  
  // 显示错误提示
  toast.error('应用发生错误，请刷新页面重试')
  
  // 返回 false 阻止错误继续传播
  return false
})

function handleRefresh() {
  hasError.value = false
  errorMessage.value = ''
  window.location.reload()
}

function handleReset() {
  hasError.value = false
  errorMessage.value = ''
}
</script>

<template>
  <div v-if="hasError" class="min-h-screen flex items-center justify-center bg-ruc-bg p-4">
    <div class="max-w-md w-full bg-white rounded-2xl shadow-card p-8 text-center">
      <div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-ruc-error/10 flex items-center justify-center">
        <svg class="w-8 h-8 text-ruc-error" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      </div>
      
      <h2 class="text-xl font-display font-semibold text-ruc-text mb-2">应用发生错误</h2>
      <p class="text-ruc-text-dim text-sm font-ui mb-6">{{ errorMessage }}</p>
      
      <div class="flex gap-3 justify-center">
        <button @click="handleReset" class="btn-secondary text-sm">
          重试
        </button>
        <button @click="handleRefresh" class="btn-primary text-sm">
          刷新页面
        </button>
      </div>
    </div>
  </div>
  
  <slot v-else />
</template>
