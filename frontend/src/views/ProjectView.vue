<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1>{{ project?.name || '项目空间' }}</h1>
        <p>{{ project?.description }}</p>
      </div>
      <div class="inline-actions">
        <el-tag :type="project?.status === 'ARCHIVED' ? 'info' : 'success'">{{ project?.status === 'ARCHIVED' ? '已归档' : '进行中' }}</el-tag>
        <el-tag>{{ roleLabel(project?.current_user_role) }}</el-tag>
        <el-button v-if="project?.current_user_role !== 'viewer'" :icon="Edit" @click="openProjectEdit">编辑项目</el-button>
        <el-button v-if="project?.current_user_role !== 'viewer' && auth.hasPermission('projects:write')" :icon="MagicStick" type="primary" :loading="running" @click="runWorkflow">运行多 Agent 工作流</el-button>
      </div>
    </div>

    <el-row :gutter="20">
      <el-col :xs="24" :lg="14">
        <h2 class="section-title">任务列表</h2>
        <el-table :data="tasks" class="data-table">
          <el-table-column prop="title" label="任务" min-width="180" />
          <el-table-column prop="priority" label="优先级" width="100" />
          <el-table-column prop="status" label="状态" width="120" />
        </el-table>
      </el-col>
      <el-col :xs="24" :lg="10">
        <h2 class="section-title">AI 员工</h2>
        <div class="agent-list">
          <div v-for="agent in agents" :key="agent.id" class="agent-row">
            <strong>{{ agent.name }}</strong>
            <span>{{ agent.tools || '通用推理' }}</span>
          </div>
        </div>
      </el-col>
    </el-row>

    <section class="report-panel">
      <div class="page-head compact">
        <div>
          <h3>项目成员</h3>
          <p>成员权限由项目角色控制，不依赖项目描述中的成员文本。</p>
        </div>
        <el-button v-if="project?.current_user_role === 'owner'" :icon="Plus" @click="memberDialog = true">邀请成员</el-button>
      </div>
      <el-table :data="members" class="data-table">
        <el-table-column prop="name" label="成员" min-width="140" />
        <el-table-column prop="email" label="邮箱" min-width="220" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">{{ roleLabel(row.role) }}</template>
        </el-table-column>
        <el-table-column v-if="project?.current_user_role === 'owner'" label="操作" width="90">
          <template #default="{ row }">
            <el-button v-if="row.role !== 'owner'" :icon="Delete" circle aria-label="移除成员" title="移除成员" @click="removeMemberRow(row)" />
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="report-panel">
      <h3>项目动态</h3>
      <div class="project-activity-list">
        <div v-for="item in activities.slice(0, 12)" :key="item.id"><strong>{{ activityLabel(item.action) }}</strong><span>{{ new Date(item.created_at).toLocaleString() }}</span></div>
        <el-empty v-if="!activities.length" description="暂无项目动态" :image-size="48" />
      </div>
    </section>

    <section v-if="workflowState" class="report-panel">
      <div class="page-head compact">
        <div><h3>Agent 工作流</h3><p>{{ workflowCompletedStages }} / {{ workflowStages.length }} 个阶段已完成</p></div>
        <div class="inline-actions">
          <el-button v-if="['QUEUED', 'RUNNING'].includes(workflowStatus)" :icon="CircleClose" :loading="workflowActionBusy" @click="cancelWorkflow">取消</el-button>
          <el-button v-if="workflowStatus === 'FAILED'" type="primary" :icon="RefreshRight" :loading="workflowActionBusy" @click="retryWorkflow">重试失败节点</el-button>
          <el-button v-if="workflowStatus === 'COMPENSATION_FAILED'" type="danger" :icon="RefreshRight" :loading="workflowActionBusy" @click="retryCompensation">重试回滚</el-button>
        </div>
      </div>
      <el-tag :type="workflowTagType">{{ workflowStatusLabel }}</el-tag>
      <p v-if="workflowError" class="workflow-error">{{ workflowError }}</p>
      <div class="workflow-steps-scroll">
        <el-steps class="workflow-steps" :active="workflowCompletedStages" finish-status="success" simple>
          <el-step v-for="stage in workflowStages" :key="stage" :title="stage" />
        </el-steps>
      </div>
      <section v-if="executionPlan" class="workflow-orchestration" aria-label="多 Agent 执行计划">
        <div class="orchestration-heading">
          <div><h4>动态执行计划</h4><p>{{ executionPlan.objective }}</p></div>
          <el-tag type="primary">{{ executionPlan.assignments.length }} 个并行分支</el-tag>
        </div>
        <div class="orchestration-branches">
          <div v-for="assignment in executionPlan.assignments" :key="assignment.role" class="orchestration-branch-row">
            <span class="branch-role">{{ specialistRoleLabel(assignment.role) }}</span>
            <div><strong>{{ assignment.deliverable }}</strong><small>{{ assignment.objective }}</small></div>
            <el-tag :type="handoffFor(assignment.role) ? 'success' : 'info'" size="small">{{ handoffFor(assignment.role) ? `已交接 · R${handoffFor(assignment.role)?.revision_round}` : '等待执行' }}</el-tag>
          </div>
        </div>
        <el-collapse v-if="specialistHandoffs.length" class="handoff-details">
          <el-collapse-item v-for="handoff in specialistHandoffs" :key="handoff.role" :name="handoff.role" :title="`${specialistRoleLabel(handoff.role)} Handoff · ${handoff.deliverable}`">
            <pre>{{ handoff.content }}</pre>
          </el-collapse-item>
        </el-collapse>
        <div v-if="qualityGate" class="quality-gate-summary" :class="{ failed: !qualityGate.passed }">
          <div><strong>{{ qualityGate.passed ? 'Quality Gate 已通过' : 'Quality Gate 需要修订' }}</strong><span>评分 {{ Math.round(qualityGate.score) }} / 100</span></div>
          <p>{{ qualityGate.summary }}</p>
          <ul v-if="qualityGate.issues.length"><li v-for="issue in qualityGate.issues" :key="issue">{{ issue }}</li></ul>
        </div>
      </section>
      <div v-if="workflowEvents.length" class="workflow-events" aria-live="polite">
        <div v-for="event in workflowEvents.slice(-8)" :key="event.id" class="workflow-event-row">
          <span>{{ workflowEventLabel(event.event_type) }}</span>
          <strong>{{ workflowStageLabel(event.node) }}</strong>
          <time>{{ new Date(event.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }}</time>
        </div>
      </div>
      <section v-if="workflowStatus === 'PAUSED'" class="workflow-approval-gate">
        <div>
          <strong>{{ workflowCurrentNode === 'quality_review' ? '质量门禁等待修订意见' : '最终报告等待人工确认' }}</strong>
          <p>{{ workflowCurrentNode === 'quality_review' ? '说明需要补充的证据、取舍或负责人；Agent 将重新执行未通过的专业分支。' : '确认当前需求、架构、任务和测试产物后继续生成最终报告。' }}</p>
        </div>
        <el-input
          v-model="workflowFeedback"
          type="textarea"
          :rows="3"
          :placeholder="workflowCurrentNode === 'quality_review' ? '输入具体修订意见' : '补充最终报告需要强调的内容（可选）'"
          aria-label="工作流人工反馈"
        />
        <el-button
          type="warning"
          :loading="workflowActionBusy"
          :disabled="workflowCurrentNode === 'quality_review' && !workflowFeedback.trim()"
          @click="continueWorkflow"
        >{{ workflowCurrentNode === 'quality_review' ? '提交修订意见' : '确认并生成报告' }}</el-button>
      </section>
      <el-table v-if="workflowSagaSteps.length" :data="workflowSagaSteps" class="data-table">
        <el-table-column label="写操作" min-width="150">
          <template #default="{ row }">{{ sagaToolLabel(row.tool_name) }}</template>
        </el-table-column>
        <el-table-column label="阶段" width="110">
          <template #default="{ row }">{{ workflowStageLabel(row.node) }}</template>
        </el-table-column>
        <el-table-column label="事务状态" width="130">
          <template #default="{ row }"><el-tag :type="sagaTagType(row.status)">{{ sagaStatusLabel(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="execute_attempts" label="执行" width="70" />
        <el-table-column prop="compensation_attempts" label="回滚" width="70" />
        <el-table-column prop="error" label="异常" min-width="180" show-overflow-tooltip />
      </el-table>
      <div v-if="workflowState.report" class="workflow-output">
        <div class="workflow-artifact-head"><h4>最终项目报告</h4><el-button size="small" @click="publishArtifact('FINAL_REPORT', 'knowledge')">发布到知识库</el-button></div>
        <MarkdownRenderer :content="String(workflowState.report)" />
      </div>
      <el-tabs v-else-if="workflowDocuments.length" v-model="activeWorkflowDocument" class="workflow-documents">
        <el-tab-pane v-for="document in workflowDocuments" :key="document.type" :label="documentLabel(document.type)" :name="document.type">
          <div class="workflow-artifact-actions">
            <el-button size="small" @click="publishArtifact(document.type, 'report')">发布为报告</el-button>
            <el-button size="small" @click="publishArtifact(document.type, 'knowledge')">发布到知识库</el-button>
          </div>
          <MarkdownRenderer :content="document.content" />
        </el-tab-pane>
      </el-tabs>
      <el-empty v-else description="工作流正在准备产物" />
    </section>

    <el-dialog v-model="memberDialog" title="邀请项目成员" width="460">
      <el-form label-position="top">
        <el-form-item label="注册邮箱">
          <el-input v-model="memberForm.email" placeholder="member@company.com" />
        </el-form-item>
        <el-form-item label="项目角色">
          <el-select v-model="memberForm.role" class="full">
            <el-option label="编辑者：可执行项目操作" value="editor" />
            <el-option label="查看者：只读" value="viewer" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="memberDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!memberForm.email" @click="inviteMember">邀请</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="projectEditDialog" title="编辑项目" width="520">
      <el-form label-position="top">
        <el-form-item label="项目名称"><el-input v-model="projectForm.name" /></el-form-item>
        <el-form-item label="项目描述"><el-input v-model="projectForm.description" type="textarea" :rows="4" /></el-form-item>
        <el-form-item v-if="project?.current_user_role === 'owner'" label="项目状态">
          <el-segmented v-model="projectForm.status" :options="[{ label: '进行中', value: 'ACTIVE' }, { label: '已归档', value: 'ARCHIVED' }]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="project?.current_user_role === 'owner'" type="danger" plain @click="deleteProject">删除项目</el-button>
        <el-button @click="projectEditDialog = false">取消</el-button>
        <el-button type="primary" :loading="projectSaving" @click="saveProject">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleClose, Delete, Edit, MagicStick, Plus, RefreshRight } from '@element-plus/icons-vue'
