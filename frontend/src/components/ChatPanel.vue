<script setup lang="ts">
import { ref, nextTick, watch, computed, onMounted, onUnmounted } from 'vue'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { useAuthStore } from '@/stores/auth'
import { usePendingStartStore } from '@/stores/pendingStart'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToast } from '@/composables/useToast'
import { useChatStream } from '@/composables/useChatStream'
import { api } from '@/api'
import type { DebatePayload, DebatePlan, DebateVoice } from '@/types'
import SkillGuide from './SkillGuide.vue'
import FileMentionPopup from './FileMentionPopup.vue'
import MarkdownIt from 'markdown-it'
import { DIRECT_ENTRIES, FUNCTION_GROUPS, entryButtonLabel } from '@/utils/composerModes'
import { ArrowUp, Square, Copy, Check, Loader2, FilePlus, FileText, X, ChevronDown, ChevronRight, ChevronLeft } from 'lucide-vue-next'

const props = defineProps<{
  sessionId: string
  skillName?: string
  modeName?: string
  source?: string
  openFile?: { name: string; path: string; ext: string } | null
}>()
const emit = defineEmits<{ done: []; generated: [file: any]; wrote: [] }>()
const sessionStore = useSessionStore()
const settingsStore = useSettingsStore()
const auth = useAuthStore()
const pendingStart = usePendingStartStore()
const workspaceStore = useWorkspaceStore()
const toast = useToast()

const { isStreaming, resultContent, progressTokens, progressPhase, lastToolUse, statusText, sendMessage: streamSend, abort } =
  useChatStream(() => props.sessionId, () => emit('done'))

const inputMessage = ref('')
const chatContainer = ref<HTMLElement | null>(null)
const showScrollBtn = ref(false)
const copiedId = ref<number | null>(null)
const selectedIds = ref<Set<number>>(new Set())
const docMenuId = ref<number | null>(null)
const generatingId = ref<number | null>(null)
const dropActive = ref(false)
const dropping = ref(false)
let dragDepth = 0
const skipWrite = ref(false)
const writingId = ref<number | null>(null)
const templatePath = ref('')
const writable = computed(() => {
  const file = props.openFile
  if (!file || skipWrite.value) return false
  return ['.md', '.txt', '.bib', '.tex', '.docx'].includes((file.ext || '').toLowerCase())
})
watch(() => props.openFile?.path, () => { skipWrite.value = false })
const docxTemplates = computed(() =>
  workspaceStore.files.filter(f => (f.ext || '').toLowerCase() === '.docx' && f.dir !== 'generated')
)
const attachedFiles = ref<any[]>([])
const mentionQuery = ref('')
const showMention = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const sendingLock = ref(false)
const modeMenu = ref(false)
const modelMenu = ref(false)
const debateSetup = ref(false)
const activeGroup = ref('')
const composerBar = ref<HTMLElement | null>(null)
const entryLabel = computed(() => entryButtonLabel(props.skillName, props.modeName))
const configuredModels = computed(() => {
  const ready = new Set(settingsStore.providers.filter((item) => item.key_configured).map((item) => item.id))
  return settingsStore.models.filter((item) => ready.has(item.provider))
})
const currentModelName = computed(() => settingsStore.models.find((item) => item.id === settingsStore.selectedModel)?.name || '选择模型')
const debateIds = ref<string[]>([])
const debateStances = ref<Record<string, string>>({})
const extraModels = ref<{ id: string; name: string; provider: string }[]>([])
const extraName = ref('')
const extraProvider = ref('')
const extraStance = ref('')
const topicSeed = ref('')
const topicModel = ref('')
const summaryModel = ref('')
const judgeModel = ref('')
const pairA = ref('')
const pairB = ref('')
const pickedRounds = ref<number[]>([])
const openedParts = ref<Record<string, boolean>>({})
const keyedProviders = computed(() => settingsStore.providers.filter((item) => item.key_configured))
const builtinChoices = computed(() => configuredModels.value.map((item) => ({ id: item.id, name: item.name, provider: item.provider })))
const seatChoices = computed(() => {
  const known = new Set(builtinChoices.value.map((item) => item.id))
  return [...builtinChoices.value, ...extraModels.value.filter((item) => !known.has(item.id))]
})
const selectedBuiltin = computed(() => debateIds.value.filter((id) => !extraModels.value.some((item) => item.id === id)))
function seatOf(id: string) {
  return seatChoices.value.find((item) => item.id === id)
}
function toggleDebate(id: string) {
  if (props.modeName === 'socratic') {
    debateIds.value = debateIds.value[0] === id ? [] : [id]
    return
  }
  if (debateIds.value.includes(id)) debateIds.value = debateIds.value.filter((item) => item !== id)
  else if (debateIds.value.length < 4) debateIds.value = [...debateIds.value, id]
}
function addExtraModel() {
  const id = extraName.value.trim()
  const provider = extraProvider.value || keyedProviders.value[0]?.id || ''
  if (!id || !provider) {
    toast.info('先在设置里保存 API Key，再填写模型名')
    return
  }
  const stance = extraStance.value.trim()
  if (builtinChoices.value.some((item) => item.id === id)) {
    if (stance) debateStances.value = { ...debateStances.value, [id]: stance }
    extraName.value = ''
    extraStance.value = ''
    if (props.modeName === 'socratic') debateIds.value = [id]
    else if (!debateIds.value.includes(id) && debateIds.value.length < 4) debateIds.value = [...debateIds.value, id]
    return
  }
  if (!extraModels.value.some((item) => item.id === id)) extraModels.value = [...extraModels.value, { id, name: id, provider }]
  if (stance) debateStances.value = { ...debateStances.value, [id]: stance }
  extraName.value = ''
  extraStance.value = ''
  if (props.modeName === 'socratic') debateIds.value = [id]
  else if (!debateIds.value.includes(id) && debateIds.value.length < 4) debateIds.value = [...debateIds.value, id]
}
function removeExtraModel(id: string) {
  extraModels.value = extraModels.value.filter((item) => item.id !== id)
  debateIds.value = debateIds.value.filter((item) => item !== id)
  const next = { ...debateStances.value }
  delete next[id]
  debateStances.value = next
}
function currentSeats() {
  return debateIds.value.map((id) => {
    const known = seatOf(id)
    return {
      model: id,
      provider: known?.provider || '',
      name: known?.name || id,
      stance: (debateStances.value[id] || '').trim(),
    }
  }).filter((item) => item.provider)
}
function debateRequest(action?: string, scope?: string, who = ''): DebatePayload | undefined {
  if (props.skillName !== 'idea-debate') return undefined
  if (props.modeName === 'socratic' || (props.modeName === 'custom' && !debateIds.value.length)) {
    const picked = configuredModels.value.find((item) => item.id === settingsStore.selectedModel)
    return {
      seats: picked ? [{ model: picked.id, provider: picked.provider, name: picked.name }] : [],
    }
  }
  if (action === 'summarize') {
    const modelId = scope === 'judge' ? judgeModel.value : summaryModel.value
    const known = seatOf(modelId)
    const pair = scope === 'judge'
      ? [pairA.value, pairB.value].filter(Boolean)
      : scope === 'speaker'
        ? [who || '']
        : []
    return {
      action: 'summarize',
      seats: known ? [{ model: known.id, provider: known.provider, name: known.name }] : [],
      summarize_model: modelId,
      summarize_scope: scope || 'rounds',
      summarize_pair: pair,
      summarize_rounds: scope === 'rounds' || scope === 'judge' ? [...pickedRounds.value] : [],
    }
  }
  return {
    action: action || undefined,
    seats: currentSeats(),
    summarize_model: action === 'topic' ? (topicModel.value || debateIds.value[0] || '') : undefined,
  }
}
watch(() => props.modeName, (mode) => {
  if (mode !== 'contrast') debateSetup.value = false
  if (mode === 'socratic' && debateIds.value.length > 1) debateIds.value = debateIds.value.slice(0, 1)
})
watch(keyedProviders, (list) => {
  if (!extraProvider.value && list[0]) extraProvider.value = list[0].id
}, { immediate: true })
const openedGroup = computed(() => FUNCTION_GROUPS.find((item) => item.skill === activeGroup.value) || null)

