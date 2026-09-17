import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('ars_token') || '')
  const user = ref<any>(null)
  const loading = ref(true)

  function setToken(t: string) {
    token.value = t
    localStorage.setItem('ars_token', t)
  }

  async function login(username: string, password: string) {
    const res = await api.login(username, password)
    setToken(res.token)
    user.value = res.user
  }

  async function checkAuth() {
    if (!token.value) { loading.value = false; return false }
    try {
      const res = await api.getMe()
      user.value = res.user
      loading.value = false
      return true
    } catch {
      logout()
      loading.value = false
      return false
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('ars_token')
  }

  return { token, user, loading, login, checkAuth, logout }
})
