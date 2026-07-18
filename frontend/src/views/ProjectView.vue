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
        <el-button v-if="project?.current_user_role !== 'viewer' && auth.hasPermission('projects:write')" :icon="MagicStick" type="primary" :loading="running" :disabled="workflowRunLocked" @click="runWorkflow">{{ workflowRunLocked ? '工作流处理中' : '运行多 Agent 工作流' }}</el-button>
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
          <el-button
            v-if="['QUEUED', 'RUNNING'].includes(workflowStatus)"
            :icon="VideoPause"
            :disabled="workflowPausePending"
            @click="openWorkflowPauseDialog"
          >{{ workflowPausePending ? '等待节点暂停' : '安全暂停' }}</el-button>
          <el-button v-if="['QUEUED', 'RUNNING'].includes(workflowStatus)" :icon="CircleClose" :loading="workflowActionBusy" @click="cancelWorkflow">取消</el-button>
          <el-button v-if="workflowStatus === 'FAILED'" type="primary" :icon="RefreshRight" :loading="workflowActionBusy" @click="retryWorkflow">重试失败节点</el-button>
          <el-button v-if="workflowStatus === 'COMPENSATION_FAILED'" type="danger" :icon="RefreshRight" :loading="workflowActionBusy" @click="retryCompensation">重试回滚</el-button>
        </div>
      </div>
      <el-tag :type="workflowTagType">{{ workflowStatusLabel }}</el-tag>
      <el-tag v-if="workflowInterventionCount" class="workflow-intervention-count" type="warning" effect="plain">人工干预 {{ workflowInterventionCount }} 次</el-tag>
      <p v-if="workflowError" class="workflow-error">{{ workflowError }}</p>
      <div v-if="workflowPausePending" class="workflow-intervention-notice" role="status" aria-live="polite">
        <el-icon aria-hidden="true"><VideoPause /></el-icon>
        <div>
          <strong>安全暂停已请求</strong>
          <span>当前“{{ workflowStageLabel(workflowCurrentNode) }}”节点提交检查点后停止。</span>
          <small>{{ workflowPauseReason }}</small>
        </div>
      </div>
      <div v-if="workflowRetrySequence > 0" class="workflow-retry-lineage" role="status">
        <el-icon aria-hidden="true"><RefreshRight /></el-icon>
        <div>
          <strong>检查点重试 #{{ workflowRetrySequence }}</strong>
          <span v-if="workflowParentId">从运行 #{{ workflowParentId }} 的“{{ workflowStageLabel(workflowRetryFromNode) }}”检查点继续，源运行保持只读。</span>
          <span v-else>从“{{ workflowStageLabel(workflowRetryFromNode) }}”检查点继续，来源运行已不再保留。</span>
        </div>
        <el-button
          v-if="workflowParentId"
          link
          type="primary"
          :icon="View"
          @click="openSourceWorkflow"
        >查看源运行</el-button>
      </div>
      <div
        v-if="workflowConnectionNotice"
        class="workflow-connection-notice"
        :class="{ reconnecting: workflowConnectionState === 'reconnecting' }"
        :role="workflowConnectionState === 'reconnecting' ? 'alert' : 'status'"
        aria-live="polite"
      >
        <el-icon aria-hidden="true"><Connection /></el-icon>
        <span>{{ workflowConnectionNotice }}</span>
        <el-button
          v-if="['reconnecting', 'closed'].includes(workflowConnectionState)"
          :icon="RefreshRight"
          size="small"
          @click="restartWorkflowEvents"
        >立即重连</el-button>
      </div>
      <div class="workflow-steps-scroll">
        <el-steps class="workflow-steps" :active="workflowCompletedStages" finish-status="success" simple>
          <el-step v-for="stage in workflowStages" :key="stage" :title="stage" />
        </el-steps>
      </div>
      <section v-if="executionPlan" class="workflow-orchestration" aria-label="多 Agent 执行计划">
        <div v-if="workflowPlanReview && planRevisions.length > 1" class="plan-version-toolbar">
          <div><strong>计划版本</strong><span>当前生成 v{{ latestPlanVersion }}</span></div>
          <div class="plan-version-selector">
            <el-segmented v-model="selectedPlanVersion" :options="planVersionOptions" aria-label="执行计划版本" />
          </div>
        </div>
        <div class="orchestration-heading">
          <div class="orchestration-copy">
            <h4>动态执行计划</h4>
            <p>{{ executionPlan.objective }}</p>
            <small>{{ executionPlan.rationale }}</small>
          </div>
          <div class="orchestration-tags">
            <el-tag type="info">v{{ displayedPlanVersion }}</el-tag>
            <el-tag v-if="executionPlanApprovalLabel" :type="executionPlanApprovalType">{{ executionPlanApprovalLabel }}</el-tag>
            <el-tag type="primary">{{ executionPlanTopologyLabel }}</el-tag>
            <el-tag v-if="executionPlanRuntimeSummary" :type="executionPlanRuntimeType">{{ executionPlanRuntimeSummary }}</el-tag>
          </div>
        </div>
        <div v-if="workflowPlanReview && selectedPlanRevision" class="plan-version-diff">
          <strong>{{ previousPlanRevision ? `相较 v${previousPlanRevision.version} 的变化` : '初始计划' }}</strong>
          <ul v-if="planVersionChanges.length"><li v-for="change in planVersionChanges" :key="change">{{ change }}</li></ul>
          <span v-else-if="previousPlanRevision">结构化计划内容未发生变化</span>
          <p v-if="selectedPlanRevision.feedback">重规划意见：{{ selectedPlanRevision.feedback }}</p>
        </div>
        <div class="plan-success-criteria">
          <strong>本轮成功标准</strong>
          <ul><li v-for="criterion in executionPlan.success_criteria" :key="criterion">{{ criterion }}</li></ul>
        </div>
        <div class="orchestration-waves">
          <section v-for="wave in executionPlanWaves" :key="wave.number" class="orchestration-wave" :aria-label="`执行计划第 ${wave.number} 波`">
            <div class="orchestration-wave-heading">
              <strong>第 {{ wave.number }} 波</strong>
              <span>{{ waveRuntimeSummary(wave.assignments) }}</span>
            </div>
            <div class="orchestration-branches">
              <div v-for="assignment in wave.assignments" :key="assignment.role" class="orchestration-branch-row">
                <span class="branch-role">{{ specialistRoleLabel(assignment.role) }}</span>
                <div class="orchestration-branch-copy">
                  <strong>{{ assignment.deliverable }}</strong>
                  <small class="branch-objective">{{ assignment.objective }}</small>
                  <small v-if="assignment.depends_on?.length" class="branch-dependencies">
                    <span class="branch-dependency-label">依赖</span>
                    <span class="branch-dependency-roles">{{ assignment.depends_on.map(specialistRoleLabel).join('、') }}</span>
                  </small>
                </div>
                <div class="branch-runtime-actions">
                  <span
                    class="branch-runtime-status"
                    :class="`is-${branchRuntimeState(assignment.role).status}`"
                    role="status"
                    :aria-label="`${specialistRoleLabel(assignment.role)}：${branchRuntimeLabel(assignment.role)}${branchRuntimeMeta(assignment.role) ? `，${branchRuntimeMeta(assignment.role)}` : ''}`"
                  >
                    <el-icon aria-hidden="true"><component :is="branchRuntimeIcon(branchRuntimeState(assignment.role).status)" /></el-icon>
                    <span>{{ branchRuntimeLabel(assignment.role) }}</span>
                    <small v-if="branchRuntimeMeta(assignment.role)">{{ branchRuntimeMeta(assignment.role) }}</small>
                  </span>
                  <el-button
                    v-if="handoffFor(assignment.role)"
                    class="branch-handoff-button"
                    :icon="View"
                    circle
                    :aria-label="`查看${specialistRoleLabel(assignment.role)}交接`"
                    :title="`查看${specialistRoleLabel(assignment.role)}交接`"
                    @click="openHandoff(assignment.role)"
                  />
                </div>
              </div>
            </div>
          </section>
        </div>
        <el-collapse v-if="specialistHandoffs.length" v-model="activeHandoffRoles" class="handoff-details">
          <el-collapse-item v-for="handoff in specialistHandoffs" :id="`handoff-${handoff.role}`" :key="handoff.role" :name="handoff.role" :title="`${specialistRoleLabel(handoff.role)} Handoff · ${handoff.deliverable}`">
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
      <section v-if="workflowStatus === 'PAUSED'" class="workflow-approval-gate" :class="{ 'plan-review': workflowPlanReview }">
        <div>
          <strong>{{ workflowApprovalTitle }}</strong>
          <p>{{ workflowApprovalDescription }}</p>
          <small v-if="workflowOperatorPaused" class="workflow-pause-reason">暂停原因：{{ workflowPauseReason }}</small>
        </div>
        <el-input
          v-model="workflowFeedback"
          type="textarea"
          :rows="3"
          :placeholder="workflowFeedbackPlaceholder"
          aria-label="工作流人工反馈"
        />
        <el-button
          v-if="!workflowPlanReview"
          type="warning"
          :loading="workflowActionBusy"
          :disabled="workflowFeedbackRequired && !workflowFeedback.trim()"
          @click="continueWorkflow()"
        >{{ workflowContinueLabel }}</el-button>
        <div v-else class="workflow-approval-actions">
          <el-button
            :icon="RefreshRight"
            :loading="workflowActionBusy"
            :disabled="!workflowFeedback.trim()"
            @click="continueWorkflow('REVISE')"
          >要求重新规划</el-button>
          <el-button
            type="primary"
            :icon="Connection"
            :loading="workflowActionBusy"
            @click="continueWorkflow('APPROVE')"
          >批准 v{{ displayedPlanVersion }} 并启动 {{ executionPlan?.assignments.length || 0 }} 个分支</el-button>
        </div>
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

    <el-dialog v-model="workflowPauseDialog" title="安全暂停工作流" width="min(520px, 94vw)" destroy-on-close>
      <p class="workflow-pause-dialog-copy">运行会在当前 Agent 节点完成并提交检查点后暂停。</p>
      <el-form label-position="top" @submit.prevent="submitWorkflowPause">
        <el-form-item label="暂停原因" required>
          <el-input
            v-model="workflowPauseFormReason"
            type="textarea"
            :rows="4"
            maxlength="1000"
            show-word-limit
            placeholder="例如：需要补充数据驻留边界后再继续"
            aria-label="暂停原因"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="workflowPauseDialog = false">取消</el-button>
        <el-button
          type="primary"
          :icon="VideoPause"
          :loading="workflowPauseSubmitting"
          :disabled="workflowPauseFormReason.trim().length < 3"
          @click="submitWorkflowPause"
        >请求安全暂停</el-button>
      </template>
    </el-dialog>

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
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleCheck, CircleClose, Clock, Connection, Delete, Edit, Loading, MagicStick, Plus, RefreshRight, VideoPause, View } from '@element-plus/icons-vue'
import { api, apiBaseURL } from '../api/client'
import type { Agent, Project, ProjectActivity, ProjectMember, Task, WorkflowEvent, WorkflowRun, WorkflowSagaStep } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import 'element-plus/es/components/message-box/style/css.mjs'
import axios from 'axios'
import { confirmDestructiveAction } from '../utils/confirm'
import { useWorkflowEventStream } from '../composables/useWorkflowEventStream'