import { api, apiBaseURL } from '../api/client'
import type { Agent, Project, ProjectActivity, ProjectMember, Task, WorkflowEvent, WorkflowRun, WorkflowSagaStep } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import axios from 'axios'
import { confirmDestructiveAction } from '../utils/confirm'

interface WorkflowAssignment {
  role: string
  objective: string
  deliverable: string
}

interface WorkflowExecutionPlan {
  objective: string
  rationale: string
  assignments: WorkflowAssignment[]
  success_criteria: string[]
}

interface WorkflowHandoff extends WorkflowAssignment {
  content: string
  revision_round: number
}

interface WorkflowQualityGate {
  score: number
  passed: boolean
  issues: string[]
  revision_roles: string[]
  summary: string
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const projectId = Number(route.params.id)
const project = ref<Project | null>(null)
const tasks = ref<Task[]>([])
const agents = ref<Agent[]>([])
const workflowState = ref<Record<string, any> | null>(null)
const workflowId = ref<number | null>(null)
const workflowStatus = ref('')
const workflowCurrentNode = ref('')
const workflowError = ref('')
const workflowFeedback = ref('')
const workflowEvents = ref<WorkflowEvent[]>([])
const workflowSagaSteps = ref<WorkflowSagaStep[]>([])
const workflowActionBusy = ref(false)
const workflowStream = ref<AbortController | null>(null)
const lastWorkflowEventId = ref(0)
const running = ref(false)
const members = ref<ProjectMember[]>([])
const activities = ref<ProjectActivity[]>([])
const memberDialog = ref(false)
const memberForm = reactive<{ email: string; role: 'editor' | 'viewer' }>({ email: '', role: 'viewer' })
const workflowRequestId = ref(crypto.randomUUID())
const projectEditDialog = ref(false)
const projectSaving = ref(false)
const projectForm = reactive({ name: '', description: '', status: 'ACTIVE' })
const activeWorkflowDocument = ref('PRD')
const workflowStages = ['需求分析', '产品方案', '架构设计', '动态规划', '专业分支', '质量门禁', '项目计划', '测试方案', '项目报告']
const executionPlan = computed<WorkflowExecutionPlan | null>(() => {
  const plan = workflowState.value?.execution_plan
  return plan && Array.isArray(plan.assignments) ? plan as WorkflowExecutionPlan : null
})
const specialistHandoffs = computed<WorkflowHandoff[]>(() => {
  const handoffs = workflowState.value?.specialist_handoffs
  return Array.isArray(handoffs) ? handoffs as WorkflowHandoff[] : []
})
const qualityGate = computed<WorkflowQualityGate | null>(() => {
  const gate = workflowState.value?.quality_gate
  return gate && typeof gate.score === 'number' ? gate as WorkflowQualityGate : null
})
const workflowDocuments = computed(() => {
  const documents = workflowState.value?.documents
  if (!Array.isArray(documents)) return []
  return documents.filter(
    (item): item is { type: string; content: string } =>
      typeof item?.type === 'string' && typeof item?.content === 'string'
  )
})
const workflowCompletedStages = computed(() => {
  if (workflowState.value?.report) return workflowStages.length
  const completedRoles = new Set(
    Array.isArray(workflowState.value?.messages)
      ? workflowState.value.messages.map((item: { role?: string }) => item.role)
      : []
  )
  let completed = [
    'requirement_agent',
    'product_agent',
    'architect_agent',
    'project_manager_agent',
    'tester_agent'
  ].filter((role) => completedRoles.has(role)).length
  if (executionPlan.value) completed += 1
  if (specialistHandoffs.value.length) completed += 1
  if (qualityGate.value?.passed) completed += 1
  return completed
})
const workflowStatusLabel = computed(() => {
  if (workflowStatus.value === 'PAUSED') {
    return workflowCurrentNode.value === 'quality_review' ? '等待质量修订' : '等待报告确认'
  }
  return ({
  QUEUED: '等待执行',
  RUNNING: '执行中',
  CANCELLING: '正在取消',
  COMPENSATING: '正在回滚',
  COMPENSATION_FAILED: '回滚失败，等待人工处理',
  CANCELLED: '已取消',
  PAUSED: '等待人工确认',
  COMPLETED: '已完成',
  FAILED: '执行失败'
  }[workflowStatus.value] || workflowStatus.value)
})
const workflowTagType = computed(() => ({
  QUEUED: 'info',
  RUNNING: 'primary',
  CANCELLING: 'warning',
  COMPENSATING: 'warning',
  COMPENSATION_FAILED: 'danger',
  CANCELLED: 'info',
  PAUSED: 'warning',
  COMPLETED: 'success',
  FAILED: 'danger'
}[workflowStatus.value] as 'primary' | 'success' | 'warning' | 'info' | 'danger' | undefined))

function documentLabel(type: string) {
  return {
    PRD: '产品需求',
    SYSTEM_DESIGN: '系统架构',
    PROJECT_PLAN: '项目计划',
    TEST_PLAN: '测试方案',
    FINAL_REPORT: '最终报告'
  }[type] || type
}

function workflowStageLabel(node: string) {
  return {
    requirement: '需求分析',
    product: '产品方案',
    architect: '架构设计',
    planning: '动态规划',
    specialists: '专业分支',
    quality_gate: '质量门禁',
    quality_review: '人工修订',
    project_manager: '项目计划',
    tester: '测试方案',
    report: '项目报告',
    completed: '完成'
  }[node] || node || '工作流'
}

function workflowEventLabel(eventType: string) {
  return {
    QUEUED: '已入队',
    STARTED: '已开始',
    RECOVERED: '已恢复',
    NODE_STARTED: '开始节点',
    NODE_COMPLETED: '完成节点',
    PLAN_CREATED: '计划已生成',
    BRANCH_STARTED: '分支已启动',
    BRANCH_COMPLETED: '分支已交接',
    QUALITY_GATE_PASSED: '质量门禁通过',
    QUALITY_GATE_FAILED: '质量门禁未通过',
    REVISION_REQUESTED: '请求自动修订',
    RETRY_SCHEDULED: '自动重试',
    SAGA_STEP_COMPLETED: '写操作已提交',
    COMPENSATION_STARTED: '开始事务回滚',
    SAGA_STEP_COMPENSATED: '写操作已回滚',
    SAGA_COMPENSATION_FAILED: '步骤回滚失败',
    COMPENSATION_FAILED: '事务回滚失败',
    COMPENSATED: '事务回滚完成',
    PAUSED: '等待确认',
    COMPLETED: '执行完成',
    CANCEL_REQUESTED: '请求取消',
    CANCELLED: '已取消',
    FAILED: '执行失败'
  }[eventType] || eventType
}

function specialistRoleLabel(role: string) {
  return {
    test_engineer: '测试工程师',
    operations_analyst: '运营分析师',
    knowledge_admin: '知识库管理员',
    notification_secretary: '通知秘书'
  }[role] || role
}

function handoffFor(role: string) {
  return specialistHandoffs.value.find((handoff) => handoff.role === role)
}

function sagaStatusLabel(status: string) {
  return {
    PENDING: '待执行',
    EXECUTING: '执行中',
    COMPLETED: '已提交',
    FAILED: '执行失败',
    COMPENSATING: '回滚中',
    COMPENSATED: '已回滚',
    COMPENSATION_FAILED: '回滚失败'
  }[status] || status
}

function sagaTagType(status: string) {
  return {
    PENDING: 'info',
    EXECUTING: 'primary',
    COMPLETED: 'success',
    FAILED: 'danger',
    COMPENSATING: 'warning',
    COMPENSATED: 'info',
    COMPENSATION_FAILED: 'danger'
  }[status] as 'primary' | 'success' | 'warning' | 'info' | 'danger' | undefined
}

function sagaToolLabel(tool: string) {
  return { task_create: '创建项目任务', report_create: '创建最终报告' }[tool] || tool
}

function activityLabel(action: string) {
  return {
    'project.update': '项目配置已更新',
    'project.member_upsert': '项目成员已更新',
    'project.member_remove': '项目成员已移除',
    'task.create': '创建了任务',
    'task.update': '更新了任务',
    'task.comment': '添加了任务评论',
    'meeting.tasks_create': '会议行动项已转为任务',
    'workflow.artifact_publish': '工作流产物已发布'
  }[action] || action
}

function applyWorkflow(workflow: WorkflowRun) {
  if (workflowCurrentNode.value !== workflow.current_node) workflowFeedback.value = ''
  workflowId.value = workflow.workflow_id
  workflowStatus.value = workflow.status
  workflowCurrentNode.value = workflow.current_node
  workflowState.value = workflow.state
  workflowError.value = workflow.error
}

async function refreshWorkflow() {
  if (!workflowId.value) return
  const [workflowResponse, sagaResponse] = await Promise.all([
    api.get<WorkflowRun>(`/workflow/${workflowId.value}`),
    api.get<WorkflowSagaStep[]>(`/workflow/${workflowId.value}/saga-steps`)
  ])
  applyWorkflow(workflowResponse.data)
  workflowSagaSteps.value = sagaResponse.data
}

function watchWorkflowEvents() {
  if (!workflowId.value) return
  workflowStream.value?.abort()
  const controller = new AbortController()
  workflowStream.value = controller
  void consumeWorkflowEvents(workflowId.value, controller)
}

async function consumeWorkflowEvents(id: number, controller: AbortController) {
  try {
    const response = await fetch(`${apiBaseURL}/workflow/${id}/events?last_event_id=${lastWorkflowEventId.value}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` },
      signal: controller.signal
    })
    if (!response.ok || !response.body) throw new Error('工作流进度连接失败')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() || ''
      for (const block of blocks) {
        const raw = block.match(/^data: (.+)$/m)?.[1]
        if (!raw) continue
        const event = JSON.parse(raw) as WorkflowEvent
        if (!workflowEvents.value.some((item) => item.id === event.id)) workflowEvents.value.push(event)
        lastWorkflowEventId.value = Math.max(lastWorkflowEventId.value, event.id)
        if (['NODE_COMPLETED', 'PLAN_CREATED', 'BRANCH_COMPLETED', 'QUALITY_GATE_PASSED', 'QUALITY_GATE_FAILED', 'REVISION_REQUESTED', 'SAGA_STEP_COMPLETED', 'SAGA_STEP_COMPENSATED', 'SAGA_COMPENSATION_FAILED', 'COMPENSATION_FAILED', 'COMPENSATED', 'PAUSED', 'COMPLETED', 'FAILED', 'CANCELLED', 'RETRY_SCHEDULED'].includes(event.event_type)) {
          await refreshWorkflow()
        }
      }
    }
    await refreshWorkflow()
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) {
      ElMessage.error(error instanceof Error ? error.message : '工作流进度连接失败')
    }
  }
}

