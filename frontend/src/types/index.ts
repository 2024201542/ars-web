export interface Skill {
  name: string
  display_name: string
  description: string
  modes: string[]
  icon: string | null
}

export interface Mode {
  name: string
  display_name: string
  description: string
  phases: string[]
  estimated_time: string
  paper_types: string[]
}

export interface Session {
  id: string
  skill_name: string
  mode_name: string
  title: string | null
  status: string
  current_phase?: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: number
  session_id: string
  role: string
  content: string | null
  agent_name: string | null
  phase_name: string | null
  metadata: string | null
  created_at: string
  _streaming?: boolean
  _rawContent?: string
}

export interface Artifact {
  id: number
  session_id: string
  artifact_type: string
  content: string
  format: string
  created_at: string
}

export interface SessionDetail {
  session: Session
  messages: Message[]
  artifacts: Artifact[]
}

export interface ProviderInfo {
  id: string
  display_name: string
  protocol: string
  default_base_url: string | null
  key_setting: string
  base_url_setting: string
  key_configured: boolean
  base_url: string
}

export interface ModelInfo {
  id: string
  name: string
  provider: string
  provider_display_name: string
  protocol: string
  desc: string
}

export interface Settings {
  model: string
  providers: ProviderInfo[]
  anthropic_key_configured: boolean
}

export interface SSEEvent {
  event: string
  data: any
}

// ── Workspace types (session-scoped) ──

export interface WorkspaceFile {
  id: string
  name: string
  path: string          // relative path from session workspace root
  size_bytes: number
  modified_at: string
  ext: string           // e.g. ".md", ".csv", ".py"
  dir: string           // parent dir, e.g. "" or "uploads"
  columns?: string[]    // CSV column names
}
