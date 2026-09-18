<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { api } from '@/api'
import { toast } from '@/composables/useToast'
import {
  Users, Loader2, Copy, Check, Ban, SendHorizontal, GitMerge, RotateCcw, UserPlus,
} from 'lucide-vue-next'

const props = defineProps<{ sessionId: string; disabled?: boolean }>()
const emit = defineEmits<{ refreshed: [] }>()

const open = ref(false)
const loading = ref(false)
const acting = ref(false)
const copied = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({})
const expiresDays = ref(7)
const note = ref('')
const state = ref<any>(null)
const lastLink = ref('')
const lastHandoffId = ref('')
const previewId = ref('')
const preview = ref<any>(null)
const previewLoading = ref(false)
const myDiffOpen = ref(false)
const myDiff = ref<any>(null)
const myDiffLoading = ref(false)
const lastBannerKind = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

function placePanel() {
  const anchor = rootRef.value
  if (!anchor) return
  const rect = anchor.getBoundingClientRect()
  const width = Math.min(368, window.innerWidth - 24)
  let left = rect.right - width
  if (left < 12) left = 12
  if (left + width > window.innerWidth - 12) left = window.innerWidth - width - 12
  const gap = 8
  const bottom = Math.max(12, window.innerHeight - rect.top + gap)
  panelStyle.value = {
    position: 'fixed',
    left: `${left}px`,
    bottom: `${bottom}px`,
    width: `${width}px`,
    zIndex: '80',
  }
}

function onDocClick(e: MouseEvent) {
  const t = e.target as Node
  if (rootRef.value?.contains(t)) return
  if (panelRef.value?.contains(t)) return
  open.value = false
}

function onWinChange() {
  if (open.value) placePanel()
}

onMounted(() => {
  document.addEventListener('click', onDocClick, true)
  window.addEventListener('resize', onWinChange)
  window.addEventListener('scroll', onWinChange, true)
  refresh()
  pollTimer = setInterval(() => { refresh(true) }, 12000)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick, true)
  window.removeEventListener('resize', onWinChange)
  window.removeEventListener('scroll', onWinChange, true)
  if (pollTimer) clearInterval(pollTimer)
})
watch(() => props.sessionId, () => {
  lastBannerKind.value = ''
  myDiffOpen.value = false
  myDiff.value = null
  refresh()
})
watch(open, async (v) => {
  if (v) {
    await refresh()
    await nextTick()
    placePanel()
  }
})

async function refresh(silent = false) {
  if (!props.sessionId) return
  if (!silent) loading.value = true
  try {
    const next = await api.getSessionCollab(props.sessionId)
    const prevKind = lastBannerKind.value
    state.value = next
    if (next?.is_fork && next.banner_kind && next.banner_kind !== prevKind) {
      if (next.banner_kind === 'your_turn' && prevKind && prevKind !== 'your_turn') {
        toast.success('主稿方请你继续修改了')
      } else if (next.banner_kind === 'waiting_slot' && prevKind === 'your_turn') {
        toast.error(next.banner || '稿子已被其他人占用')
      } else if (next.banner_kind === 'waiting_slot' && prevKind && prevKind !== 'waiting_slot') {
        toast.error(next.banner || '当前有人正在修改')
      }
    }
    if (next?.banner_kind) lastBannerKind.value = next.banner_kind
  } catch {
    if (!silent) state.value = null
  } finally {
    if (!silent) loading.value = false
  }
}

async function loadMyDiff() {
  if (!props.sessionId) return
  if (myDiffOpen.value) {
    myDiffOpen.value = false
    return
  }
  myDiffLoading.value = true
  myDiffOpen.value = true
  try {
    myDiff.value = await api.getCollabForkDiff(props.sessionId)
  } catch (e: any) {
    myDiff.value = null
    myDiffOpen.value = false
    toast.error(e.message || '预览失败')
  } finally {
    myDiffLoading.value = false
  }
}

