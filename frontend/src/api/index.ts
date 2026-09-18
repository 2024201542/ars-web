import type { Session, SessionDetail, Skill, Mode, Settings, ModelInfo, ProviderInfo, WorkspaceFile } from '@/types'

// 开发环境用 localhost:8000，部署时用相对路径 /api（由 nginx 反向代理）
const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

function getAuthHeaders(): Record<string, string> {
  const t = localStorage.getItem('ars_token')
  return t ? { Authorization: `Bearer ${t}` } : {}
}

function getAuthToken(): string {
  return localStorage.getItem('ars_token') || ''
}

/** 为 URL 附加 auth token（用于 img/iframe/a 等无法带 header 的场景） */
function withAuthToken(url: string): string {
  const token = getAuthToken()
  if (!token) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(token)}`
}

// 请求重试机制
async function requestWithRetry<T>(
  url: string, 
  options?: RequestInit, 
  retries = 3
): Promise<T> {
  const authHeaders = getAuthHeaders()
  const hasBody = options?.method && options.method !== 'GET' && options.method !== 'HEAD'
  
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`${BASE_URL}${url}`, {
        ...options,
        headers: {
          ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
          ...authHeaders,
          ...(options?.headers || {}),
        },
      })
      
      if (!res.ok) {
        let msg = `HTTP ${res.status}`
        try {
          const err = await res.json()
          if (typeof err.detail === 'string') msg = err.detail
          else if (Array.isArray(err.detail) && err.detail.length) {
            const d = err.detail[0]
            msg = d.msg || d.message || (d.loc ? `${d.loc.join('.')}: 参数无效` : msg)
            // 常见：body 缺失时提示更可读
            if (/field required/i.test(msg) || d.type === 'missing') {
              msg = '请求数据不完整，请检查用户名和密码是否已填写'
            }
          }
        } catch (e) { console.error("API error:", url, e) }
        
        // 5xx 错误才重试
        if (res.status >= 500 && i < retries - 1) {
          await new Promise(resolve => setTimeout(resolve, 1000 * (i + 1)))
          continue
        }
        
        throw new Error(msg)
      }
      
      if (res.status === 204) return undefined as T
      return res.json()
      
    } catch (error) {
      // 网络错误重试
      if (i < retries - 1) {
        console.warn(`请求失败，${i + 1}/${retries} 次重试:`, url)
        await new Promise(resolve => setTimeout(resolve, 1000 * (i + 1)))
        continue
      }
      throw error
    }
  }
  
  throw new Error('请求失败')
}

// 使用重试机制的请求函数
async function request<T>(url: string, options?: RequestInit): Promise<T> {
  return requestWithRetry<T>(url, options, 3)
}

export const api = {
  // Generic helper for admin
  get: <T=any>(url: string) => request<T>(url),
  post: <T=any>(url: string, body: any) => request<T>(url, { method: 'POST', body: JSON.stringify(body) }),
  del: <T=any>(url: string) => request<T>(url, { method: 'DELETE' }),

  // Auth
  login: (username: string, password: string) =>
    request<any>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  getMe: () => request<any>('/auth/me'),
  logout: () => request<any>('/auth/logout', { method: 'POST' }),

  // Skills
  getSkills: () => request<{ data: Skill[] }>('/skills'),
  getSkillModes: (name: string) => request<{ data: Mode[] }>(`/skills/${name}/modes`),
  getSkillConfig: (name: string) => request<any>(`/skills/${name}/config`),

  // Sessions
  createSession: (skill: string, mode: string, title?: string) =>
    request<Session>('/sessions', { method: 'POST', body: JSON.stringify({ skill_name: skill, mode_name: mode, title }) }),
  listSessions: (page = 1, limit = 50, skill?: string) =>
    request<any>(`/sessions?page=${page}&limit=${limit}${skill ? `&skill=${encodeURIComponent(skill)}` : ''}`),
  getSession: (id: string) => request<SessionDetail>(`/sessions/${id}`),
  deleteSession: (id: string) => request<void>(`/sessions/${id}`, { method: 'DELETE' }),
  updateSession: (id: string, title: string) =>
    request<Session>(`/sessions/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),

  // Chat (SSE)
  chatSSE: (sessionId: string, message: string, model?: string) => {
    const authHeaders = getAuthHeaders()
    return fetch(`${BASE_URL}/sessions/${sessionId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify({ message, model }),
    })
  },
  stopChat: (sessionId: string) => request<{ ok: boolean }>(`/sessions/${sessionId}/chat/stop`, { method: 'POST' }),

  // Export
  exportResult: (sessionId: string, format: string, scope = 'conversation') =>
    request<{ file_id: string; filename: string; status?: string; warning?: string; format?: string }>(
      `/sessions/${sessionId}/export`,
      { method: 'POST', body: JSON.stringify({ format, scope }) },
    ),
  createShare: (sessionId: string, expires_days = 7, include_files = false) =>
    request<{ token: string; url_path: string; expires_at: string; title: string; message_count: number }>(
      `/sessions/${sessionId}/share`,
      { method: 'POST', body: JSON.stringify({ expires_days, include_files }) },
    ),
  listShares: (sessionId: string) => request<{ data: any[] }>(`/sessions/${sessionId}/shares`),
  revokeShare: (token: string) => request<{ ok: boolean }>(`/shares/${token}`, { method: 'DELETE' }),
  getPublicShare: (token: string) => {
    const base = import.meta.env.VITE_API_BASE_URL || '/api'
    return fetch(`${base}/public/shares/${encodeURIComponent(token)}`).then(async (r) => {
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`)
      return body
    })
  },

  // Collab (异步交接)
  createCollabInvite: (sessionId: string, expires_days = 7) =>
    request<{ id: string; token: string; url_path: string; expires_at: string; title: string; root_session_id: string }>(
      `/sessions/${sessionId}/collab/invite`,
      { method: 'POST', body: JSON.stringify({ expires_days }) },
    ),
  previewCollabInvite: (token: string) => request<any>(`/collab/invites/${encodeURIComponent(token)}`),
  acceptCollabInvite: (token: string) =>
    request<{ handoff_id: string; session_id: string; skill_name?: string; already: boolean; status?: string; message?: string }>(
      `/collab/invites/${encodeURIComponent(token)}/accept`,
      { method: 'POST', body: JSON.stringify({}) },
    ),
  submitCollabReview: (sessionId: string, note = '') =>
    request<{ ok: boolean; handoff_id: string; message: string }>(
      `/sessions/${sessionId}/collab/submit`,
      { method: 'POST', body: JSON.stringify({ note }) },
    ),
  mergeCollabHandoff: (handoffId: string, mode: 'append_theirs' | 'keep_ours_only' | 'full_fork' = 'append_theirs') =>
    request<{ ok: boolean; root_session_id: string; skill_name?: string; message: string; mode?: string; three_way?: any }>(
      `/collab/handoffs/${handoffId}/merge`,
      { method: 'POST', body: JSON.stringify({ mode }) },
    ),
  rejectCollabHandoff: (handoffId: string, note = '') =>
    request<{ ok: boolean; message: string }>(
      `/collab/handoffs/${handoffId}/reject`,
      { method: 'POST', body: JSON.stringify({ note }) },
    ),
  revokeCollabInvite: (handoffId: string) =>
    request<{ ok: boolean }>(`/collab/handoffs/${handoffId}/revoke`, { method: 'POST', body: JSON.stringify({}) }),
  getCollabInbox: () =>
    request<{
      data: any[]
      review_count: number
      rejected_count: number
      turn_count?: number
      waiting_count?: number
      submitted_count?: number
      alert_count?: number
    }>('/collab/inbox'),
  getSessionCollab: (sessionId: string) => request<any>(`/sessions/${sessionId}/collab`),
  previewCollabHandoff: (handoffId: string) =>
    request<{
      handoff_id: string
      status: string
      note: string
      from_user: string
      fork_title: string
      diff_summary?: { same: number; added: number; removed: number; changed: number }
      three_way?: {
        root_diverged: boolean
        has_conflict: boolean
        ours_delta_count: number
        theirs_delta_count: number
        ours_delta: { role: string; content: string }[]
        theirs_delta: { role: string; content: string }[]
        hint: string
      }
      messages: {
        role: string
        author: string
        content: string
        created_at?: string
        change?: 'same' | 'added' | 'removed' | 'changed'
        lines?: { type: 'same' | 'add' | 'del'; text: string }[]
      }[]
    }>(`/collab/handoffs/${handoffId}/preview`),
  requestCollabEdit: (handoffId: string, force = false) =>
    request<{
      ok: boolean
      needs_confirm?: boolean
      has_local_changes?: boolean
      handoff_id: string
      partner_name?: string
      fork_session_id?: string
      stashed?: boolean
      message: string
    }>(
      `/collab/handoffs/${handoffId}/request-edit`,
      { method: 'POST', body: JSON.stringify({ force }) },
    ),
  getCollabForkDiff: (sessionId: string) =>
    request<{
      handoff_id: string
      status: string
      can_submit: boolean
      hint: string
      vs_baseline: any[]
      vs_baseline_summary: { same: number; added: number; removed: number; changed: number }
      vs_root: any[]
      vs_root_summary: { same: number; added: number; removed: number; changed: number }
      three_way?: any
    }>(`/sessions/${sessionId}/collab/diff-preview`),

  getExportUrl: (sessionId: string, fileId: string) =>
    withAuthToken(`${BASE_URL}/sessions/${sessionId}/exports/${fileId}`),

  // Settings
  getSettings: () => request<Settings>('/settings'),
  updateSettings: (data: Record<string, string>) =>
    request<{ ok: boolean }>('/settings', { method: 'PUT', body: JSON.stringify(data) }),

  // Models & Providers
  getModels: () => request<{ data: ModelInfo[] }>('/settings/models'),
  getProviders: () => request<{ data: ProviderInfo[] }>('/settings/providers'),

  // Workspace — Files (session-scoped)
  listWorkspaceFiles: (sessionId: string) =>
    request<{ data: WorkspaceFile[] }>(`/workspace/files?session_id=${encodeURIComponent(sessionId)}`),
  uploadFile: (sessionId: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    const authHeaders = getAuthHeaders()
    return fetch(`${BASE_URL}/workspace/files?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
      headers: authHeaders,
      body: fd,
    }).then(r => r.ok ? r.json() as Promise<WorkspaceFile> : r.json().then(e => { throw new Error(e.detail) }))
  },
  getFileContent: (sessionId: string, path: string) =>
    request<{ content: string; path: string }>(`/workspace/files/content?session_id=${encodeURIComponent(sessionId)}&path=${encodeURIComponent(path)}`),
  getFileDownloadUrl: (sessionId: string, path: string) =>
    withAuthToken(`${BASE_URL}/workspace/files/download?session_id=${encodeURIComponent(sessionId)}&path=${encodeURIComponent(path)}`),
  getFilePreviewUrl: (sessionId: string, path: string) =>
    withAuthToken(`${BASE_URL}/workspace/files/preview?session_id=${encodeURIComponent(sessionId)}&path=${encodeURIComponent(path)}`),
  deleteWorkspaceFile: (sessionId: string, path: string) =>
    request<void>(`/workspace/files?session_id=${encodeURIComponent(sessionId)}&path=${encodeURIComponent(path)}`, { method: 'DELETE' }),
  refreshWorkspace: (sessionId: string) =>
    request<{ data: WorkspaceFile[] }>(`/workspace/refresh?session_id=${encodeURIComponent(sessionId)}`, { method: 'POST' }),
}
