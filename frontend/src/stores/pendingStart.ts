import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface PendingStart {
  sessionId: string
  message: string
  files: File[]
}

const STORAGE_KEY = 'ars-pending-start'

/** 首页按下发送后，把第一句话带到新建的会话里自动发出。 */
export const usePendingStartStore = defineStore('pendingStart', () => {
  const job = ref<PendingStart | null>(null)

  function set(sessionId: string, message: string, files: File[]) {
    job.value = { sessionId, message, files }
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ sessionId, message }))
    } catch { /* 忽略隐私模式写失败 */ }
  }

  function consume(sessionId: string): PendingStart | null {
    let current = job.value
    if (!current || current.sessionId !== sessionId) {
      try {
        const raw = sessionStorage.getItem(STORAGE_KEY)
        if (raw) {
          const parsed = JSON.parse(raw) as { sessionId?: string; message?: string }
          if (parsed.sessionId === sessionId) {
            current = { sessionId, message: parsed.message || '', files: [] }
          }
        }
      } catch { /* 忽略损坏的暂存 */ }
    }
    if (!current || current.sessionId !== sessionId) return null
    if (!current.message && !current.files.length) return null
    job.value = null
    try { sessionStorage.removeItem(STORAGE_KEY) } catch { /* ignore */ }
    return current
  }

  return { set, consume }
})
