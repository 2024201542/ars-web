import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { SKILL_ROUTES } from '@/utils/constants'
import { findStart, DEFAULT_START_ID } from '@/utils/startOptions'

export function useNewChat() {
  const router = useRouter()
  const sessionStore = useSessionStore()
  const toast = useToast()
  const creating = ref(false)

  async function goNew(activeSessionId?: string) {
    if (creating.value) return
    const current = sessionStore.currentSession
    const alreadyEmpty = Boolean(
      current
      && activeSessionId
      && activeSessionId === current.id
      && current.title === '新对话'
      && sessionStore.messages.length === 0,
    )
    if (alreadyEmpty) return
    const option = findStart(DEFAULT_START_ID)
    creating.value = true
    try {
      const session = await api.createSession(option.skill, option.mode, '新对话')
      const name = SKILL_ROUTES[option.skill] || 'paper'
      await router.push(`/session/${session.id}/${name}`)
    } catch (err: any) {
      toast.error('新建失败：' + (err.message || ''))
    } finally {
      creating.value = false
    }
  }

  return { creating, goNew }
}
