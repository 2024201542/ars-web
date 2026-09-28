<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useSettingsStore } from '@/stores/settings'
import { useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { SKILL_LABELS, SKILL_ROUTES } from '@/utils/constants'
import { describeSession } from '@/utils/startOptions'
import { useNewChat } from '@/composables/useNewChat'
import CollabInboxButton from '@/components/CollabInboxButton.vue'
import {
  Plus, Search, Clock, Settings, Shield, LogOut, Pencil, Trash2, Check, X, PanelLeft,
} from 'lucide-vue-next'

const props = withDefaults(defineProps<{ activeSessionId?: string; mode?: 'dock' | 'history' }>(), {
  mode: 'dock',
})
const emit = defineEmits<{ close: [] }>()

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const settings = useSettingsStore()
const sessionStore = useSessionStore()
const toast = useToast()

const sessions = ref<any[]>([])
const loading = ref(false)
const searching = ref(false)
const query = ref('')
const searchRef = ref<HTMLInputElement | null>(null)
const accountOpen = ref(false)
const drawerOpen = ref(false)
const editingId = ref<string | null>(null)
const editingTitle = ref('')
const deletingId = ref<string | null>(null)
const rootRef = ref<HTMLElement | null>(null)
const { creating, goNew: createChat } = useNewChat()

const currentModel = computed(() => {
  const model = settings.models.find((item) => item.id === settings.selectedModel)
  return model?.name || '未选择模型'
})

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return sessions.value
  return sessions.value.filter((item) => {
    const title = (item.title || '').toLowerCase()
    const skill = (SKILL_LABELS[item.skill_name] || item.skill_name || '').toLowerCase()
    return title.includes(q) || skill.includes(q)
  })
})

async function loadSessions() {
  loading.value = true
  try {
    const data = await api.listSessions(1, 50)
    sessions.value = data.data || []
  } catch {
    sessions.value = []
  } finally {
    loading.value = false
  }
}

function closeDrawer() {
  drawerOpen.value = false
}

async function goNew() {
  accountOpen.value = false
  searching.value = false
  query.value = ''
  closeDrawer()
  emit('close')
  await createChat(props.activeSessionId)
}

function focusSearch() {
  searching.value = true
  setTimeout(() => searchRef.value?.focus(), 0)
}

defineExpose({ focusSearch })

function openSearch() {
  searching.value = true
  drawerOpen.value = true
  setTimeout(() => searchRef.value?.focus(), 0)
}

function openSession(item: any) {
  if (editingId.value || deletingId.value) return
  closeDrawer()
  emit('close')
  if (item.id === props.activeSessionId) return
  const name = SKILL_ROUTES[item.skill_name] || 'research'
  router.push(`/session/${item.id}/${name}`)
}

function startRename(item: any, event: Event) {
  event.stopPropagation()
  deletingId.value = null
  editingId.value = item.id
  editingTitle.value = item.title || ''
}

function cancelRename(event?: Event) {
  event?.stopPropagation()
  editingId.value = null
}

async function saveRename(item: any, event?: Event) {
  event?.stopPropagation()
  const title = editingTitle.value.trim()
  if (!title) {
    toast.warning('标题不能为空')
    return
  }
  try {
    const updated = await api.updateSession(item.id, title)
    item.title = updated.title || title
    if (sessionStore.currentSession?.id === item.id) sessionStore.currentSession.title = item.title
    editingId.value = null
  } catch (err: any) {
    toast.error('保存失败：' + (err.message || ''))
  }
}

async function confirmDelete(item: any, event: Event) {
  event.stopPropagation()
  if (deletingId.value !== item.id) {
    deletingId.value = item.id
    return
  }
  try {
    await api.deleteSession(item.id)
    sessions.value = sessions.value.filter((row) => row.id !== item.id)
    deletingId.value = null
    toast.success('会话已删除')
    if (item.id === props.activeSessionId) router.push('/')
  } catch (err: any) {
    toast.error('删除失败：' + (err.message || ''))
  }
}

