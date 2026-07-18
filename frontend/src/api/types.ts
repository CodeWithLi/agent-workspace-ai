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
  forbidden_keywords: string[]
  rubric: string
  minimum_score: number
  weight: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface EvaluationAgentSnapshot {
  id: number
  name: string
  role: string
  version: number
  model: string
}

export interface EvaluationRun {
  id: number
  request_id?: string | null
  status: string
  suite_revision?: number | null
  baseline_run_id?: number | null
  total_cases: number
  completed_cases: number
  progress_percent: number
  passed_cases: number
  average_score: number
  baseline_average_score?: number | null
  score_delta?: number | null
  gate_passed?: boolean | null
  gate_failures: string[]
  dimension_averages: Record<string, number>
  baseline_dimension_averages: Record<string, number>
  agent_snapshots: EvaluationAgentSnapshot[]
  error: string
  attempt_count: number
  max_attempts: number
  retryable: boolean
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

export interface EvaluationResult {
  id: number
  case_id: number
  case_name: string
  agent_role: string
  agent_name: string
  agent_version?: number | null
  model: string
  input_text: string
  expected_keywords: string[]
  forbidden_keywords: string[]
  rubric: string
  answer: string
  score: number
  baseline_answer: string
  baseline_score?: number | null
  score_delta?: number | null
  dimensions: Record<string, number>
  baseline_dimensions: Record<string, number>
  score_source: string
  latency_ms: number
  regressed: boolean
  passed: boolean
  matched_keywords: string[]
  missing_keywords: string[]
  forbidden_hits: string[]
  judge_reason: string
  judge_error: string
  error: string
  created_at: string
}

export interface EvaluationRunDetail extends EvaluationRun {
  results: EvaluationResult[]
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
  parent_workflow_id: number | null
  retry_from_node: string
  retry_sequence: number
  pause_requested_at?: string | null
  pause_requested_by_user_id?: number | null
  pause_reason: string
  intervention_count: number
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

export type WorkflowTraceStatus =
  | 'QUEUED'
  | 'RUNNING'
  | 'CANCELLING'
  | 'COMPENSATING'
  | 'COMPENSATION_FAILED'
  | 'CANCELLED'
  | 'PAUSED'
  | 'COMPLETED'
  | 'FAILED'

export interface TraceWindow {
  start_at: string
  end_at: string
  days: number
  analysis_truncated: boolean
}

export interface TraceMetricSummary {
  total_runs: number
  active_runs: number
  completed_runs: number
  failed_runs: number
  cancelled_runs: number
  success_rate: number
  average_duration_ms: number
  p95_duration_ms: number
  total_tokens: number
  total_cost_micros: number
  total_llm_calls: number
}

export interface TraceTrendPoint {
  bucket: string
  runs: number
  completed: number
  failed: number
  cancelled: number
  total_tokens: number
  total_cost_micros: number
}

export interface TraceProjectOption {
  project_id: number
  project_name: string
}

export interface TraceAgentMetric {
  agent_id?: number | null
  agent_name: string
  agent_role: string
  providers: string[]
  models: string[]
  workflow_count: number
  call_count: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  total_cost_micros: number
  average_latency_ms: number
  p95_latency_ms: number
  max_latency_ms: number
}

export interface TraceBottleneck {
  key: string
  node: string
  label: string
  kind: string
  execution_count: number
  average_duration_ms: number
  p95_duration_ms: number
  max_duration_ms: number
  compute_share_percent: number
}

export interface TraceRun {
  workflow_id: number
  project_id: number
  parent_workflow_id: number | null
  retry_from_node: string
  retry_sequence: number
  intervention_count: number
  project_name: string
  owner_id: number
  owner_name: string
  status: WorkflowTraceStatus
  current_node: string
  duration_ms: number
  queue_ms: number
  total_tokens: number
  total_cost_micros: number
  llm_call_count: number
  agent_count: number
  event_count: number
  error: string
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

export interface TraceOverview {
  window: TraceWindow
  metrics: TraceMetricSummary
  status_counts: Record<string, number>
  trend: TraceTrendPoint[]
  projects: TraceProjectOption[]
  agents: TraceAgentMetric[]
  bottlenecks: TraceBottleneck[]
  recent_runs: TraceRun[]
}

export type TraceHealthStatus = 'HEALTHY' | 'AT_RISK' | 'BREACHED' | 'INSUFFICIENT_DATA'

export interface TraceSLOTargets {
  success_rate_percent: number
  p95_duration_ms: number
  average_cost_micros: number
  minimum_sample_runs: number
  anomaly_sensitivity: number
}

export interface TraceSLOMetric {
  key: string
  label: string
  unit: 'percent' | 'duration' | 'cost'
  target: number
  actual: number
  compliant: boolean
}

export interface TraceHealthSummary {
  status: TraceHealthStatus
  sample_count: number
  completed_count: number
  failed_count: number
  compliant_metric_count: number
  breached_metric_count: number
  error_budget_allowed_failures: number
  error_budget_consumed_failures: number
  error_budget_remaining_percent: number
}

export interface TraceAnomaly {
  workflow_id: number
  project_id: number
  project_name: string
  status: WorkflowTraceStatus
  severity: 'CRITICAL' | 'WARNING'
  signals: string[]
  duration_ms: number
  total_cost_micros: number
  detected_at: string
}

export interface TraceHealth {
  window: TraceWindow
  targets: TraceSLOTargets
  summary: TraceHealthSummary
  metrics: TraceSLOMetric[]
  anomalies: TraceAnomaly[]
}

export type TraceAlertStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED'

export interface TraceAlert {
  id: number
  workflow_id: number
  project_id: number
  project_name: string
  severity: 'CRITICAL' | 'WARNING'
  status: TraceAlertStatus
  signals: string[]
  duration_ms: number
  total_cost_micros: number
  detected_at: string
  acknowledged_by_user_id?: number | null
  acknowledged_at?: string | null
  resolved_by_user_id?: number | null
  resolved_at?: string | null
  resolution_note: string
  created_at: string
  updated_at: string
}

export interface TraceAlertCollection {
  summary: {
    total: number
    open: number
    acknowledged: number
    resolved: number
    critical: number
  }
  items: TraceAlert[]
}

export interface TraceSpan {
  span_id: string
  kind: string
  node: string
  label: string
  agent_role: string
  agent_name: string
  status: string
  attempt: number
  started_at: string
  finished_at?: string | null
  duration_ms: number
  llm_call_count: number
  total_tokens: number
  total_cost_micros: number
  model_latency_ms: number
  payload: Record<string, unknown>
}

export interface TraceModelCall {
  id: number
  agent_id?: number | null
  agent_name: string
  agent_role: string
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

export interface TraceEventDetail {
  id: number
  node: string
  event_type: string
  message: string
  payload: Record<string, unknown>
  created_at: string
}

export interface TraceDetailMetrics {
  total_duration_ms: number
  queue_ms: number
  active_compute_ms: number
  human_wait_ms: number
  coordination_ms: number
  total_tokens: number
  total_cost_micros: number
  total_llm_calls: number
  critical_span_id?: string | null
}

export interface TraceDetail {
  run: TraceRun
  metrics: TraceDetailMetrics
  spans: TraceSpan[]
  model_calls: TraceModelCall[]
  events: TraceEventDetail[]
}

export type TraceComparisonDirection = 'IMPROVED' | 'REGRESSED' | 'CHANGED' | 'UNCHANGED'
export type TraceComparisonChangeType = 'ADDED' | 'REMOVED' | 'MODIFIED' | 'UNCHANGED'
export type TraceComparisonVerdict = 'IMPROVED' | 'REGRESSED' | 'MIXED' | 'UNCHANGED'

export interface TraceComparisonMetric {
  key: string
  label: string
  unit: 'duration' | 'tokens' | 'cost' | 'count'
  baseline_value: number
  candidate_value: number
  delta: number
  delta_percent?: number | null
  direction: TraceComparisonDirection
  lower_is_better: boolean
}

export interface TraceComparisonAgent {
  key: string
  agent_id?: number | null
  agent_name: string
  agent_role: string
  change_type: TraceComparisonChangeType
  baseline_providers: string[]
  candidate_providers: string[]
  baseline_models: string[]
  candidate_models: string[]
  baseline_calls: number
  candidate_calls: number
  baseline_tokens: number
  candidate_tokens: number
  token_delta: number
  baseline_cost_micros: number
  candidate_cost_micros: number
  cost_delta_micros: number
  baseline_average_latency_ms: number
  candidate_average_latency_ms: number
  latency_delta_ms: number
  latency_direction: TraceComparisonDirection
}

export interface TraceComparisonSpan {
  key: string
  kind: string
  node: string
  label: string
  agent_role: string
  change_type: TraceComparisonChangeType
  baseline_executions: number
  candidate_executions: number
  baseline_duration_ms: number
  candidate_duration_ms: number
  duration_delta_ms: number
  duration_delta_percent?: number | null
  duration_direction: TraceComparisonDirection
  baseline_tokens: number
  candidate_tokens: number
  token_delta: number
  baseline_cost_micros: number
  candidate_cost_micros: number
  cost_delta_micros: number
}

export interface TraceComparisonSummary {
  verdict: TraceComparisonVerdict
  outcome_direction: TraceComparisonDirection
  regression_count: number
  improvement_count: number
  changed_agent_count: number
  changed_span_count: number
}

export interface TraceComparison {
  baseline: TraceRun
  candidate: TraceRun
  summary: TraceComparisonSummary
  metrics: TraceComparisonMetric[]
  agents: TraceComparisonAgent[]
  spans: TraceComparisonSpan[]
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

export type PrototypeGenerationOperation = 'CREATE' | 'REGENERATE'

export type PrototypeGenerationJobStatus =
  | 'QUEUED'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'CANCELLING'
  | 'CANCELLED'

export type PrototypeGenerationStageName =
  | 'queued'
  | 'product_definition'
  | 'architecture'
  | 'architecture_repair'
  | 'deterministic_repair'
  | 'quality_review'
  | 'quality_review_repair'
  | 'persisting'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface PrototypeGenerationStage {
  stage: PrototypeGenerationStageName
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
  round?: number
  agent_role?: string | null
  message?: string
  started_at?: string | null
  finished_at?: string | null
}

export interface PrototypeGenerationJob {
  job_id: number
  operation: PrototypeGenerationOperation
  project_id: number
  title: string
  prototype_id?: number | null
  base_version?: number | null
  target_version?: number | null
  status: PrototypeGenerationJobStatus
  stage: PrototypeGenerationStageName
  stage_history: PrototypeGenerationStage[]
  progress_percent: number
  attempt_count: number
  max_attempts: number
  latest_event_id: number
  retryable: boolean
  error_code: string | null
  error_message: string | null
  result_prototype_id: number | null
  result_version: number | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  updated_at: string
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