async function load() {
  const agentRequest = auth.hasPermission('agents:read')
    ? api.get<Agent[]>('/agents')
    : Promise.resolve({ data: [] as Agent[] })
  const [projectRes, taskRes, agentRes, memberRes, workflowRes, activityRes] = await Promise.all([
    api.get<Project>(`/projects/${projectId}`),
    api.get<Task[]>(`/projects/${projectId}/tasks`),
    agentRequest,
    api.get<ProjectMember[]>(`/projects/${projectId}/members`),
    api.get<WorkflowRun[]>('/workflow', { params: { project_id: projectId } }),
    api.get<ProjectActivity[]>(`/projects/${projectId}/activity`, { params: { limit: 50 } })
  ])
  project.value = projectRes.data
  tasks.value = taskRes.data
  agents.value = agentRes.data
  members.value = memberRes.data
  activities.value = activityRes.data
  const latestWorkflow = workflowRes.data[0]
  if (latestWorkflow) {
    applyWorkflow(latestWorkflow)
    const { data } = await api.get<WorkflowSagaStep[]>(`/workflow/${latestWorkflow.workflow_id}/saga-steps`)
    workflowSagaSteps.value = data
    watchWorkflowEvents()
  }
}

async function retryCompensation() {
  if (!workflowId.value) return
  workflowActionBusy.value = true
  try {
    const { data } = await api.post<WorkflowRun>(`/workflow/${workflowId.value}/retry-compensation`)
    applyWorkflow(data)
    await refreshWorkflow()
    watchWorkflowEvents()
  } finally {
    workflowActionBusy.value = false
  }
}