interface WorkflowAssignment {
  role: string
  objective: string
  deliverable: string
  depends_on?: string[]
}

interface WorkflowExecutionPlan {
  objective: string
  rationale: string
  assignments: WorkflowAssignment[]
  success_criteria: string[]
}

interface WorkflowPlanRevision {
  version: number
  plan: WorkflowExecutionPlan
  feedback: string
  created_at: string
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

type BranchRuntimeStatus = 'waiting' | 'running' | 'retrying' | 'completed' | 'restored' | 'failed' | 'paused' | 'cancelling' | 'cancelled'

interface BranchRuntimeState {
  status: BranchRuntimeStatus
  attempt: number
  retryDelaySeconds: number
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
const workflowParentId = ref<number | null>(null)
const workflowRetryFromNode = ref('')
const workflowRetrySequence = ref(0)
const workflowPauseRequestedAt = ref<string | null>(null)
const workflowPauseReason = ref('')
const workflowInterventionCount = ref(0)
const workflowStatus = ref('')
const workflowCurrentNode = ref('')
const workflowError = ref('')
const workflowFeedback = ref('')
const selectedPlanVersion = ref(1)
const workflowEvents = ref<WorkflowEvent[]>([])
const activeHandoffRoles = ref<string[]>([])
const workflowSagaSteps = ref<WorkflowSagaStep[]>([])
const workflowActionBusy = ref(false)
const running = ref(false)
const members = ref<ProjectMember[]>([])
const activities = ref<ProjectActivity[]>([])
const memberDialog = ref(false)
const memberForm = reactive<{ email: string; role: 'editor' | 'viewer' }>({ email: '', role: 'viewer' })
const workflowRequestId = ref(crypto.randomUUID())
const projectEditDialog = ref(false)
const projectSaving = ref(false)
const workflowPauseDialog = ref(false)
const workflowPauseSubmitting = ref(false)
const workflowPauseFormReason = ref('')
const workflowPauseRequestId = ref(crypto.randomUUID())
const projectForm = reactive({ name: '', description: '', status: 'ACTIVE' })
const activeWorkflowDocument = ref('PRD')
const workflowStages = ['需求分析', '产品方案', '架构设计', '动态规划', '计划审批', '专业分支', '质量门禁', '项目计划', '测试方案', '项目报告']
const workflowConnectionDetail = ref('')
const {
  connectionState: workflowConnectionState,
  lastEventId: lastWorkflowEventId,
  start: startWorkflowEventStream,
  restart: restartWorkflowEventStream,
  stop: stopWorkflowEventStream,
  clear: clearWorkflowEventStream,
  dispose: disposeWorkflowEventStream
} = useWorkflowEventStream({
  onEvent: handleWorkflowEvent,
  onConnectionState: (state, detail) => {
    workflowConnectionDetail.value = state === 'reconnecting' && detail.retryInMs
      ? `${Math.max(1, Math.ceil(detail.retryInMs / 1000))} 秒后自动重连`
      : ''
  }
})
const workflowStreamActive = computed(() => ['QUEUED', 'RUNNING', 'CANCELLING', 'COMPENSATING'].includes(workflowStatus.value))
const workflowPausePending = computed(() => workflowStatus.value === 'RUNNING' && Boolean(workflowPauseRequestedAt.value))
const workflowOperatorPaused = computed(() => workflowStatus.value === 'PAUSED' && Boolean(workflowPauseRequestedAt.value))
const workflowPlanReview = computed(() => (
  workflowStatus.value === 'PAUSED'
  && workflowCurrentNode.value === 'plan_review'
  && !workflowOperatorPaused.value
))
const workflowFeedbackRequired = computed(() => workflowOperatorPaused.value || workflowCurrentNode.value === 'quality_review')
const workflowApprovalTitle = computed(() => {
  if (workflowOperatorPaused.value) return `运行已在“${workflowStageLabel(workflowCurrentNode.value)}”安全暂停`
  if (workflowPlanReview.value) return `执行计划 v${displayedPlanVersion.value} 等待批准`
  return workflowCurrentNode.value === 'quality_review' ? '质量门禁等待修订意见' : '最终报告等待人工确认'
})
const workflowApprovalDescription = computed(() => {
  if (workflowOperatorPaused.value) return '恢复指令会写入运行上下文，并传递给后续全部 Agent。'
  if (workflowPlanReview.value) return '核对角色、依赖、交付物和成功标准。批准后将按依赖波次启动专业 Agent；需要调整时请填写具体意见。'
  return workflowCurrentNode.value === 'quality_review'
    ? '说明需要补充的证据、取舍或负责人；Agent 将重新执行未通过的专业分支。'
    : '确认当前需求、架构、任务和测试产物后继续生成最终报告。'
})
const workflowFeedbackPlaceholder = computed(() => {
  if (workflowOperatorPaused.value) return '输入恢复指令，后续 Agent 将基于该约束继续执行'
  if (workflowPlanReview.value) return '需要重新规划时，说明缺失角色、目标、交付物或成功标准'
  return workflowCurrentNode.value === 'quality_review' ? '输入具体修订意见' : '补充最终报告需要强调的内容（可选）'
})
const workflowContinueLabel = computed(() => {
  if (workflowOperatorPaused.value) return '应用指令并继续'
  return workflowCurrentNode.value === 'quality_review' ? '提交修订意见' : '确认并生成报告'
})
const workflowRunLocked = computed(() => [
  'QUEUED',
  'RUNNING',
  'CANCELLING',
  'COMPENSATING',
  'COMPENSATION_FAILED',
  'PAUSED'
].includes(workflowStatus.value))
const workflowConnectionNotice = computed(() => {
  if (!workflowStreamActive.value) return ''
  if (workflowConnectionState.value === 'connected') {
    return '实时进度已连接，刷新或离开页面不会中断后台 Agent。'
  }
  if (workflowConnectionState.value === 'reconnecting') {
    return `实时进度暂时中断，后台 Agent 仍在执行。${workflowConnectionDetail.value}`
  }
  if (workflowConnectionState.value === 'closed') {
    return '实时进度连接已关闭，后台 Agent 仍在执行。'
  }
  return '正在恢复实时进度，后台 Agent 会继续执行。'
})
const planRevisions = computed<WorkflowPlanRevision[]>(() => {
  const revisions = workflowState.value?.plan_revisions
  if (Array.isArray(revisions)) {
    const valid = revisions.filter((item): item is WorkflowPlanRevision => (
      Number.isInteger(item?.version)
      && item.version > 0
      && item.plan
      && Array.isArray(item.plan.assignments)
      && Array.isArray(item.plan.success_criteria)
    ))
    if (valid.length) return [...valid].sort((left, right) => left.version - right.version)
  }
  const plan = workflowState.value?.execution_plan
  if (!plan || !Array.isArray(plan.assignments) || !Array.isArray(plan.success_criteria)) return []
  return [{
    version: Number(workflowState.value?.plan_version) || 1,
    plan: plan as WorkflowExecutionPlan,
    feedback: '',
    created_at: ''
  }]
})
const latestPlanVersion = computed(() => planRevisions.value[planRevisions.value.length - 1]?.version || 1)
const planVersionOptions = computed(() => planRevisions.value.map((revision) => ({
  label: `v${revision.version}`,
  value: revision.version
})))
const displayedPlanVersion = computed(() => {
  if (workflowPlanReview.value && selectedPlanVersion.value) return selectedPlanVersion.value
  return Number(workflowState.value?.plan_version) || latestPlanVersion.value
})
const selectedPlanRevision = computed(() => (
  planRevisions.value.find((revision) => revision.version === displayedPlanVersion.value) || null
))
const previousPlanRevision = computed(() => {
  const selectedIndex = planRevisions.value.findIndex((revision) => revision.version === displayedPlanVersion.value)
  return selectedIndex > 0 ? planRevisions.value[selectedIndex - 1] : null
})
const planVersionChanges = computed(() => {
  const current = selectedPlanRevision.value?.plan
  const previous = previousPlanRevision.value?.plan
  if (!current || !previous) return []
  const changes: string[] = []
  if (current.objective !== previous.objective) changes.push('调整总体目标')
  if (current.rationale !== previous.rationale) changes.push('更新编排理由')
  const currentByRole = new Map(current.assignments.map((assignment) => [assignment.role, assignment]))
  const previousByRole = new Map(previous.assignments.map((assignment) => [assignment.role, assignment]))
  const addedRoles = [...currentByRole.keys()].filter((role) => !previousByRole.has(role))
  const removedRoles = [...previousByRole.keys()].filter((role) => !currentByRole.has(role))
  if (addedRoles.length) changes.push(`新增角色：${addedRoles.map(specialistRoleLabel).join('、')}`)
  if (removedRoles.length) changes.push(`移除角色：${removedRoles.map(specialistRoleLabel).join('、')}`)
  const updatedRoles = [...currentByRole.keys()].filter((role) => {
    const prior = previousByRole.get(role)
    const next = currentByRole.get(role)
    return prior && next && (
      prior.objective !== next.objective
      || prior.deliverable !== next.deliverable
      || JSON.stringify(prior.depends_on || []) !== JSON.stringify(next.depends_on || [])
    )
  })
  if (updatedRoles.length) changes.push(`更新分支：${updatedRoles.map(specialistRoleLabel).join('、')}`)
  const addedCriteria = current.success_criteria.filter((criterion) => !previous.success_criteria.includes(criterion))
  const removedCriteria = previous.success_criteria.filter((criterion) => !current.success_criteria.includes(criterion))
  if (addedCriteria.length) changes.push(`新增 ${addedCriteria.length} 项成功标准`)
  if (removedCriteria.length) changes.push(`移除 ${removedCriteria.length} 项成功标准`)
  return changes
})
const executionPlan = computed<WorkflowExecutionPlan | null>(() => {
  if (workflowPlanReview.value && selectedPlanRevision.value) return selectedPlanRevision.value.plan
  const plan = workflowState.value?.execution_plan
  return plan && Array.isArray(plan.assignments) ? plan as WorkflowExecutionPlan : null
})
const executionPlanWaves = computed(() => {
  const plan = executionPlan.value
  if (!plan) return []
  let remaining = [...plan.assignments]
  const resolved = new Set<string>()
  const waves: Array<{ number: number; assignments: WorkflowAssignment[] }> = []
  while (remaining.length) {
    const assignments = remaining.filter((assignment) => (
      (assignment.depends_on || []).every((role) => resolved.has(role))
    ))
    if (!assignments.length) return [{ number: 1, assignments: plan.assignments }]
    waves.push({ number: waves.length + 1, assignments })
    const waveRoles = new Set(assignments.map((assignment) => assignment.role))
    assignments.forEach((assignment) => resolved.add(assignment.role))
    remaining = remaining.filter((assignment) => !waveRoles.has(assignment.role))
  }
  return waves
})
const executionPlanTopologyLabel = computed(() => {
  const branchCount = executionPlan.value?.assignments.length || 0
  const waveCount = executionPlanWaves.value.length
  return waveCount > 1 ? `${branchCount} 个分支 · ${waveCount} 波` : `${branchCount} 个并行分支`
})
const executionPlanApprovalLabel = computed(() => {
  if (!workflowState.value?.require_plan_approval) return ''
  if (workflowState.value?.plan_approved) return '已批准'
  if (workflowCurrentNode.value === 'planning' && ['QUEUED', 'RUNNING'].includes(workflowStatus.value)) return '重新规划中'
  return '待审批'
})
const executionPlanApprovalType = computed<'success' | 'warning' | 'info'>(() => {
  if (workflowState.value?.plan_approved) return 'success'
  return workflowCurrentNode.value === 'planning' ? 'info' : 'warning'
})
const specialistHandoffs = computed<WorkflowHandoff[]>(() => {
  const handoffs = workflowState.value?.specialist_handoffs
  return Array.isArray(handoffs) ? handoffs as WorkflowHandoff[] : []
})
const branchRuntimeByRole = computed(() => {
  const states = new Map<string, BranchRuntimeState>()
  for (const assignment of executionPlan.value?.assignments || []) {
    states.set(assignment.role, { status: 'waiting', attempt: 0, retryDelaySeconds: 0 })
  }
  const updateState = (role: string, update: Partial<BranchRuntimeState>) => {
    if (!states.has(role)) return
    states.set(role, {
      ...states.get(role)!,
      ...update
    })
  }
  for (const event of [...workflowEvents.value].sort((left, right) => left.id - right.id)) {
    const attempt = Number(event.payload?.branch_attempt) || 0
    if (event.event_type === 'WAVE_RESTORED') {
      const roles = Array.isArray(event.payload?.roles) ? event.payload.roles : []
      for (const role of roles) {
        if (typeof role === 'string') updateState(role, { status: 'restored', attempt })
      }
      continue
    }
    const role = typeof event.payload?.role === 'string' ? event.payload.role : ''
    if (!role) continue
    if (event.event_type === 'BRANCH_STARTED') {
      updateState(role, { status: 'running', attempt, retryDelaySeconds: 0 })
    } else if (event.event_type === 'BRANCH_RETRY_SCHEDULED') {
      updateState(role, {
        status: 'retrying',
        attempt,
        retryDelaySeconds: Number(event.payload?.retry_delay_seconds) || 0
      })
    } else if (event.event_type === 'BRANCH_FAILED') {
      updateState(role, {
        status: event.payload?.will_retry === true ? 'retrying' : 'failed',
        attempt
      })
    } else if (event.event_type === 'BRANCH_COMPLETED') {
      updateState(role, { status: 'completed', attempt, retryDelaySeconds: 0 })
    }
  }
  for (const assignment of executionPlan.value?.assignments || []) {
    const current = states.get(assignment.role)!
    if (current.status === 'waiting' && handoffFor(assignment.role)) {
      states.set(assignment.role, { ...current, status: 'completed' })
      continue
    }
    if (!['running', 'retrying'].includes(current.status)) continue
    if (workflowStatus.value === 'PAUSED') states.set(assignment.role, { ...current, status: 'paused' })
    else if (workflowStatus.value === 'CANCELLING') states.set(assignment.role, { ...current, status: 'cancelling' })
    else if (workflowStatus.value === 'CANCELLED') states.set(assignment.role, { ...current, status: 'cancelled' })
    else if (workflowStatus.value === 'FAILED') states.set(assignment.role, { ...current, status: 'failed' })
  }
  return states
})
const executionPlanRuntimeSummary = computed(() => {
  const assignments = executionPlan.value?.assignments || []
  if (!assignments.length) return ''
  const states = assignments.map((assignment) => branchRuntimeState(assignment.role).status)
  const completed = states.filter((status) => ['completed', 'restored'].includes(status)).length
  const running = states.filter((status) => status === 'running').length
  const retrying = states.filter((status) => status === 'retrying').length
  const failed = states.filter((status) => status === 'failed').length
  if (!completed && !running && !retrying && !failed) return ''
  const details = [
    completed ? `${completed}/${assignments.length} 已交接` : '',
    running ? `${running} 执行中` : '',
    retrying ? `${retrying} 待重试` : '',
    failed ? `${failed} 失败` : ''
  ].filter(Boolean)
  return details.join(' · ')
})
const executionPlanRuntimeType = computed<'primary' | 'success' | 'warning' | 'info' | 'danger'>(() => {
  const statuses = [...branchRuntimeByRole.value.values()].map((state) => state.status)
  if (statuses.some((status) => status === 'failed')) return 'danger'
  if (statuses.some((status) => ['retrying', 'paused', 'cancelling'].includes(status))) return 'warning'
  if (statuses.some((status) => status === 'running')) return 'primary'
  if (statuses.length && statuses.every((status) => ['completed', 'restored'].includes(status))) return 'success'
  return 'info'
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
  if (executionPlan.value) {
    completed += 1
    if (!workflowState.value?.require_plan_approval || workflowState.value?.plan_approved) completed += 1
  }
  if (specialistHandoffs.value.length) completed += 1
  if (qualityGate.value?.passed) completed += 1
  return completed
})
const workflowStatusLabel = computed(() => {
  if (workflowPausePending.value) return '等待安全暂停'
  if (workflowStatus.value === 'PAUSED') {
    if (workflowOperatorPaused.value) return '人工干预中'
    if (workflowCurrentNode.value === 'plan_review') return '等待计划审批'
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
}[workflowPausePending.value ? 'PAUSED' : workflowStatus.value] as 'primary' | 'success' | 'warning' | 'info' | 'danger' | undefined))

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
    plan_review: '计划审批',
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
    NODE_FAILED: '节点执行失败',
    PLAN_CREATED: '计划已生成',
    PLAN_APPROVED: '计划已批准',
    PLAN_REVISION_REQUESTED: '要求重新规划',
    WAVE_STARTED: '执行波次已启动',
    WAVE_COMPLETED: '执行波次已完成',
    WAVE_CHECKPOINTED: '执行波次已保存',
    WAVE_RESTORED: '执行波次已恢复',
    BRANCH_STARTED: '分支已启动',
    BRANCH_COMPLETED: '分支已交接',
    BRANCH_FAILED: '分支执行失败',
    BRANCH_RETRY_SCHEDULED: '分支准备重试',
    QUALITY_GATE_PASSED: '质量门禁通过',
    QUALITY_GATE_FAILED: '质量门禁未通过',
    REVISION_REQUESTED: '请求自动修订',
    RETRY_SCHEDULED: '自动重试',
    RETRY_CREATED: '已创建重试运行',
    RETRY_QUEUED: '检查点重试入队',
    PAUSE_REQUESTED: '已请求安全暂停',
    PAUSE_SKIPPED: '运行结束，暂停未生效',
    INTERVENTION_APPLIED: '已应用恢复指令',
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

function branchRuntimeState(role: string): BranchRuntimeState {
  return branchRuntimeByRole.value.get(role)
    || { status: 'waiting', attempt: 0, retryDelaySeconds: 0 }
}

function branchRuntimeLabel(role: string) {
  return {
    waiting: '等待执行',
    running: '执行中',
    retrying: '等待重试',
    completed: '已交接',
    restored: '检查点恢复',
    failed: '执行失败',
    paused: '已暂停',
    cancelling: '正在取消',
    cancelled: '已取消'
  }[branchRuntimeState(role).status]
}

function branchRuntimeMeta(role: string) {
  const state = branchRuntimeState(role)
  const handoff = handoffFor(role)
  return [
    state.attempt > 0 ? `A${state.attempt}` : '',
    handoff ? `R${handoff.revision_round}` : '',
    state.retryDelaySeconds > 0 ? `${state.retryDelaySeconds}s` : ''
  ].filter(Boolean).join(' · ')
}

function branchRuntimeIcon(status: BranchRuntimeStatus) {
  return {
    waiting: Clock,
    running: Loading,
    retrying: RefreshRight,
    completed: CircleCheck,
    restored: RefreshRight,
    failed: CircleClose,
    paused: VideoPause,
    cancelling: Loading,
    cancelled: CircleClose
  }[status]
}

function waveRuntimeSummary(assignments: WorkflowAssignment[]) {
  const states = assignments.map((assignment) => branchRuntimeState(assignment.role).status)
  if (states.every((status) => status === 'waiting')) {
    return assignments.length > 1 ? `${assignments.length} 个 Agent 并行` : '单 Agent 执行'
  }
  const completed = states.filter((status) => ['completed', 'restored'].includes(status)).length
  const active = states.filter((status) => ['running', 'retrying', 'paused', 'cancelling'].includes(status)).length
  const failed = states.filter((status) => ['failed', 'cancelled'].includes(status)).length
  return [
    `${completed}/${assignments.length} 已完成`,
    active ? `${active} 处理中` : '',
    failed ? `${failed} 异常` : ''
  ].filter(Boolean).join(' · ')
}

async function openHandoff(role: string) {
  if (!handoffFor(role)) return
  activeHandoffRoles.value = [role]
  await nextTick()
  document.getElementById(`handoff-${role}`)?.scrollIntoView({ block: 'nearest' })
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
    'project.create': '项目已创建',
    'project.update': '项目配置已更新',
    'project.member_upsert': '项目成员已更新',
    'project.member_remove': '项目成员已移除',
    'task.create': '创建了任务',
    'task.update': '更新了任务',
    'task.comment': '添加了任务评论',
    'meeting.tasks_create': '会议行动项已转为任务',
    'workflow.artifact_publish': '工作流产物已发布',
    'workflow.queued': '工作流已入队',
    'workflow.continue': '工作流已继续',
    'workflow.plan_approved': '执行计划已批准',
    'workflow.plan_revision_requested': '执行计划要求重做',
    'workflow.pause_requested': '工作流已请求安全暂停',
    'workflow.operator_paused': '工作流已在安全节点暂停',
    'workflow.retry': '工作流已重试',
    'workflow.cancel_requested': '工作流已请求取消',
    'workflow.compensation_retry': '工作流回滚已重试'
  }[action] || action
}

function applyWorkflow(workflow: WorkflowRun) {
  const enteredTerminalState = ['COMPLETED', 'FAILED', 'CANCELLED'].includes(workflow.status)
    && workflowStatus.value !== workflow.status
  const previousPlanVersion = Number(workflowState.value?.plan_version) || 0
  if (workflowCurrentNode.value !== workflow.current_node) workflowFeedback.value = ''
  workflowId.value = workflow.workflow_id
  workflowParentId.value = workflow.parent_workflow_id
  workflowRetryFromNode.value = workflow.retry_from_node
  workflowRetrySequence.value = workflow.retry_sequence
  workflowPauseRequestedAt.value = workflow.pause_requested_at || null
  workflowPauseReason.value = workflow.pause_reason || ''
  workflowInterventionCount.value = workflow.intervention_count || 0
  workflowStatus.value = workflow.status
  workflowCurrentNode.value = workflow.current_node
  workflowState.value = workflow.state
  const nextRevisions = Array.isArray(workflow.state?.plan_revisions) ? workflow.state.plan_revisions : []
  const nextPlanVersion = Number(workflow.state?.plan_version)
    || Math.max(0, ...nextRevisions.map((item: { version?: number }) => Number(item?.version) || 0))
    || (workflow.state?.execution_plan ? 1 : 0)
  const availableVersions = new Set(nextRevisions.map((item: { version?: number }) => Number(item?.version)))
  if (
    nextPlanVersion > previousPlanVersion
    || (availableVersions.size && !availableVersions.has(selectedPlanVersion.value))
  ) {
    selectedPlanVersion.value = nextPlanVersion || 1
  }
  workflowError.value = workflow.error
  if (enteredTerminalState) workflowRequestId.value = crypto.randomUUID()
}

function openSourceWorkflow() {
  if (!workflowParentId.value) return
  void router.push({ path: '/traces', query: { run: String(workflowParentId.value) } })
}

async function refreshWorkflow() {
  if (!workflowId.value) return
  const workflowResponse = await api.get<WorkflowRun>(`/workflow/${workflowId.value}`)
  applyWorkflow(workflowResponse.data)
}

async function refreshWorkflowSagaSteps() {
  if (!workflowId.value) return
  const sagaResponse = await api.get<WorkflowSagaStep[]>(`/workflow/${workflowId.value}/saga-steps`)
  workflowSagaSteps.value = sagaResponse.data
}

async function loadWorkflowEventHistory(id: number): Promise<number> {
  const { data } = await api.get<WorkflowEvent[]>(`/workflow/${id}/events/history`, {
    params: { limit: 100 }
  })
  workflowEvents.value = data
  return data[data.length - 1]?.id || 0
}

function watchWorkflowEvents(cursor = lastWorkflowEventId.value) {
  if (!workflowId.value) return
  if (!workflowStreamActive.value) {
    stopWorkflowEventStream()
    return
  }
  startWorkflowEventStream({
    eventsUrl: `${apiBaseURL}/workflow/${workflowId.value}/events`,
    lastEventId: cursor
  })
}

async function handleWorkflowEvent(event: WorkflowEvent): Promise<boolean> {
  if (event.workflow_id !== workflowId.value) return true
  if (!workflowEvents.value.some((item) => item.id === event.id)) {
    workflowEvents.value.push(event)
  }
  await refreshWorkflow()
  if (
    event.event_type.startsWith('SAGA_')
    || ['COMPENSATION_STARTED', 'COMPENSATION_FAILED', 'COMPENSATED'].includes(event.event_type)
  ) {
    await refreshWorkflowSagaSteps()
  }
  if (!workflowStreamActive.value) workflowRequestId.value = crypto.randomUUID()
  return workflowStreamActive.value
}

function restartWorkflowEvents() {
  if (!workflowId.value || !workflowStreamActive.value) return
  restartWorkflowEventStream()
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
    const [sagaResponse, eventCursor] = await Promise.all([
      api.get<WorkflowSagaStep[]>(`/workflow/${latestWorkflow.workflow_id}/saga-steps`),
      loadWorkflowEventHistory(latestWorkflow.workflow_id)
    ])
    workflowSagaSteps.value = sagaResponse.data
    watchWorkflowEvents(eventCursor)
  } else {
    workflowState.value = null
    workflowId.value = null
    workflowEvents.value = []
    workflowSagaSteps.value = []
    clearWorkflowEventStream()
  }
}

