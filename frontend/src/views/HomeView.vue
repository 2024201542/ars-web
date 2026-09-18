<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import { api } from '@/api'
import { SKILL_LABELS, SKILL_ROUTES, SKILL_DESCRIPTIONS } from '@/utils/constants'
import ModeSelector from '@/components/ModeSelector.vue'
import type { Skill, Mode } from '@/types'
import {
  Search, Edit3, ClipboardCheck, Rocket, Database,
  Settings, ChevronRight, Info, Shield,
} from 'lucide-vue-next'
import CollabInboxButton from '@/components/CollabInboxButton.vue'

const router = useRouter()
const auth = useAuthStore()
const settings = useSettingsStore()
const toast = useToast()

const SKILL_ICONS: Record<string, any> = {
  search: Search,
  edit: Edit3,
  clipboard: ClipboardCheck,
  rocket: Rocket,
  database: Database,
}

const skills = ref<Skill[]>([])
const loading = ref(true)
const showModeSelector = ref(false)
const selectedSkill = ref<Skill | null>(null)

const currentModel = computed(() => {
  const m = settings.models.find(x => x.id === settings.selectedModel)
  return m?.name || '未选择'
})
const currentProvider = computed(() => {
  const m = settings.models.find(x => x.id === settings.selectedModel)
  const p = settings.providers.find(x => x.id === m?.provider)
  return p?.display_name || ''
})

onMounted(async () => {
  if (!settings.loaded) void settings.load()
  try {
    const sd = await api.getSkills()
    skills.value = sd.data
  } catch { toast.error('连接服务器失败') }
  finally { loading.value = false }
})

function handleSkillClick(skill: Skill) {
  if (!settings.isConfigured) { router.push('/settings'); toast.info('请先配置 API Key'); return }
  selectedSkill.value = skill; showModeSelector.value = true
}
async function handleModeSelect(mode: Mode) {
  if (!selectedSkill.value) return
  try {
    const s = await api.createSession(selectedSkill.value.name, mode.name)
    showModeSelector.value = false
    router.push(`/session/${s.id}/${SKILL_ROUTES[selectedSkill.value.name] || 'research'}`)
  } catch (e: any) { toast.error('创建会话失败: ' + (e.message || '')) }
}
</script>

<template>
  <div class="min-h-screen flex flex-col">
    <!-- Header -->
    <header class="border-b border-ruc-divider bg-white/80 backdrop-blur-md sticky top-0 z-30">
      <div class="max-w-6xl mx-auto px-5 py-4 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="logo-mark">
            <span class="logo-mark-text">A</span>
          </div>
          <div>
            <h1 class="text-ruc-red font-display text-xl font-semibold leading-none">ARS Web</h1>
            <p class="text-ruc-text-light text-xs font-ui mt-0.5">学术研究助手</p>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <div v-if="settings.isConfigured" class="hidden md:flex items-center gap-2.5 px-3 py-2 rounded-xl bg-ruc-warm border border-ruc-divider">
            <span class="dot-green" />
            <div class="text-left leading-tight">
              <p class="text-[11px] font-ui text-ruc-text-light">{{ currentProvider }}</p>
              <p class="text-sm font-ui font-medium text-ruc-text">{{ currentModel }}</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <CollabInboxButton />
            <span class="text-xs font-ui text-ruc-text-light hidden sm:inline">{{ auth.user?.display_name || auth.user?.username }}</span>
            <button v-if="auth.user?.role === 'admin'" @click="router.push('/admin')" class="btn-secondary flex items-center gap-2 text-sm">
              <Shield class="w-4 h-4" />
              管理
            </button>
            <button @click="router.push('/settings')" class="btn-secondary flex items-center gap-2 text-sm">
              <Settings class="w-4 h-4" />
              设置
            </button>
            <button @click="auth.logout(); router.push('/login')" class="btn-ghost text-sm text-ruc-text-dim">
              退出
            </button>
          </div>
        </div>
      </div>
    </header>

    <main class="flex-1 py-12 px-5">
      <div class="max-w-4xl mx-auto">
        <!-- Hero -->
        <div class="text-center mb-12 animate-fade-in">
          <h2 class="text-4xl font-display font-semibold text-ruc-text mb-3">欢迎使用 ARS Web</h2>
          <p class="text-ruc-text-dim text-lg font-ui max-w-lg mx-auto">学术研究智能助手，助力您的科研工作</p>
          <div v-if="!settings.loaded" class="mt-4 flex justify-center">
            <div class="w-6 h-6 border-2 border-ruc-red/20 border-t-ruc-red rounded-full animate-spin" />
          </div>
          <div v-else-if="!settings.isConfigured" class="mt-4">
            <button @click="router.push('/settings')" class="inline-flex items-center gap-1.5 text-ruc-red/80 hover:text-ruc-red text-sm font-ui transition-colors">
              <Info class="w-4 h-4" />
              请先配置 API Key 以开始使用 →
            </button>
          </div>
        </div>

        <!-- Skeleton -->
        <div v-if="loading" class="grid grid-cols-1 md:grid-cols-2 gap-5 mb-12">
          <div v-for="i in 4" :key="i" class="card animate-pulse">
            <div class="flex gap-4">
              <div class="w-12 h-12 rounded-xl bg-ruc-bg" />
              <div class="flex-1 space-y-3">
                <div class="h-5 bg-ruc-bg rounded w-24" />
                <div class="h-4 bg-ruc-bg rounded w-full" />
                <div class="h-3 bg-ruc-bg rounded w-16" />
              </div>
            </div>
          </div>
        </div>

        <!-- Skill Cards -->
        <div v-else-if="!skills.length" class="text-center py-10 text-ruc-text-dim font-ui text-sm">
          未检测到技能目录。请确认后端 <code class="text-ruc-red">ARS_SKILLS_PATH</code> 指向含 deep-research 等技能的仓库根目录。
        </div>
        <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-5 mb-12">
          <div
            v-for="skill in skills" :key="skill.name"
            @click="handleSkillClick(skill)"
            class="card cursor-pointer group"
          >
            <div class="flex items-start gap-4">
              <div class="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 transition-colors duration-300"
                   :class="settings.isConfigured ? 'bg-ruc-red-pale group-hover:bg-ruc-red-soft' : 'bg-ruc-bg'">
                <component :is="SKILL_ICONS[skill.icon] || Search"
                  class="w-6 h-6 transition-colors duration-300"
                  :class="settings.isConfigured ? 'text-ruc-red group-hover:text-ruc-red-light' : 'text-ruc-text-light'" />
              </div>
              <div class="flex-1 min-w-0">
                <h3 class="text-ruc-red font-display text-lg font-semibold mb-1.5 group-hover:text-ruc-red-light transition-colors">
                  {{ SKILL_LABELS[skill.name] || skill.name }}
                </h3>
                <p class="text-ruc-text-dim text-sm font-ui leading-relaxed line-clamp-2 mb-2">{{ SKILL_DESCRIPTIONS[skill.name] || skill.description }}</p>
                <span class="badge-dim">{{ skill.modes }} 种模式</span>
              </div>
              <ChevronRight class="w-5 h-5 text-ruc-text-light group-hover:text-ruc-red group-hover:translate-x-1 transition-all duration-300 flex-shrink-0 mt-3" />
            </div>
          </div>
        </div>
      </div>
    </main>

    <ModeSelector v-if="showModeSelector && selectedSkill" :skill="selectedSkill" @select="handleModeSelect" @close="showModeSelector = false" />
  </div>
</template>
