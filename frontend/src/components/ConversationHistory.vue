<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { toast } from '@/composables/useToast'
import { SKILL_LABELS, SKILL_ROUTES } from '@/utils/constants'
import { MessageCircle, Clock, Plus, Trash2, Pencil, Check, X } from 'lucide-vue-next'

const props = defineProps<{ collapsed: boolean; skillName: string; currentSessionId: string }>()
const emit = defineEmits<{ toggle: []; newSession: []; deleted: [id: string]; renamed: [payload: { id: string; title: string }] }>()

const router = useRouter()
const sessions = ref<any[]>([])
const loading = ref(false)
const editingId = ref<string | null>(null)
const editingTitle = ref('')
const deletingId = ref<string | null>(null)

async function loadSessions() {
  loading.value = true
  try {
    const data = await api.listSessions(1, 50, props.skillName || undefined)
    sessions.value = data.data || []
  } catch { sessions.value = [] }
  finally { loading.value = false }
}

function handleSelectSession(s: any) {
  if (editingId.value || deletingId.value) return
  if (s.id === props.currentSessionId) return
  const route = SKILL_ROUTES[s.skill_name] || 'research'
  router.push(`/session/${s.id}/${route}`)
}

function startRename(s: any, e: Event) {
  e.stopPropagation()
  editingId.value = s.id
  editingTitle.value = s.title || ''
}

function cancelRename(e?: Event) {
  e?.stopPropagation()
  editingId.value = null
  editingTitle.value = ''
}

async function saveRename(s: any, e?: Event) {
  e?.stopPropagation()
  const title = editingTitle.value.trim()
  if (!title) { toast.warning('标题不能为空'); return }
  try {
    const updated = await api.updateSession(s.id, title)
    s.title = updated.title || title
    editingId.value = null
    toast.success('已保存标题')
    emit('renamed', { id: s.id, title: s.title })
  } catch (err: any) {
    toast.error('保存失败：' + (err.message || '未知错误'))
  }
}

async function confirmDelete(s: any, e: Event) {
  e.stopPropagation()
  if (deletingId.value !== s.id) {
    deletingId.value = s.id
    return
  }
  try {
    await api.deleteSession(s.id)
    sessions.value = sessions.value.filter((x) => x.id !== s.id)
    deletingId.value = null
    toast.success('会话已删除')
    emit('deleted', s.id)
  } catch (err: any) {
    toast.error('删除失败：' + (err.message || '未知错误'))
  }
}

function cancelDelete(e: Event) {
  e.stopPropagation()
  deletingId.value = null
}

function fmtDate(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 86400000) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

watch(() => [props.skillName, props.currentSessionId], () => loadSessions(), { immediate: true })
defineExpose({ loadSessions })
</script>

