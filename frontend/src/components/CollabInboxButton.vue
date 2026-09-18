<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { SKILL_ROUTES } from '@/utils/constants'
import { toast } from '@/composables/useToast'
import { Bell, Loader2, GitMerge, RotateCcw, Clock, SendHorizontal } from 'lucide-vue-next'

const router = useRouter()
const open = ref(false)
const loading = ref(false)
const acting = ref(false)
const items = ref<any[]>([])
const alertCount = ref(0)
const rootRef = ref<HTMLElement | null>(null)
const lastAlert = ref(0)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const r = await api.getCollabInbox()
    items.value = r.data || []
    const next = (r as any).alert_count ?? ((r.review_count || 0) + ((r as any).turn_count || 0))
    if (silent && next > lastAlert.value && lastAlert.value > 0) {
      const turn = items.value.find((x) => x.kind === 'your_turn')
      const wait = items.value.find((x) => x.kind === 'waiting')
      if (turn) toast.success(`协作：${turn.root_title} — 请你继续修改`)
      else if (wait) toast.error(`协作：${wait.root_title} — ${wait.from_user} 正在修改`)
    }
    alertCount.value = next
    lastAlert.value = next
  } catch {
    if (!silent) {
      items.value = []
      alertCount.value = 0
    }
  } finally {
    if (!silent) loading.value = false
  }
}

function onDocClick(e: MouseEvent) {
  if (rootRef.value && !rootRef.value.contains(e.target as Node)) open.value = false
}

onMounted(() => {
  load()
  document.addEventListener('click', onDocClick, true)
  pollTimer = setInterval(() => load(true), 15000)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick, true)
  if (pollTimer) clearInterval(pollTimer)
})

function openSession(sessionId: string, skill?: string) {
  const routeName = SKILL_ROUTES[skill || ''] || 'research'
  open.value = false
  router.push(`/session/${sessionId}/${routeName}`)
}

async function mergeOne(id: string, rootId: string, skill?: string) {
  acting.value = true
  try {
    await api.mergeCollabHandoff(id)
    toast.success('已采纳进主稿')
    await load()
    openSession(rootId, skill)
  } catch (e: any) {
    toast.error(e.message || '采纳失败')
  } finally {
    acting.value = false
  }
}

async function rejectOne(id: string) {
  const reason = window.prompt('退回说明（可选）') ?? ''
  acting.value = true
  try {
    await api.rejectCollabHandoff(id, reason.trim())
    toast.success('已退回')
    await load()
  } catch (e: any) {
    toast.error(e.message || '退回失败')
  } finally {
    acting.value = false
  }
}

function kindText(it: any) {
  if (it.kind === 'review') return `${it.from_user} 交回待你审阅`
  if (it.kind === 'your_turn') return '主稿方请你继续修改并交回'
  if (it.kind === 'waiting') return `「${it.from_user}」正在修改（${it.busy_status_label || '占用中'}），请等待`
  if (it.kind === 'submitted') return '已交回，等待主稿方审阅'
  return '主稿方已退回，请继续修改后再交回'
}
</script>

<template>
  <div ref="rootRef" class="relative">
    <button
      class="btn-secondary text-sm flex items-center gap-2 relative"
      @click="open = !open; if (open) load()"
      title="协作待办"
    >
      <Bell class="w-4 h-4" />
      <span class="hidden sm:inline">待办</span>
      <span
        v-if="alertCount > 0"
        class="absolute -top-1 -right-1 min-w-[1.1rem] h-4 px-1 rounded-full bg-ruc-red text-white text-[10px] flex items-center justify-center"
      >{{ alertCount }}</span>
    </button>

    <div v-if="open" class="absolute right-0 top-full mt-2 w-80 bg-white border border-ruc-divider rounded-xl shadow-modal z-50 p-3">
      <p class="text-sm font-ui font-medium text-ruc-text mb-2">协作待办</p>
      <div v-if="loading" class="py-6 text-center text-ruc-text-light text-xs flex justify-center gap-2">
        <Loader2 class="w-4 h-4 animate-spin" /> 加载中
      </div>
      <div v-else-if="!items.length" class="py-6 text-center text-ruc-text-light text-xs">暂无待办</div>
      <div v-else class="space-y-2 max-h-80 overflow-y-auto">
        <div v-for="it in items" :key="it.id" class="rounded-lg border border-ruc-divider p-2.5 space-y-2">
          <p class="text-xs font-ui text-ruc-text font-medium truncate">{{ it.root_title }}</p>
          <p class="text-[11px] text-ruc-text-light leading-relaxed">{{ kindText(it) }}</p>
          <div v-if="it.kind === 'review'" class="flex gap-2">
            <button class="flex-1 btn-primary text-[11px] py-1.5 flex items-center justify-center gap-1" :disabled="acting" @click="mergeOne(it.id, it.root_session_id, it.skill_name)">
              <GitMerge class="w-3 h-3" /> 采纳
            </button>
            <button class="flex-1 text-[11px] py-1.5 rounded-lg border border-ruc-divider text-ruc-error" :disabled="acting" @click="rejectOne(it.id)">退回</button>
            <button class="text-[11px] px-2 py-1.5 rounded-lg border border-ruc-divider" @click="openSession(it.fork_session_id, it.skill_name)">看副本</button>
          </div>
          <button
            v-else-if="it.kind === 'your_turn' || it.kind === 'rejected'"
            class="w-full text-[11px] py-1.5 rounded-lg border border-ruc-divider flex items-center justify-center gap-1"
            @click="openSession(it.fork_session_id, it.skill_name)"
          >
            <RotateCcw class="w-3 h-3" /> 打开副本继续改
          </button>
          <button
            v-else-if="it.kind === 'submitted'"
            class="w-full text-[11px] py-1.5 rounded-lg border border-ruc-divider flex items-center justify-center gap-1 text-ruc-text-dim"
            @click="openSession(it.fork_session_id, it.skill_name)"
          >
            <SendHorizontal class="w-3 h-3" /> 查看我交回的副本
          </button>
          <button
            v-else
            class="w-full text-[11px] py-1.5 rounded-lg border border-amber-200 bg-amber-50 text-amber-950 flex items-center justify-center gap-1"
            @click="openSession(it.fork_session_id, it.skill_name)"
          >
            <Clock class="w-3 h-3" /> 打开我的副本（等待中）
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
