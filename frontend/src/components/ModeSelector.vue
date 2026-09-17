<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '@/api'
import { SKILL_LABELS } from '@/utils/constants'
import type { Skill, Mode } from '@/types'
import { X, Search, Sparkles } from 'lucide-vue-next'

const props = defineProps<{ skill: Skill }>()
const emit = defineEmits<{ select: [mode: Mode]; close: [] }>()

const modes = ref<Mode[]>([])
const loading = ref(true)
const query = ref('')
const error = ref('')

onMounted(async () => {
  try {
    const data = await api.getSkillModes(props.skill.name)
    modes.value = data.data
  } catch (e: any) {
    error.value = '加载模式失败：' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
})

const filteredModes = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return modes.value
  return modes.value.filter(m =>
    m.display_name.toLowerCase().includes(q) ||
    m.description.toLowerCase().includes(q) ||
    m.phases.some(p => p.toLowerCase().includes(q)),
  )
})

// 推荐模式：第一个 full 模式，没有则取第一个
const recommendedName = computed(() => {
  const full = modes.value.find(m => m.name === 'full')
  return full?.name || modes.value[0]?.name || ''
})
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @click.self="emit('close')">
    <div class="bg-ruc-card border border-ruc-divider rounded-lg w-full max-w-lg max-h-[85vh] flex flex-col shadow-modal">
      <!-- Header -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-ruc-divider flex-shrink-0">
        <h2 class="text-ruc-red font-display text-lg font-semibold">
          {{ SKILL_LABELS[skill.name] || skill.name }}
          <span class="text-ruc-text-dim font-ui text-sm font-normal ml-2">选择模式</span>
        </h2>
        <button
          @click="emit('close')"
          class="text-ruc-text-dim hover:text-ruc-text transition-colors p-1"
        >
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- 搜索框 -->
      <div v-if="modes.length >= 5" class="px-6 pt-3 flex-shrink-0">
        <div class="relative">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ruc-text-dim" />
          <input
            v-model="query"
            type="text"
            placeholder="搜索模式..."
            class="input-field w-full !pl-10 text-sm"
          />
        </div>
      </div>

      <!-- Content -->
      <div class="flex-1 overflow-y-auto px-6 py-4">
        <div v-if="loading" class="flex items-center justify-center py-12">
          <div class="w-8 h-8 border-2 border-ruc-red/30 border-t-ruc-red rounded-full animate-spin" />
        </div>

        <div v-else-if="error" class="text-center py-8 text-ruc-error font-ui text-sm">
          {{ error }}
        </div>

        <div v-else-if="filteredModes.length === 0" class="text-center py-8 text-ruc-text-dim font-ui text-sm">
          未找到匹配 "{{ query }}" 的模式
        </div>

        <div v-else class="space-y-2.5">
          <div
            v-for="mode in filteredModes"
            :key="mode.name"
            @click="emit('select', mode)"
            class="p-4 rounded-lg border cursor-pointer transition-all duration-200 group relative"
            :class="mode.name === recommendedName
              ? 'border-ruc-red/30 hover:border-ruc-red/60 hover:bg-ruc-red/10'
              : 'border-ruc-divider hover:border-ruc-red/30 hover:bg-ruc-red/5'"
          >
            <!-- 推荐标记 -->
            <span
              v-if="mode.name === recommendedName"
              class="absolute top-2 right-3 text-[10px] px-2 py-0.5 rounded-full font-ui border
                     border-ruc-red/30 text-ruc-red bg-ruc-red/10 flex items-center gap-1"
            >
              <Sparkles class="w-3 h-3" />
              推荐
            </span>

            <div class="flex items-center justify-between mb-2 pr-16">
              <h3 class="text-ruc-red font-ui font-medium group-hover:text-ruc-red-light transition-colors">
                {{ mode.display_name }}
              </h3>
              <span class="text-ruc-text-dim text-xs font-ui">{{ mode.estimated_time }}</span>
            </div>
            <p class="text-ruc-text-dim text-sm font-ui leading-relaxed pr-4">{{ mode.description }}</p>

            <!-- 阶段标签：全部显示，使用 flexible wrap -->
            <div class="flex flex-wrap gap-1.5 mt-3">
              <span
                v-for="phase in mode.phases"
                :key="phase"
                class="text-xs text-ruc-text-dim bg-ruc-bg/60 px-2 py-0.5 rounded-lg font-ui border border-ruc-divider"
              >
                {{ phase }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="px-6 py-3 border-t border-ruc-divider flex-shrink-0">
        <p class="text-ruc-text-dim text-xs font-ui">
          共 {{ modes.length }} 种模式 · 点击即可开始
        </p>
      </div>
    </div>
  </div>
</template>