async function retryCompensation() {
  if (!workflowId.value) return
  workflowActionBusy.value = true
  try {
    const { data } = await api.post<WorkflowRun>(`/workflow/${workflowId.value}/retry-compensation`)
    applyWorkflow(data)
    await refreshWorkflowSagaSteps()
    const cursor = await loadWorkflowEventHistory(data.workflow_id)
    watchWorkflowEvents(cursor)
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
      require_plan_approval: true,
      request_id: workflowRequestId.value
    }, { suppressErrorToast: true })
    workflowEvents.value = []
    applyWorkflow(data)
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

function openWorkflowPauseDialog() {
  if (!workflowId.value || workflowPausePending.value) return
  workflowPauseFormReason.value = ''
  workflowPauseRequestId.value = crypto.randomUUID()
  workflowPauseDialog.value = true
}

async function submitWorkflowPause() {
  if (!workflowId.value || workflowPauseFormReason.value.trim().length < 3) return
  workflowPauseSubmitting.value = true
  try {
    const { data } = await api.post<WorkflowRun>(`/workflow/${workflowId.value}/pause`, {
      request_id: workflowPauseRequestId.value,
      reason: workflowPauseFormReason.value.trim()
    })
    applyWorkflow(data)
    workflowPauseDialog.value = false
    const cursor = await loadWorkflowEventHistory(data.workflow_id)
    watchWorkflowEvents(cursor)
    ElMessage.success(data.status === 'PAUSED' ? '工作流已安全暂停' : '安全暂停请求已提交')
  } finally {
    workflowPauseSubmitting.value = false
  }
}