function closeComposerMenus() {
  modeMenu.value = false
  modelMenu.value = false
  debateSetup.value = false
  activeGroup.value = ''
}
const debateSetupLabel = computed(() => debateIds.value.length ? `辩论设置 · ${debateIds.value.length}` : '辩论设置')

function onComposerDocClick(event: MouseEvent) {
  if (composerBar.value && !composerBar.value.contains(event.target as Node)) closeComposerMenus()
}

function showPlanned(label: string) {
  closeComposerMenus()
  toast.info(`${label}还在待开发`)
}

async function pickEntry(skill: string, mode: string) {
  closeComposerMenus()
  if (props.skillName === skill && props.modeName === mode) return
  try {
    const updated = await api.updateSessionEntry(props.sessionId, skill, mode)
    const current = sessionStore.currentSession
    if (current && current.id === props.sessionId) {
      current.skill_name = updated.skill_name || skill
      current.mode_name = updated.mode_name || mode
    }
  } catch (err: any) {
    toast.error(err.message || '切换入口失败')
  }
}

async function pickModel(id: string) {
  modelMenu.value = false
  if (id === settingsStore.selectedModel) return
  try {
    await settingsStore.setModel(id)
  } catch (err: any) {
    toast.error(err.message || '切换模型失败')
  }
}

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

function attachWorkspaceFile(f: any) {
  if (!f?.path) return
  const token = /\s/.test(f.name || '') ? `"${f.name}"` : (f.name || f.path)
  const insert = `@${token} `
  const val = inputMessage.value
  const needSpace = val.length > 0 && !/\s$/.test(val)
  inputMessage.value = val + (needSpace ? ' ' : '') + insert
  if (!attachedFiles.value.find((x: any) => x.path === f.path)) {
    attachedFiles.value.push({ ...f })
  }
  nextTick(() => {
    const t = textareaRef.value
    if (!t) return
    t.focus()
    const pos = inputMessage.value.length
    t.setSelectionRange(pos, pos)
    resizeTextarea(t)
  })
}

function dropTypes(e: DragEvent) {
  return Array.from(e.dataTransfer?.types || [])
}

function canAcceptDrop(e: DragEvent) {
  if (isStreaming.value || dropping.value) return false
  const types = dropTypes(e)
  return types.includes('Files') || types.includes('application/x-ars-file')
}

function onComposerDragEnter(e: DragEvent) {
  if (!canAcceptDrop(e)) return
  e.preventDefault()
  dragDepth += 1
  dropActive.value = true
}

function onComposerDragOver(e: DragEvent) {
  if (!canAcceptDrop(e)) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
}

function onComposerDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dropActive.value = false
}

async function onComposerDrop(e: DragEvent) {
  e.preventDefault()
  dragDepth = 0
  dropActive.value = false
  if (isStreaming.value) return
  const raw = e.dataTransfer?.getData('application/x-ars-file')
  if (raw) {
    try {
      attachWorkspaceFile(JSON.parse(raw))
      toast.success('已加入对话')
    } catch {
      toast.error('无法加入该文件')
    }
    return
  }
  const files = Array.from(e.dataTransfer?.files || [])
  if (!files.length) return
  dropping.value = true
  try {
    for (const file of files) {
      const info = await workspaceStore.upload(props.sessionId, file)
      attachWorkspaceFile(info)
    }
    toast.success(files.length > 1 ? `已加入 ${files.length} 个文件` : `已加入 ${files[0].name}`)
  } catch (ex: any) {
    toast.error(ex.message || '上传失败')
  } finally {
    dropping.value = false
  }
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
async function copyContent(content: string, id: number) { try { await navigator.clipboard.writeText(content); copiedId.value = id; setTimeout(() => copiedId.value = null, 2000) } catch { toast.error('复制失败') } }

async function writeInto(msg: { id: number; content?: string | null }) {
  const file = props.openFile
  if (!file || writingId.value) return
  writingId.value = msg.id
  try {
    const current = await api.getFileContent(props.sessionId, file.path, props.source)
    const body = (msg.content || '').trim()
    const base = (current.content || '').replace(/\s+$/, '')
    const next = base ? `${base}\n\n${body}\n` : `${body}\n`
    await api.saveFileContent(props.sessionId, file.path, next, props.source)
    toast.success(`已写入 ${file.name}`)
    emit('wrote')
  } catch (e: any) {
    toast.error(e.message || '写入失败')
  } finally {
    writingId.value = null
  }
}

async function generateFromMessage(id: number, format: 'markdown' | 'docx', merge = false) {
  const ids = merge ? [...selectedIds.value] : [id]
  if (!ids.length) return
  generatingId.value = id
  try {
    const file = await api.generateWorkspaceDoc(props.sessionId, {
      format,
      message_ids: ids,
      template_path: format === 'docx' ? templatePath.value : '',
    })
    await workspaceStore.loadFiles(props.sessionId)
    const label = format === 'docx'
      ? (templatePath.value ? '按模板生成的 Word' : 'Word')
      : 'Markdown'
    toast.success(ids.length > 1 ? `已把 ${ids.length} 条回复生成${label}` : `已把这条回复生成${label}`)
    emit('generated', file)
    docMenuId.value = null
    if (merge) clearSelection()
  } catch (e: any) {
    toast.error(e.message || '生成失败')
  } finally {
    generatingId.value = null
  }
}

// ── 发送 ──
const steering = ref(false)
const debateHold = computed(() => {
  const list = sessionStore.messages
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const hold = list[i].debateHold
    if (list[i].role === 'assistant' && hold?.name) return hold
  }
  return null
})
const composerPlaceholder = computed(() => {
  if (debateHold.value?.between) return '这一轮说完了。写下你的意见，或直接开始下一轮'
  if (isStreaming.value && steering.value) return '可以先写下给下一位的方向。发送要等这一轮结束'
  if (isStreaming.value) return '可以先写下一句。这一轮结束前不能发送'
  if (props.skillName === 'idea-debate' && props.modeName === 'socratic') return '写下主题和你的看法，Enter 发送'
  if (props.skillName === 'literature-find' || (props.skillName === 'academic-paper' && props.modeName === 'lit-search')) return '输入检索词，Enter 发送'
  return '输入研究主题… 用 @ 引用文件，或把文件拖到这里；Enter 发送'
})

async function releaseTurn() {
  const text = inputMessage.value.trim()
  if (!text && !debateHold.value) return
  try {
    await api.debateHint(props.sessionId, text)
    inputMessage.value = ''
    toast.info(debateHold.value?.between ? (text ? '已带上你的意见，开始下一轮' : '开始下一轮') : '已记下，下一轮会看见')
  } catch (err: any) {
    toast.error(err.message || '这句提示没有送进去')
  }
}

async function handleSend() {
  if (isStreaming.value || sendingLock.value || dropping.value) return
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
  if (sess.title && sess.title !== defaultTitle && sess.title !== '新对话' && !String(sess.title).endsWith(' 会话')) return
  const title = display.replace(/\n/g, ' ').replace(/📎\s*/g, '').trim().slice(0, 40)
  if (!title) return
  try {
    const updated = await api.updateSession(props.sessionId, title)
    if (sessionStore.currentSession) sessionStore.currentSession.title = updated.title || title
  } catch {}
}

