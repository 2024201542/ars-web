<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import { usePendingStartStore } from '@/stores/pendingStart'
import { useToast } from '@/composables/useToast'
import { api } from '@/api'
import { SKILL_ROUTES } from '@/utils/constants'
import {
  START_OPTIONS, DEFAULT_START_ID, QUICK_STARTS, SUGGESTIONS,
  findStart, startTitle, type StartOption,
} from '@/utils/startOptions'
import AppSidebar from '@/components/AppSidebar.vue'
import { ChevronDown, ArrowUp, Paperclip, X, Loader2 } from 'lucide-vue-next'

const router = useRouter()
const settings = useSettingsStore()
const pending = usePendingStartStore()
const toast = useToast()

const selectedId = ref(DEFAULT_START_ID)
const menuOpen = ref(false)
const draft = ref('')
const files = ref<File[]>([])
const sending = ref(false)
const boxRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileRef = ref<HTMLInputElement | null>(null)

const current = computed(() => findStart(selectedId.value))
const workflows = computed(() => START_OPTIONS.filter((item) => item.group === '工作流'))
const tools = computed(() => START_OPTIONS.filter((item) => item.group === '工具'))

function pick(option: StartOption) {
  selectedId.value = option.id
  menuOpen.value = false
  textareaRef.value?.focus()
}

function onPickFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const list = Array.from(input.files || [])
  for (const file of list) {
    if (!files.value.some((item) => item.name === file.name && item.size === file.size)) files.value.push(file)
  }
  input.value = ''
}

function removeFile(index: number) {
  files.value.splice(index, 1)
}

async function start(text?: string, optionId?: string) {
  if (sending.value) return
  if (optionId) selectedId.value = optionId
  const message = (text ?? draft.value).trim()
  if (!message && !files.value.length) {
    textareaRef.value?.focus()
    return
  }
  if (!settings.isConfigured) {
    toast.info('请先配置 API Key')
    router.push('/settings')
    return
  }
  const option = findStart(selectedId.value)
  sending.value = true
  try {
    const title = (message || files.value[0]?.name || '新会话').replace(/\s+/g, ' ').slice(0, 40)
    const session = await api.createSession(option.skill, option.mode, title)
    pending.set(session.id, message, files.value.slice())
    files.value = []
    draft.value = ''
    const routeName = SKILL_ROUTES[option.skill] || 'research'
    await router.push(`/session/${session.id}/${routeName}`)
  } catch (err: any) {
    toast.error('创建会话失败: ' + (err.message || ''))
  } finally {
    sending.value = false
  }
}

function resetForNew() {
  draft.value = ''
  files.value = []
  menuOpen.value = false
  selectedId.value = DEFAULT_START_ID
  nextTick(() => textareaRef.value?.focus())
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void start()
  }
}

function onDocClick(event: MouseEvent) {
  if (boxRef.value && !boxRef.value.contains(event.target as Node)) menuOpen.value = false
}

onMounted(() => {
  if (!settings.loaded) void settings.load()
  document.addEventListener('click', onDocClick)
  window.addEventListener('ars-new', resetForNew)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('ars-new', resetForNew)
})
</script>