async function continueWorkflow(decision?: 'APPROVE' | 'REVISE') {
  if (!workflowId.value) return
  const operatorResume = workflowOperatorPaused.value
  if (workflowPlanReview.value && !decision) return
  if (decision === 'REVISE' && !workflowFeedback.value.trim()) return
  workflowActionBusy.value = true
  try {
    const feedback = workflowFeedback.value.trim()
      || (decision === 'APPROVE' ? '' : '人工确认通过，请生成最终项目报告。')
    const { data } = await api.post<WorkflowRun>('/workflow/continue', {
      workflow_id: workflowId.value,
      human_feedback: feedback,
      decision,
      plan_version: workflowPlanReview.value ? displayedPlanVersion.value : undefined
    })
    workflowFeedback.value = ''
    applyWorkflow(data)
    const cursor = await loadWorkflowEventHistory(data.workflow_id)
    watchWorkflowEvents(cursor)
    if (operatorResume) ElMessage.success('恢复指令已应用')
    else if (decision === 'APPROVE') ElMessage.success(`执行计划 v${displayedPlanVersion.value} 已批准，专业分支开始执行`)
    else if (decision === 'REVISE') ElMessage.success('重新规划要求已提交')
    else ElMessage.success('工作流已继续')
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
    await refreshWorkflowSagaSteps()
    const cursor = await loadWorkflowEventHistory(data.workflow_id)
    watchWorkflowEvents(cursor)
    await auth.fetchMe()
  } finally {
    workflowActionBusy.value = false
  }
}

