<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarkdownIt from 'markdown-it'
import { Loader2, Lock, AlertTriangle, ArrowLeft } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const md = new MarkdownIt({ html: false, breaks: true, linkify: true })

const loading = ref(true)
const error = ref('')
const data = ref<any>(null)

const token = computed(() => String(route.params.token || ''))

const messages = computed(() => data.value?.snapshot?.messages || [])

onMounted(async () => {
  loading.value = true
  error.value = ''
  try {
    const base = import.meta.env.VITE_API_BASE_URL || '/api'
    // public endpoint lives under /api/public/...
    const url = `${base}/public/shares/${encodeURIComponent(token.value)}`
    const res = await fetch(url)
    const body = await res.json().catch(() => ({}))
    if (!res.ok) {
      error.value = body.detail || `无法打开分享（${res.status}）`
      return
    }
    data.value = body
  } catch (e: any) {
    error.value = e.message || '网络错误'
  } finally {
    loading.value = false
  }
})

function renderMarkdown(t: string) {
  return t ? md.render(t) : ''
}

function fmtDate(iso?: string) {
  if (!iso) return ''
  try { return new Date(iso).toLocaleString('zh-CN') } catch { return iso }
}
</script>

<template>
  <div class="min-h-screen bg-ruc-bg">
    <header class="sticky top-0 z-10 bg-white/90 backdrop-blur border-b border-ruc-divider">
      <div class="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
        <div class="min-w-0">
          <p class="text-xs font-ui text-ruc-text-light flex items-center gap-1"><Lock class="w-3 h-3" />只读分享</p>
          <h1 class="text-base font-display text-ruc-text truncate">{{ data?.title || '学术研究会话' }}</h1>
        </div>
        <button @click="router.push('/login')" class="text-xs font-ui text-ruc-text-dim hover:text-ruc-red px-2 py-1 rounded-lg hover:bg-ruc-warm flex items-center gap-1">
          <ArrowLeft class="w-3 h-3" />登录 ARS
        </button>
      </div>
    </header>

    <main class="max-w-3xl mx-auto px-4 py-6">
      <div v-if="loading" class="flex items-center justify-center py-20 text-ruc-text-dim gap-2">
        <Loader2 class="w-5 h-5 animate-spin" /> 加载分享内容…
      </div>

      <div v-else-if="error" class="bg-white border border-ruc-divider rounded-2xl p-8 text-center">
        <AlertTriangle class="w-8 h-8 text-ruc-error mx-auto mb-3" />
        <p class="text-ruc-text font-ui mb-2">{{ error }}</p>
        <p class="text-xs text-ruc-text-light">链接可能已过期、被撤销或不存在</p>
      </div>

      <template v-else>
        <div class="mb-4 text-xs font-ui text-ruc-text-light flex flex-wrap gap-3">
          <span v-if="data?.snapshot?.skill_name">技能：{{ data.snapshot.skill_name }}</span>
          <span v-if="data?.snapshot?.mode_name">模式：{{ data.snapshot.mode_name }}</span>
          <span v-if="data?.expires_at">有效期至：{{ fmtDate(data.expires_at) }}</span>
          <span>{{ messages.length }} 条消息</span>
        </div>

        <div class="space-y-4">
          <div
            v-for="(msg, idx) in messages"
            :key="idx"
            class="flex"
            :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div
              class="max-w-[85%] rounded-2xl px-4 py-3 border"
              :class="msg.role === 'user' ? 'bg-ruc-warm border-ruc-divider' : 'bg-white border-ruc-divider shadow-sm'"
            >
              <p class="text-[10px] font-ui text-ruc-text-light mb-1">{{ msg.role === 'user' ? '提问' : '回答' }}</p>
              <div v-if="msg.role === 'user'" class="text-sm font-ui text-ruc-text whitespace-pre-wrap leading-relaxed">{{ msg.content }}</div>
              <div v-else class="markdown-body text-sm" v-html="renderMarkdown(msg.content)" />
            </div>
          </div>
        </div>

        <p class="mt-10 text-center text-[11px] font-ui text-ruc-text-light">此页面为只读快照，无法继续对话或下载附件</p>
      </template>
    </main>
  </div>
</template>