<template>
  <div class="h-screen flex bg-ruc-bg">
    <AppSidebar />
    <main class="flex-1 min-w-0 overflow-y-auto flex flex-col items-center justify-center px-4 py-16 md:px-8">
      <p class="text-sm font-ui text-ruc-text-dim mb-4">从一句话开始。方式已经选好，也可以再换。</p>

      <div ref="boxRef" class="w-full max-w-2xl relative">
        <div class="rounded-2xl bg-white border border-ruc-divider shadow-elevated overflow-hidden">
          <button
            class="w-full bg-ruc-red text-white px-4 py-2.5 flex items-center gap-2 text-left hover:bg-ruc-red-light transition-colors"
            @click.stop="menuOpen = !menuOpen"
          >
            <span class="text-sm font-ui font-medium truncate">{{ startTitle(current) }}</span>
            <span
              v-if="current.trial"
              class="text-[10px] font-ui px-1.5 py-0.5 rounded bg-ruc-gold text-white flex-shrink-0"
            >试验</span>
            <ChevronDown class="w-4 h-4 ml-auto flex-shrink-0 transition-transform" :class="menuOpen ? 'rotate-180' : ''" />
          </button>

          <div v-if="files.length" class="px-4 pt-3 flex flex-wrap gap-1.5">
            <span
              v-for="(file, index) in files"
              :key="file.name + file.size"
              class="inline-flex items-center gap-1 text-[11px] font-ui px-2 py-1 rounded-full bg-ruc-red-pale text-ruc-red"
            >
              {{ file.name }}
              <button class="hover:text-ruc-red-dark" @click="removeFile(index)"><X class="w-3 h-3" /></button>
            </span>
          </div>

          <textarea
            ref="textareaRef"
            v-model="draft"
            rows="3"
            placeholder="说说你想写什么…"
            class="w-full resize-none px-4 py-3 text-sm font-ui text-ruc-text placeholder:text-ruc-text-light focus:outline-none"
            @keydown="onKeydown"
          />

          <div class="px-3 pb-3 flex items-center justify-between gap-2">
            <button
              class="inline-flex items-center gap-1.5 text-xs font-ui text-ruc-text-dim hover:text-ruc-red px-2 py-1.5 rounded-lg hover:bg-ruc-red-pale"
              @click="fileRef?.click()"
            >
              <Paperclip class="w-3.5 h-3.5" /> 上传材料
            </button>
            <input ref="fileRef" type="file" class="hidden" multiple accept=".pdf,.doc,.docx,.txt,.md,.png,.jpg,.jpeg" @change="onPickFiles" />
            <button
              class="w-9 h-9 rounded-lg flex items-center justify-center text-white bg-ruc-red hover:bg-ruc-red-light disabled:opacity-40 disabled:cursor-not-allowed"
              :disabled="sending || (!draft.trim() && !files.length)"
              title="开始"
              @click="start()"
            >
              <Loader2 v-if="sending" class="w-4 h-4 animate-spin" />
              <ArrowUp v-else class="w-4 h-4" />
            </button>
          </div>
        </div>

        <div
          v-if="menuOpen"
          class="absolute left-0 right-0 top-11 z-30 bg-white border border-ruc-divider rounded-xl shadow-modal py-2 max-h-[60vh] overflow-y-auto"
        >
          <p class="px-3 pt-1 pb-1 text-[10px] font-ui tracking-wider text-ruc-text-light">工作流</p>
          <button
            v-for="option in workflows"
            :key="option.id"
            class="w-full px-3 py-2 text-left hover:bg-ruc-red-pale"
            :class="option.id === selectedId ? 'bg-ruc-red-pale' : ''"
            @click="pick(option)"
          >
            <span class="flex items-center gap-2 text-sm font-ui" :class="option.id === selectedId ? 'text-ruc-red' : 'text-ruc-text'">
              {{ startTitle(option) }}
              <span v-if="option.trial" class="text-[10px] px-1.5 py-0.5 rounded bg-ruc-warm text-ruc-gold border border-ruc-gold/30">试验</span>
            </span>
            <span class="block text-[11px] font-ui text-ruc-text-dim mt-0.5">{{ option.hint }}</span>
          </button>
          <p class="px-3 pt-2 pb-1 text-[10px] font-ui tracking-wider text-ruc-text-light">工具</p>
          <button
            v-for="option in tools"
            :key="option.id"
            class="w-full px-3 py-2 text-left hover:bg-ruc-red-pale"
            :class="option.id === selectedId ? 'bg-ruc-red-pale' : ''"
            @click="pick(option)"
          >
            <span class="block text-sm font-ui" :class="option.id === selectedId ? 'text-ruc-red' : 'text-ruc-text'">{{ startTitle(option) }}</span>
            <span class="block text-[11px] font-ui text-ruc-text-dim mt-0.5">{{ option.hint }}</span>
          </button>
        </div>
      </div>

      <div class="w-full max-w-2xl flex flex-wrap gap-2 mt-4">
        <button
          v-for="item in QUICK_STARTS"
          :key="item.id"
          class="px-3 py-1.5 rounded-full border text-xs font-ui transition-colors"
          :class="item.id === selectedId
            ? 'border-ruc-red bg-ruc-red-pale text-ruc-red'
            : 'border-ruc-border bg-white text-ruc-text-dim hover:border-ruc-red/40 hover:text-ruc-red'"
          @click="pick(findStart(item.id))"
        >
          {{ item.label }}
        </button>
      </div>

      <div class="w-full max-w-2xl grid grid-cols-1 sm:grid-cols-3 gap-3 mt-8">
        <button
          v-for="card in SUGGESTIONS"
          :key="card.startId"
          class="text-left bg-white border border-ruc-divider rounded-xl p-3 hover:border-ruc-red/30 hover:bg-ruc-red-pale/40 transition-colors"
          :disabled="sending"
          @click="start(card.text, card.startId)"
        >
          <span class="text-[10px] font-ui text-ruc-red">建议</span>
          <p class="text-xs font-ui text-ruc-text leading-relaxed mt-1">{{ card.text }}</p>
        </button>
      </div>
    </main>
  </div>
</template>