function authorLabel(msg: { role: string; metadata?: string | null }) {
  if (!msg.metadata) return ''
  try {
    const meta = typeof msg.metadata === 'string' ? JSON.parse(msg.metadata) : msg.metadata
    return meta?.author || ''
  } catch {
    return ''
  }
}

function fileEdits(msg: { edits?: { backup_id: string; files: { path: string; name: string; action: string }[] } | null; metadata?: string | null }) {
  if (msg.edits?.files?.length) return msg.edits
  if (!msg.metadata) return null
  try {
    const meta = typeof msg.metadata === 'string' ? JSON.parse(msg.metadata) : msg.metadata
    return meta?.edits?.files?.length ? meta.edits : null
  } catch {
    return null
  }
}

function editSummary(msg: { edits?: { files: { name: string; path: string; action: string }[] } | null; metadata?: string | null }) {
  const edits = fileEdits(msg)
  if (!edits) return ''
  const label = (action: string) => action === 'created' ? '新建' : action === 'deleted' ? '删除' : '修改'
  return edits.files.map((item) => `${label(item.action)} ${item.name || item.path}`).join('，')
}

const undoingId = ref<number | null>(null)
async function undoEdits(msg: { id: number; editsUndone?: boolean; edits?: { backup_id: string } | null; metadata?: string | null }) {
  const edits = fileEdits(msg)
  if (!edits?.backup_id || undoingId.value) return
  undoingId.value = msg.id
  try {
    await api.undoEdits(edits.backup_id)
    msg.editsUndone = true
    toast.success('已撤销这次修改')
    emit('done')
  } catch (err: any) {
    if (String(err.message || '').includes('已经撤销')) msg.editsUndone = true
    toast.error(err.message || '撤销失败')
  } finally {
    undoingId.value = null
  }
}

function pipelineState(msg: { pipeline?: { awaiting?: boolean; done?: boolean; label?: string; group?: string; file?: string; next_label?: string; index?: number; total?: number } | null; metadata?: string | null }) {
  if (msg.pipeline) return msg.pipeline
  if (!msg.metadata) return null
  try {
    const meta = typeof msg.metadata === 'string' ? JSON.parse(msg.metadata) : msg.metadata
    return meta?.pipeline || null
  } catch {
    return null
  }
}

function debateVoices(msg: { debate?: { voices: DebateVoice[] } | null; metadata?: string | null }): DebateVoice[] {
  if (msg.debate?.voices?.length) return msg.debate.voices
  if (!msg.metadata) return []
  try {
    const meta = typeof msg.metadata === 'string' ? JSON.parse(msg.metadata) : msg.metadata
    return meta?.debate?.voices || []
  } catch {
    return []
  }
}

function debatePlanOf(msg: { debatePlan?: DebatePlan | null; metadata?: string | null }): DebatePlan | null {
  if (msg.debatePlan?.topic) return msg.debatePlan
  if (!msg.metadata) return null
  try {
    const meta = typeof msg.metadata === 'string' ? JSON.parse(msg.metadata) : msg.metadata
    return meta?.debate_plan?.topic ? meta.debate_plan : null
  } catch {
    return null
  }
}

function speechVoices(msg: { debate?: { voices: DebateVoice[] } | null; metadata?: string | null }) {
  return debateVoices(msg).filter((item) => item.kind !== 'summary' && item.kind !== 'judge')
}

function speakers(msg: { debate?: { voices: DebateVoice[] } | null; metadata?: string | null }) {
  const seen = new Set<string>()
  const rows: DebateVoice[] = []
  for (const item of speechVoices(msg)) {
    if (!item.model || seen.has(item.model)) continue
    seen.add(item.model)
    rows.push(item)
  }
  return rows
}

function isLatestDebate(msg: { id: number }) {
  const list = sessionStore.messages
  for (let i = list.length - 1; i >= 0; i -= 1) {
    if (speechVoices(list[i]).length) return list[i].id === msg.id
  }
  return false
}

function voiceKind(voice: DebateVoice) {
  if (voice.kind === 'judge') return '法官'
  if (voice.kind === 'summary') return '总结'
  if (voice.round === 2) return '回应'
  return '发言'
}

function showRoundMark(voices: DebateVoice[], index: number) {
  const voice = voices[index]
  if (!voice?.round || voice.kind === 'summary' || voice.kind === 'judge') return false
  const prev = voices[index - 1]
  return !prev || prev.round !== voice.round || prev.kind === 'summary' || prev.kind === 'judge'
}

function partKey(msgId: number, index: number, part: string) {
  return `${msgId}:${index}:${part}`
}

function partOpen(msgId: number, index: number, part: string, text?: string) {
  const key = partKey(msgId, index, part)
  if (key in openedParts.value) return openedParts.value[key]
  return (text || '').length <= 180
}

function togglePart(msgId: number, index: number, part: string, text?: string) {
  const key = partKey(msgId, index, part)
  openedParts.value = { ...openedParts.value, [key]: !partOpen(msgId, index, part, text) }
}

function applyPlan(plan: DebatePlan) {
  if (plan.topic) inputMessage.value = plan.topic
  const next = { ...debateStances.value }
  for (const [id, stance] of Object.entries(plan.stances || {})) next[id] = stance
  debateStances.value = next
}

function isLatestAssistant(msg: { id: number }) {
  const list = sessionStore.messages
  for (let i = list.length - 1; i >= 0; i -= 1) {
    if (list[i].role === 'assistant') return list[i].id === msg.id
  }
  return false
}

async function continuePipeline(starting = false) {
  if (sendingLock.value || isStreaming.value || !settingsStore.isConfigured) return
  sendingLock.value = true
  const text = starting ? '开始' : '确认，继续下一步'
  const author = auth.user?.display_name || auth.user?.username || ''
  const metadata = author ? JSON.stringify({ author }) : null
  sessionStore.addMessage({ id: Date.now(), session_id: props.sessionId, role: 'user', content: text, agent_name: null, phase_name: null, metadata, created_at: new Date().toISOString() })
  sessionStore.addMessage({ id: Date.now() + 1, session_id: props.sessionId, role: 'assistant', content: '', agent_name: null, phase_name: null, metadata: null, created_at: new Date().toISOString() })
  scrollToBottom(true)
  try {
    await streamSend(text, settingsStore.selectedModel || undefined, undefined, 'continue')
  } finally {
    sendingLock.value = false
  }
}

