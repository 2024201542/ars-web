<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { SKILL_ROUTES, SKILL_LABELS } from '@/utils/constants'
import { toast } from '@/composables/useToast'
import { Loader2, Users, AlertTriangle, CheckCircle2 } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const token = computed(() => String(route.params.token || ''))

const loading = ref(true)
const accepting = ref(false)
const error = ref('')
const data = ref<any>(null)

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.previewCollabInvite(token.value)
  } catch (e: any) {
    error.value = e.message || '无法打开邀请'
  } finally {
    loading.value = false
  }
}

async function accept() {
  accepting.value = true
  try {
    const r = await api.acceptCollabInvite(token.value)
    toast.success(r.message || (r.already ? '已打开你的接续副本' : '已创建接续副本，可以继续修改'))
    const skill = r.skill_name || data.value?.skill_name || 'deep-research'
    const routeName = SKILL_ROUTES[skill] || 'research'
    router.replace(`/session/${r.session_id}/${routeName}`)
  } catch (e: any) {
    toast.error(e.message || '接受失败')
  } finally {
    accepting.value = false
  }
}

function goFork() {
  if (!data.value?.fork_session_id) return
  const skill = data.value?.skill_name || 'deep-research'
  const routeName = SKILL_ROUTES[skill] || 'research'
  router.replace(`/session/${data.value.fork_session_id}/${routeName}`)
}
</script>

<template>
  <div class="min-h-screen bg-ruc-bg flex items-start justify-center px-4 py-10">
    <div class="w-full max-w-lg">
      <div v-if="loading" class="card text-center py-12 text-ruc-text-dim flex items-center justify-center gap-2">
        <Loader2 class="w-5 h-5 animate-spin" /> 加载邀请…
      </div>

      <div v-else-if="error" class="card text-center py-10">
        <AlertTriangle class="w-8 h-8 text-ruc-error mx-auto mb-3" />
        <p class="text-ruc-text font-ui mb-2">{{ error }}</p>
        <button class="btn-secondary text-sm mt-2" @click="router.push('/')">返回首页</button>
      </div>

      <div v-else class="card space-y-4 animate-fade-in">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-xl bg-ruc-red-pale flex items-center justify-center flex-shrink-0">
            <Users class="w-5 h-5 text-ruc-red" />
          </div>
          <div class="min-w-0">
            <p class="text-xs font-ui text-ruc-text-light">协作邀请 · 发给你继续</p>
            <h1 class="text-lg font-display font-semibold text-ruc-red truncate">{{ data.title }}</h1>
            <p class="text-xs font-ui text-ruc-text-dim mt-1">
              来自 {{ data.from_user }}
              <span v-if="data.skill_name"> · {{ SKILL_LABELS[data.skill_name] || data.skill_name }}</span>
              <span> · {{ data.message_count }} 条消息</span>
            </p>
          </div>
        </div>

        <p class="text-sm font-ui text-ruc-text-dim leading-relaxed">
          接受后会在你的账号下生成可写副本，并出现在对方的协作列表里。改完后在会话里点「协作 → 交回审阅」。之后对方可直接「请你继续」，不必再发新链接。
        </p>

        <div v-if="data.preview_messages?.length" class="rounded-xl bg-ruc-bg border border-ruc-divider p-3 space-y-2 max-h-48 overflow-y-auto">
          <p class="text-[11px] font-ui text-ruc-text-light">对话预览（节选）</p>
          <div v-for="(m, i) in data.preview_messages" :key="i" class="text-xs font-ui text-ruc-text">
            <span class="text-ruc-text-light">{{ m.role === 'user' ? '提问' : '回答' }}：</span>
            {{ m.content }}
          </div>
        </div>

        <div v-if="data.is_own_invite" class="text-xs font-ui text-ruc-error bg-ruc-error-soft rounded-lg px-3 py-2">
          这是你自己发出的邀请。请用另一个账号登录后再打开此链接。
        </div>

        <div v-else-if="data.already_accepted_by_me" class="space-y-2">
          <p class="text-xs font-ui text-ruc-success flex items-center gap-1">
            <CheckCircle2 class="w-3.5 h-3.5" /> 你已接受过，可直接打开副本
          </p>
          <button class="w-full btn-primary text-sm py-2.5" @click="goFork">打开我的接续副本</button>
        </div>

        <div v-else-if="data.status === 'invite_pending'" class="space-y-2">
          <button class="w-full btn-primary text-sm py-2.5" :disabled="accepting" @click="accept">
            <Loader2 v-if="accepting" class="w-4 h-4 animate-spin inline mr-1" />
            接受并继续编辑
          </button>
          <button class="w-full btn-ghost text-sm" @click="router.push('/')">稍后再说</button>
        </div>

        <div v-else class="text-xs font-ui text-ruc-text-dim">
          当前状态：{{ data.status }}（可能已被接受或已结束）
        </div>
      </div>
    </div>
  </div>
</template>
