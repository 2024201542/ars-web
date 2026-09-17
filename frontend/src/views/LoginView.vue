<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/composables/useToast'
import { LogIn } from 'lucide-vue-next'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const submitting = ref(false)

async function handleSubmit() {
  if (!username.value.trim() || !password.value.trim()) {
    toast.warning('请填写用户名和密码')
    return
  }
  submitting.value = true
  try {
    await auth.login(username.value.trim(), password.value.trim())
    router.push('/')
  } catch (e: any) {
    toast.error(e.message || String(e) || '登录失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-ruc-bg px-4">
    <div class="w-full max-w-sm animate-fade-in">
      <div class="text-center mb-8">
        <div class="logo-mark w-14 h-14 mx-auto mb-4">
          <span class="logo-mark-text">A</span>
        </div>
        <h1 class="text-2xl font-display font-semibold text-ruc-red">ARS Web</h1>
        <p class="text-ruc-text-light text-sm font-ui mt-1">学术研究助手</p>
      </div>

      <div class="card">
        <h2 class="text-lg font-display font-semibold text-ruc-red mb-5 text-center">登录</h2>

        <div class="space-y-3 mb-4">
          <input v-model="username" type="text" placeholder="用户名" class="input-field w-full text-sm" @keydown.enter="handleSubmit" />
          <input v-model="password" type="password" placeholder="密码" class="input-field w-full text-sm" @keydown.enter="handleSubmit" />
        </div>

        <button @click="handleSubmit" :disabled="submitting" class="btn-primary w-full flex items-center justify-center gap-2">
          <LogIn class="w-4 h-4" />
          {{ submitting ? '登录中...' : '登录' }}
        </button>
      </div>

      <p class="text-center mt-4 text-xs font-ui text-ruc-text-light">
        请联系管理员获取账号
      <div class="card mt-3 text-center animate-fade-in"><p class="text-xs font-ui text-ruc-text-dim mb-2">📖 首次使用？</p><p class="text-xs font-ui text-ruc-text-light">1️⃣ 管理员创建账号 2️⃣ 登录后配置 API Key 3️⃣ 选择技能开始研究</p></div>
      </p>
    </div>
  </div>
</template>
