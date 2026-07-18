export interface User {
  id: number
  email: string
  name: string
  role: 'admin' | 'member'
  is_active: boolean
  permissions: string
  ai_token_balance: number
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
  status: 'ACTIVE' | 'ARCHIVED'
  created_at: string
  updated_at: string
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
  concurrency_limit: number
  current_version: number
}

export interface AgentVersion {
  id: number
  agent_id: number
  version: number
  status: 'DRAFT' | 'PUBLISHED' | 'ARCHIVED'
  description: string
  system_prompt: string
  model: string
  memory_enable: boolean
  knowledge_access: boolean
  human_approval_required: boolean
  concurrency_limit: number
  release_note: string
  created_by_user_id?: number | null
  created_at: string
  published_at?: string | null
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
  mode: 'SINGLE' | 'TEAM'
  created_at: string
}

export interface ChatMessage {
  id?: number
  conversation_id?: number
  agent_id?: number | null
  role: string
  stage?: string
  content: string
  thinking?: string
  tool_calls?: string
  parent_message_id?: number | null
  regenerated_from_id?: number | null
  feedback?: 1 | -1 | null
  created_at?: string
  client_id?: string
}

export interface Task {
  id: number
  project_id: number
  title: string
  description: string
  priority: string
  status: string
  assignee_agent_id?: number | null
  assignee_user_id?: number | null
  due_date: string
  due_at?: string | null
  source_prototype_id?: number | null
  source_prototype_version?: number | null
  source_screen_id?: string | null
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
  source_label: string
  metadata_json: string
  version: number
  attempts: number
  max_attempts: number
  error: string
  indexed_at?: string | null
  active_index_version: number
  pending_index_version?: number | null
  parser_name: string
  parser_version: string
  chunker_name: string
  chunker_version: string
  element_count: number
  chunk_count: number
  index_config_json: string
  created_at: string
  updated_at: string
}

export interface KnowledgeIndexVersion {
  version: number
  status: string
  parser_name: string
  parser_version: string
  chunker_name: string
  chunker_version: string
  embedding_model: string
  embedding_dimensions: number
  element_count: number
  chunk_count: number
  config_json: string
  error: string
  activated_at?: string | null
  created_at: string
  updated_at: string
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
  updated_at: string
}