function roleLabel(role?: string) {
  return { owner: '负责人', editor: '编辑者', viewer: '查看者' }[role || ''] || '成员'
}

async function inviteMember() {
  await api.post(`/projects/${projectId}/members`, memberForm)
  memberDialog.value = false
  memberForm.email = ''
  memberForm.role = 'viewer'
  await load()
}

async function removeMemberRow(row: unknown) {
  const member = row as ProjectMember
  if (!await confirmDestructiveAction(`确认将 ${member.name} 移出项目吗？`, '移除项目成员')) return
  await api.delete(`/projects/${projectId}/members/${member.id}`)
  await load()
}

async function runWorkflow() {
  running.value = true
  try {
    const { data } = await api.post('/workflow/run', {
      project_id: projectId,
      user_input: `${project.value?.name}: ${project.value?.description}`,
      pause_before_report: true,
      request_id: workflowRequestId.value
    }, { suppressErrorToast: true })
    workflowEvents.value = []
    lastWorkflowEventId.value = 0
    applyWorkflow(data)
    watchWorkflowEvents()
    await auth.fetchMe()
    await load()
  } catch (error) {
    const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null
    const message = typeof detail === 'string' ? detail : '工作流启动失败'
    ElMessage.error(message)
    if (axios.isAxiosError(error) && error.response?.status === 402) await router.push('/wallet')
  } finally {
    running.value = false
  }
}

