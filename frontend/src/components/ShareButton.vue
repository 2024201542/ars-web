<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/api'
import { toast } from '@/composables/useToast'
import { Link2, Loader2, Copy, Check, Ban } from 'lucide-vue-next'

const props = defineProps<{ sessionId: string; disabled?: boolean }>()

const open = ref(false)
const creating = ref(false)
const copied = ref(false)
const lastLink = ref('')
const lastToken = ref('')
const expiresAt = ref('')
const rootRef = ref<HTMLElement | null>(null)
const expiresDays = ref(7)

function onDocClick(e: MouseEvent) {
  if (rootRef.value && !rootRef.value.contains(e.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('click', onDocClick, true))
onUnmounted(() => document.removeEventListener('click', onDocClick, true))

function absoluteShareUrl(path: string) {
  const origin = window.location.origin
  if (path.startsWith('/#/')) return origin + path
  if (path.startsWith('#')) return origin + '/' + path
  return origin + (path.startsWith('/') ? path : '/' + path)
}

/** HTTP 非安全上下文没有 navigator.clipboard，用 textarea 回退 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through
  }
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

async function createShare() {
  if (!props.sessionId || props.disabled) return
  creating.value = true
  try {
    const res = await api.createShare(props.sessionId, expiresDays.value, false)
    lastToken.value = res.token
    lastLink.value = absoluteShareUrl(res.url_path)
    expiresAt.value = res.expires_at
    const ok = await copyText(lastLink.value)
    copied.value = ok
    if (ok) {
      toast.success(`已创建分享链接（${res.message_count} 条消息），已复制`)
      setTimeout(() => { copied.value = false }, 2000)
    } else {
      toast.success(`已创建分享链接（${res.message_count} 条消息），请手动复制下方链接`)
    }
  } catch (e: any) {
    toast.error('创建分享失败：' + (e.message || '未知错误'))
  } finally {
    creating.value = false
  }
}

async function copyAgain() {
  if (!lastLink.value) return
  const ok = await copyText(lastLink.value)
  if (ok) {
    copied.value = true
    toast.success('链接已复制')
    setTimeout(() => { copied.value = false }, 1500)
  } else {
    toast.error('自动复制失败，请手动选中链接复制')
  }
}

async function revoke() {
  if (!lastToken.value) return
  try {
    await api.revokeShare(lastToken.value)
    toast.success('已撤销分享链接')
    lastLink.value = ''
    lastToken.value = ''
    expiresAt.value = ''
  } catch (e: any) {
    toast.error('撤销失败：' + (e.message || '未知错误'))
  }
}

function fmtDate(iso: string) {
  try { return new Date(iso).toLocaleString('zh-CN') } catch { return iso }
}

function selectLink(e: Event) {
  const el = e.target as HTMLInputElement
  el.select()
}
</script>

<template>
  <div ref="rootRef" class="relative">
    <button
      class="btn-secondary text-sm flex items-center gap-2"
      :disabled="disabled || creating"
      @click="open = !open"
      title="生成只读分享链接"
    >
      <Loader2 v-if="creating" class="w-4 h-4 animate-spin" />
      <Link2 v-else class="w-4 h-4" />
      分享
    </button>

    <div v-if="open" class="absolute bottom-full right-0 mb-2 w-80 bg-white border border-ruc-divider rounded-xl shadow-modal z-40 p-3">
      <p class="text-sm font-ui text-ruc-text font-medium mb-1">只读分享链接</p>
      <p class="text-[11px] font-ui text-ruc-text-light mb-3">任何人打开链接可查看当前对话快照，不能继续提问。可随时撤销。</p>

      <label class="flex items-center justify-between text-xs font-ui text-ruc-text-dim mb-3">
        <span>有效期</span>
        <select v-model.number="expiresDays" class="border border-ruc-border rounded-lg px-2 py-1 bg-white">
          <option :value="1">1 天</option>
          <option :value="7">7 天</option>
          <option :value="30">30 天</option>
        </select>
      </label>

      <button
        class="w-full btn-primary text-sm py-2 mb-2"
        :disabled="creating || disabled"
        @click="createShare"
      >生成并复制链接</button>

      <div v-if="lastLink" class="rounded-lg bg-ruc-bg p-2 space-y-2">
        <input
          :value="lastLink"
          readonly
          class="w-full text-[11px] font-ui text-ruc-text bg-white border border-ruc-divider rounded-lg px-2 py-1.5"
          @focus="selectLink"
          @click="selectLink"
        />
        <p v-if="expiresAt" class="text-[10px] text-ruc-text-light">有效期至 {{ fmtDate(expiresAt) }}</p>
        <div class="flex gap-2">
          <button class="flex-1 text-xs font-ui px-2 py-1.5 rounded-lg border border-ruc-divider hover:border-ruc-red/30 flex items-center justify-center gap-1" @click="copyAgain">
            <Check v-if="copied" class="w-3 h-3 text-ruc-success" />
            <Copy v-else class="w-3 h-3" />
            {{ copied ? '已复制' : '复制' }}
          </button>
          <button class="flex-1 text-xs font-ui px-2 py-1.5 rounded-lg border border-ruc-error/30 text-ruc-error hover:bg-ruc-error/5 flex items-center justify-center gap-1" @click="revoke">
            <Ban class="w-3 h-3" /> 撤销
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
