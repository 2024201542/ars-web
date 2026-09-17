import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import type { WorkspaceFile } from '@/types'

export const useWorkspaceStore = defineStore('workspace', () => {
  const files = ref<WorkspaceFile[]>([])
  const loading = ref(false)

  async function loadFiles(sessionId: string) {
    loading.value = true
    try {
      const d = await api.listWorkspaceFiles(sessionId)
      files.value = d.data
    } catch { files.value = [] }
    finally { loading.value = false }
  }

  async function upload(sessionId: string, file: File) {
    const info = await api.uploadFile(sessionId, file)
    await loadFiles(sessionId)
    return info
  }

  async function remove(sessionId: string, filePath: string) {
    await api.deleteWorkspaceFile(sessionId, filePath)
    files.value = files.value.filter(f => f.path !== filePath)
  }

  async function refresh(sessionId: string) {
    try {
      const d = await api.refreshWorkspace(sessionId)
      files.value = d.data
    } catch { /* ignore */ }
  }

  return { files, loading, loadFiles, upload, remove, refresh }
})
