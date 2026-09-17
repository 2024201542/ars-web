<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import { api } from '@/api'
import type { ProviderInfo, ModelInfo } from '@/types'
import {
  ArrowLeft, Eye, EyeOff, Check, Loader2, ShieldCheck, Sparkles, Key, Globe,
} from 'lucide-vue-next'

const router = useRouter()
const settings = useSettingsStore()
const toast = useToast()

const keyInputs = ref<Record<string, string>>({})
const showKey = ref<Record<string, boolean>>({})
const baseUrlInputs = ref<Record<string, string>>({})
const savingKey = ref<Record<string, boolean>>({})
const savingUrl = ref<Record<string, boolean>>({})
const savedKey = ref<Record<string, boolean>>({})
const activeTab = ref<string>('')

const RECOMMENDED_MODEL = 'deepseek-chat'

onMounted(async () => {
  await settings.load()
  for (const p of settings.providers) {
    keyInputs.value[p.id] = ''
    baseUrlInputs.value[p.id] = p.base_url || ''
  }
  if (settings.providers.length > 0) {
    const cfg = settings.providers.find(p => p.key_configured)
    activeTab.value = cfg?.id || settings.providers[0]?.id || ''
  }
})

function modelsByProvider(pid: string): ModelInfo[] { return settings.models.filter(m => m.provider === pid) }

async function saveProviderKey(pid: string) {
  const k = keyInputs.value[pid]?.trim(); if (!k) return
  savingKey.value[pid] = true
  try {
    await settings.saveKey(pid, k)
    keyInputs.value[pid] = ''
    savedKey.value[pid] = true; setTimeout(() => savedKey.value[pid] = false, 2000)
    toast.success('API Key 保存成功')
  } catch (e: any) { toast.error(e.message || '保存失败') }
  finally { savingKey.value[pid] = false }
}

async function saveProviderBaseUrl(pid: string) {
  savingUrl.value[pid] = true
  try { await settings.saveBaseUrl(pid, baseUrlInputs.value[pid]?.trim() || ''); toast.success('端点已更新') }
  catch (e: any) { toast.error(e.message || '保存失败') }
  finally { savingUrl.value[pid] = false }
}

async function handleModelChange(mid: string) { await settings.setModel(mid); toast.success('模型已切换') }
</script>