export interface Report {
  id: number
  project_id: number
  report_type: string
  title: string
  content: string
  created_at: string
  updated_at: string
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

export interface SystemSettingItem {
  key: string
  label: string
  category: string
  value: unknown
  value_type: 'str' | 'int' | 'float' | 'bool' | 'list'
  minimum?: number | null
  maximum?: number | null
  secret: boolean
  configured: boolean
  source: string
  restart_required: boolean
  updated_at?: string | null
}

export interface SystemSettings {
  environment: string
  items: SystemSettingItem[]
}

export interface Requirement {
  id: number
  project_id?: number | null
  title: string
  content: string
  status: string
  analysis: string
  created_at: string
  updated_at: string
}

export interface TaskComment {
  id: number
  task_id: number
  user_id: number
  user_name: string
  content: string
  created_at: string
}

export interface ProjectActivity {
  id: number
  action: string
  resource_type: string
  resource_id: string
  details: string
  user_id?: number | null
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

export interface TokenTransaction {
  id: number
  user_id: number
  amount: number
  balance_after: number
  transaction_type: string
  reference_type: string
  reference_id: string
  description: string
  created_at: string
}

export interface Wallet {
  balance: number
  chat_cost: number
  workflow_cost: number
  recharge_tokens_per_yuan: number
  fake_recharge: boolean
  transactions: TokenTransaction[]
}

export interface LLMUsage {
  id: number
  user_id?: number | null
  project_id?: number | null
  agent_id?: number | null
  workflow_id?: number | null
  agent_run_id?: number | null
  operation: string
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  estimated_cost_micros: number
  latency_ms: number
  usage_source: string
  created_at: string
}

export interface EvaluationCase {
  id: number
  name: string
  agent_role: string
  input_text: string
  expected_keywords: string[]
  enabled: boolean
  created_at: string
}

export interface EvaluationRun {
  id: number
  status: string
  total_cases: number
  passed_cases: number
  average_score: number
  created_at: string
  finished_at?: string | null
}

export interface RechargeOrder {
  id: number
  order_no: string
  user_id: number
  amount_cents: number
  token_amount: number
  status: string
  created_at: string
  paid_at?: string | null
}

export interface WorkflowRun {
  workflow_id: number
  project_id: number
  status: string
  current_node: string
  state: Record<string, unknown>
  attempt_count: number
  max_attempts: number
  error: string
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
}

export interface WorkflowEvent {
  id: number
  workflow_id: number
  node: string
  event_type: string
  message: string
  payload: Record<string, unknown>
  created_at: string
}

export interface WorkflowSagaStep {
  id: number
  workflow_id: number
  sequence: number
  node: string
  tool_name: string
  compensation_action: string
  idempotency_key: string
  status: string
  input_json: string
  output_json: string
  transition_log_json: string
  execute_attempts: number
  compensation_attempts: number
  error: string
  started_at?: string | null
  completed_at?: string | null
  compensated_at?: string | null
  created_at: string
  updated_at: string
}

export type PrototypeComponentType =
  | 'heading'
  | 'text'
  | 'input'
  | 'textarea'
  | 'select'
  | 'button'
  | 'link'
  | 'stepper'
  | 'stats'
  | 'callout'
  | 'table'
  | 'tabs'
  | 'list'
  | 'divider'

export interface PrototypeAction {
  type: 'navigate' | 'toast' | 'submit' | 'copy' | 'advance_step' | 'back'
  target?: string | null
  message?: string | null
}

export interface PrototypeOption {
  label: string
  value: string
}

export interface PrototypeComponentSpec {
  id: string
  type: PrototypeComponentType
  label: string
  text: string
  placeholder: string
  value: string
  variant: 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'danger'
  required: boolean
  disabled: boolean
  options: PrototypeOption[]
  items: Record<string, unknown>[]
  columns: string[]
  steps: string[]
  active_step: number
  action?: PrototypeAction | null
}

export interface PrototypeSection {
  id: string
  title: string
  description: string
  width: 'narrow' | 'medium' | 'wide' | 'full'
  components: PrototypeComponentSpec[]
}

export interface PrototypeScreen {
  id: string
  name: string
  description: string
  layout: 'auth' | 'app' | 'dashboard' | 'form' | 'list'
  sections: PrototypeSection[]
}

export interface PrototypeSpecification {
  product_name: string
  summary: string
  start_screen_id: string
  theme: {
    primary: string
    accent: string
    background: string
    surface: string
    foreground: string
    radius: 'compact' | 'soft' | 'rounded'
  }
  screens: PrototypeScreen[]
}

export interface PrototypeQualityCheck {
  name: string
  passed: boolean
  detail: string
}

export interface PrototypeQuality {
  score: number
  passed: boolean
  checks: PrototypeQualityCheck[]
  issues: string[]
  reviewer_summary?: string
  reviewer_score?: number
  reviewer_passed?: boolean
  repair_rounds?: number
  review_contract_repairs?: number
  deterministic_repairs?: number
}

export interface PrototypeAgentTrace {
  role: string
  agent_id: number | null
  name: string
  model: string
  prompt_version?: number
  output: string
  stage?: 'product_definition' | 'architecture' | 'architecture_repair' | 'deterministic_repair' | 'quality_review' | 'quality_review_repair'
  round?: number
  fallback?: boolean
  contract_repair?: number
}

export interface PrototypeVersion {
  id: number
  version: number
  source_prompt: string
  specification: PrototypeSpecification
  agent_trace: PrototypeAgentTrace[]
  quality: PrototypeQuality
  generation_mode: string
  created_by_user_id: number
  created_at: string
}

export interface ProductPrototype {
  id: number
  project_id: number
  requirement_id?: number | null
  created_by_user_id: number
  title: string
  summary: string
  status: 'DRAFT' | 'REVIEW' | 'APPROVED' | 'ARCHIVED'
  active_version: number
  screen_count: number
  quality_score: number
  created_at: string
  updated_at: string
}

export interface ProductPrototypeDetail extends ProductPrototype {
  current: PrototypeVersion
  versions: PrototypeVersion[]
}

export interface PrototypeReviewComment {
  id: number
  prototype_id: number
  prototype_version: number
  screen_id?: string | null
  user_id: number
  user_name: string
  body: string
  status: 'OPEN' | 'RESOLVED'
  resolved_by_user_id?: number | null
  resolved_at?: string | null
  created_at: string
  updated_at: string
}

export interface PrototypeTestCase {
  id: number
  prototype_id: number
  prototype_version: number
  screen_id: string
  case_key: string
  title: string
  preconditions: string
  steps: string[]
  expected_result: string
  priority: string
  created_at: string
}

export interface PrototypeMaterialization {
  id: number
  prototype_id: number
  prototype_version: number
  task_ids: number[]
  test_cases: PrototypeTestCase[]
  created_at: string
}