function absoluteUrl(path: string) {
  const origin = window.location.origin
  if (path.startsWith('/#/')) return origin + path
  if (path.startsWith('#')) return origin + '/' + path
  return origin + (path.startsWith('/') ? path : '/' + path)
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* fallthrough */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

async function createInvite() {
  if (!props.sessionId || props.disabled) return
  acting.value = true
  try {
    const res = await api.createCollabInvite(props.sessionId, expiresDays.value)
    lastHandoffId.value = res.id
    lastLink.value = absoluteUrl(res.url_path)
    const ok = await copyText(lastLink.value)
    copied.value = ok
    toast.success(ok ? '已生成接续链接并复制' : '已生成接续链接，请手动复制')
    await refresh()
    emit('refreshed')
  } catch (e: any) {
    toast.error(e.message || '生成失败')
  } finally {
    acting.value = false
  }
}

async function submitReview() {
  acting.value = true
  try {
    const r = await api.submitCollabReview(props.sessionId, note.value.trim())
    toast.success(r.message || '已交回审阅')
    note.value = ''
    open.value = false
    await refresh()
    emit('refreshed')
  } catch (e: any) {
    toast.error(e.message || '交回失败')
  } finally {
    acting.value = false
  }
}

async function togglePreview(id: string) {
  if (previewId.value === id) {
    previewId.value = ''
    preview.value = null
    return
  }
  previewLoading.value = true
  previewId.value = id
  try {
    preview.value = await api.previewCollabHandoff(id)
  } catch (e: any) {
    preview.value = null
    previewId.value = ''
    toast.error(e.message || '预览失败')
  } finally {
    previewLoading.value = false
  }
}

async function mergeOne(id: string, mode: 'append_theirs' | 'keep_ours_only' | 'full_fork' = 'append_theirs') {
  acting.value = true
  try {
    const r = await api.mergeCollabHandoff(id, mode)
    toast.success(r.message || '已采纳')
    previewId.value = ''
    preview.value = null
    await refresh()
    emit('refreshed')
    window.location.reload()
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
    const r = await api.rejectCollabHandoff(id, reason.trim())
    toast.success(r.message || '已退回')
    await refresh()
    emit('refreshed')
  } catch (e: any) {
    toast.error(e.message || '退回失败')
  } finally {
    acting.value = false
  }
}

async function requestEdit(id: string, force = false) {
  acting.value = true
  try {
    const r = await api.requestCollabEdit(id, force)
    if (r.needs_confirm && !force) {
      const ok = window.confirm(
        (r.message || '对方副本有未交回修改。') +
          '\n\n确定后会：先存成草稿 → 再把副本同步成最新主稿 → 请对方继续。',
      )
      if (ok) {
        acting.value = false
        await requestEdit(id, true)
        return
      }
      toast.error('已取消')
      return
    }
    toast.success(r.message || '已请对方继续')
    await refresh()
    emit('refreshed')
  } catch (e: any) {
    toast.error(e.message || '操作失败')
  } finally {
    acting.value = false
  }
}

async function revokeOne(id: string) {
  acting.value = true
  try {
    await api.revokeCollabInvite(id)
    toast.success('已撤销邀请')
    lastLink.value = ''
    await refresh()
  } catch (e: any) {
    toast.error(e.message || '撤销失败')
  } finally {
    acting.value = false
  }
}

async function copyLastLink() {
  if (!lastLink.value) return
  const ok = await copyText(lastLink.value)
  copied.value = ok
  toast.success(ok ? '已复制' : '请手动复制')
  if (ok) setTimeout(() => { copied.value = false }, 1500)
}

function selectLink(e: Event) {
  ;(e.target as HTMLInputElement).select()
}

/** 接续人列表里已交回的，审阅操作统一走「待你审阅」，避免两处按钮 */
function partnersNonReview() {
  return (state.value?.partners || []).filter((p: any) => p.status !== 'review_pending')
}

function changeLabel(change?: string) {
  if (change === 'added') return '新增'
  if (change === 'removed') return '主稿有、副本无'
  if (change === 'changed') return '有修改'
  return '未改'
}

function changeBlockClass(change?: string) {
  if (change === 'added') return 'bg-emerald-50 border-emerald-200/80'
  if (change === 'removed') return 'bg-rose-50 border-rose-200/80 opacity-90'
  if (change === 'changed') return 'bg-amber-50 border-amber-200/80'
  return 'bg-ruc-bg/60 border-ruc-divider opacity-75'
}

function changeTagClass(change?: string) {
  if (change === 'added') return 'text-emerald-700 bg-emerald-100'
  if (change === 'removed') return 'text-rose-700 bg-rose-100'
  if (change === 'changed') return 'text-amber-800 bg-amber-100'
  return 'text-ruc-text-light bg-ruc-bg'
}

function lineClass(type?: string) {
  if (type === 'add') return 'bg-emerald-100/90 text-emerald-950 border-l-2 border-emerald-500 pl-1.5'
  if (type === 'del') return 'bg-rose-100/90 text-rose-950 border-l-2 border-rose-400 pl-1.5 line-through decoration-rose-300/80'
  return 'text-ruc-text-dim pl-1.5'
}

/** 按钮上直接可见的短状态，无需点开 */
function buttonStatus() {
  const s = state.value
  if (!s) return null
  if (s.pending_reviews?.length) {
    return { text: `待审 ${s.pending_reviews.length}`, tone: 'alert' as const, title: '有交回待你审阅' }
  }
  if (s.banner_kind === 'your_turn') {
    return { text: '请你改', tone: 'go' as const, title: s.banner || '主稿方请你继续修改' }
  }
  if (s.banner_kind === 'rejected') {
    return { text: '已退回', tone: 'warn' as const, title: s.banner || '已被退回' }
  }
  if (s.banner_kind === 'submitted') {
    return { text: '已交回', tone: 'muted' as const, title: s.banner || '等待主稿方审阅' }
  }
  if (s.banner_kind === 'waiting_slot' && s.active_editor) {
    const name = s.active_editor.partner_name || '他人'
    return { text: `${name} 占用`, tone: 'warn' as const, title: s.banner || `${name} 正在修改` }
  }
  if (s.active_editor && !s.active_editor.is_me) {
    const name = s.active_editor.partner_name || '他人'
    const short = s.active_editor.status === 'review_pending' ? '待审' : '改中'
    return { text: `${name} ${short}`, tone: 'warn' as const, title: `当前轮到 ${name}（${s.active_editor.status_label}）` }
  }
  if (s.active_editor?.is_me) {
    return { text: '你在改', tone: 'go' as const, title: '当前轮到你修改' }
  }
  if (s.banner_kind === 'idle') {
    return { text: '等待中', tone: 'muted' as const, title: s.banner || '等待主稿方请你继续' }
  }
  return null
}
</script>

<template>
  <div ref="rootRef" class="relative">
    <button
      class="btn-secondary text-sm flex items-center gap-1.5 max-w-[14rem]"
      :class="{
        '!border-amber-400 !text-amber-900 bg-amber-50': buttonStatus()?.tone === 'warn',
        '!border-emerald-400 !text-emerald-900 bg-emerald-50': buttonStatus()?.tone === 'go',
        '!border-ruc-red !text-ruc-red bg-ruc-red-pale/60': buttonStatus()?.tone === 'alert',
      }"
      :disabled="disabled || acting"
      @click="open = !open"
      :title="buttonStatus()?.title || '协作：发给对方继续 / 交回 / 审阅'"
    >
      <Loader2 v-if="acting || loading" class="w-4 h-4 animate-spin shrink-0" />
      <Users v-else class="w-4 h-4 shrink-0" />
      <span class="shrink-0">协作</span>
      <span
        v-if="buttonStatus()"
        class="text-[11px] font-ui truncate border-l border-current/25 ml-0.5 pl-1.5"
      >{{ buttonStatus()!.text }}</span>
      <span
        v-else-if="state?.partners?.length"
        class="min-w-[1.1rem] h-4 px-1 rounded-full bg-ruc-red/15 text-ruc-red text-[10px] flex items-center justify-center"
      >{{ state.partners.length }}</span>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="panelRef"
        :style="panelStyle"
        class="bg-white border border-ruc-divider rounded-xl shadow-modal px-4 py-3 space-y-3 max-h-[min(70vh,520px)] overflow-y-auto"
      >
        <div>
          <p class="text-sm font-ui text-ruc-text font-medium">协作交接</p>
          <p class="text-[11px] font-ui text-ruc-text-light mt-0.5 leading-relaxed">
            链接只认人一次。接续方可预览自己的改动再交回；有人占用时其他人会收到提醒。
          </p>
          <p v-if="state?.active_editor" class="text-[11px] font-ui text-ruc-red mt-1">
            当前轮到：{{ state.active_editor.partner_name }}{{ state.active_editor.is_me ? '（你）' : '' }}（{{ state.active_editor.status_label }}）
          </p>
        </div>

        <!-- 接续方：状态条 + 预览 + 交回 -->
        <div v-if="state?.is_fork" class="space-y-2">
          <div
            v-if="state.banner"
            class="rounded-lg border px-2.5 py-2 text-[11px] font-ui leading-relaxed"
            :class="{
              'border-emerald-200 bg-emerald-50 text-emerald-950': state.banner_kind === 'your_turn',
              'border-amber-200 bg-amber-50 text-amber-950': state.banner_kind === 'waiting_slot' || state.banner_kind === 'rejected',
              'border-ruc-divider bg-ruc-bg text-ruc-text-dim': state.banner_kind === 'idle' || state.banner_kind === 'submitted',
            }"
          >
            {{ state.banner }}
          </div>

          <div v-if="state?.can_submit" class="rounded-lg border border-ruc-divider p-2.5 space-y-2 bg-ruc-warm/40">
            <p class="text-xs font-ui text-ruc-text font-medium flex items-center gap-1">
              <SendHorizontal class="w-3.5 h-3.5 text-ruc-red" />
              交回审阅
              <span v-if="state.fork_status === 'rejected'" class="text-ruc-error font-normal">（已被退回，可再交）</span>
            </p>
            <button
              class="w-full text-xs py-1.5 rounded-lg border border-ruc-divider bg-white text-ruc-text"
              :disabled="myDiffLoading"
              @click="loadMyDiff"
            >
              {{ myDiffOpen ? '收起我的改动预览' : '先预览我改了什么' }}
            </button>
            <div v-if="myDiffOpen" class="max-h-52 overflow-y-auto rounded-lg bg-white border border-ruc-divider p-2 space-y-2">
              <p v-if="myDiffLoading" class="text-[11px] text-ruc-text-dim">加载中…</p>
              <template v-else-if="myDiff">
                <p class="text-[10px] text-ruc-text-dim">{{ myDiff.hint }}</p>
                <div
                  v-if="myDiff.three_way"
                  class="rounded-md border px-2 py-1 text-[10px]"
                  :class="myDiff.three_way.has_conflict ? 'border-amber-300 bg-amber-50' : 'border-ruc-divider bg-ruc-bg'"
                >
                  {{ myDiff.three_way.hint }}
                </div>
                <div class="flex flex-wrap gap-1 text-[10px]">
                  <span class="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">+{{ myDiff.vs_baseline_summary?.added ?? 0 }}</span>
                  <span class="px-1.5 py-0.5 rounded bg-rose-100 text-rose-700">−{{ myDiff.vs_baseline_summary?.removed ?? 0 }}</span>
                  <span class="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">~{{ myDiff.vs_baseline_summary?.changed ?? 0 }}</span>
                </div>
                <div
                  v-for="(m, i) in (myDiff.vs_baseline || []).filter((x: any) => x.change !== 'same')"
                  :key="'d'+i"
                  class="text-[11px] rounded-md border p-2"
                  :class="changeBlockClass(m.change)"
                >
                  <div class="flex gap-1.5 mb-0.5">
                    <span class="text-ruc-red/80">{{ m.author }}</span>
                    <span class="text-[10px] px-1 rounded" :class="changeTagClass(m.change)">{{ changeLabel(m.change) }}</span>
                  </div>
                  <div v-if="m.lines?.length" class="space-y-0.5 font-mono text-[10px]">
                    <p v-for="(ln, li) in m.lines" :key="li" class="whitespace-pre-wrap" :class="lineClass(ln.type)">{{ ln.type === 'add' ? '+' : ln.type === 'del' ? '−' : ' ' }}{{ ln.text }}</p>
                  </div>
                  <p v-else class="whitespace-pre-wrap text-ruc-text">{{ m.content }}</p>
                </div>
                <p v-if="!(myDiff.vs_baseline || []).some((x: any) => x.change !== 'same')" class="text-[11px] text-ruc-text-dim">相对开改时尚未检出差异</p>
              </template>
            </div>
            <input v-model="note" class="input-field w-full text-xs" placeholder="交回说明（可选）" />
            <button class="w-full btn-primary text-xs py-2" :disabled="acting" @click="submitReview">交回给主稿方</button>
          </div>
          <p v-else-if="state.wait_reason && !state.banner" class="text-[11px] font-ui text-ruc-text-dim">
            {{ state.wait_reason }}
          </p>
        </div>

        <!-- 主稿方：待审阅（含预览） -->
        <div v-if="state?.pending_reviews?.length" class="space-y-2">
          <p class="text-xs font-ui text-ruc-text font-medium flex items-center gap-1">
            <GitMerge class="w-3.5 h-3.5 text-ruc-red" /> 待你审阅
          </p>
          <div
            v-for="r in state.pending_reviews"
            :key="r.id"
            class="rounded-lg border border-ruc-red/20 bg-ruc-red-pale/50 p-2.5 space-y-2"
          >
            <p class="text-[11px] font-ui text-ruc-text">{{ r.from_user || '协作者' }} 已交回</p>
            <p v-if="r.note" class="text-[11px] text-ruc-text-dim">说明：{{ r.note }}</p>
            <button
              class="w-full text-xs py-1.5 rounded-lg border border-ruc-divider hover:border-ruc-red/30 text-ruc-text bg-white"
              :disabled="previewLoading"
              @click="togglePreview(r.id)"
            >
              {{ previewId === r.id ? '收起预览' : '先预览再决定' }}
            </button>
            <div
              v-if="previewId === r.id"
              class="max-h-64 overflow-y-auto rounded-lg bg-white border border-ruc-divider p-2.5 space-y-2"
            >
              <p v-if="previewLoading" class="text-[11px] text-ruc-text-dim">正在加载预览…</p>
              <template v-else-if="preview?.messages?.length">
                <div
                  v-if="preview.three_way"
                  class="rounded-md border px-2 py-1.5 text-[10px] font-ui leading-relaxed"
                  :class="preview.three_way.has_conflict ? 'border-amber-300 bg-amber-50 text-amber-950' : 'border-ruc-divider bg-ruc-bg text-ruc-text-dim'"
                >
                  <p class="font-medium mb-0.5">{{ preview.three_way.has_conflict ? '三方冲突（类 Git）' : '三方对比' }}</p>
                  <p>{{ preview.three_way.hint }}</p>
                  <p class="mt-0.5">主稿侧改动 {{ preview.three_way.ours_delta_count }} 条 · 对方改动 {{ preview.three_way.theirs_delta_count }} 条</p>
                </div>
                <div class="flex flex-wrap gap-1.5 text-[10px] font-ui pb-1 border-b border-ruc-divider">
                  <span class="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">+新增 {{ preview.diff_summary?.added ?? 0 }}</span>
                  <span class="px-1.5 py-0.5 rounded bg-rose-100 text-rose-700">−删除 {{ preview.diff_summary?.removed ?? 0 }}</span>
                  <span class="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">~修改 {{ preview.diff_summary?.changed ?? 0 }}</span>
                  <span class="px-1.5 py-0.5 rounded bg-ruc-bg text-ruc-text-light">未改 {{ preview.diff_summary?.same ?? 0 }}</span>
                </div>
                <div
                  v-for="(m, i) in preview.messages"
                  :key="i"
                  class="text-[11px] font-ui rounded-md border p-2"
                  :class="changeBlockClass(m.change)"
                >
                  <div class="flex items-center gap-1.5 mb-1 flex-wrap">
                    <span class="text-ruc-red/80">{{ m.author || (m.role === 'user' ? '用户' : '助手') }}</span>
                    <span class="text-[10px] px-1 py-0.5 rounded" :class="changeTagClass(m.change)">{{ changeLabel(m.change) }}</span>
                  </div>
                  <div v-if="m.lines?.length" class="space-y-0.5 font-mono text-[10px] leading-relaxed">
                    <p
                      v-for="(ln, li) in m.lines"
                      :key="li"
                      class="whitespace-pre-wrap break-words rounded-sm py-0.5"
                      :class="lineClass(ln.type)"
                    ><span v-if="ln.type === 'add'" class="select-none text-emerald-600 mr-0.5">+</span><span v-else-if="ln.type === 'del'" class="select-none text-rose-500 mr-0.5">−</span><span v-else class="select-none text-transparent mr-0.5">·</span>{{ ln.text }}</p>
                  </div>
                  <p v-else class="text-ruc-text whitespace-pre-wrap leading-relaxed">{{ m.content }}</p>
                </div>
              </template>
              <p v-else class="text-[11px] text-ruc-text-dim">副本里还没有可预览的消息</p>
            </div>
            <div class="flex flex-col gap-1.5">
              <button class="w-full btn-primary text-xs py-1.5" :disabled="acting" @click="mergeOne(r.id, 'append_theirs')">
                {{ preview?.three_way?.has_conflict ? '保留主稿并并入对方改动' : '采纳对方改动进主稿' }}
              </button>
              <button
                v-if="preview?.three_way?.has_conflict || preview?.three_way?.root_diverged"
                class="w-full text-xs py-1.5 rounded-lg border border-ruc-divider text-ruc-text"
                :disabled="acting"
                @click="mergeOne(r.id, 'keep_ours_only')"
              >
                仅保留主稿（不并入对方）
              </button>
              <button class="w-full text-xs py-1.5 rounded-lg border border-ruc-divider hover:border-ruc-error/40 text-ruc-error flex items-center justify-center gap-1" :disabled="acting" @click="rejectOne(r.id)">
                <RotateCcw class="w-3 h-3" /> 退回对方再改
              </button>
            </div>
          </div>
        </div>

        <!-- 主稿方：已接受的接续人（不含待审阅，避免重复） -->
        <div v-if="partnersNonReview().length" class="space-y-2">
          <p class="text-xs font-ui text-ruc-text font-medium flex items-center gap-1">
            <UserPlus class="w-3.5 h-3.5 text-ruc-red" /> 已接受的接续人
          </p>
          <div
            v-for="p in partnersNonReview()"
            :key="p.handoff_id"
            class="rounded-lg border border-ruc-divider p-2.5 space-y-1.5"
          >
            <div class="flex items-center justify-between gap-2">
              <p class="text-[11px] font-ui text-ruc-text font-medium truncate">{{ p.partner_name }}</p>
              <span class="text-[10px] font-ui text-ruc-text-light shrink-0">{{ p.status_label }}</span>
            </div>
            <p v-if="p.has_local_changes" class="text-[10px] text-amber-800 bg-amber-50 rounded px-1.5 py-0.5">
              副本有未交回修改；请继续前会先存草稿再同步主稿
            </p>
            <button
              v-if="p.can_request_continue"
              class="w-full btn-primary text-xs py-1.5"
              :disabled="acting"
              @click="requestEdit(p.handoff_id)"
            >
              请 TA 继续
            </button>
          </div>
        </div>

        <!-- 发出邀请（仅主稿） -->
        <div v-if="state?.can_invite !== false && !state?.is_fork" class="rounded-lg border border-ruc-divider p-2.5 space-y-2">
          <p class="text-xs font-ui text-ruc-text font-medium">发给新人（第一次用链接）</p>
          <label class="flex items-center justify-between text-[11px] font-ui text-ruc-text-dim">
            <span>有效期</span>
            <select v-model.number="expiresDays" class="border border-ruc-border rounded-lg px-2 py-1 bg-white">
              <option :value="1">1 天</option>
              <option :value="7">7 天</option>
              <option :value="30">30 天</option>
            </select>
          </label>
          <button class="w-full btn-primary text-xs py-2" :disabled="acting || disabled" @click="createInvite">
            生成接续链接
          </button>
          <div v-if="lastLink || state?.open_invites?.length" class="space-y-1.5">
            <input
              v-if="lastLink"
              :value="lastLink"
              readonly
              class="w-full text-[11px] font-ui bg-ruc-bg border border-ruc-divider rounded-lg px-2 py-1.5"
              @focus="selectLink"
              @click="selectLink"
            />
            <div class="flex gap-2" v-if="lastLink">
              <button class="flex-1 text-xs py-1.5 rounded-lg border border-ruc-divider flex items-center justify-center gap-1" @click="copyLastLink">
                <Check v-if="copied" class="w-3 h-3 text-ruc-success" />
                <Copy v-else class="w-3 h-3" />
                复制
              </button>
              <button
                v-if="lastHandoffId"
                class="flex-1 text-xs py-1.5 rounded-lg border border-ruc-error/30 text-ruc-error flex items-center justify-center gap-1"
                @click="revokeOne(lastHandoffId)"
              >
                <Ban class="w-3 h-3" /> 撤销
              </button>
            </div>
            <p v-for="inv in (state?.open_invites || [])" :key="inv.id" class="text-[10px] text-ruc-text-light truncate">
              待接受：{{ inv.url_path }}
            </p>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