async function retryWorkflow() {
  if (!workflowId.value) return
  const sourceWorkflowId = workflowId.value
  try {
    await ElMessageBox.confirm(
      `失败运行 #${sourceWorkflowId} 将保持只读，并从“${workflowStageLabel(workflowCurrentNode.value)}”检查点创建一条新运行。`,
      '创建检查点重试',
      {
        type: 'warning',
        confirmButtonText: '创建重试运行',
        cancelButtonText: '取消'
      }
    )
  } catch {
    return
  }
  workflowActionBusy.value = true
  try {
    const { data } = await api.post<WorkflowRun>(`/workflow/${sourceWorkflowId}/retry`, {
      request_id: crypto.randomUUID()
    })
    applyWorkflow(data)
    workflowSagaSteps.value = []
    await refreshWorkflowSagaSteps()
    const cursor = await loadWorkflowEventHistory(data.workflow_id)
    watchWorkflowEvents(cursor)
    await auth.fetchMe()
    ElMessage.success(`已创建检查点重试运行 #${data.workflow_id}`)
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
onBeforeUnmount(disposeWorkflowEventStream)
</script>

<style scoped>
.agent-row {
  min-width: 0;
}

.agent-row span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.workflow-steps {
  min-width: 960px;
}

.workflow-steps :deep(.el-step__title) {
  flex-shrink: 0;
  white-space: nowrap;
}

.workflow-steps :deep(.el-step.is-simple:not(:last-of-type) .el-step__title) {
  max-width: none;
}

.workflow-connection-notice {
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 8px 10px;
  border-left: 3px solid var(--color-primary);
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-secondary-text);
  font-size: 12px;
  line-height: 1.5;
}

.workflow-connection-notice.reconnecting {
  border-left-color: var(--color-warning);
  background: #fff7ed;
}

.workflow-connection-notice span {
  min-width: 0;
  flex: 1;
}

.workflow-connection-notice .el-button {
  margin-left: auto;
}

.workflow-retry-lineage {
  display: flex;
  min-height: 44px;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding: 10px 12px;
  border-left: 3px solid var(--color-primary);
  background: var(--color-primary-soft);
  color: var(--color-secondary-text);
}

.workflow-retry-lineage > .el-icon {
  flex: 0 0 auto;
  color: var(--color-primary);
  font-size: 18px;
}

.workflow-retry-lineage > div {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
}

.workflow-retry-lineage strong {
  color: var(--color-foreground);
  font-size: 13px;
}

.workflow-retry-lineage span {
  overflow-wrap: anywhere;
  font-size: 12px;
  line-height: 1.5;
}

.workflow-intervention-count {
  margin-left: 8px;
}

.workflow-intervention-notice {
  display: flex;
  min-height: 44px;
  align-items: flex-start;
  gap: 10px;
  margin-top: 12px;
  padding: 10px 12px;
  border-left: 3px solid var(--color-warning);
  background: #fffbeb;
  color: var(--color-secondary-text);
}

.workflow-intervention-notice > .el-icon {
  margin-top: 2px;
  flex: 0 0 auto;
  color: var(--color-warning);
  font-size: 18px;
}

.workflow-intervention-notice > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.workflow-intervention-notice strong {
  color: var(--color-foreground);
  font-size: 13px;
}

.workflow-intervention-notice span,
.workflow-intervention-notice small,
.workflow-pause-reason {
  overflow-wrap: anywhere;
  font-size: 12px;
  line-height: 1.5;
}

.workflow-intervention-notice small,
.workflow-pause-reason {
  color: var(--color-muted-text);
}

.workflow-pause-dialog-copy {
  margin: 0 0 16px;
  color: var(--color-secondary-text);
  font-size: 13px;
  line-height: 1.6;
}

.workflow-orchestration {
  margin: 18px 0;
  padding: 16px 0;
  border-block: 1px solid var(--color-border);
}

.plan-version-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--color-border);
}

