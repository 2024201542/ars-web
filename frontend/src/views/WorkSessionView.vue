<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToast } from '@/composables/useToast'
import { api } from '@/api'
import { SKILL_LABELS, SKILL_ROUTES } from '@/utils/constants'
import type { Message, Mode } from '@/types'
import FileTree from '@/components/FileTree.vue'
import FilePreview from '@/components/FilePreview.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import ConversationHistory from '@/components/ConversationHistory.vue'
import ModeSelector from '@/components/ModeSelector.vue'
import CollabInboxButton from '@/components/CollabInboxButton.vue'
import { ArrowLeft, PanelLeftClose, PanelLeft, ChevronDown, ChevronUp } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const sessionStore = useSessionStore()
const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()

const sessionId = computed(() => route.params.id as string)
const skillName = computed(() => (route.meta.skill as string) || '')
const skillTitle = computed(() => SKILL_LABELS[skillName.value] || skillName.value || '工作区')
const currentModel = computed(() => {
  const m = settingsStore.models.find(x => x.id === settingsStore.selectedModel)
  return m?.name || ''
})

const fileTreeOpen = ref(window.innerWidth > 768)
const fileTreeWidth = ref(260)
const previewOpen = ref(false)
const previewSize = ref(360)       // 预览区固定像素高度
const previewMaxSize = ref(800)
const historyVisible = ref(true)
const selectedFile = ref<any>(null)
const selectedPath = ref<string | null>(null)
const draggingSidebar = ref(false)
const draggingSplit = ref(false)

// 新建会话模态
const showNewSessionModal = ref(false)


function onSessionDeleted(id: string) {
  if (id === sessionId.value) router.push('/')
}
function onSessionRenamed(payload: { id: string; title: string }) {
  if (payload.id === sessionId.value && sessionStore.currentSession) {
    sessionStore.currentSession.title = payload.title
  }
}

function onSidebarMD(e: MouseEvent) { if (!fileTreeOpen.value) return; draggingSidebar.value = true; e.preventDefault() }
function onSplitMD(e: MouseEvent) { draggingSplit.value = true; e.preventDefault() }
function onMouseMove(e: MouseEvent) {
  if (draggingSidebar.value) fileTreeWidth.value = Math.max(180, Math.min(500, e.clientX))
  if (draggingSplit.value) {
    const el = document.getElementById('right-panel')
    if (!el) return
    const rect = el.getBoundingClientRect()
    const newHeight = Math.max(150, Math.min(rect.height * 0.65, rect.height - e.clientY + rect.top))
    previewSize.value = newHeight
    previewMaxSize.value = newHeight
  }
}
function onMouseUp() { draggingSidebar.value = false; draggingSplit.value = false }
function saveLayout() {
  localStorage.setItem('ars-layout-sw', String(fileTreeWidth.value))
  localStorage.setItem('ars-layout-ps', String(previewSize.value))
}
function restoreLayout() {
  fileTreeWidth.value = Number(localStorage.getItem('ars-layout-sw')) || 260
  previewSize.value = Number(localStorage.getItem('ars-layout-ps')) || 360
  previewMaxSize.value = Number(localStorage.getItem('ars-layout-ps')) || 360
}

const previewKey = ref(0)
function openPreview(file: any) {
  selectedFile.value = file
  previewOpen.value = true
  previewKey.value++
}

async function handleNewSession(mode: Mode) {
  showNewSessionModal.value = false
  try {
    const s = await api.createSession(skillName.value, mode.name, `${SKILL_LABELS[skillName.value]} - ${mode.display_name}`)
    const routeName = SKILL_ROUTES[skillName.value] || 'research'
    router.push(`/session/${s.id}/${routeName}`)
  } catch (e: any) { toast.error('创建会话失败: ' + (e.message || '')) }
}

async function loadSession() {
  try {
    const detail = await api.getSession(sessionId.value)
    sessionStore.setSession(detail.session)
    detail.messages.forEach((m: Message) => sessionStore.addMessage(m))
    await workspaceStore.loadFiles(sessionId.value)
  } catch { toast.error('加载会话失败') }
}

onMounted(async () => {
  restoreLayout()
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
  await loadSession()
})
onUnmounted(() => {
  saveLayout()
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
  sessionStore.clearSession()
})

// 当路由参数变化（通过历史切换到另一个session）时重新加载
watch(() => route.params.id, async (newId, oldId) => {
  if (newId && newId !== oldId) await loadSession()
})
</script>

