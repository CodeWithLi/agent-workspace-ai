<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h2>{{ project?.name || '项目空间' }}</h2>
        <p>{{ project?.description }}</p>
      </div>
      <div class="inline-actions">
        <el-tag>{{ roleLabel(project?.current_user_role) }}</el-tag>
        <el-button v-if="project?.current_user_role !== 'viewer' && auth.hasPermission('projects:write')" :icon="MagicStick" type="primary" :loading="running" @click="runWorkflow">运行多 Agent 工作流</el-button>
      </div>
    </div>

    <el-row :gutter="20">
      <el-col :span="14">
        <h3>任务列表</h3>
        <el-table :data="tasks" class="data-table">
          <el-table-column prop="title" label="任务" min-width="180" />
          <el-table-column prop="priority" label="优先级" width="100" />
          <el-table-column prop="status" label="状态" width="120" />
        </el-table>
      </el-col>
      <el-col :span="10">
        <h3>AI员工</h3>
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
            <el-button v-if="row.role !== 'owner'" :icon="Delete" circle title="移除成员" @click="removeMemberRow(row)" />
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-if="workflowState" class="report-panel">
      <div class="page-head compact">
        <div><h3>Agent 工作流</h3><p>{{ workflowCompletedStages }} / 6 个阶段已完成</p></div>
        <el-button v-if="workflowStatus === 'PAUSED'" type="warning" @click="continueWorkflow">人工确认并继续</el-button>
      </div>
      <el-tag>{{ workflowStatus }}</el-tag>
      <div class="workflow-steps-scroll">
        <el-steps class="workflow-steps" :active="workflowCompletedStages" finish-status="success" simple>
          <el-step v-for="stage in workflowStages" :key="stage" :title="stage" />
        </el-steps>
      </div>
      <div v-if="workflowState.report" class="workflow-output">
        <h4>最终项目报告</h4>
        <MarkdownRenderer :content="String(workflowState.report)" />
      </div>
      <el-tabs v-else-if="workflowDocuments.length" v-model="activeWorkflowDocument" class="workflow-documents">
        <el-tab-pane v-for="document in workflowDocuments" :key="document.type" :label="documentLabel(document.type)" :name="document.type">
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
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Delete, MagicStick, Plus } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { Agent, Project, ProjectMember, Task, WorkflowRun } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import axios from 'axios'

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
const running = ref(false)
const members = ref<ProjectMember[]>([])
const memberDialog = ref(false)
const memberForm = reactive<{ email: string; role: 'editor' | 'viewer' }>({ email: '', role: 'viewer' })
const workflowRequestId = ref(crypto.randomUUID())
const activeWorkflowDocument = ref('PRD')
const workflowStages = ['需求分析', '产品方案', '架构设计', '项目计划', '测试方案', '项目报告']
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
  return [
    'requirement_agent',
    'product_agent',
    'architect_agent',
    'project_manager_agent',
    'tester_agent'
  ].filter((role) => completedRoles.has(role)).length
})

function documentLabel(type: string) {
  return {
    PRD: '产品需求',
    SYSTEM_DESIGN: '系统架构',
    PROJECT_PLAN: '项目计划',
    TEST_PLAN: '测试方案',
    FINAL_REPORT: '最终报告'
  }[type] || type
}

async function load() {
  const agentRequest = auth.hasPermission('agents:read')
    ? api.get<Agent[]>('/agents')
    : Promise.resolve({ data: [] as Agent[] })
  const [projectRes, taskRes, agentRes, memberRes, workflowRes] = await Promise.all([
    api.get<Project>(`/projects/${projectId}`),
    api.get<Task[]>(`/projects/${projectId}/tasks`),
    agentRequest,
    api.get<ProjectMember[]>(`/projects/${projectId}/members`),
    api.get<WorkflowRun[]>('/workflow', { params: { project_id: projectId } })
  ])
  project.value = projectRes.data
  tasks.value = taskRes.data
  agents.value = agentRes.data
  members.value = memberRes.data
  const latestWorkflow = workflowRes.data[0]
  if (latestWorkflow) {
    workflowId.value = latestWorkflow.workflow_id
    workflowStatus.value = latestWorkflow.status
    workflowState.value = latestWorkflow.state
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
    })
    workflowId.value = data.workflow_id
    workflowStatus.value = data.status
    workflowState.value = data.state
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
  const { data } = await api.post('/workflow/continue', {
    workflow_id: workflowId.value,
    human_feedback: '人工确认通过，请生成最终项目报告。'
  })
  workflowStatus.value = data.status
  workflowState.value = data.state
  if (data.status === 'COMPLETED' || data.status === 'FAILED') workflowRequestId.value = crypto.randomUUID()
}

onMounted(load)
</script>
