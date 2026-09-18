import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import type { ModelInfo, ProviderInfo } from '@/types'

export const useSettingsStore = defineStore('settings', () => {
  const selectedModel = ref<string | null>(null)
  const isConfigured = ref(false)
  const loaded = ref(false)
  const models = ref<ModelInfo[]>([])
  const providers = ref<ProviderInfo[]>([])

  /** 当前选中模型对应的 provider 信息 */
  const currentProvider = computed(() => {
    const m = models.value.find(m => m.id === selectedModel.value)
    return providers.value.find(p => p.id === (m?.provider || ''))
  })

  async function load() {
    try {
      const [settings, modelData, providerData] = await Promise.all([
        api.getSettings(),
        api.getModels(),
        api.getProviders(),
      ])

      // 合并两个 provider 数据源：
      // - providerData（/api/providers）有 key_setting/base_url_setting + key_configured
      // - settings.providers（/api/settings）有 key_configured/base_url（在线值）
      // 以前者为基础，后者覆盖 key_configured / base_url 确保准确性
      const settingsProviders = settings.providers as ProviderInfo[] || []
      const settingsMap = Object.fromEntries(settingsProviders.map(p => [p.id, p]))
      providers.value = (providerData.data || []).map(p => {
        const sp = settingsMap[p.id]
        if (!sp) return p
        return { ...p, key_configured: sp.key_configured, base_url: sp.base_url || p.base_url }
      })

      if (settings.model) selectedModel.value = settings.model
      models.value = modelData.data
      isConfigured.value = providers.value.some(p => p.key_configured)
      loaded.value = true
    } catch {
      loaded.value = true
    }
  }

  async function saveKey(providerId: string, key: string) {
    const prov = providers.value.find(p => p.id === providerId)
    if (!prov) return
    await api.updateSettings({ [prov.key_setting]: key })
    // 本地乐观更新
    prov.key_configured = !!key
    isConfigured.value = providers.value.some(p => p.key_configured)

    // 当前模型所属提供商若未配 Key，自动切到刚保存的提供商的第一个模型
    // （否则聊天仍走默认 deepseek-chat，后端会报「尚未配置 DeepSeek」）
    const cur = models.value.find(m => m.id === selectedModel.value)
    const curOk = cur && providers.value.find(p => p.id === cur.provider)?.key_configured
    if (!curOk) {
      const first = models.value.find(m => m.provider === providerId)
      if (first) await setModel(first.id)
    }
  }

  async function saveBaseUrl(providerId: string, url: string) {
    const prov = providers.value.find(p => p.id === providerId)
    if (!prov) return
    await api.updateSettings({ [prov.base_url_setting]: url })
    prov.base_url = url
  }

  async function setModel(model: string) {
    selectedModel.value = model
    await api.updateSettings({ model })
  }

  return {
    selectedModel, isConfigured, loaded, models, providers, currentProvider,
    load, saveKey, saveBaseUrl, setModel,
  }
})
