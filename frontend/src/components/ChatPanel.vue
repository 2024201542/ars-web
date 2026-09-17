<script setup lang="ts">
import { ref, nextTick, watch, computed } from 'vue'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import { useChatStream } from '@/composables/useChatStream'
import { api } from '@/api'
import ExportButton from './ExportButton.vue'
import ShareButton from './ShareButton.vue'
import SkillGuide from './SkillGuide.vue'
import FileMentionPopup from './FileMentionPopup.vue'
import MarkdownIt from 'markdown-it'
import { ArrowUp, Square, Copy, Check, Loader2, Circle, CheckCircle, Download } from 'lucide-vue-next'

const props = defineProps<{ sessionId: string; skillName?: string; modeName?: string }>()
const emit = defineEmits<{ done: [] }>()
const sessionStore = useSessionStore()
const settingsStore = useSettingsStore()
const toast = useToast()

const { isStreaming, resultContent, progressTokens, progressPhase, lastToolUse, statusText, sendMessage: streamSend, abort } =
  useChatStream(props.sessionId, () => emit('done'))

const inputMessage = ref('')
const chatContainer = ref<HTMLElement | null>(null)
const showScrollBtn = ref(false)
const copiedId = ref<number | null>(null)
const selectedIds = ref<Set<number>>(new Set())
const attachedFiles = ref<any[]>([])
const mentionQuery = ref('')
const showMention = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const sendingLock = ref(false)

const md = new MarkdownIt({ html: false, breaks: true, linkify: true })
const charCount = computed(() => inputMessage.value.length)
const isCharLimitExceeded = computed(() => charCount.value > 50000)

// ── 滚动 ──
function isNearBottom() { const el = chatContainer.value; return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80 }
function scrollToBottom(smooth?: boolean) { nextTick(() => chatContainer.value?.scrollTo({ top: chatContainer.value.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })) }
function onScroll() { showScrollBtn.value = !isNearBottom() }
watch(() => resultContent.value, () => { if (isStreaming.value && isNearBottom()) scrollToBottom(); else if (!isStreaming.value) showScrollBtn.value = !isNearBottom() })

// ── @ 文件引用（Cursor 风格：选中后在输入框留下 @文件名，可连续 @）──
const mentionPopupRef = ref<InstanceType<typeof FileMentionPopup> | null>(null)

function resizeTextarea(t: HTMLTextAreaElement) {
  t.style.height = 'auto'
  t.style.height = Math.min(t.scrollHeight, 160) + 'px'
}