function fmtDate(iso: string) {
  if (!iso) return ''
  const date = new Date(iso)
  const diff = Date.now() - date.getTime()
  if (diff < 86400000) return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

function onDocClick(event: MouseEvent) {
  if (rootRef.value && !rootRef.value.contains(event.target as Node)) accountOpen.value = false
}

function goSettings() {
  accountOpen.value = false
  closeDrawer()
  router.push('/settings')
}

function goAdmin() {
  accountOpen.value = false
  closeDrawer()
  router.push('/admin')
}

function logout() {
  accountOpen.value = false
  auth.logout()
  router.push('/login')
}

onMounted(() => {
  if (!settings.loaded) void settings.load()
  loadSessions()
  document.addEventListener('click', onDocClick)
})
onUnmounted(() => document.removeEventListener('click', onDocClick))
watch(() => route.fullPath, () => loadSessions())
</script>

<template>
  <button
    v-if="mode === 'dock'"
    class="md:hidden fixed top-3 left-3 z-50 w-9 h-9 rounded-lg bg-white border border-ruc-divider shadow-card flex items-center justify-center text-ruc-text"
    title="打开侧栏"
    @click="drawerOpen = !drawerOpen"
  >
    <PanelLeft class="w-4 h-4" />
  </button>
  <div
    v-if="mode === 'dock' && drawerOpen"
    class="md:hidden fixed inset-0 z-40 bg-black/30"
    @click="closeDrawer"
  />

  <aside
    ref="rootRef"
    class="h-full bg-white flex flex-col"
    :class="mode === 'history'
      ? 'relative w-full'
      : ['fixed md:static z-40 inset-y-0 left-0 w-[240px] flex-shrink-0 border-r border-ruc-divider transition-transform duration-200', drawerOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0']"
  >
    <div v-if="mode === 'dock'" class="px-3 pt-4 pb-3 flex items-center gap-2.5">
      <div class="logo-mark !w-8 !h-8">
        <span class="logo-mark-text !text-base">A</span>
      </div>
      <div class="min-w-0">
        <p class="text-ruc-red font-display text-base font-semibold leading-none">ARS Web</p>
        <p class="text-[11px] text-ruc-text-light font-ui mt-0.5">学术研究助手</p>
      </div>
    </div>
    <div v-else class="px-3 pt-3 pb-2 flex items-center justify-between border-b border-ruc-divider">
      <p class="text-xs font-ui font-medium text-ruc-text-dim">历史对话</p>
      <button class="p-1 text-ruc-text-light hover:text-ruc-red rounded" title="关闭" @click="emit('close')">
        <X class="w-3.5 h-3.5" />
      </button>
    </div>

    <nav v-if="mode === 'dock'" class="px-2 space-y-0.5">
      <button class="nav-item" :disabled="creating" @click="goNew">
        <Plus class="w-4 h-4" /> 新建
      </button>
      <button class="nav-item" :class="searching ? 'bg-ruc-red-pale text-ruc-red' : ''" @click="openSearch">
        <Search class="w-4 h-4" /> 搜索
      </button>
      <input
        v-if="searching"
        ref="searchRef"
        v-model="query"
        type="text"
        placeholder="搜索会话标题"
        class="w-full mt-1 mb-1 px-2.5 py-1.5 text-xs font-ui rounded-lg border border-ruc-border focus:outline-none focus:border-ruc-red/40"
        @keydown.esc="searching = false; query = ''"
      />
      <CollabInboxButton variant="sidebar" />
    </nav>

    <div v-if="mode === 'history'" class="px-2 pt-2">
      <input
        ref="searchRef"
        v-model="query"
        type="text"
        placeholder="搜索对话"
        class="w-full px-2.5 py-1.5 text-xs font-ui rounded-lg border border-ruc-border focus:outline-none focus:border-ruc-red/40"
        @keydown.esc="query = ''; emit('close')"
      />
    </div>

    <p v-if="mode === 'dock'" class="px-3 pt-4 pb-1 text-[11px] font-ui text-ruc-text-light flex items-center gap-1">
      <Clock class="w-3 h-3" /> 最近
    </p>
    <div class="flex-1 overflow-y-auto px-2 pb-2">
      <div v-if="loading && !sessions.length" class="py-6 flex justify-center">
        <div class="w-4 h-4 border-2 border-ruc-red/20 border-t-ruc-red rounded-full animate-spin" />
      </div>
      <p v-else-if="!filtered.length" class="px-2 py-4 text-[11px] font-ui text-ruc-text-light text-center">
        {{ query ? '没有匹配的会话' : '还没有会话' }}
      </p>
      <div
        v-for="item in filtered"
        :key="item.id"
        role="button"
        class="group relative px-2.5 py-2 rounded-lg cursor-pointer mb-0.5"
        :class="item.id === activeSessionId ? 'bg-ruc-red-pale text-ruc-red' : 'hover:bg-ruc-warm text-ruc-text'"
        @click="openSession(item)"
      >
        <div v-if="editingId === item.id" class="flex items-center gap-1" @click.stop>
          <input
            v-model="editingTitle"
            class="flex-1 min-w-0 text-xs px-1.5 py-1 rounded border border-ruc-red/30 focus:outline-none"
            @keydown.enter="saveRename(item)"
            @keydown.esc="cancelRename()"
          />
          <button class="p-1 text-ruc-red" @click="saveRename(item, $event)"><Check class="w-3 h-3" /></button>
          <button class="p-1 text-ruc-text-light" @click="cancelRename($event)"><X class="w-3 h-3" /></button>
        </div>
        <template v-else>
          <p class="text-xs font-ui font-medium truncate pr-10 leading-snug">{{ item.title || '未命名会话' }}</p>
          <p class="text-[10px] font-ui mt-0.5 truncate" :class="item.id === activeSessionId ? 'text-ruc-red/70' : 'text-ruc-text-light'">
            {{ SKILL_LABELS[item.skill_name] || item.skill_name }} · {{ describeSession(item.skill_name, item.mode_name) }}
            · {{ fmtDate(item.updated_at || item.created_at) }}
          </p>
          <div class="absolute top-1.5 right-1 hidden group-hover:flex items-center bg-white/95 rounded border border-ruc-divider">
            <button class="p-1 text-ruc-text-dim hover:text-ruc-red" title="重命名" @click="startRename(item, $event)">
              <Pencil class="w-3 h-3" />
            </button>
            <button
              v-if="deletingId !== item.id"
              class="p-1 text-ruc-text-dim hover:text-ruc-error"
              title="删除"
              @click="confirmDelete(item, $event)"
            >
              <Trash2 class="w-3 h-3" />
            </button>
            <template v-else>
              <button class="px-1 text-[10px] text-white bg-ruc-error rounded-sm" @click="confirmDelete(item, $event)">删</button>
              <button class="p-1 text-ruc-text-light" @click.stop="deletingId = null"><X class="w-3 h-3" /></button>
            </template>
          </div>
        </template>
      </div>
    </div>

    <div v-if="mode === 'dock'" class="border-t border-ruc-divider p-2 space-y-0.5">
      <button class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-ruc-warm text-left" @click="goSettings">
        <span class="dot-green flex-shrink-0" />
        <span class="text-[11px] font-ui text-ruc-text-dim truncate">{{ currentModel }}</span>
      </button>
      <div class="relative">
        <button
          class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-ruc-red-pale text-left"
          @click.stop="accountOpen = !accountOpen"
        >
          <span class="w-5 h-5 rounded-full bg-ruc-red text-white text-[10px] font-ui flex items-center justify-center flex-shrink-0">
            {{ (auth.user?.display_name || auth.user?.username || '?').slice(0, 1) }}
          </span>
          <span class="text-xs font-ui text-ruc-text truncate">{{ auth.user?.display_name || auth.user?.username }}</span>
        </button>
        <div
          v-if="accountOpen"
          class="absolute bottom-full left-0 mb-1 w-full bg-white border border-ruc-divider rounded-xl shadow-modal py-1 z-50"
        >
          <button class="menu-row" @click="goSettings"><Settings class="w-3.5 h-3.5" /> 设置</button>
          <button v-if="auth.user?.role === 'admin'" class="menu-row" @click="goAdmin">
            <Shield class="w-3.5 h-3.5" /> 管理
          </button>
          <button class="menu-row" @click="logout"><LogOut class="w-3.5 h-3.5" /> 退出</button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.nav-item {
  @apply w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-sm font-ui text-ruc-text hover:bg-ruc-warm text-left cursor-pointer;
}
.menu-row {
  @apply w-full flex items-center gap-2 px-3 py-2 text-xs font-ui text-ruc-text hover:bg-ruc-red-pale hover:text-ruc-red text-left;
}
</style>