<template>
  <div class="h-screen flex flex-col select-none"
    :class="{ 'cursor-col-resize': draggingSidebar, 'cursor-row-resize': draggingSplit }">

    <!-- Header -->
    <header class="flex-shrink-0 z-30 bg-white/90 backdrop-blur-md border-b border-ruc-divider">
      <div class="px-4 py-2.5 flex items-center gap-2">
        <button @click="router.push('/')"
          class="text-ruc-text-light hover:text-ruc-red p-1.5 -ml-1.5 rounded-lg hover:bg-ruc-warm flex-shrink-0 transition-all" title="返回首页">
          <ArrowLeft class="w-4 h-4" />
        </button>
        <button @click="fileTreeOpen = !fileTreeOpen"
          class="text-ruc-text-light hover:text-ruc-red p-1.5 rounded-lg hover:bg-ruc-warm flex-shrink-0 transition-all"
          :title="fileTreeOpen ? '收起文件树' : '展开文件树'">
          <component :is="fileTreeOpen ? PanelLeftClose : PanelLeft" class="w-4 h-4" />
        </button>
        <div class="hidden sm:block w-px h-5 bg-ruc-divider mx-0.5" />
        <div class="flex-1 min-w-0">
          <h1 class="text-ruc-red font-display text-sm font-semibold truncate leading-tight">
            {{ sessionStore.currentSession?.title || skillTitle }}
          </h1>
          <p class="text-ruc-text-light text-[11px] font-ui truncate mt-0.5">
            {{ skillTitle }}
            <template v-if="currentModel"> · {{ currentModel }}</template>
            <template v-if="sessionStore.messages.length"> · {{ sessionStore.messages.length }} 条消息</template>
          </p>
        </div>
        <CollabInboxButton />
      </div>
    </header>

    <div class="flex-1 flex min-h-0 overflow-hidden">
      <!-- Left: FileTree -->
      <div
        class="flex-shrink-0 bg-ruc-warm/40 border-r border-ruc-divider overflow-hidden"
        :class="fileTreeOpen ? 'flex flex-col' : ''"
        :style="{ width: fileTreeOpen ? fileTreeWidth + 'px' : '36px' }">
        <FileTree
          :session-id="sessionId"
          :collapsed="!fileTreeOpen"
          v-model:selected-path="selectedPath"
          @select="openPreview"
          @toggle="fileTreeOpen = true"
        />
      </div>

      <div v-if="fileTreeOpen" @mousedown="onSidebarMD"
        class="w-[3px] flex-shrink-0 cursor-col-resize bg-transparent hover:bg-ruc-red/30 active:bg-ruc-red/60 transition-colors relative group">
        <div class="absolute inset-y-0 -left-1 -right-1" />
      </div>

      <!-- Right -->
      <div id="right-panel" class="flex-1 flex flex-col min-w-0 overflow-hidden">
        <!-- Preview: 固定像素高度，由拖拽手柄控制 -->
        <div v-show="previewOpen" class="flex-shrink-0 mx-2 mt-2 rounded-2xl bg-white shadow-card overflow-auto"
             :style="{ height: previewSize + 'px', maxHeight: previewMaxSize + 'px' }">
          <FilePreview :key="previewKey" :session-id="sessionId" :file="selectedFile" />
        </div>
        <div v-show="previewOpen" @mousedown="onSplitMD"
          class="h-2 flex-shrink-0 cursor-row-resize flex items-center justify-center group transition-colors">
          <div class="flex flex-col gap-0.5 py-0.5">
            <div class="w-6 h-0.5 rounded-full bg-ruc-border group-hover:bg-ruc-red/40 group-active:bg-ruc-red/60 transition-colors" />
            <div class="w-4 h-0.5 rounded-full bg-ruc-border group-hover:bg-ruc-red/40 group-active:bg-ruc-red/60 transition-colors mx-auto" />
            <div class="w-6 h-0.5 rounded-full bg-ruc-border group-hover:bg-ruc-red/40 group-active:bg-ruc-red/60 transition-colors" />
          </div>
        </div>

        <div class="flex-shrink-0 px-3 py-1 flex items-center justify-center">
          <button
            @click="previewOpen = !previewOpen"
            class="flex items-center gap-1.5 text-[11px] font-ui text-ruc-text-light hover:text-ruc-red transition-colors px-3 py-1 rounded-lg hover:bg-ruc-warm"
          >
            {{ previewOpen ? '收起文件预览' : '展开文件预览' }}
            <component :is="previewOpen ? ChevronUp : ChevronDown" class="w-3 h-3" />
          </button>
        </div>

        <!-- Chat area with session history -->
        <div class="flex-1 min-h-[120px] mx-2 mb-2 flex rounded-2xl bg-white shadow-card overflow-hidden">
          <div class="border-r border-ruc-divider bg-ruc-warm/30 flex-shrink-0"
               :class="historyVisible ? 'w-[200px]' : 'w-[36px]'">
            <ConversationHistory
              :collapsed="!historyVisible"
              :skill-name="skillName"
              :current-session-id="sessionId"
              @toggle="historyVisible = !historyVisible"
              @new-session="showNewSessionModal = true"
             @deleted="onSessionDeleted" @renamed="onSessionRenamed" />
          </div>
          <div class="flex-1 min-w-0">
            <ChatPanel :key="sessionId" :session-id="sessionId" :skill-name="skillName" :mode-name="sessionStore.currentSession?.mode_name" @done="workspaceStore.refresh(sessionId)" />
          </div>
        </div>
      </div>
    </div>

    <!-- 新建会话模态 -->
    <ModeSelector
      v-if="showNewSessionModal && skillName"
      :skill="{ name: skillName } as any"
      @select="handleNewSession"
      @close="showNewSessionModal = false"
    />
  </div>
</template>