async function continueWorkflow() {
  if (!workflowId.value) return
  workflowActionBusy.value = true
  try {
    const feedback = workflowFeedback.value.trim() || '人工确认通过，请生成最终项目报告。'
    const { data } = await api.post<WorkflowRun>('/workflow/continue', {
      workflow_id: workflowId.value,
      human_feedback: feedback
    })
    workflowFeedback.value = ''
    applyWorkflow(data)
    watchWorkflowEvents()
    if (data.status === 'COMPLETED' || data.status === 'FAILED') workflowRequestId.value = crypto.randomUUID()
  } finally {
    workflowActionBusy.value = false
  }
}

async function cancelWorkflow() {
  if (!workflowId.value) return
  if (!await confirmDestructiveAction('取消后当前节点会停止，已完成节点结果将保留。确认取消吗？', '取消工作流')) return
  workflowActionBusy.value = true
  try {
    const { data } = await api.post<WorkflowRun>(`/workflow/${workflowId.value}/cancel`)
    applyWorkflow(data)
    await auth.fetchMe()
  } finally {
    workflowActionBusy.value = false
  }
}

async function retryWorkflow() {
  if (!workflowId.value) return
  workflowActionBusy.value = true
  try {
    const { data } = await api.post<WorkflowRun>(`/workflow/${workflowId.value}/retry`, {
      request_id: crypto.randomUUID()
    })
    applyWorkflow(data)
    await auth.fetchMe()
    watchWorkflowEvents()
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 402) await router.push('/wallet')
    else throw error
  } finally {
    workflowActionBusy.value = false
  }
}