<template>
  <div class="min-h-screen flex flex-col">
    <header class="border-b border-ruc-divider bg-white/80 backdrop-blur-md sticky top-0 z-30">
      <div class="max-w-3xl mx-auto px-5 py-4 flex items-center gap-4">
        <button @click="router.push('/')" class="text-ruc-text-light hover:text-ruc-red transition-colors p-1.5 rounded-lg hover:bg-ruc-warm">
          <ArrowLeft class="w-5 h-5" />
        </button>
        <h1 class="text-ruc-red font-display text-xl font-semibold">设置</h1>
      </div>
    </header>

    <main class="flex-1 py-8 px-5">
      <div class="max-w-3xl mx-auto space-y-6">

        <!-- Provider Tab bar -->
        <div class="flex gap-1 bg-ruc-card rounded-xl p-1.5 border border-ruc-divider shadow-card overflow-x-auto">
          <button
            v-for="p in settings.providers" :key="p.id"
            @click="activeTab = p.id"
            class="flex-1 min-w-max px-4 py-2 rounded-lg text-sm font-ui font-medium transition-all duration-200 flex items-center justify-center gap-2"
            :class="activeTab === p.id
              ? 'bg-ruc-red-pale text-ruc-red shadow-sm border border-ruc-red/20'
              : 'text-ruc-text-dim hover:text-ruc-text hover:bg-ruc-bg'"
          >
            {{ p.display_name }}
            <span v-if="p.key_configured" class="dot-green" />
          </button>
        </div>

        <!-- Provider card -->
        <div v-for="p in settings.providers" v-show="activeTab === p.id" :key="p.id" class="card">
          <div class="flex items-start justify-between mb-5">
            <div>
              <h3 class="text-ruc-red font-display text-lg font-semibold flex items-center gap-2">
                {{ p.display_name }}
                <span v-if="p.id === 'deepseek'" class="badge-gold text-[11px]"><Sparkles class="w-3 h-3" />推荐</span>
              </h3>
              <p class="text-ruc-text-light text-xs font-ui mt-1.5 flex items-center gap-1.5">
                <Key class="w-3 h-3" />
                {{ p.protocol === 'openai' ? 'OpenAI 兼容' : 'Anthropic 协议' }}
                <template v-if="p.default_base_url"> · {{ p.default_base_url }}</template>
              </p>
            </div>
            <span v-if="p.key_configured" class="flex items-center gap-1.5 badge-success">
              <ShieldCheck class="w-3 h-3" /> 已配置
            </span>
          </div>

          <!-- API Key -->
          <div class="mb-4">
            <label class="text-ruc-text-dim text-xs font-ui font-medium mb-1.5 block">API Key</label>
            <div class="flex gap-2">
              <div class="flex-1 relative">
                <input
                  v-model="keyInputs[p.id]"
                  :type="showKey[p.id] ? 'text' : 'password'"
                  :placeholder="p.key_setting === 'deepseek_api_key' ? 'sk-...' : '输入 API Key...'"
                  class="input-field w-full !pr-10 text-sm font-mono"
                  @keydown.enter="saveProviderKey(p.id)"
                />
                <button @click="showKey[p.id] = !showKey[p.id]" class="absolute right-3 top-1/2 -translate-y-1/2 text-ruc-text-light hover:text-ruc-text p-1">
                  <EyeOff v-if="showKey[p.id]" class="w-4 h-4" />
                  <Eye v-else class="w-4 h-4" />
                </button>
              </div>
              <button
                @click="saveProviderKey(p.id)"
                :disabled="savingKey[p.id] || p.key_configured || !keyInputs[p.id]?.trim()"
                class="btn-primary text-sm flex items-center gap-1.5 h-10 px-4 flex-shrink-0"
              >
                <Loader2 v-if="savingKey[p.id]" class="w-3.5 h-3.5 animate-spin" />
                <Check v-else-if="savedKey[p.id]" class="w-3.5 h-3.5" />
                <span>{{ p.key_configured ? '已配置' : '保存' }}</span>
              </button>
            </div>
          </div>

          <!-- Base URL -->
          <div class="mb-4">
            <label class="text-ruc-text-dim text-xs font-ui font-medium mb-1.5 flex items-center gap-1.5">
              <Globe class="w-3 h-3" /> 自定义 API 端点 (可选)
            </label>
            <input
              v-model="baseUrlInputs[p.id]"
              type="text"
              :placeholder="p.default_base_url || 'https://api.anthropic.com'"
              class="input-field w-full text-sm font-mono"
              @blur="saveProviderBaseUrl(p.id)"
              @keydown.enter="saveProviderBaseUrl(p.id)"
            />
          </div>

          <!-- Models -->
          <div v-if="modelsByProvider(p.id).length" class="pt-4 border-t border-ruc-divider">
            <p class="text-ruc-text-dim text-xs font-ui font-medium mb-3">选择模型</p>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="m in modelsByProvider(p.id)" :key="m.id"
                @click="handleModelChange(m.id)"
                class="relative text-xs px-3 py-2 rounded-lg border transition-all duration-200"
                :class="settings.selectedModel === m.id
                  ? 'border-ruc-red/40 bg-ruc-red-pale text-ruc-red shadow-glow-sm'
                  : 'border-ruc-divider text-ruc-text-dim hover:border-ruc-red/20 hover:text-ruc-text hover:bg-ruc-warm'"
                :title="m.desc"
              >
                {{ m.name }}
                <span v-if="m.id === RECOMMENDED_MODEL" class="absolute -top-1.5 -right-1.5 badge-red text-[9px] !px-1.5 !py-0.5">荐</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Help -->
        <div class="card-flat">
          <h3 class="text-ruc-red font-display text-lg font-semibold mb-3">使用说明</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div class="flex items-start gap-3 p-3 rounded-lg bg-ruc-warm">
              <span class="w-6 h-6 rounded-full bg-ruc-red text-white text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">1</span>
              <p class="text-ruc-text text-sm font-ui">至少配置 DeepSeek（推荐）或其他提供商的 API Key</p>
            </div>
            <div class="flex items-start gap-3 p-3 rounded-lg bg-ruc-warm">
              <span class="w-6 h-6 rounded-full bg-ruc-red text-white text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">2</span>
              <p class="text-ruc-text text-sm font-ui">点击模型切换，对话将自动路由到对应 API</p>
            </div>
            <div class="flex items-start gap-3 p-3 rounded-lg bg-ruc-warm">
              <span class="w-6 h-6 rounded-full bg-ruc-red text-white text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">3</span>
              <p class="text-ruc-text text-sm font-ui">支持 Anthropic 协议和 OpenAI 兼容协议</p>
            </div>
            <div class="flex items-start gap-3 p-3 rounded-lg bg-ruc-warm">
              <span class="w-6 h-6 rounded-full bg-ruc-red text-white text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">4</span>
              <p class="text-ruc-text text-sm font-ui">Key 在服务器端加密存储，不会明文落盘</p>
            </div>
          </div>
        </div>

      </div>
    </main>
  </div>
</template>
