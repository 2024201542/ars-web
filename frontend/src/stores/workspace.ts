import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import type { WorkspaceFile } from '@/types'

type RootInfo = { source?: 'site' | 'local' | 'none'; label?: string; path?: string; truncated?: boolean }

export const useWorkspaceStore = defineStore('workspace', () => {
  const files = ref<WorkspaceFile[]>([])
  const loading = ref(false)
  const source = ref<'site' | 'local' | 'none'>('none')
  const rootLabel = ref('项目文件')
  const rootPath = ref('')
  const truncated = ref(false)

  function apply(data: { data?: WorkspaceFile[]; root?: RootInfo } | null) {
    files.value = data?.data || []
    source.value = data?.root?.source === 'local' ? 'local' : data?.root?.source === 'site' ? 'site' : 'none'
    rootLabel.value = data?.root?.label || '项目文件'
    rootPath.value = data?.root?.path || ''
    truncated.value = !!data?.root?.truncated
  }

  async function loadFiles(sessionId: string) {
    loading.value = true
    try {
      apply(await api.listWorkspaceFiles(sessionId))
    } catch { files.value = [] }
    finally { loading.value = false }
  }

  async function upload(sessionId: string, file: File, relativePath?: string) {
    const info = await api.uploadFile(sessionId, file, relativePath, source.value)
    await loadFiles(sessionId)
    return info
  }

  async function remove(sessionId: string, filePath: string) {
    await api.deleteWorkspaceFile(sessionId, filePath, source.value)
    const prefix = `${filePath}/`
    files.value = files.value.filter(f => f.path !== filePath && !f.path.startsWith(prefix))
  }

  async function refresh(sessionId: string) {
    try {
      apply(await api.refreshWorkspace(sessionId))
    } catch { /* ignore */ }
  }

  async function openFolder(sessionId: string, path = '') {
    const info = await api.openLocalFolder(sessionId, path)
    if (!info.cancelled) await loadFiles(sessionId)
    return info
  }

  async function closeFolder(sessionId: string) {
    apply(await api.closeLocalFolder(sessionId))
  }

  async function createFile(sessionId: string, kind: string, directory = '') {
    const info = await api.createWorkspaceFile(sessionId, { kind, directory, source: source.value })
    await loadFiles(sessionId)
    return info
  }

  async function createDirectory(sessionId: string, name: string, directory = '') {
    const info = await api.createWorkspaceDir(sessionId, { name, directory, source: source.value })
    await loadFiles(sessionId)
    return info
  }

  async function rename(sessionId: string, path: string, name: string) {
    const info = await api.renameWorkspaceFile(sessionId, { path, name, source: source.value })
    await loadFiles(sessionId)
    return info
  }

  return {
    files, loading, source, rootLabel, rootPath, truncated,
    loadFiles, upload, remove, refresh, openFolder, closeFolder, createFile, createDirectory, rename,
  }
})