function openProjectEdit() {
  if (!project.value) return
  Object.assign(projectForm, {
    name: project.value.name,
    description: project.value.description,
    status: project.value.status
  })
  projectEditDialog.value = true
}

async function saveProject() {
  if (!project.value) return
  projectSaving.value = true
  try {
    const { data } = await api.patch<Project>(`/projects/${projectId}`, projectForm)
    project.value = data
    projectEditDialog.value = false
  } finally {
    projectSaving.value = false
  }
}

async function deleteProject() {
  if (!await confirmDestructiveAction('删除项目会同时删除其协作数据，且无法恢复。确认继续吗？', '删除项目')) return
  await api.delete(`/projects/${projectId}`)
  await router.push('/projects')
}

async function publishArtifact(documentType: string, target: 'report' | 'knowledge') {
  if (!workflowId.value) return
  await api.post(`/workflow/${workflowId.value}/publish`, {
    document_type: documentType,
    target,
    request_id: crypto.randomUUID()
  })
  ElMessage.success(target === 'report' ? '产物已发布为报告' : '产物已进入知识索引队列')
}

onMounted(load)
onBeforeUnmount(() => workflowStream.value?.abort())
</script>

<style scoped>
.workflow-orchestration {
  margin: 18px 0;
  padding: 16px 0;
  border-block: 1px solid var(--color-border);
}

