<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/composables/useToast'
import { api } from '@/api'
import {
  ArrowLeft, Users, MessageSquare, Trash2, UserPlus, Shield, Clock, BarChart3,
} from 'lucide-vue-next'
import { SKILL_LABELS } from '@/utils/constants'

const router = useRouter()
const auth = useAuthStore()

const users = ref<any[]>([])
const stats = ref<any>({})
const selectedUserSessions = ref<any[]>([])
const selectedUserName = ref('')
const loading = ref(true)
const showNewUser = ref(false)
const newUsername = ref('')
const newPassword = ref('')
const activeTab = ref<'users' | 'overview'>('users')

onMounted(async () => {
  if (auth.user?.role !== 'admin') {
    toast.error('无权访问')
    router.push('/')
    return
  }
  await loadData()
})

async function loadData() {
  loading.value = true
  try {
    const [u, s] = await Promise.all([
      api.get('/admin/users'),
      api.get('/admin/stats'),
    ])
    users.value = u.data || []
    stats.value = s
  } catch { toast.error('加载失败') }
  finally { loading.value = false }
}

async function createUser() {
  const username = newUsername.value.trim()
  const password = newPassword.value.trim()
  if (!username) { toast.error('请填写用户名'); return }
  if (password.length < 4) { toast.error('密码至少 4 位'); return }
  try {
    await api.post('/admin/users', {
      username,
      password,
      display_name: username,
      role: 'user',
    })
    toast.success('用户已创建')
    newUsername.value = ''
    newPassword.value = ''
    showNewUser.value = false
    await loadData()
  } catch (e: any) { toast.error(e.message || '创建失败') }
}

async function deleteUser(id: string, name: string) {
  if (!confirm(`确定删除用户 ${name}？其所有会话和数据将被清除。`)) return
  try {
    await api.del(`/admin/users/${id}`)
    toast.success('已删除')
    await loadData()
  } catch (e: any) { toast.error(e.message || '删除失败') }
}

async function viewSessions(userId: string, userName: string) {
  try {
    const r = await api.get(`/admin/users/${userId}/sessions`)
    selectedUserSessions.value = r.data || []
    selectedUserName.value = userName
  } catch { toast.error('加载失败') }
}