<template>
  <template v-if="collapsed">
    <div class="flex flex-col h-full w-full items-center pt-3 gap-2">
      <button @click="emit('toggle')" class="text-ruc-text-light hover:text-ruc-red transition-colors p-1" title="展开历史对话">
        <MessageCircle class="w-4 h-4" />
      </button>
      <span class="text-[10px] font-ui text-ruc-text-light writing-vertical">{{ sessions.length }}</span>
    </div>
  </template>

  <template v-else>
    <div class="flex flex-col h-full">
      <div class="flex items-center justify-between px-3 py-2.5 border-b border-ruc-divider flex-shrink-0">
        <span class="text-xs font-ui font-medium text-ruc-text-dim flex items-center gap-1.5">
          <MessageCircle class="w-3.5 h-3.5" />
          {{ SKILL_LABELS[skillName] || '会话' }}
        </span>
        <button
          @click="emit('newSession')"
          class="flex items-center gap-1 text-[11px] font-ui text-ruc-text-light hover:text-ruc-red bg-ruc-bg hover:bg-ruc-warm px-2 py-1 rounded-lg transition-colors"
          title="新建会话"
        >
          <Plus class="w-3 h-3" />
          新建
        </button>
      </div>

      <div class="flex-1 overflow-y-auto py-1">
        <div v-if="loading" class="flex items-center justify-center py-8">
          <div class="w-4 h-4 border-2 border-ruc-red/30 border-t-ruc-red rounded-full animate-spin" />
        </div>
        <div v-else-if="sessions.length === 0" class="px-3 py-6 text-center">
          <MessageCircle class="w-5 h-5 mx-auto text-ruc-divider mb-2" />
          <p class="text-ruc-text-light text-xs font-ui">暂无会话</p>
        </div>

        <div
          v-for="s in sessions"
          :key="s.id"
          @click="handleSelectSession(s)"
          class="mx-2 px-3 py-2.5 rounded-xl cursor-pointer transition-all duration-150 group relative"
          :class="s.id === currentSessionId
            ? 'bg-ruc-red-pale border border-ruc-red/15'
            : 'hover:bg-ruc-warm border border-transparent hover:border-ruc-divider'"
        >
          <div v-if="editingId === s.id" class="flex items-center gap-1" @click.stop>
            <input
              v-model="editingTitle"
              @keydown.enter="saveRename(s)"
              @keydown.esc="cancelRename()"
              class="flex-1 min-w-0 text-xs font-ui px-2 py-1 rounded-lg border border-ruc-red/30 focus:outline-none focus:ring-1 focus:ring-ruc-red/30 bg-white"
              autofocus
            />
            <button @click="saveRename(s, $event)" class="p-1 text-ruc-success hover:bg-white rounded" title="保存"><Check class="w-3.5 h-3.5" /></button>
            <button @click="cancelRename($event)" class="p-1 text-ruc-text-light hover:bg-white rounded" title="取消"><X class="w-3.5 h-3.5" /></button>
          </div>
          <template v-else>
            <p class="text-xs font-ui font-medium truncate leading-relaxed pr-12"
               :class="s.id === currentSessionId ? 'text-ruc-red' : 'text-ruc-text'">
              {{ s.title || '未命名会话' }}
            </p>
            <div class="flex items-center gap-1.5 mt-1">
              <span class="text-[10px] font-ui text-ruc-text-light px-1.5 py-0.5 rounded bg-ruc-bg">{{ s.mode_name }}</span>
              <span class="text-[10px] font-ui text-ruc-text-light flex items-center gap-0.5">
                <Clock class="w-2.5 h-2.5" />{{ fmtDate(s.updated_at || s.created_at) }}
              </span>
            </div>
            <div class="absolute top-2 right-2 hidden group-hover:flex items-center gap-0.5 bg-white/90 rounded-lg border border-ruc-divider shadow-sm p-0.5">
              <button @click="startRename(s, $event)" class="p-1 text-ruc-text-dim hover:text-ruc-red rounded" title="重命名 / 保存标题"><Pencil class="w-3 h-3" /></button>
              <button
                v-if="deletingId !== s.id"
                @click="confirmDelete(s, $event)"
                class="p-1 text-ruc-text-dim hover:text-ruc-error rounded"
                title="删除会话"
              ><Trash2 class="w-3 h-3" /></button>
              <template v-else>
                <button @click="confirmDelete(s, $event)" class="px-1.5 py-0.5 text-[10px] text-white bg-ruc-error rounded" title="确认删除">删</button>
                <button @click="cancelDelete($event)" class="p-1 text-ruc-text-light" title="取消"><X class="w-3 h-3" /></button>
              </template>
            </div>
          </template>
        </div>
      </div>

      <div class="px-3 py-1.5 border-t border-ruc-divider flex-shrink-0 flex items-center justify-between">
        <span class="text-[10px] font-ui text-ruc-text-light">{{ sessions.length }} 个会话</span>
        <button @click="emit('toggle')" class="text-[10px] font-ui text-ruc-text-light hover:text-ruc-text px-1.5 py-0.5 rounded transition-colors" title="折叠">收起</button>
      </div>
    </div>
  </template>
</template>

<style scoped>
.writing-vertical { writing-mode: vertical-rl; text-orientation: mixed; }
</style>
