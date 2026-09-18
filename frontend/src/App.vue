<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useSettingsStore } from '@/stores/settings'
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import ToastContainer from '@/components/ToastContainer.vue'
import ErrorBoundary from '@/components/ErrorBoundary.vue'

const auth = useAuthStore()
const settings = useSettingsStore()
const router = useRouter()

// 暗色模式
const isDark = typeof localStorage !== 'undefined' ? localStorage.getItem('ars_dark') === '1' : false
if (isDark) document.documentElement.classList.add('dark')

function toggleDark() {
  document.documentElement.classList.toggle('dark')
  localStorage.setItem('ars_dark', document.documentElement.classList.contains('dark') ? '1' : '0')
}

// 全局快捷键
function onKeydown(e: KeyboardEvent) {
  if (e.ctrlKey || e.metaKey) {
    if (e.key === 'b') { e.preventDefault(); /* 文件树切换已在 WorkSessionView 中处理 */ }
    if (e.key === 'd') { e.preventDefault(); toggleDark() }
    if (e.key === 'h') { e.preventDefault(); router.push('/') }
    if (e.key === 's') { e.preventDefault(); router.push('/settings') }
  }
}
document.addEventListener('keydown', onKeydown)

;(window as any).__toggleDark = toggleDark

onMounted(async () => {
  const ok = await auth.checkAuth()
  if (!ok) {
    const cur = router.currentRoute.value
    if (cur.name !== 'login' && !cur.meta.guest && !cur.meta.public) {
      router.push({ path: '/login', query: { redirect: cur.fullPath } })
    }
    return
  }
  settings.load()
})
</script>

<template>
  <ErrorBoundary>
    <div class="min-h-screen bg-ruc-bg dark:bg-gray-900">
      <router-view />
      <ToastContainer />
    </div>
  </ErrorBoundary>
</template>