async function doSend(msg: string) {
  if (sendingLock.value || isStreaming.value || !settingsStore.isConfigured) {
    if (!settingsStore.isConfigured) toast.info('请先配置 API Key')
    return
  }
  if (props.skillName === 'idea-debate' && props.modeName === 'socratic' && !settingsStore.selectedModel) {
    toast.info('先在右边选一个模型')
    return
  }
  if (props.skillName === 'idea-debate' && props.modeName === 'contrast' && debateIds.value.length < 2) {
    toast.info('多模型辩论至少选两个模型，同一个接口里的不同模型也可以')
    return
  }
  if (props.skillName === 'idea-debate' && props.modeName === 'custom' && debateIds.value.length < 1 && !settingsStore.selectedModel) {
    toast.info('先在右边选一个模型')
    return
  }
  sendingLock.value = true
  let fullMsg = msg
  if (attachedFiles.value.length) {
    const ctx: string[] = []
    for (const f of attachedFiles.value) {
      if (f.is_dir) { ctx.push(`[文件夹: ${f.path}]`); continue }
      try { const r = await api.getFileContent(props.sessionId, f.path); ctx.push(`[文件: ${f.name}]\n${r.content}`) } catch { ctx.push(`[文件: ${f.name}]`) }
    }
    fullMsg = msg ? `${ctx.join('\n\n')}\n---\n用户问题: ${msg}` : `${ctx.join('\n\n')}\n---\n请分析以上文件内容`
  }
  const display = attachedFiles.value.length ? attachedFiles.value.map((f: any) => `📎 ${f.name}`).join(' ') + (msg ? '\n' + msg : '') : msg
  const author = auth.user?.display_name || auth.user?.username || ''
  const metadata = author ? JSON.stringify({ author }) : null
  sessionStore.addMessage({ id: Date.now(), session_id: props.sessionId, role: 'user', content: display, agent_name: null, phase_name: null, metadata, created_at: new Date().toISOString() })
  void maybeSaveTitle(display)
  const aid = Date.now() + 1
  sessionStore.addMessage({ id: aid, session_id: props.sessionId, role: 'assistant', content: '', agent_name: null, phase_name: null, metadata: null, created_at: new Date().toISOString() })
  scrollToBottom(true)
  steering.value = props.skillName === 'idea-debate' && props.modeName === 'contrast'
  try {
    await streamSend(
      fullMsg,
      settingsStore.selectedModel || undefined,
      writable.value ? props.openFile?.path : undefined,
      undefined,
      undefined,
      debateRequest(),
    )
  } finally {
    steering.value = false
    sendingLock.value = false
  }
}

async function draftTopic() {
  const text = topicSeed.value.trim() || inputMessage.value.trim()
  if (!text) {
    toast.info('先在下面写下你的看法')
    return
  }
  if (debateIds.value.length < 2) {
    toast.info('先点选上面要辩论的模型')
    return
  }
  if (sendingLock.value || isStreaming.value || !settingsStore.isConfigured) return
  await postDebate(text, text, debateRequest('topic'))
}

function debateRounds(msg: { debate?: { voices: DebateVoice[] } | null; metadata?: string | null }) {
  const found = new Set<number>()
  for (const item of speechVoices(msg)) {
    if (item.round) found.add(item.round)
  }
  return [...found].sort((a, b) => a - b)
}

function speakerName(msg: { debate?: { voices: DebateVoice[] } | null; metadata?: string | null }, id: string) {
  return speakers(msg).find((item) => item.model === id)?.name || ''
}

function toggleRound(round: number) {
  pickedRounds.value = pickedRounds.value.includes(round)
    ? pickedRounds.value.filter((item) => item !== round)
    : [...pickedRounds.value, round]
}

async function summarizeDebate(scope: 'rounds' | 'speaker' | 'judge', who = '', name = '') {
  const modelId = scope === 'judge' ? judgeModel.value : summaryModel.value
  if (!modelId) {
    toast.info(scope === 'judge' ? '先选一个法官模型' : '先选一个用来整理的模型')
    return
  }
  if (scope === 'rounds' && !pickedRounds.value.length) {
    toast.info('先标选要整理的轮次')
    return
  }
  if (scope === 'speaker' && !who) {
    toast.info('先选好这一位')
    return
  }
  if (scope === 'judge' && (!pairA.value || !pairB.value || pairA.value === pairB.value)) {
    toast.info('先选好第一位和第二位，法官根据这两位的发言来判断')
    return
  }
  const rounds = [...pickedRounds.value].sort((a, b) => a - b).join('、')
  const text = scope === 'judge'
    ? '请法官根据这两位的发言判断'
    : scope === 'speaker'
      ? `请整理${name || '这位'}的观点`
      : `请整理第${rounds}轮`
  await postDebate(text, text, debateRequest('summarize', scope, who))
}

