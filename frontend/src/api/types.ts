export interface User {
  id: number
  email: string
  name: string
  role: 'admin' | 'member'
  is_active: boolean
  permissions: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface Project {
  id: number
  name: string
  description: string
  members: string
  owner_id: number
  created_at: string
  current_user_role: 'owner' | 'editor' | 'viewer'
}

export interface ProjectMember {
  id: number
  project_id: number
  user_id: number
  email: string
  name: string
  role: 'owner' | 'editor' | 'viewer'
  created_at: string
}

export interface Agent {
  id: number
  name: string
  role: string
  description: string
  system_prompt: string
  model: string
  tools: string
  memory_enable: boolean
  knowledge_access: boolean
  human_approval_required: boolean
}

export interface AgentTool {
  id: number
  agent_id: number
  name: string
  description: string
  enabled: boolean
  allowed_roles: string
}

export interface AgentAction {
  id: number
  user_id: number
  project_id?: number | null
  agent_id: number
  conversation_id?: number | null
  tool_name: string
  input_json: string
  result_json: string
  status: 'PENDING' | 'EXECUTED' | 'REJECTED'
  approved_by_user_id?: number | null
  created_at: string
  decided_at?: string | null
}

export interface Conversation {
  id: number
  title: string
  project_id?: number | null
  agent_id: number
  user_id: number
  created_at: string
}

export interface ChatMessage {
  id?: number
  conversation_id?: number
  role: string
  content: string
  thinking?: string
  tool_calls?: string
  created_at?: string
}

export interface Task {
  id: number
  project_id: number
  title: string
  description: string
  priority: string
  status: string
  assignee_agent_id?: number | null
  due_date: string
  created_at: string
  updated_at: string
}

export interface KnowledgeDocument {
  id: number
  project_id?: number | null
  filename: string
  content_type: string
  status: string
  summary: string
  created_at: string
}

export interface DashboardStats {
  projects: number
  agents: number
  tasks: Record<string, number>
  documents: number
  recent_activities: string[]
}

export interface Meeting {
  id: number
  project_id?: number | null
  title: string
  transcript: string
  summary: string
  action_items: string
  created_at: string
}

export interface Report {
  id: number
  project_id: number
  report_type: string
  title: string
  content: string
  created_at: string
}

export interface NotificationItem {
  id: number
  project_id?: number | null
  title: string
  content: string
  channel: string
  schedule_at: string
  recipient_user_id?: number | null
  recipient_email: string
  scheduled_for?: string | null
  status: string
  attempts: number
  sent_at?: string | null
  last_error: string
  created_at: string
}

export interface SystemSetting {
  provider: string
  base_url: string
  model: string
  embedding_model: string
  milvus_collection: string
  environment: string
  allow_registration: boolean
  registration_email_domains: string[]
}

export interface Requirement {
  id: number
  project_id?: number | null
  title: string
  content: string
  status: string
  analysis: string
  created_at: string
}

export interface GlobalSearchResult {
  type: string
  title: string
  description: string
  url: string
}

export interface AuditLog {
  id: number
  user_id?: number | null
  project_id?: number | null
  action: string
  resource_type: string
  resource_id: string
  details: string
  ip_address: string
  created_at: string
}
