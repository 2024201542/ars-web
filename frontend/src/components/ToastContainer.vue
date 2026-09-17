<script setup lang="ts">
import { toasts, toast } from '@/composables/useToast'

function getIconClass(type: string) {
  switch (type) {
    case 'success': return 'text-ruc-success'
    case 'error': return 'text-ruc-error'
    case 'warning': return 'text-yellow-400'
    case 'info': return 'text-ruc-red'
    default: return 'text-ruc-red'
  }
}

function getBgClass(type: string) {
  switch (type) {
    case 'success': return 'bg-ruc-success/10 border-ruc-success/20'
    case 'error': return 'bg-ruc-error/10 border-ruc-error/20'
    case 'warning': return 'bg-yellow-400/10 border-yellow-400/20'
    case 'info': return 'bg-ruc-red/10 border-ruc-red/20'
    default: return 'bg-ruc-red/10 border-ruc-red/20'
  }
}
</script>

<template>
  <div class="fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
    <TransitionGroup name="toast">
      <div
        v-for="t in toasts"
        :key="t.id"
        class="pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-lg border backdrop-blur-md bg-ruc-card/95 shadow-elevated min-w-[300px]"
        :class="getBgClass(t.type)"
      >
        <div class="flex-shrink-0">
          <svg v-if="t.type === 'success'" class="w-5 h-5 text-ruc-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
          <svg v-else-if="t.type === 'error'" class="w-5 h-5 text-ruc-error" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <svg v-else-if="t.type === 'warning'" class="w-5 h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <svg v-else class="w-5 h-5 text-ruc-red" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <p class="flex-1 text-sm font-ui text-ruc-text">{{ t.message }}</p>
        <button
          @click="toast.remove(t.id)"
          class="flex-shrink-0 text-ruc-text-dim hover:text-ruc-text transition-colors"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}
</style>
