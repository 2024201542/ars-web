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

export interface DebateVoice {
  model: string
  name: string
  provider?: string
  provider_name?: string
  stance?: string
  round: number
  kind?: string
  thinking?: string
  answer?: string
  error?: string
}

export interface DebatePlan {
  topic: string
  stances?: Record<string, string>
}

export interface DebateSeat {
  model: string
  provider: string
  name?: string
  stance?: string
}

export interface DebatePayload {
  seats?: DebateSeat[]
  action?: string
  summarize_model?: string
  summarize_scope?: string
  summarize_pair?: string[]
  summarize_rounds?: number[]
  rounds?: number
  materials?: { name: string; path: string; source?: string }[]
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
  edits?: { backup_id: string; files: { path: string; name: string; action: string }[] } | null
  editsUndone?: boolean
  debate?: { voices: DebateVoice[] } | null
  debatePlan?: DebatePlan | null
  debateHold?: { name: string; model?: string; round?: number; between?: boolean } | null
  pipeline?: {
    index: number
    total: number
    group?: string
    label?: string
    file?: string
    folder?: string
    awaiting?: boolean
    done?: boolean
    next_label?: string
    need_folder?: boolean
  } | null
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
  key_unreadable?: boolean
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
  is_dir?: boolean
}