async function postDebate(display: string, payload: string, debate?: DebatePayload) {
  if (sendingLock.value || isStreaming.value || !settingsStore.isConfigured) {
    if (!settingsStore.isConfigured) toast.info('请先配置 API Key')
    return
  }
  sendingLock.value = true
  const author = auth.user?.display_name || auth.user?.username || ''
  const metadata = author ? JSON.stringify({ author }) : null
  sessionStore.addMessage({ id: Date.now(), session_id: props.sessionId, role: 'user', content: display, agent_name: null, phase_name: null, metadata, created_at: new Date().toISOString() })
  sessionStore.addMessage({ id: Date.now() + 1, session_id: props.sessionId, role: 'assistant', content: '', agent_name: null, phase_name: null, metadata: null, created_at: new Date().toISOString() })
  scrollToBottom(true)
  try {
    await streamSend(payload, settingsStore.selectedModel || undefined, undefined, undefined, undefined, debate)
  } finally {
    sendingLock.value = false
  }
}
const pendingStarted = ref(false)
async function startPending() {
  if (pendingStarted.value) return
  const job = pendingStart.consume(props.sessionId)
  if (!job) return
  pendingStarted.value = true
  if (job.files.length) {
    dropping.value = true
    for (const file of job.files) {
      try {
        const uploaded = await api.uploadFile(props.sessionId, file)
        if (!attachedFiles.value.find((item: any) => item.path === uploaded.path)) attachedFiles.value.push(uploaded)
      } catch (err: any) {
        toast.error('上传失败：' + (err.message || file.name))
      }
    }
    dropping.value = false
    emit('done')
  }
  const text = job.message.trim()
  if (!text && !attachedFiles.value.length) return
  inputMessage.value = ''
  await doSend(text)
}
onMounted(() => {
  void startPending()
  document.addEventListener('click', onComposerDocClick)
})
onUnmounted(() => document.removeEventListener('click', onComposerDocClick))
defineExpose({ startPending })
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
  <div class="h-full flex flex-col relative select-text">
    <div ref="chatContainer" data-chat-container @scroll="onScroll" class="flex-1 overflow-y-auto px-4 sm:px-6 py-4 space-y-4">
      <div v-if="!sessionStore.messages.length" class="flex items-start justify-center h-full pt-4">
        <SkillGuide v-if="props.skillName" :skill="props.skillName" :mode="props.modeName||'full'" />
        <div v-else class="text-center max-w-sm animate-fade-in"><div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-ruc-red-pale flex items-center justify-center"><Loader2 class="w-8 h-8 text-ruc-red/30" /></div><p class="text-ruc-text-dim text-lg font-display mb-2">开始您的学术研究</p><p class="text-ruc-text-light text-sm font-ui">在下方输入研究主题，AI 将协助您完成学术工作</p></div>
      </div>
      <div v-for="msg in sessionStore.messages" :key="msg.id" :data-msg-id="msg.id" class="flex animate-fade-in group/msg" :class="msg.role==='user'?'justify-end':'justify-start'">
        <div class="max-w-[80%] sm:max-w-[72%] flex flex-col" :class="msg.role==='user'?'items-end':'items-start'">
        <div class="w-full rounded-2xl px-4 py-3 relative group select-text" :class="msg.role==='user'?'bg-ruc-warm border border-ruc-divider':'bg-white border border-ruc-divider shadow-sm'">
          <div v-if="msg.role==='user'" class="text-ruc-text font-ui text-sm whitespace-pre-wrap leading-relaxed">
            <p v-if="authorLabel(msg)" class="text-[10px] text-ruc-red/80 mb-1">{{ authorLabel(msg) }}</p>
            {{ msg.content }}
          </div>
          <div v-else-if="msg._streaming && msg.content" class="text-ruc-text font-ui text-sm whitespace-pre-wrap leading-relaxed">
            <p v-if="authorLabel(msg)" class="text-[10px] text-ruc-text-dim mb-1">{{ authorLabel(msg) }}</p>
            {{ msg.content }}<span class="inline-block w-0.5 h-4 bg-ruc-red ml-0.5 animate-pulse align-middle" />
          </div>
          <div v-else-if="msg.content" class="markdown-body text-sm" :class="{'ring-2 ring-ruc-red/20 rounded-lg':selectedIds.has(msg.id)}">
            <p v-if="authorLabel(msg)" class="text-[10px] text-ruc-text-dim mb-1 not-prose">{{ authorLabel(msg) }}</p>
            <div v-html="renderMarkdown(msg.content!)" />
          </div>
          <div v-else class="py-2 w-full max-w-[320px]">
            <p class="text-sm font-ui text-ruc-text-dim mb-2">{{ isStreaming ? statusText : '这次没有收到正文。请再发一次。' }}</p>
            <div v-if="isStreaming" class="h-1.5 bg-ruc-bg rounded-full overflow-hidden">
              <div
                v-if="progressTokens > 0"
                class="h-full bg-ruc-red rounded-full transition-all duration-500"
                :style="{ width: Math.min(92, 18 + progressTokens / 30) + '%' }"
              />
              <div v-else class="h-full w-2/5 bg-ruc-red/80 rounded-full ars-indet" />
            </div>
          </div>
          <div v-if="msg.role === 'assistant' && speakers(msg).length" class="mt-2 text-[11px] font-ui text-ruc-text-dim leading-relaxed">
            <span v-for="(item, rosterIndex) in speakers(msg)" :key="'roster-' + item.model">{{ rosterIndex ? '；' : '' }}{{ item.name }}<template v-if="item.stance">：{{ item.stance }}</template></span>
          </div>
          <div v-if="msg.role === 'assistant' && debateVoices(msg).length" class="mt-2 space-y-2">
            <template v-for="(voice, voiceIndex) in debateVoices(msg)" :key="voice.model + '-' + voice.round + '-' + voice.kind + '-' + voiceIndex">
            <p v-if="showRoundMark(debateVoices(msg), voiceIndex)" class="text-[10px] font-ui text-ruc-text-dim">第 {{ voice.round }} 轮</p>
            <div class="rounded-xl border border-ruc-divider bg-ruc-bg px-3 py-2">
              <p class="text-[11px] font-ui text-ruc-red"><template v-if="voice.round && voice.kind !== 'summary' && voice.kind !== 'judge'">第{{ voice.round }}轮 · </template>{{ voice.name }}<span v-if="voice.stance"> · {{ voice.stance }}</span> · {{ voiceKind(voice) }}</p>
              <p v-if="voice.error" class="mt-1 text-xs font-ui text-ruc-text-dim whitespace-pre-wrap">{{ voice.error }}</p>
              <template v-else>
                <div class="mt-1 flex items-center gap-2">
                  <p class="text-[10px] font-ui text-ruc-text-light">思考</p>
                  <button v-if="(voice.thinking || '').length > 180" type="button" class="text-[10px] font-ui text-ruc-red" @click="togglePart(msg.id, voiceIndex, 'thinking', voice.thinking)">{{ partOpen(msg.id, voiceIndex, 'thinking', voice.thinking) ? '收起' : '展开' }}</button>
                </div>
                <p v-if="partOpen(msg.id, voiceIndex, 'thinking', voice.thinking)" class="text-xs font-ui text-ruc-text whitespace-pre-wrap leading-relaxed">{{ voice.thinking || '这一侧没有单独的思考。' }}</p>
                <div class="mt-1 flex items-center gap-2">
                  <p class="text-[10px] font-ui text-ruc-text-light">结果</p>
                  <button v-if="(voice.answer || '').length > 180" type="button" class="text-[10px] font-ui text-ruc-red" @click="togglePart(msg.id, voiceIndex, 'answer', voice.answer)">{{ partOpen(msg.id, voiceIndex, 'answer', voice.answer) ? '收起' : '展开' }}</button>
                </div>
                <p v-if="partOpen(msg.id, voiceIndex, 'answer', voice.answer)" class="text-xs font-ui text-ruc-text whitespace-pre-wrap leading-relaxed">{{ voice.answer }}</p>
              </template>
            </div>
            </template>
          </div>
          <div v-if="msg.role === 'assistant' && debatePlanOf(msg)" class="mt-2 rounded-xl border border-ruc-divider bg-ruc-warm px-3 py-2">
            <p class="text-[11px] font-ui text-ruc-text">辩题：{{ debatePlanOf(msg)?.topic }}</p>
            <p v-for="(stance, id) in (debatePlanOf(msg)?.stances || {})" :key="'plan-' + id" class="mt-1 text-[11px] font-ui text-ruc-text-dim">{{ seatOf(String(id))?.name || id }}：{{ stance }}</p>
            <button type="button" class="mt-1 text-[11px] font-ui text-ruc-red" @click="applyPlan(debatePlanOf(msg)!)">填进输入框</button>
          </div>
          <div v-if="props.skillName === 'idea-debate' && props.modeName === 'contrast' && !msg._streaming && !isStreaming && isLatestDebate(msg)" class="mt-2 space-y-2">
            <div>
              <p class="text-[10px] font-ui text-ruc-text-dim mb-1">标选要整理的轮次</p>
              <div class="flex flex-wrap items-center gap-1">
                <label v-for="round in debateRounds(msg)" :key="'round-' + round" class="inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[11px] font-ui" :class="pickedRounds.includes(round) ? 'border-ruc-red bg-ruc-red-pale text-ruc-red' : 'border-ruc-divider text-ruc-text-dim'">
                  <input type="checkbox" class="accent-ruc-red" :checked="pickedRounds.includes(round)" @change="toggleRound(round)" />
                  第{{ round }}轮
                </label>
                <select v-model="summaryModel" class="max-w-[140px] rounded-md border border-ruc-divider bg-white px-1.5 py-1 text-[11px] font-ui text-ruc-text">
                  <option value="">选模型来整理</option>
                  <option v-for="item in seatChoices" :key="'sum-' + item.id" :value="item.id">{{ item.name }}</option>
                </select>
                <button type="button" class="px-2 py-1 rounded-md border border-ruc-divider text-[11px] font-ui text-ruc-text hover:border-ruc-red/40" @click="summarizeDebate('rounds')">整理所选轮次</button>
              </div>
            </div>
            <div>
              <p class="text-[10px] font-ui text-ruc-text-dim mb-1">分开整理一位的观点</p>
              <div class="flex flex-wrap items-center gap-1">
                <select v-model="pairA" class="max-w-[120px] rounded-md border border-ruc-divider bg-white px-1.5 py-1 text-[11px] font-ui text-ruc-text">
                  <option value="">第一位</option>
                  <option v-for="item in speakers(msg)" :key="'a-' + item.model" :value="item.model">{{ item.name }}</option>
                </select>
                <button type="button" class="px-2 py-1 rounded-md border border-ruc-divider text-[11px] font-ui text-ruc-text hover:border-ruc-red/40" @click="summarizeDebate('speaker', pairA, speakerName(msg, pairA))">{{ speakerName(msg, pairA) ? `整理${speakerName(msg, pairA)}的观点` : '整理第一位的观点' }}</button>
              </div>
              <div class="mt-1 flex flex-wrap items-center gap-1">
                <select v-model="pairB" class="max-w-[120px] rounded-md border border-ruc-divider bg-white px-1.5 py-1 text-[11px] font-ui text-ruc-text">
                  <option value="">第二位</option>
                  <option v-for="item in speakers(msg)" :key="'b-' + item.model" :value="item.model">{{ item.name }}</option>
                </select>
                <button type="button" class="px-2 py-1 rounded-md border border-ruc-divider text-[11px] font-ui text-ruc-text hover:border-ruc-red/40" @click="summarizeDebate('speaker', pairB, speakerName(msg, pairB))">{{ speakerName(msg, pairB) ? `整理${speakerName(msg, pairB)}的观点` : '整理第二位的观点' }}</button>
              </div>
            </div>
            <div>
              <p class="text-[10px] font-ui text-ruc-text-dim mb-1">法官</p>
              <div class="flex flex-wrap items-center gap-1">
                <select v-model="judgeModel" class="max-w-[140px] rounded-md border border-ruc-divider bg-white px-1.5 py-1 text-[11px] font-ui text-ruc-text">
                  <option value="">选法官模型</option>
                  <option v-for="item in seatChoices" :key="'judge-' + item.id" :value="item.id">{{ item.name }}</option>
                </select>
                <button type="button" class="px-2 py-1 rounded-md bg-ruc-red text-white text-[11px] font-ui" @click="summarizeDebate('judge')">请法官判断</button>
              </div>
            </div>
          </div>
        </div>
        <div v-if="props.skillName === 'academic-pipeline' && !msg._streaming && !isStreaming && isLatestAssistant(msg) && pipelineState(msg)?.awaiting" class="mt-2 px-1">
          <p v-if="(pipelineState(msg).index ?? 0) < 0" class="text-[11px] font-ui text-ruc-text-dim mb-1.5">步骤已列好，点开始才写第一步。</p>
          <p v-else class="text-[11px] font-ui text-ruc-text-dim mb-1.5">第 {{ (pipelineState(msg).index || 0) + 1 }}/{{ pipelineState(msg).total }} 步已完成：{{ pipelineState(msg).group }} · {{ pipelineState(msg).label }}</p>
          <button class="px-3 py-1.5 rounded-lg bg-ruc-red text-white text-xs font-ui hover:bg-ruc-red-light" @click="continuePipeline((pipelineState(msg).index ?? 0) < 0)">{{ (pipelineState(msg).index ?? 0) < 0 ? '开始' : '确认，继续' }}：{{ pipelineState(msg).next_label }}</button>
        </div>
        <p v-else-if="props.skillName === 'academic-pipeline' && !msg._streaming && isLatestAssistant(msg) && pipelineState(msg)?.done" class="mt-2 px-1 text-[11px] font-ui text-ruc-text-dim">全流程已做完，各步文件都在这个文件夹里。</p>
        <div v-if="fileEdits(msg) && !msg._streaming" class="mt-1 px-1 text-[11px] font-ui text-ruc-text-dim inline-flex items-center gap-2 max-w-full">
          <span class="truncate">{{ editSummary(msg) }}</span>
          <button
            class="flex-shrink-0 px-2 py-0.5 rounded-md text-ruc-red hover:bg-ruc-red-pale disabled:text-ruc-text-light"
            :disabled="msg.editsUndone || undoingId === msg.id"
            @click="undoEdits(msg)"
          >{{ msg.editsUndone ? '已撤销' : '撤销这次修改' }}</button>
        </div>
        <div
          v-if="msg.role==='assistant' && msg.content && !msg._streaming"
          class="flex items-center gap-1 mt-1 px-1 opacity-0 group-hover/msg:opacity-100 focus-within:opacity-100 transition-opacity"
          :class="docMenuId === msg.id ? '!opacity-100' : ''"
        >
          <button class="p-1 rounded-md text-ruc-text-light hover:text-ruc-red hover:bg-ruc-warm" title="复制" @click="copyContent(msg.content!, msg.id)">
            <Check v-if="copiedId===msg.id" class="w-3.5 h-3.5 text-ruc-success" />
            <Copy v-else class="w-3.5 h-3.5" />
          </button>
          <button
            v-if="writable"
            class="px-2 py-1 rounded-md text-[11px] font-ui text-ruc-text-dim hover:text-ruc-red hover:bg-ruc-warm inline-flex items-center gap-1"
            :disabled="writingId === msg.id"
            title="把这条回复接到当前文稿末尾"
            @click="writeInto(msg)"
          >
            <Loader2 v-if="writingId===msg.id" class="w-3 h-3 animate-spin" />
            <FileText v-else class="w-3 h-3" />
            写入文稿
          </button>
          <button class="px-2 py-1 rounded-md text-[11px] font-ui text-ruc-text-dim hover:text-ruc-red hover:bg-ruc-warm inline-flex items-center gap-1" @click="docMenuId = docMenuId === msg.id ? null : msg.id; if (docMenuId) workspaceStore.loadFiles(sessionId)">
            <Loader2 v-if="generatingId===msg.id" class="w-3 h-3 animate-spin" />
            <FilePlus v-else class="w-3 h-3" />
            生成文档
          </button>
        </div>
        <div v-if="docMenuId===msg.id" class="flex flex-col gap-1 mt-1 px-1 max-w-full">
          <div class="flex items-center gap-1 flex-wrap">
            <button class="px-2 py-1 rounded-md border border-ruc-divider text-[11px] font-ui text-ruc-text hover:border-ruc-red/40" :disabled="generatingId===msg.id" @click="generateFromMessage(msg.id, 'markdown')">Markdown</button>
            <button class="px-2 py-1 rounded-md border border-ruc-divider text-[11px] font-ui text-ruc-text hover:border-ruc-red/40" :disabled="generatingId===msg.id" @click="generateFromMessage(msg.id, 'docx')">{{ templatePath ? '按模板生成 Word' : 'Word' }}</button>
            <button class="px-2 py-1 rounded-md text-[11px] font-ui" :class="selectedIds.has(msg.id)?'bg-ruc-red text-white':'text-ruc-text-dim hover:text-ruc-red hover:bg-ruc-warm'" @click="toggleSelect(msg.id)">{{ selectedIds.has(msg.id) ? '已加入合并' : '加入合并' }}</button>
          </div>
          <div v-if="selectedIds.size > 1" class="flex items-center gap-1 flex-wrap">
            <button class="px-2 py-1 rounded-md border border-ruc-divider text-[11px] font-ui text-ruc-text hover:border-ruc-red/40" :disabled="generatingId===msg.id" @click="generateFromMessage(msg.id, 'markdown', true)">合并 {{ selectedIds.size }} 条为 Markdown</button>
            <button class="px-2 py-1 rounded-md border border-ruc-divider text-[11px] font-ui text-ruc-text hover:border-ruc-red/40" :disabled="generatingId===msg.id" @click="generateFromMessage(msg.id, 'docx', true)">合并为 Word</button>
            <button class="px-2 py-1 text-[11px] font-ui text-ruc-text-light hover:text-ruc-text" @click="clearSelection">取消合并</button>
          </div>
          <label class="flex items-center gap-1 text-[11px] font-ui text-ruc-text-dim">
            <span class="flex-shrink-0">对照模板</span>
            <select v-model="templatePath" class="max-w-[220px] rounded-md border border-ruc-divider bg-white px-1.5 py-1 text-[11px] text-ruc-text">
              <option value="">不套模板（默认样式）</option>
              <option v-for="f in docxTemplates" :key="f.path" :value="f.path">{{ f.name }}</option>
            </select>
          </label>
          <p class="text-[10px] text-ruc-text-light leading-relaxed">先把学校 Word 模板上传到左侧文件栏。会沿用它的标题样式、页边距和页眉页脚，正文示例会被换成这篇回复。封面、目录、题注还做不到。</p>
        </div>
        </div>
      </div>
    </div>
    <div
      class="flex-shrink-0 border-t border-ruc-divider bg-white/80 backdrop-blur-md px-4 sm:px-6 py-3 relative z-20"
      :class="dropActive ? 'ring-2 ring-inset ring-ruc-red/50 bg-ruc-red-pale/40' : ''"
      @dragenter="onComposerDragEnter"
      @dragover="onComposerDragOver"
      @dragleave="onComposerDragLeave"
      @drop="onComposerDrop"
    >
      <button v-if="showScrollBtn" type="button" @click="scrollToBottom(true)" class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-10 px-3 py-1.5 rounded-full bg-white border border-ruc-divider shadow-elevated text-xs font-ui text-ruc-text-dim hover:text-ruc-red hover:border-ruc-red/30 transition-all animate-fade-in">↓ 回到底部</button>
      <div v-if="dropActive" class="pointer-events-none absolute inset-2 rounded-2xl border-2 border-dashed border-ruc-red/50 flex items-center justify-center text-xs font-ui text-ruc-red bg-white/70">松开即可加入对话</div>
      <div v-if="writable && openFile" class="flex items-center gap-1.5 mb-2 text-[11px] font-ui text-ruc-text-dim">
        <FileText class="w-3 h-3 flex-shrink-0 text-ruc-red/60" />
        <span class="truncate">将写入：{{ openFile.name }}</span>
        <button class="ml-auto p-0.5 rounded hover:bg-ruc-warm hover:text-ruc-text" title="这次不写入这篇" @click="skipWrite = true">
          <X class="w-3 h-3" />
        </button>
      </div>
      <div v-if="isStreaming" class="flex items-center gap-2 mb-2 text-xs font-ui"><Loader2 class="w-3 h-3 animate-spin text-ruc-red/60" /><span class="text-ruc-text-dim">{{ statusText }}</span><span v-if="progressTokens>0" class="text-ruc-text-light ml-auto">{{ progressTokens }} tokens</span></div>
      <div v-else-if="dropping" class="flex items-center gap-2 mb-2 text-xs font-ui text-ruc-text-dim"><Loader2 class="w-3 h-3 animate-spin text-ruc-red/60" />正在加入文件…</div>
      <div ref="composerBar" class="relative rounded-2xl border bg-white transition-all duration-150" :class="isCharLimitExceeded ? 'border-ruc-error/50 ring-2 ring-ruc-error/20' : 'border-ruc-border focus-within:border-ruc-red/40 focus-within:ring-2 focus-within:ring-ruc-red/15'">
        <p v-if="props.skillName === 'idea-debate' && props.modeName === 'socratic'" class="px-4 pt-2 text-[11px] font-ui text-ruc-text-dim leading-relaxed">写下主题和你的看法。它会用一问一答引导你思考，一次只问一个问题。你回答之后，再接着问下一句。</p>
        <p v-else-if="props.skillName === 'literature-find'" class="px-4 pt-2 text-[11px] font-ui text-ruc-text-dim leading-relaxed">输入检索词。结果来自 OpenAlex，列出题名、作者、年份、来源和 DOI。缺的留空。关键词检索受限时，先用 Crossref 定位 DOI，再向 OpenAlex 读取。知网还没接通，不会编造文献。</p>
        <p v-else-if="props.skillName === 'academic-paper' && props.modeName === 'lit-search'" class="px-4 pt-2 text-[11px] font-ui text-ruc-text-dim leading-relaxed">这里仍是知网接口，还没接通，只会记下检索词。开放检索在「文献查找」里。</p>
        <textarea ref="textareaRef" v-model="inputMessage" @keydown="handleKeydown" @input="onTextareaInput" :disabled="dropping" :placeholder="composerPlaceholder" rows="1" class="w-full resize-none font-ui text-sm bg-transparent border-0 px-4 pt-3 pb-1 placeholder:text-ruc-text-light focus:outline-none disabled:text-ruc-text-light" style="min-height:44px;max-height:160px" />
        <FileMentionPopup v-if="showMention" ref="mentionPopupRef" :session-id="sessionId" :query="mentionQuery" @select="onFileSelect" @close="showMention=false" />
        <div class="flex items-center gap-1 px-2 pb-2">
          <div class="relative min-w-0">
            <button type="button" class="inline-flex items-center gap-1 max-w-[9rem] px-2 py-1 rounded-lg text-xs font-ui text-ruc-text hover:bg-ruc-warm" title="选择对话入口" @click.stop="modeMenu = !modeMenu; modelMenu = false; debateSetup = false; if (!modeMenu) activeGroup = ''">
              <span class="truncate">{{ entryLabel }}</span>
              <ChevronDown class="w-3.5 h-3.5 flex-shrink-0 text-ruc-text-light" />
            </button>
            <div v-if="modeMenu" class="absolute left-0 bottom-full mb-2 z-40 w-64 max-h-72 overflow-y-auto bg-white border border-ruc-divider rounded-xl shadow-modal py-1" @click.stop>
              <template v-if="!openedGroup">
                <button v-for="item in DIRECT_ENTRIES" :key="item.skill" class="w-full px-3 py-2 text-left hover:bg-ruc-warm" :class="skillName === item.skill && modeName === item.mode ? 'bg-ruc-red-pale' : ''" @click="pickEntry(item.skill, item.mode)">
                  <span class="block text-xs font-ui" :class="skillName === item.skill ? 'text-ruc-red' : 'text-ruc-text'">{{ item.label }}</span>
                  <span class="block text-[10px] font-ui text-ruc-text-light mt-0.5">{{ item.hint }}</span>
                </button>
                <p class="px-3 pt-2 pb-1 text-[10px] font-ui text-ruc-text-light">功能</p>
                <button v-for="group in FUNCTION_GROUPS" :key="group.skill" class="w-full px-3 py-2 text-left hover:bg-ruc-warm flex items-center gap-2" @click="group.planned ? showPlanned(group.label) : (activeGroup = group.skill)">
                  <span class="min-w-0 flex-1">
                    <span class="flex items-center gap-1.5 text-xs font-ui text-ruc-text">
                      {{ group.label }}
                      <span v-if="group.trial" class="text-[10px] px-1 py-0.5 rounded bg-ruc-warm text-ruc-gold border border-ruc-gold/30">试验</span>
                      <span v-if="group.planned" class="text-[10px] px-1 py-0.5 rounded bg-ruc-warm text-ruc-text-dim border border-ruc-divider">待开发</span>
                    </span>
                  </span>
                  <ChevronRight v-if="!group.planned" class="w-3.5 h-3.5 text-ruc-text-light flex-shrink-0" />
                </button>
              </template>
              <template v-else>
                <button class="w-full px-3 py-2 text-left text-xs font-ui text-ruc-text-dim hover:bg-ruc-warm inline-flex items-center gap-1" @click="activeGroup = ''">
                  <ChevronLeft class="w-3.5 h-3.5" /> {{ openedGroup.label }}
                </button>
                <button v-for="item in openedGroup.modes" :key="item.mode" class="w-full px-3 py-2 text-left hover:bg-ruc-warm" :class="skillName === openedGroup.skill && modeName === item.mode ? 'bg-ruc-red-pale' : ''" @click="pickEntry(openedGroup.skill, item.mode)">
                  <span class="block text-xs font-ui" :class="skillName === openedGroup.skill && modeName === item.mode ? 'text-ruc-red' : 'text-ruc-text'">{{ item.label }}</span>
                  <span class="block text-[10px] font-ui text-ruc-text-light mt-0.5">{{ item.hint }}</span>
                </button>
              </template>
            </div>
          </div>
          <div v-if="props.skillName === 'idea-debate' && props.modeName === 'contrast'" class="relative min-w-0">
            <button type="button" class="inline-flex items-center gap-1 max-w-[9rem] px-2 py-1 rounded-lg text-xs font-ui text-ruc-text hover:bg-ruc-warm" title="辩论设置" @click.stop="debateSetup = !debateSetup; modeMenu = false; modelMenu = false">
              <span class="truncate">{{ debateSetupLabel }}</span>
              <ChevronDown class="w-3.5 h-3.5 flex-shrink-0 text-ruc-text-light" />
            </button>
            <div v-if="debateSetup" class="absolute left-0 bottom-full mb-2 z-40 w-72 max-h-80 overflow-y-auto bg-white border border-ruc-divider rounded-xl shadow-modal p-3" @click.stop>
              <p v-if="props.modeName === 'socratic'" class="text-[11px] font-ui text-ruc-text-dim mb-2">选一个模型。它会用提问把想法问紧。</p>
              <p v-else-if="props.modeName === 'contrast'" class="text-[11px] font-ui text-ruc-text-dim mb-2">先点选要辩论的模型，再在名字旁边给每位分配辩题。</p>
              <p v-else class="text-[11px] font-ui text-ruc-text-dim mb-2">选一个或多个模型。问法写在输入框里。</p>
              <div class="flex flex-wrap gap-1">
                <button
                  v-for="item in builtinChoices"
                  :key="item.id"
                  type="button"
                  class="px-2 py-1 rounded-full border text-[11px] font-ui"
                  :class="debateIds.includes(item.id) ? 'border-ruc-red bg-ruc-red-pale text-ruc-red' : 'border-ruc-divider text-ruc-text-dim'"
                  @click="toggleDebate(item.id)"
                >{{ item.name }}</button>
              </div>
              <div v-if="props.modeName === 'contrast'" class="mt-2 space-y-1">
                <p v-if="!selectedBuiltin.length" class="text-[10px] font-ui text-ruc-text-light">点上面的模型，辩题就写在这里。</p>
                <label v-for="id in selectedBuiltin" :key="'stance-' + id" class="flex items-center gap-1">
                  <span class="w-24 truncate text-[10px] font-ui text-ruc-text-dim">{{ seatOf(id)?.name || id }}</span>
                  <input v-model="debateStances[id]" type="text" placeholder="这位的辩题" class="flex-1 min-w-0 rounded-md border border-ruc-divider px-2 py-1 text-[11px] font-ui text-ruc-text" />
                </label>
              </div>
              <div class="mt-2 border-y border-ruc-divider py-2">
                <p class="mb-1 text-[10px] font-ui text-ruc-text-dim">加上新的辩论成员</p>
                <div class="flex flex-wrap items-center gap-1">
                  <input v-model="extraName" type="text" placeholder="模型名，如 glm-5" class="w-36 rounded-md border border-ruc-divider px-2 py-1 text-[11px] font-ui text-ruc-text" />
                  <select v-model="extraProvider" class="max-w-[120px] rounded-md border border-ruc-divider bg-white px-1.5 py-1 text-[11px] font-ui text-ruc-text">
                    <option v-for="item in keyedProviders" :key="item.id" :value="item.id">{{ item.display_name }}</option>
                  </select>
                </div>
                <input v-if="props.modeName === 'contrast'" v-model="extraStance" type="text" placeholder="这位的辩题" class="mt-1 w-full rounded-md border border-ruc-divider px-2 py-1 text-[11px] font-ui text-ruc-text" />
                <button type="button" class="mt-1 px-2 py-1 rounded-md border border-ruc-divider text-[11px] font-ui text-ruc-text hover:border-ruc-red/40" @click="addExtraModel">加上</button>
                <div v-for="item in extraModels" :key="'extra-' + item.id" class="mt-1.5">
                  <div class="flex items-center gap-1">
                    <button type="button" class="min-w-0 truncate px-2 py-1 rounded-full border text-[11px] font-ui" :class="debateIds.includes(item.id) ? 'border-ruc-red bg-ruc-red-pale text-ruc-red' : 'border-ruc-divider text-ruc-text-dim'" @click="toggleDebate(item.id)">{{ item.name }}</button>
                    <button type="button" class="ml-auto inline-flex items-center gap-0.5 px-1.5 py-1 text-[10px] font-ui text-ruc-text-dim hover:text-ruc-red" @click="removeExtraModel(item.id)">
                      <X class="w-3 h-3" /> 删除
                    </button>
                  </div>
                  <input v-if="props.modeName === 'contrast'" v-model="debateStances[item.id]" type="text" placeholder="这位的辩题" class="mt-1 w-full rounded-md border border-ruc-divider px-2 py-1 text-[11px] font-ui text-ruc-text" />
                </div>
              </div>
              <div v-if="props.modeName === 'contrast'" class="mt-2">
                <p class="text-[10px] font-ui text-ruc-text-light mb-1">辩题可以自己写在输入框里直接发。要自动生成，先点选上面要辩论的模型，把看法写在下面。生成后可以自己给每位分配不同辩题。</p>
                <textarea v-model="topicSeed" rows="2" placeholder="你的看法" class="mb-1 w-full resize-none rounded-md border border-ruc-divider px-2 py-1 text-[11px] font-ui text-ruc-text"></textarea>
                <div class="flex flex-wrap items-center gap-1">
                  <select v-model="topicModel" class="max-w-[140px] rounded-md border border-ruc-divider bg-white px-1.5 py-1 text-[11px] font-ui text-ruc-text">
                    <option value="">用第一位拟辩题</option>
                    <option v-for="item in seatChoices" :key="'topic-' + item.id" :value="item.id">{{ item.name }}</option>
                  </select>
                  <button type="button" class="px-2 py-1 rounded-md bg-ruc-red text-white text-[11px] font-ui" @click="draftTopic">生成辩题</button>
                </div>
              </div>
            </div>
          </div>
          <div v-if="settingsStore.isConfigured" class="relative min-w-0">
            <button type="button" class="inline-flex items-center gap-1 max-w-[9rem] px-2 py-1 rounded-lg text-xs font-ui text-ruc-text-dim hover:bg-ruc-warm hover:text-ruc-text" title="选择模型" @click.stop="modelMenu = !modelMenu; modeMenu = false; debateSetup = false; activeGroup = ''">
              <span class="truncate">{{ currentModelName }}</span>
              <ChevronDown class="w-3.5 h-3.5 flex-shrink-0" />
            </button>
            <div v-if="modelMenu" class="absolute left-0 bottom-full mb-2 z-40 w-56 max-h-64 overflow-y-auto bg-white border border-ruc-divider rounded-xl shadow-modal py-1" @click.stop>
              <button v-for="item in configuredModels" :key="item.id" class="w-full px-3 py-2 text-left text-xs font-ui hover:bg-ruc-warm" :class="settingsStore.selectedModel === item.id ? 'bg-ruc-red-pale text-ruc-red' : 'text-ruc-text'" @click="pickModel(item.id)">
                {{ item.name }}
              </button>
            </div>
          </div>
          <div class="ml-auto flex items-center gap-1 flex-shrink-0">
            <button v-if="debateHold && isStreaming" type="button" class="px-2 py-1 rounded-md bg-ruc-red text-white text-[11px] font-ui" @click="releaseTurn">{{ inputMessage.trim() ? '按这个意见开始下一轮' : '开始下一轮' }}</button>
            <button v-else-if="steering && isStreaming" type="button" class="px-2 py-1 rounded-md border border-ruc-divider text-[11px] font-ui text-ruc-text disabled:text-ruc-text-light" :disabled="!inputMessage.trim()" @click="releaseTurn">插入提示</button>
            <button v-if="!isStreaming" @click="handleSend" :disabled="!inputMessage.trim() && !attachedFiles.length" class="w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200" :class="(inputMessage.trim()||attachedFiles.length)?'bg-ruc-red text-white hover:bg-ruc-red-light':'bg-ruc-bg text-ruc-text-light cursor-not-allowed'"><ArrowUp class="w-4 h-4" /></button>
            <button v-else @click="handleStop" class="w-8 h-8 rounded-lg bg-ruc-error-soft border border-ruc-error/20 flex items-center justify-center hover:bg-ruc-error/10" title="停止生成"><Square class="w-3.5 h-3.5 text-ruc-error" /></button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
