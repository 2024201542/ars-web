import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Session, Message } from '@/types'

export const useSessionStore = defineStore('session', () => {
  const currentSession = ref<Session | null>(null)
  const messages = ref<Message[]>([])
  const isStreaming = ref(false)
  const currentPhase = ref('')

  function setSession(session: Session) {
    currentSession.value = session
    messages.value = []
    currentPhase.value = ''
  }

  function addMessage(msg: Message) {
    messages.value.push(msg)
  }

  function setStreaming(val: boolean) {
    isStreaming.value = val
  }

  function setPhase(phase: string) {
    currentPhase.value = phase
  }

  function clearSession() {
    currentSession.value = null
    messages.value = []
    isStreaming.value = false
    currentPhase.value = ''
  }

  return { currentSession, messages, isStreaming, currentPhase, setSession, addMessage, setStreaming, setPhase, clearSession }
})