function fmtDate(iso: string) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="min-h-screen flex flex-col bg-ruc-bg">
    <header class="border-b border-ruc-divider bg-white/90 backdrop-blur-md sticky top-0 z-30">
      <div class="max-w-6xl mx-auto px-5 py-4 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <button @click="router.push('/')" class="text-ruc-text-light hover:text-ruc-red p-1.5 rounded-lg hover:bg-ruc-warm transition-all">
            <ArrowLeft class="w-5 h-5" />
          </button>
          <h1 class="text-ruc-red font-display text-xl font-semibold">管理面板</h1>
          <span class="badge-red text-[10px]">管理员</span>
        </div>
        <div class="flex items-center gap-3">
          <span class="text-xs font-ui text-ruc-text-light">{{ auth.user?.display_name }}</span>
          <button @click="auth.logout(); router.push('/login')" class="btn-ghost text-sm">退出</button>
        </div>
      </div>
    </header>

    <main class="flex-1 py-8 px-5">
      <div class="max-w-6xl mx-auto">
        <!-- Stats -->
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <div class="card-flat flex items-center gap-4">
            <div class="w-10 h-10 rounded-xl bg-ruc-red-pale flex items-center justify-center"><Users class="w-5 h-5 text-ruc-red" /></div>
            <div><p class="text-xs font-ui text-ruc-text-light">用户总数</p><p class="text-xl font-display font-semibold text-ruc-text">{{ stats.user_count || 0 }}</p></div>
          </div>
          <div class="card-flat flex items-center gap-4">
            <div class="w-10 h-10 rounded-xl bg-ruc-red-pale flex items-center justify-center"><MessageSquare class="w-5 h-5 text-ruc-red" /></div>
            <div><p class="text-xs font-ui text-ruc-text-light">会话总数</p><p class="text-xl font-display font-semibold text-ruc-text">{{ stats.session_count || 0 }}</p></div>
          </div>
        </div>

        <!-- Tab bar -->
        <div class="flex gap-1 bg-white rounded-xl p-1.5 border border-ruc-divider shadow-card mb-6 w-fit">
          <button @click="activeTab = 'users'" class="px-4 py-2 rounded-lg text-sm font-ui font-medium transition-all"
            :class="activeTab === 'users' ? 'bg-ruc-red-pale text-ruc-red shadow-sm border border-ruc-red/20' : 'text-ruc-text-dim hover:text-ruc-text'">用户管理</button>
        </div>

        <!-- User Management -->
        <div v-if="activeTab === 'users'">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-lg font-display font-semibold text-ruc-text">用户列表</h2>
            <button @click="showNewUser = !showNewUser" class="btn-primary text-sm flex items-center gap-1.5">
              <UserPlus class="w-4 h-4" /> 创建用户
            </button>
          </div>

          <!-- New user form -->
          <div v-if="showNewUser" class="card mb-4 animate-fade-in">
            <div class="flex gap-3 items-end">
              <div class="flex-1">
                <label class="text-xs font-ui text-ruc-text-dim mb-1 block">用户名</label>
                <input v-model="newUsername" class="input-field w-full text-sm" placeholder="登录用户名" @keydown.enter="createUser" />
              </div>
              <div class="flex-1">
                <label class="text-xs font-ui text-ruc-text-dim mb-1 block">密码（至少4位）</label>
                <input v-model="newPassword" type="password" class="input-field w-full text-sm" placeholder="至少4位" @keydown.enter="createUser" />
              </div>
              <button @click="createUser" :disabled="!newUsername.trim() || newPassword.length < 4" class="btn-primary text-sm h-10 px-4">创建</button>
            </div>
          </div>

          <!-- User table -->
          <div class="card-flat overflow-hidden">
            <table class="w-full text-sm font-ui">
              <thead>
                <tr class="border-b border-ruc-divider text-left text-xs text-ruc-text-light uppercase tracking-wider">
                  <th class="px-4 py-3 font-medium">用户名</th>
                  <th class="px-4 py-3 font-medium">角色</th>
                  <th class="px-4 py-3 font-medium hidden sm:table-cell">创建时间</th>
                  <th class="px-4 py-3 font-medium hidden sm:table-cell">最后登录</th>
                  <th class="px-4 py-3 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ruc-divider">
                <tr v-for="u in users" :key="u.id" class="hover:bg-ruc-warm transition-colors">
                  <td class="px-4 py-3 font-medium text-ruc-text">{{ u.username }}</td>
                  <td class="px-4 py-3">
                    <span class="badge-red" v-if="u.role === 'admin'"><Shield class="w-3 h-3" /> 管理员</span>
                    <span class="badge-dim" v-else>用户</span>
                  </td>
                  <td class="px-4 py-3 text-ruc-text-light hidden sm:table-cell">{{ fmtDate(u.created_at) }}</td>
                  <td class="px-4 py-3 text-ruc-text-light hidden sm:table-cell">{{ fmtDate(u.last_login_at) }}</td>
                  <td class="px-4 py-3 text-right">
                    <button @click="viewSessions(u.id, u.username)" class="text-xs font-ui text-ruc-red hover:underline mr-3">查看会话</button>
                    <button v-if="u.id !== auth.user?.id" @click="deleteUser(u.id, u.username)" class="text-xs font-ui text-ruc-text-light hover:text-ruc-error" title="删除">
                      <Trash2 class="w-3.5 h-3.5 inline" />
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="users.length === 0" class="px-4 py-8 text-center text-ruc-text-light text-sm">暂无用户</div>
          </div>

          <!-- Selected user sessions -->
          <div v-if="selectedUserSessions.length > 0" class="mt-6">
            <h3 class="text-sm font-ui font-medium text-ruc-text mb-3 flex items-center gap-2">
              <MessageSquare class="w-4 h-4 text-ruc-red" />
              {{ selectedUserName }} 的会话 ({{ selectedUserSessions.length }})
            </h3>
            <div class="card-flat space-y-2">
              <div v-for="s in selectedUserSessions" :key="s.id" class="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-ruc-warm transition-colors">
                <div>
                  <p class="text-sm font-ui text-ruc-text">{{ s.title || '未命名' }}</p>
                  <div class="flex items-center gap-2 mt-1">
                    <span class="text-xs font-ui text-ruc-text-light">{{ SKILL_LABELS[s.skill_name] || s.skill_name }}</span>
                    <span class="text-xs font-ui text-ruc-text-light">· {{ s.mode_name }}</span>
                    <span class="text-xs font-ui text-ruc-text-light">· <Clock class="w-2.5 h-2.5 inline" /> {{ fmtDate(s.created_at) }}</span>
                  </div>
                </div>
                <span class="badge-dim" v-if="s.status === 'completed'">已完成</span>
                <span class="badge-dim" v-else>{{ s.status }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