function onTextareaInput(e: Event) {
  const t = e.target as HTMLTextAreaElement
  inputMessage.value = t.value
  resizeTextarea(t)
  const caret = t.selectionStart
  const before = t.value.slice(0, caret)
  const m = before.match(/@("[^"]*"|[^\s@]*)$/)
  if (m) {
    const raw = m[1]
    mentionQuery.value = (raw.startsWith('"') && raw.endsWith('"')) ? raw.slice(1, -1) : raw
    showMention.value = true
  } else {
    showMention.value = false
    mentionQuery.value = ''
  }
}

function onFileSelect(f: any) {
  const t = textareaRef.value
  const val = inputMessage.value
  const caret = t?.selectionStart ?? val.length
  const before = val.slice(0, caret)
  const after = val.slice(caret)
  const token = /\s/.test(f.name) ? `"${f.name}"` : f.name
  const insert = `@${token}`
  const m = before.match(/@("[^"]*"|[^\s@]*)$/)
  let newBefore: string
  if (m) {
    newBefore = before.slice(0, before.length - m[0].length) + insert + ' '
  } else {
    const needSpace = before.length > 0 && !/\s$/.test(before)
    newBefore = before + (needSpace ? ' ' : '') + insert + ' '
  }
  inputMessage.value = newBefore + after
  if (!attachedFiles.value.find((x: any) => x.path === f.path)) {
    attachedFiles.value.push({ ...f })
  }
  showMention.value = false
  mentionQuery.value = ''
  nextTick(() => {
    if (!t) return
    const pos = newBefore.length
    t.focus()
    t.setSelectionRange(pos, pos)
    resizeTextarea(t)
  })
}

function removeAttachedFile(f: any) {
  attachedFiles.value = attachedFiles.value.filter((x: any) => x.path !== f.path)
}

/** 已完成的 @提及：@"带空格" 或 @普通文件名 */
function findMentions(text: string): { start: number; end: number; name: string }[] {
  const out: { start: number; end: number; name: string }[] = []
  const re = /@("[^"]+"|[^\s@]+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const raw = m[1]
    const name = (raw.startsWith('"') && raw.endsWith('"')) ? raw.slice(1, -1) : raw
    out.push({ start: m.index, end: m.index + m[0].length, name })
  }
  return out
}

function syncAttachedFromText() {
  const names = new Set(findMentions(inputMessage.value).map((x) => x.name))
  attachedFiles.value = attachedFiles.value.filter(
    (f: any) => names.has(f.name) || names.has(f.path)
  )
}

/** Backspace / Delete 时整段删掉 @文件，避免半截文件名 */
function tryDeleteWholeMention(e: KeyboardEvent): boolean {
  const t = textareaRef.value
  if (!t || showMention.value) return false
  if (e.key !== 'Backspace' && e.key !== 'Delete') return false

  const val = inputMessage.value
  let selStart = t.selectionStart
  let selEnd = t.selectionEnd
  const mentions = findMentions(val)

  // 选中范围正好是某个 @提及 → 整段删除
  if (selStart !== selEnd) {
    const exact = mentions.find((m) => m.start === selStart && m.end === selEnd)
    if (!exact) return false
    e.preventDefault()
    let delEnd = exact.end
    if (val[delEnd] === ' ') delEnd++
    inputMessage.value = val.slice(0, exact.start) + val.slice(delEnd)
    syncAttachedFromText()
    nextTick(() => {
      t.focus()
      t.setSelectionRange(exact.start, exact.start)
      resizeTextarea(t)
    })
    return true
  }

  const caret = selStart
  let target: { start: number; end: number; name: string } | undefined

  if (e.key === 'Backspace') {
    // 光标在提及内部或末尾
    target = mentions.find((m) => caret > m.start && caret <= m.end)
    // 光标在提及后紧跟的空格后面（我们插入时带了尾随空格）
    if (!target && caret > 0 && val[caret - 1] === ' ') {
      target = mentions.find((m) => m.end === caret - 1)
    }
  } else {
    // Delete：光标在提及开头或内部
    target = mentions.find((m) => caret >= m.start && caret < m.end)
  }

  if (!target) return false

  e.preventDefault()
  let delEnd = target.end
  if (val[delEnd] === ' ') delEnd++
  inputMessage.value = val.slice(0, target.start) + val.slice(delEnd)
  syncAttachedFromText()
  nextTick(() => {
    t.focus()
    t.setSelectionRange(target!.start, target!.start)
    resizeTextarea(t)
  })
  return true
}

// ── 多选导出 ──
function toggleSelect(id: number) { const s = new Set(selectedIds.value); if (s.has(id)) { s.delete(id) } else { s.add(id) }; selectedIds.value = s }
function clearSelection() { selectedIds.value = new Set() }
function exportMarkdown() {
  const sel = sessionStore.messages.filter((m: any) => selectedIds.value.has(m.id))
  if (!sel.length) { toast.warning('请先选择消息'); return }
  let md = `# 研究报告\n> ${new Date().toLocaleString('zh-CN')}\n\n---\n\n`
  sel.forEach((m: any) => { md += m.role === 'user' ? `### 💬 提问\n${m.content||''}\n\n` : `### 🤖 回复\n${m.content||''}\n\n`; md += '---\n\n' })
  const b = new Blob([md], { type: 'text/markdown;charset=utf-8' }); const u = URL.createObjectURL(b)
  const a = document.createElement('a'); a.href = u; a.download = `ars_export_${new Date().toISOString().slice(0,10)}.md`; a.click()
  URL.revokeObjectURL(u); toast.success(`已导出 ${sel.length} 条`); clearSelection()
}
async function copyContent(content: string, id: number) { try { await navigator.clipboard.writeText(content); copiedId.value = id; setTimeout(() => copiedId.value = null, 2000) } catch { toast.error('复制失败') } }

// ── 发送 ──
async function handleSend() {
  let msg = inputMessage.value.trim()
  if (!msg && !attachedFiles.value.length) return

  // 只保留「完整且能对应到已选文件」的 @提及；残缺/手打的 @xxx 不当附件，避免串文件
  const mentions = findMentions(msg)
  const resolved = mentions.filter((m) =>
    attachedFiles.value.some((f: any) => f.name === m.name || f.path === m.name)
  )
  const resolvedNames = new Set(resolved.map((m) => m.name))
  attachedFiles.value = attachedFiles.value.filter(
    (f: any) => resolvedNames.has(f.name) || resolvedNames.has(f.path)
  )

  // 从发给模型的正文里去掉未解析成功的残缺 @片段（已解析的保留为 @名，便于对照）
  // 不做破坏性改写：模型侧真正内容靠附件注入；display 仍用附件列表
  doSend(msg)
  inputMessage.value = ''
  attachedFiles.value = []
  showMention.value = false
  if (textareaRef.value) { textareaRef.value.style.height = 'auto' }
}
async function maybeSaveTitle(display: string) {
  const sess = sessionStore.currentSession
  if (!sess) return
  const defaultTitle = `${sess.skill_name || 'session'} 会话`
  if (sess.title && sess.title !== defaultTitle && !String(sess.title).endsWith(' 会话')) return
  const title = display.replace(/\n/g, ' ').replace(/📎\s*/g, '').trim().slice(0, 40)
  if (!title) return
  try {
    const updated = await api.updateSession(props.sessionId, title)
    if (sessionStore.currentSession) sessionStore.currentSession.title = updated.title || title
  } catch {}
}

async function doSend(msg: string) {
  if (sendingLock.value || isStreaming.value || !settingsStore.isConfigured) {
    if (!settingsStore.isConfigured) toast.info('请先配置 API Key')
    return
  }
  sendingLock.value = true
  let fullMsg = msg
  if (attachedFiles.value.length) {
    const ctx: string[] = []
    for (const f of attachedFiles.value) { try { const r = await api.getFileContent(props.sessionId, f.path); ctx.push(`[文件: ${f.name}]\n${r.content}`) } catch { ctx.push(`[文件: ${f.name}]`) } }
    fullMsg = msg ? `${ctx.join('\n\n')}\n---\n用户问题: ${msg}` : `${ctx.join('\n\n')}\n---\n请分析以上文件内容`
  }
  const display = attachedFiles.value.length ? attachedFiles.value.map((f: any) => `📎 ${f.name}`).join(' ') + (msg ? '\n' + msg : '') : msg
  sessionStore.addMessage({ id: Date.now(), session_id: props.sessionId, role: 'user', content: display, agent_name: null, phase_name: null, metadata: null, created_at: new Date().toISOString() })
  void maybeSaveTitle(display)
  const aid = Date.now() + 1
  sessionStore.addMessage({ id: aid, session_id: props.sessionId, role: 'assistant', content: '', agent_name: null, phase_name: null, metadata: null, created_at: new Date().toISOString() })
  scrollToBottom(true)
  try {
    await streamSend(fullMsg, settingsStore.selectedModel || undefined)
  } finally {
    sendingLock.value = false
  }
}
async function handleStop() { try { await api.stopChat(props.sessionId) } catch {} abort() }
function handleKeydown(e: KeyboardEvent) {
  if (showMention.value && ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(e.key)) {
    e.preventDefault()
    e.stopPropagation()
    mentionPopupRef.value?.handleKeydown(e)
    return
  }
  if (tryDeleteWholeMention(e)) return
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
function renderMarkdown(t: string) { return t ? md.render(t) : '' }
</script>

<template>
  <div class="h-full flex flex-col relative">
    <div ref="chatContainer" data-chat-container @scroll="onScroll" class="flex-1 overflow-y-auto px-4 sm:px-6 py-4 space-y-4">
      <div v-if="!sessionStore.messages.length" class="flex items-start justify-center h-full pt-4">
        <SkillGuide v-if="props.skillName" :skill="props.skillName" :mode="props.modeName||'full'" />
        <div v-else class="text-center max-w-sm animate-fade-in"><div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-ruc-red-pale flex items-center justify-center"><Loader2 class="w-8 h-8 text-ruc-red/30" /></div><p class="text-ruc-text-dim text-lg font-display mb-2">开始您的学术研究</p><p class="text-ruc-text-light text-sm font-ui">在下方输入研究主题，AI 将协助您完成学术工作</p></div>
      </div>
      <div v-for="msg in sessionStore.messages" :key="msg.id" :data-msg-id="msg.id" class="flex items-start gap-2 animate-fade-in" :class="msg.role==='user'?'justify-end':'justify-start'">
        <button v-if="msg.role==='assistant' && msg.content" @click="toggleSelect(msg.id)" class="flex-shrink-0 mt-3 p-0.5 rounded-full transition-all" :class="selectedIds.has(msg.id)?'text-ruc-red opacity-100':'text-ruc-text-light opacity-0 group-hover:opacity-100'"><CheckCircle v-if="selectedIds.has(msg.id)" class="w-4 h-4" /><Circle v-else class="w-4 h-4" /></button>
        <div class="max-w-[80%] sm:max-w-[72%] rounded-2xl px-4 py-3 relative group" :class="msg.role==='user'?'bg-ruc-warm border border-ruc-divider':'bg-white border border-ruc-divider shadow-sm'">
          <button v-if="msg.role==='assistant' && msg.content" @click="copyContent(msg.content!,msg.id)" class="absolute -top-1.5 -right-1.5 opacity-0 group-hover:opacity-100 transition-all p-1.5 rounded-lg bg-white border border-ruc-divider shadow-elevated hover:border-ruc-red/30" title="复制"><Check v-if="copiedId===msg.id" class="w-3 h-3 text-ruc-success" /><Copy v-else class="w-3 h-3 text-ruc-text-dim" /></button>
          <div v-if="msg.role==='user'" class="text-ruc-text font-ui text-sm whitespace-pre-wrap leading-relaxed">{{ msg.content }}</div>
          <div v-else-if="msg._streaming && msg.content" class="text-ruc-text font-ui text-sm whitespace-pre-wrap leading-relaxed">{{ msg.content }}<span class="inline-block w-0.5 h-4 bg-ruc-red ml-0.5 animate-pulse align-middle" /></div>
          <div v-else-if="msg.content" class="markdown-body text-sm" :class="{'ring-2 ring-ruc-red/20 rounded-lg':selectedIds.has(msg.id)}" v-html="renderMarkdown(msg.content!)" />
          <div v-else class="py-1"><div class="flex items-center gap-2.5 text-ruc-text-dim font-ui text-sm"><Loader2 class="w-4 h-4 animate-spin text-ruc-red/50" /><span class="animate-pulse-soft">{{ statusText }}</span></div><div class="mt-2 h-1.5 bg-ruc-bg rounded-full overflow-hidden w-full max-w-[300px]"><div class="h-full bg-ruc-red/30 rounded-full transition-all duration-500 ease-out" :style="{width:Math.min(100,Math.max(5,(progressTokens/50)*2))+'%'}" /></div></div>
        </div>
      </div>
    </div>
    <button v-if="showScrollBtn && !isStreaming" @click="scrollToBottom(true)" class="absolute bottom-[120px] left-1/2 -translate-x-1/2 z-10 px-3 py-1.5 rounded-full bg-white border border-ruc-divider shadow-elevated text-xs font-ui text-ruc-text-dim hover:text-ruc-red hover:border-ruc-red/30 transition-all animate-fade-in">↓ 回到底部</button>
    <div v-if="selectedIds.size>0" class="flex-shrink-0 px-4 sm:px-6 py-2 border-t border-ruc-divider bg-ruc-red-pale flex items-center justify-between gap-3"><span class="text-xs font-ui text-ruc-red font-medium">已选择 {{ selectedIds.size }} 条</span><div class="flex items-center gap-2"><button @click="clearSelection" class="text-xs font-ui text-ruc-text-dim hover:text-ruc-text px-2 py-1 rounded-lg hover:bg-ruc-bg transition-colors">取消</button><button @click="exportMarkdown" class="btn-primary text-xs !py-1.5 !px-3 flex items-center gap-1"><Download class="w-3 h-3" />导出 Markdown</button></div></div>
    <div v-if="sessionStore.messages.length && !isStreaming" class="flex-shrink-0 px-4 sm:px-6 py-2 border-t border-ruc-divider flex items-center gap-3 bg-white/50"><ShareButton :session-id="sessionId" />
<ExportButton :session-id="sessionId" /><span class="text-xs font-ui text-ruc-text-light">{{ sessionStore.messages.length }} 条消息<template v-if="resultContent"> · 最近回复 {{ resultContent.length }} 字</template></span></div>
    <div class="flex-shrink-0 border-t border-ruc-divider bg-white/80 backdrop-blur-md px-4 sm:px-6 py-3">
      <div v-if="isStreaming" class="flex items-center gap-2 mb-2 text-xs font-ui"><Loader2 class="w-3 h-3 animate-spin text-ruc-red/60" /><span class="text-ruc-text-dim">{{ statusText }}</span><span v-if="progressTokens>0" class="text-ruc-text-light ml-auto">{{ progressTokens }} tokens</span></div>
      <div class="flex gap-2.5 items-end relative">
        <div class="flex-1 relative">
          <textarea ref="textareaRef" v-model="inputMessage" @keydown="handleKeydown" @input="onTextareaInput" :disabled="isStreaming" placeholder="输入研究主题… 用 @ 引用文件，可连续 @ 多个；Enter 发送" rows="1" class="w-full resize-none font-ui text-sm bg-white border border-ruc-border rounded-2xl px-4 py-3 placeholder:text-ruc-text-light focus:outline-none focus:border-ruc-red/40 focus:ring-2 focus:ring-ruc-red/15 transition-all duration-150 disabled:bg-ruc-bg disabled:text-ruc-text-light" :class="{'!border-ruc-error/50 !ring-ruc-error/20':isCharLimitExceeded}" style="min-height:44px;max-height:160px" />
          <FileMentionPopup v-if="showMention" ref="mentionPopupRef" :session-id="sessionId" :query="mentionQuery" @select="onFileSelect" @close="showMention=false" />
        </div>
        <button v-if="!isStreaming" @click="handleSend" :disabled="!inputMessage.trim() && !attachedFiles.length" class="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 transition-all duration-200" :class="(inputMessage.trim()||attachedFiles.length)?'bg-ruc-red text-white shadow-sm shadow-ruc-red/20 hover:bg-ruc-red-light hover:shadow-md hover:-translate-y-0.5 active:translate-y-0 active:shadow-none':'bg-ruc-bg text-ruc-text-light cursor-not-allowed'"><ArrowUp class="w-5 h-5" /></button>
        <button v-else @click="handleStop" class="w-10 h-10 rounded-xl bg-ruc-error-soft border border-ruc-error/20 flex items-center justify-center flex-shrink-0 hover:bg-ruc-error/10 hover:border-ruc-error/40 transition-all duration-200" title="停止生成"><Square class="w-4 h-4 text-ruc-error" /></button>
      </div>
    </div>
  </div>
</template>