.plan-version-toolbar > div:first-child {
  display: grid;
  gap: 3px;
}

.plan-version-toolbar strong {
  font-size: 13px;
}

.plan-version-toolbar span {
  color: var(--color-muted-text);
  font-size: 11px;
}

.plan-version-selector {
  max-width: 60%;
  overflow-x: auto;
  scrollbar-width: thin;
}

.plan-version-selector :deep(.el-segmented) {
  min-width: max-content;
}

.orchestration-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.orchestration-copy {
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

.orchestration-copy small {
  display: block;
  max-width: 900px;
  margin-top: 5px;
  color: var(--color-muted-text);
  font-size: 12px;
  line-height: 1.5;
}

.orchestration-tags {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.plan-version-diff {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border-left: 3px solid var(--color-primary);
  background: var(--color-primary-soft);
}

.plan-version-diff strong,
.plan-version-diff span,
.plan-version-diff li,
.plan-version-diff p {
  font-size: 12px;
  line-height: 1.5;
}

.plan-version-diff ul {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 22px;
  margin: 0;
  padding-left: 18px;
  color: var(--color-secondary-text);
}

.plan-version-diff p {
  margin: 0;
  color: var(--color-secondary-text);
  overflow-wrap: anywhere;
}

.plan-success-criteria {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 12px;
  padding: 11px 12px;
  border-top: 1px solid var(--color-border);
  background: #f6f8fa;
}

.plan-success-criteria strong {
  font-size: 12px;
}

.plan-success-criteria ul {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 22px;
  margin: 0;
  padding-left: 18px;
  color: var(--color-secondary-text);
  font-size: 12px;
  line-height: 1.55;
}

.orchestration-waves {
  border-top: 1px solid var(--color-border);
}

.orchestration-wave + .orchestration-wave {
  border-top: 1px solid var(--color-border);
}

.orchestration-wave-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 34px;
  padding: 7px 8px;
  background: #f6f8fa;
}

.orchestration-wave-heading strong {
  color: var(--color-primary);
  font-size: 12px;
}

.orchestration-wave-heading span {
  color: var(--color-muted-text);
  font-size: 11px;
}

.orchestration-branches {
  min-width: 0;
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

.orchestration-branch-copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.orchestration-branch-row strong {
  font-size: 13px;
}

.branch-objective,
.branch-dependencies {
  color: var(--color-muted-text);
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.branch-dependencies {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 6px;
  color: var(--color-secondary-text);
}

.branch-dependency-label {
  color: var(--color-muted-text);
  font-weight: 600;
}

.branch-runtime-actions {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.branch-runtime-status {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  gap: 5px;
  padding: 4px 7px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-secondary-text);
  font-size: 11px;
  font-weight: 650;
  line-height: 1.25;
  white-space: nowrap;
}

.branch-runtime-status .el-icon {
  flex: 0 0 auto;
  font-size: 14px;
}

.branch-runtime-status small {
  color: currentColor;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  opacity: 0.78;
}

.branch-runtime-status.is-running,
.branch-runtime-status.is-restored {
  border-color: #bfdbfe;
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.branch-runtime-status.is-retrying,
.branch-runtime-status.is-paused,
.branch-runtime-status.is-cancelling {
  border-color: #fde68a;
  background: #fffbeb;
  color: var(--color-warning);
}

.branch-runtime-status.is-completed {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: var(--color-success);
}

.branch-runtime-status.is-failed {
  border-color: #fecaca;
  background: #fef2f2;
  color: var(--color-danger);
}

.branch-runtime-status.is-cancelled {
  background: #f6f8fa;
  color: var(--color-muted-text);
}

.branch-runtime-status.is-running .el-icon,
.branch-runtime-status.is-cancelling .el-icon {
  animation: branch-status-spin 1.1s linear infinite;
}

.branch-handoff-button {
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
}

@keyframes branch-status-spin {
  to { transform: rotate(360deg); }
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

.workflow-approval-gate.plan-review {
  grid-template-columns: minmax(240px, 0.9fr) minmax(320px, 1.3fr) minmax(250px, auto);
}

.workflow-approval-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.workflow-approval-actions .el-button {
  min-height: 40px;
  margin-left: 0;
}

@media (max-width: 900px) {
  .workflow-approval-gate {
    grid-template-columns: 1fr;
  }

  .workflow-approval-gate .el-button {
    width: 100%;
    min-height: 44px;
  }

  .workflow-approval-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .plan-version-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .plan-version-selector {
    max-width: 100%;
  }

  .plan-version-selector :deep(.el-segmented) {
    min-height: 44px;
  }
}

@media (max-width: 640px) {
  .report-panel > .page-head .inline-actions .el-button {
    min-height: 44px;
  }

  .workflow-retry-lineage {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .workflow-retry-lineage .el-button {
    width: 100%;
    min-height: 44px;
  }

  :global(.el-dialog[aria-label="安全暂停工作流"] .el-dialog__footer .el-button) {
    min-height: 44px;
  }

  .workflow-connection-notice {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .workflow-connection-notice .el-button {
    width: 100%;
    min-height: 44px;
    margin-left: 0;
  }

  .orchestration-heading {
    flex-direction: column;
  }

  .orchestration-tags {
    justify-content: flex-start;
  }

  .plan-success-criteria {
    grid-template-columns: 1fr;
  }

  .orchestration-branch-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .branch-role {
    grid-column: 1 / -1;
  }

  .orchestration-wave-heading {
    align-items: flex-start;
  }

  .branch-runtime-actions {
    align-items: flex-end;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  .branch-runtime-status.is-running .el-icon,
  .branch-runtime-status.is-cancelling .el-icon {
    animation: none;
  }
}
</style>
