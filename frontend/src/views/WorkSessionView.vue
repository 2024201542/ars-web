<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useRoute, useRouter } from 'vue-router'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import { useNewChat } from '@/composables/useNewChat'
import { api } from '@/api'
import { SKILL_LABELS } from '@/utils/constants'
import { entryTitle } from '@/utils/composerModes'
import type { Message } from '@/types'
import FileTree from '@/components/FileTree.vue'
import FilePreview from '@/components/FilePreview.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import CollabButton from '@/components/CollabButton.vue'
import CollabInboxButton from '@/components/CollabInboxButton.vue'
import ShareButton from '@/components/ShareButton.vue'
import ExportButton from '@/components/ExportButton.vue'
import {
  PanelRightClose, PanelRight, Plus, History, Settings, Shield, LogOut, MoreHorizontal, X,
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const sessionStore = useSessionStore()
const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const auth = useAuthStore()
const { creating, goNew } = useNewChat()

const sessionId = computed(() => route.params.id as string)
const skillName = computed(() => (route.meta.skill as string) || '')
const skillTitle = computed(() => SKILL_LABELS[skillName.value] || skillName.value || '工作区')
const modeTitle = computed(() => entryTitle(sessionStore.currentSession?.skill_name, sessionStore.currentSession?.mode_name) || skillTitle.value)
const currentModel = computed(() => {
  const m = settingsStore.models.find(x => x.id === settingsStore.selectedModel)
  return m?.name || '未选择模型'
})
const displayName = computed(() => auth.user?.display_name || auth.user?.username || '')

const fileTreeOpen = ref(window.innerWidth > 768)
const fileTreeWidth = ref(240)
const agentOpen = ref(true)
const agentWidth = ref(420)
const historyOpen = ref(false)
const moreOpen = ref(false)
const moreRoot = ref<HTMLElement | null>(null)
const accountOpen = ref(false)
const chatReady = ref(false)
const chatRef = ref<{ startPending: () => Promise<void> } | null>(null)
const historyRef = ref<{ focusSearch: () => void } | null>(null)
const accountRoot = ref<HTMLElement | null>(null)
let loadToken = 0
const openFiles = ref<any[]>([])
const selectedFile = ref<any>(null)
const selectedPath = ref<string | null>(null)
const dirtyPaths = ref<Record<string, boolean>>({})
const previewMap = new Map<string, { confirmLeave: () => Promise<boolean>; isDirty: () => boolean; reload: () => Promise<void> }>()
const draggingSidebar = ref(false)
const draggingAgent = ref(false)

function onSidebarMD(e: MouseEvent) { if (!fileTreeOpen.value) return; draggingSidebar.value = true; e.preventDefault() }
function onAgentMD(e: MouseEvent) { if (!agentOpen.value) return; draggingAgent.value = true; e.preventDefault() }
function onMouseMove(e: MouseEvent) {
  if (draggingSidebar.value) {
    fileTreeWidth.value = Math.max(180, Math.min(420, e.clientX))
  }
  if (draggingAgent.value) {
    agentWidth.value = Math.max(320, Math.min(680, window.innerWidth - e.clientX))
  }
}
function onMouseUp() { draggingSidebar.value = false; draggingAgent.value = false }
function saveLayout() {
  localStorage.setItem('ars-layout-sw', String(fileTreeWidth.value))
  localStorage.setItem('ars-layout-aw', String(agentWidth.value))
}
function restoreLayout() {
  fileTreeWidth.value = Number(localStorage.getItem('ars-layout-sw')) || 240
  agentWidth.value = Number(localStorage.getItem('ars-layout-aw')) || 420
}

function setPreviewRef(path: string, el: any) {
  if (el) previewMap.set(path, el)
  else previewMap.delete(path)
}

function onPreviewDirty(path: string, value: boolean) {
  if (Boolean(dirtyPaths.value[path]) === value) return
  dirtyPaths.value = { ...dirtyPaths.value, [path]: value }
}

function activateTab(file: any) {
  selectedFile.value = file
  selectedPath.value = file?.path || null
}

async function confirmPreviewLeave() {
  for (const file of [...openFiles.value]) {
    const preview = previewMap.get(file.path)
    if (!preview?.isDirty?.()) continue
    activateTab(file)
    await nextTick()
    if (!(await preview.confirmLeave())) return false
  }
  return true
}

function openPreview(file: any) {
  if (!file?.path) return
  const hit = openFiles.value.find((item) => item.path === file.path)
  if (hit) {
    if (hit.name !== file.name) hit.name = file.name
    activateTab(hit)
    return
  }
  const current = selectedFile.value
  const currentGone = current && !workspaceStore.files.some((row) => row.path === current.path)
  if (currentGone) {
    const index = openFiles.value.findIndex((item) => item.path === current.path)
    if (index >= 0) openFiles.value.splice(index, 1, file)
    else openFiles.value = [...openFiles.value, file]
  } else {
    openFiles.value = [...openFiles.value, file]
  }
  activateTab(file)
}

function closeRemoved(path: string) {
  const prefix = `${path}/`
  openFiles.value = openFiles.value.filter((item) => item.path !== path && !item.path.startsWith(prefix))
  const nextDirty = { ...dirtyPaths.value }
  delete nextDirty[path]
  for (const key of Object.keys(nextDirty)) {
    if (key.startsWith(prefix)) delete nextDirty[key]
  }
  dirtyPaths.value = nextDirty
  if (selectedPath.value === path || (selectedPath.value || '').startsWith(prefix)) {
    activateTab(openFiles.value[openFiles.value.length - 1] || null)
  }
}

async function closeTab(file: any) {
  if (selectedPath.value !== file.path) {
    activateTab(file)
    await nextTick()
  }
  const preview = previewMap.get(file.path)
  if (preview && !(await preview.confirmLeave())) return
  const index = openFiles.value.findIndex((item) => item.path === file.path)
  openFiles.value = openFiles.value.filter((item) => item.path !== file.path)
  const nextDirty = { ...dirtyPaths.value }
  delete nextDirty[file.path]
  dirtyPaths.value = nextDirty
  const neighbor = openFiles.value[Math.min(index, openFiles.value.length - 1)] || null
  activateTab(neighbor)
}

async function onChatDone() {
  await workspaceStore.refresh(sessionId.value)
  const current = selectedFile.value
  if (!current) return
  const preview = previewMap.get(current.path)
  if (preview?.isDirty?.()) return
  await preview?.reload?.()
}

async function onGeneratedFile(file: any) {
  await workspaceStore.loadFiles(sessionId.value)
  selectedPath.value = file?.path || null
  fileTreeOpen.value = true
  if (file) openPreview(file)
}

async function loadSession() {
  const token = ++loadToken
  chatReady.value = false
  try {
    const detail = await api.getSession(sessionId.value)
    if (token !== loadToken) return
    sessionStore.setSession(detail.session)
    detail.messages.forEach((m: Message) => sessionStore.addMessage(m))
    await workspaceStore.loadFiles(sessionId.value)
    if (token !== loadToken) return
    chatReady.value = true
    await nextTick()
    if (token !== loadToken) return
    await chatRef.value?.startPending()
  } catch {
    toast.error('加载会话失败')
  }
}

async function onNew() {
  historyOpen.value = false
  await goNew(sessionId.value)
}

async function toggleHistory() {
  historyOpen.value = !historyOpen.value
  if (!historyOpen.value) return
  await nextTick()
  historyRef.value?.focusSearch()
}

const editableOpen = computed(() => {
  const file = selectedFile.value
  if (!file) return null
  const ext = (file.ext || '').toLowerCase()
  if (!['.md', '.txt', '.bib', '.tex', '.docx'].includes(ext)) return null
  return { name: file.name as string, path: file.path as string, ext }
})

async function onWrote() {
  await workspaceStore.refresh(sessionId.value)
  const current = selectedFile.value
  if (!current) return
  const preview = previewMap.get(current.path)
  if (preview?.isDirty?.()) {
    toast.info('这篇正在编辑，写入已存到文件，当前编辑区没有被覆盖')
    return
  }
  await preview?.reload?.()
}

function onDocClick(event: MouseEvent) {
  const target = event.target as Node
  if (accountRoot.value && !accountRoot.value.contains(target)) accountOpen.value = false
  if (moreRoot.value && !moreRoot.value.contains(target)) moreOpen.value = false
}

function goSettings() {
  accountOpen.value = false
  router.push('/settings')
}
function goAdmin() {
  accountOpen.value = false
  router.push('/admin')
}
function logout() {
  accountOpen.value = false
  auth.logout()
  router.push('/login')
}

onBeforeRouteLeave(async () => {
  if (!(await confirmPreviewLeave())) return false
})

onMounted(async () => {
  restoreLayout()
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
  document.addEventListener('click', onDocClick)
  await loadSession()
})
onUnmounted(() => {
  saveLayout()
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
  document.removeEventListener('click', onDocClick)
  sessionStore.clearSession()
})

watch(() => route.params.id, async (newId, oldId) => {
  historyOpen.value = false
  if (newId && newId !== oldId) await loadSession()
})

watch(() => workspaceStore.source + '|' + workspaceStore.rootPath, () => {
  openFiles.value = []
  dirtyPaths.value = {}
  activateTab(null)
})
</script>

<template>
  <div class="h-screen flex select-none bg-ruc-bg"
    :class="{ 'cursor-col-resize': draggingSidebar || draggingAgent }">
    <div
      class="flex-shrink-0 bg-white border-r border-ruc-divider overflow-hidden flex flex-col"
      :style="{ width: fileTreeOpen ? fileTreeWidth + 'px' : '40px' }">
      <FileTree
        class="flex-1 min-h-0"
        :session-id="sessionId"
        :before-leave="confirmPreviewLeave"
        :collapsed="!fileTreeOpen"
        v-model:selected-path="selectedPath"
        @select="openPreview"
        @removed="closeRemoved"
        @toggle="fileTreeOpen = true"
        @collapse="fileTreeOpen = false"
      />
      <div v-if="fileTreeOpen" ref="accountRoot" class="border-t border-ruc-divider p-2 relative flex-shrink-0">
        <button
          class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-ruc-warm text-left"
          @click="goSettings"
        >
          <span class="dot-green flex-shrink-0" />
          <span class="text-[11px] font-ui text-ruc-text-dim truncate">{{ currentModel }}</span>
        </button>
        <button
          class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-ruc-red-pale text-left"
          @click.stop="accountOpen = !accountOpen"
        >
          <span class="w-5 h-5 rounded-full bg-ruc-red text-white text-[10px] font-ui flex items-center justify-center flex-shrink-0">
            {{ displayName.slice(0, 1) || '?' }}
          </span>
          <span class="text-xs font-ui text-ruc-text truncate">{{ displayName }}</span>
        </button>
        <div
          v-if="accountOpen"
          class="absolute bottom-full left-2 right-2 mb-1 bg-white border border-ruc-divider rounded-xl shadow-modal py-1 z-50"
        >
          <button class="menu-row" @click="goSettings"><Settings class="w-3.5 h-3.5" /> 设置</button>
          <button v-if="auth.user?.role === 'admin'" class="menu-row" @click="goAdmin">
            <Shield class="w-3.5 h-3.5" /> 管理
          </button>
          <button class="menu-row" @click="logout"><LogOut class="w-3.5 h-3.5" /> 退出</button>
        </div>
      </div>
    </div>

    <div v-if="fileTreeOpen" @mousedown="onSidebarMD"
      class="w-[3px] flex-shrink-0 cursor-col-resize bg-transparent hover:bg-ruc-red/30 active:bg-ruc-red/60 transition-colors relative">
      <div class="absolute inset-y-0 -left-1 -right-1" />
    </div>

    <div class="flex-1 min-w-0 flex flex-col bg-white">
      <div v-if="openFiles.length" class="h-9 flex-shrink-0 border-b border-ruc-divider flex items-stretch overflow-x-auto bg-ruc-bg">
        <div
          v-for="file in openFiles"
          :key="file.path"
          class="group flex items-center gap-1.5 pl-2.5 pr-1 max-w-[200px] border-r border-ruc-divider cursor-pointer flex-shrink-0"
          :class="file.path === selectedPath ? 'bg-white text-ruc-text' : 'text-ruc-text-dim hover:bg-white/80'"
          :title="file.path"
          @click="activateTab(file)"
        >
          <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" :class="dirtyPaths[file.path] ? 'bg-ruc-text' : 'bg-transparent'" />
          <span class="text-xs font-ui truncate">{{ file.name }}</span>
          <button class="p-0.5 rounded text-ruc-text-light hover:text-ruc-text hover:bg-ruc-warm flex-shrink-0" title="关闭" @click.stop="closeTab(file)">
            <X class="w-3 h-3" />
          </button>
        </div>
      </div>
      <div class="flex-1 min-h-0 select-text relative">
        <FilePreview
          v-for="file in openFiles"
          v-show="file.path === selectedPath"
          :key="file.path + '|' + workspaceStore.source"
          :ref="(el) => setPreviewRef(file.path, el)"
          :session-id="sessionId"
          :source="workspaceStore.source"
          :file="file"
          @dirty="(value) => onPreviewDirty(file.path, value)"
        />
        <div v-if="!openFiles.length" class="h-full flex items-center justify-center px-6">
          <div class="text-center max-w-sm">
            <p class="text-sm font-ui text-ruc-text-dim">从左侧点开一个文件，这里会展开预览</p>
            <p class="text-xs font-ui text-ruc-text-light mt-2">上方标题可以切换和关闭。改过的标题左边会有一个小点，关掉时仍会问要不要保存</p>
          </div>
        </div>
      </div>
    </div>

    <div v-if="agentOpen" @mousedown="onAgentMD"
      class="w-[3px] flex-shrink-0 cursor-col-resize bg-transparent hover:bg-ruc-red/30 active:bg-ruc-red/60 transition-colors relative">
      <div class="absolute inset-y-0 -left-1 -right-1" />
    </div>

    <div
      v-if="agentOpen"
      class="flex-shrink-0 bg-ruc-bg border-l border-ruc-divider flex flex-col min-w-0"
      :style="{ width: agentWidth + 'px' }">
      <div class="flex-shrink-0 bg-white border-b border-ruc-divider px-3 py-2 flex items-center gap-2">
        <div class="min-w-0 flex-1">
          <p class="text-sm font-display font-semibold text-ruc-red truncate leading-tight">
            {{ sessionStore.currentSession?.title || skillTitle }}
          </p>
          <p class="text-[11px] font-ui text-ruc-text-light truncate mt-0.5">
            {{ modeTitle }}
          </p>
        </div>
        <div ref="moreRoot" class="relative">
          <button
            class="p-1.5 rounded-lg text-ruc-text-light hover:text-ruc-red hover:bg-ruc-warm"
            title="分享和导出"
            @click.stop="moreOpen = !moreOpen"
          >
            <MoreHorizontal class="w-4 h-4" />
          </button>
          <div v-if="moreOpen" class="absolute right-0 top-full mt-1 z-40 w-36 bg-white border border-ruc-divider rounded-xl shadow-modal p-1" @click.stop>
            <ShareButton :session-id="sessionId" placement="down" compact />
            <ExportButton :session-id="sessionId" placement="down" compact />
          </div>
        </div>
        <button
          class="p-1.5 rounded-lg text-ruc-text-light hover:text-ruc-red hover:bg-ruc-warm"
          title="收起对话"
          @click="agentOpen = false"
        >
          <PanelRightClose class="w-4 h-4" />
        </button>
      </div>
      <div class="flex-shrink-0 bg-white border-b border-ruc-divider px-2 py-1.5 flex items-center gap-1">
        <button class="p-1.5 rounded-lg text-ruc-text-dim hover:text-ruc-red hover:bg-ruc-warm disabled:opacity-50" :disabled="creating" title="新建一条对话" @click="onNew">
          <Plus class="w-4 h-4" />
        </button>
        <button class="p-1.5 rounded-lg text-ruc-text-dim hover:text-ruc-red hover:bg-ruc-warm" :class="historyOpen ? 'bg-ruc-red-pale text-ruc-red' : ''" title="历史对话，可在里面搜索" @click="toggleHistory">
          <History class="w-4 h-4" />
        </button>
        <div class="ml-auto flex items-center gap-1 min-w-0">
          <CollabInboxButton variant="toolbar" />
          <CollabButton :session-id="sessionId" compact anchor="below" />
        </div>
      </div>
      <div class="flex-1 min-h-0 relative">
        <div v-if="historyOpen" class="absolute inset-0 z-20 bg-white flex flex-col">
          <AppSidebar
            ref="historyRef"
            mode="history"
            :active-session-id="sessionId"
            @close="historyOpen = false"
          />
        </div>
        <div class="h-full flex flex-col">
          <ChatPanel
            v-if="chatReady"
            ref="chatRef"
            :key="sessionId"
            :session-id="sessionId"
            :skill-name="sessionStore.currentSession?.skill_name || skillName"
            :mode-name="sessionStore.currentSession?.mode_name"
            :source="workspaceStore.source"
            :open-file="editableOpen"
            @done="onChatDone"
            @wrote="onWrote"
            @generated="onGeneratedFile"
          />
        </div>
      </div>
    </div>

    <button
      v-else
      class="w-10 flex-shrink-0 border-l border-ruc-divider bg-white text-ruc-text-light hover:text-ruc-red flex flex-col items-center justify-center gap-2"
      title="打开对话"
      @click="agentOpen = true"
    >
      <PanelRight class="w-4 h-4" />
      <span class="text-[11px] font-ui writing-vertical">对话</span>
    </button>
  </div>
</template>

<style scoped>
.chip {
  @apply inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-ui text-ruc-text hover:bg-ruc-warm disabled:opacity-50;
}
.menu-row {
  @apply w-full flex items-center gap-2 px-3 py-2 text-xs font-ui text-ruc-text hover:bg-ruc-red-pale hover:text-ruc-red text-left;
}
.writing-vertical {
  writing-mode: vertical-rl;
}
</style>