.orchestration-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.orchestration-heading > div {
  min-width: 0;
}

.orchestration-heading h4 {
  margin: 0 0 5px;
  font-size: 15px;
}

.orchestration-heading p {
  max-width: 900px;
  margin: 0;
  color: var(--color-secondary-text);
  font-size: 13px;
  line-height: 1.55;
}

.orchestration-branches {
  border-top: 1px solid var(--color-border);
}

.orchestration-branch-row {
  display: grid;
  min-height: 62px;
  grid-template-columns: 112px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid var(--color-border);
}

.branch-role {
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
}

.orchestration-branch-row > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.orchestration-branch-row strong {
  font-size: 13px;
}

.orchestration-branch-row small {
  overflow: hidden;
  color: var(--color-muted-text);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.handoff-details {
  margin-top: 12px;
  border-top: 0;
}

.handoff-details :deep(.el-collapse-item__header) {
  min-height: 44px;
  font-size: 12px;
}

.handoff-details pre {
  max-height: 280px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border-radius: var(--radius-md);
  background: #f6f8fa;
  color: var(--color-secondary-text);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.quality-gate-summary {
  margin-top: 12px;
  padding: 12px 14px;
  border-left: 3px solid var(--color-success);
  background: #f0fdf4;
}

.quality-gate-summary.failed {
  border-left-color: var(--color-warning);
  background: #fffbeb;
}

.quality-gate-summary > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.quality-gate-summary strong,
.quality-gate-summary span {
  font-size: 12px;
}

.quality-gate-summary span {
  color: var(--color-muted-text);
  font-variant-numeric: tabular-nums;
}

.quality-gate-summary p,
.quality-gate-summary ul {
  margin: 7px 0 0;
  color: var(--color-secondary-text);
  font-size: 12px;
  line-height: 1.55;
}

.quality-gate-summary ul {
  padding-left: 18px;
}

.workflow-approval-gate {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(300px, 1.4fr) auto;
  align-items: center;
  gap: 16px;
  margin: 16px 0;
  padding: 14px 16px;
  border-left: 3px solid var(--color-warning);
  background: #fffbeb;
}

.workflow-approval-gate > div {
  display: grid;
  gap: 4px;
}

.workflow-approval-gate strong {
  font-size: 13px;
}

.workflow-approval-gate p {
  margin: 0;
  color: var(--color-secondary-text);
  font-size: 11px;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .workflow-approval-gate {
    grid-template-columns: 1fr;
  }

  .workflow-approval-gate .el-button {
    width: 100%;
    min-height: 44px;
  }
}

@media (max-width: 640px) {
  .orchestration-heading {
    flex-direction: column;
  }

  .orchestration-branch-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .branch-role {
    grid-column: 1 / -1;
  }

  .orchestration-branch-row small {
    white-space: normal;
  }
}
</style>
