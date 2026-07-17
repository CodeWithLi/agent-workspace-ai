<template>
  <section class="page narrow-page">
    <div class="page-head">
      <div>
        <span class="page-kicker">数字员工团队</span>
        <h1>AI 员工</h1>
        <p>配置职责、Prompt、模型、工具权限与人工确认策略。</p>
      </div>
      <div class="inline-actions">
        <span class="page-count">{{ agents.length }} 名员工</span>
        <el-button v-if="auth.user?.role === 'admin'" :icon="DataAnalysis" @click="openEvaluation">回归评测</el-button>
      </div>
    </div>

    <div class="agent-card-grid">
      <article v-for="agent in agents" :key="agent.id" class="employee-card">
        <div class="employee-card-head">
          <div class="employee-title">
            <span class="employee-icon"><el-icon><Cpu /></el-icon></span>
            <div><h2>{{ agent.name }}</h2><span>{{ roleLabel(agent.role) }}</span></div>
          </div>
          <el-button v-if="auth.user?.role === 'admin'" class="employee-config" :icon="Setting" circle aria-label="配置 AI 员工" title="配置" @click="openConfig(agent)" />
        </div>
        <p>{{ agent.description }}</p>
        <div class="employee-meta">
          <span><small>模型</small><strong>{{ agent.model }}</strong></span>
          <span><small>人工确认</small><strong>{{ agent.human_approval_required ? '需要' : '不需要' }}</strong></span>
          <span><small>Memory</small><strong>{{ agent.memory_enable ? '启用' : '关闭' }}</strong></span>
          <span><small>版本</small><strong>v{{ agent.current_version }}</strong></span>
        </div>
        <div class="employee-tools-label"><span>已授权工具</span><small>{{ tools(agent).length }}</small></div>
        <div class="tool-tags">
          <el-tag v-for="tool in tools(agent)" :key="tool" size="small" effect="plain">{{ tool }}</el-tag>
        </div>
      </article>
    </div>

    <el-dialog v-model="configDialog" :title="`配置 ${activeAgent?.name || ''}`" width="min(720px, calc(100vw - 32px))" top="5vh" class="agent-config-dialog">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="角色配置" name="profile">
          <el-form label-position="top">
            <el-form-item label="职责说明"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" show-word-limit /></el-form-item>
            <el-form-item label="System Prompt"><el-input v-model="form.system_prompt" type="textarea" :rows="8" maxlength="12000" show-word-limit /></el-form-item>
            <el-form-item label="模型"><el-input v-model="form.model" placeholder="glm-4-flash" /></el-form-item>
            <div class="settings-switches">
              <el-form-item label="Memory"><el-switch v-model="form.memory_enable" /></el-form-item>
              <el-form-item label="知识库访问"><el-switch v-model="form.knowledge_access" /></el-form-item>
              <el-form-item label="写操作人工确认"><el-switch v-model="form.human_approval_required" /></el-form-item>
            </div>
            <el-form-item label="最大并发"><el-input-number v-model="form.concurrency_limit" :min="1" :max="100" /></el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="工具权限" name="tools">
          <el-alert type="info" show-icon :closable="false" title="工具必须同时通过代码硬白名单、数据库启停和用户角色校验。" />
          <el-table :data="agentTools" class="data-table tool-table">
            <el-table-column prop="name" label="工具" min-width="190" />
            <el-table-column label="允许角色" min-width="260">
              <template #default="{ row }">
                <el-select v-model="row.allowedRoleValues" multiple :disabled="!row.enabled" @change="updateToolRow(row)">
                  <el-option label="管理员" value="admin" />
                  <el-option label="成员" value="member" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="100">
              <template #default="{ row }"><el-switch v-model="row.enabled" @change="updateToolRow(row)" /></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="版本记录" name="versions">
          <el-table :data="agentVersions" class="data-table tool-table">
            <el-table-column label="版本" width="90">
              <template #default="{ row }">v{{ row.version }}</template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><el-tag :type="row.status === 'PUBLISHED' ? 'success' : row.status === 'DRAFT' ? 'warning' : 'info'" size="small">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="model" label="模型" min-width="130" />
            <el-table-column prop="release_note" label="发布说明" min-width="180" />
            <el-table-column label="操作" width="130" align="right">
              <template #default="{ row }">
                <el-button v-if="row.status === 'DRAFT'" link type="primary" @click="publishVersion(row.id)">发布</el-button>
                <el-button v-if="row.status === 'ARCHIVED'" link @click="rollbackVersion(row.version)">回滚</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-input v-model="releaseNote" class="release-note-input" placeholder="版本说明" maxlength="500" />
        <el-button @click="configDialog = false">取消</el-button>
        <el-button :loading="savingDraft" :disabled="!validForm" @click="saveDraft">保存草稿</el-button>
        <el-button type="primary" :loading="saving" :disabled="!validForm" @click="saveAgent">发布配置</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="evaluationDialog" title="Agent 回归评测" width="min(860px, calc(100vw - 32px))" top="5vh">
      <el-form label-position="top" class="evaluation-form">
        <el-row :gutter="14">
          <el-col :xs="24" :md="12"><el-form-item label="用例名称"><el-input v-model="evaluationForm.name" /></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="Agent"><el-select v-model="evaluationForm.agent_role" class="full"><el-option v-for="agent in agents" :key="agent.role" :label="agent.name" :value="agent.role" /></el-select></el-form-item></el-col>
        </el-row>
        <el-form-item label="输入"><el-input v-model="evaluationForm.input_text" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="预期关键词"><el-input v-model="evaluationForm.keywords" placeholder="使用逗号分隔" /></el-form-item>
        <el-button :icon="Plus" :disabled="!validEvaluationCase" @click="createEvaluationCase">添加用例</el-button>
      </el-form>
      <el-table :data="evaluationCases" class="data-table tool-table">
        <el-table-column prop="name" label="用例" min-width="150" />
        <el-table-column prop="agent_role" label="Agent" min-width="130" />
        <el-table-column label="预期关键词" min-width="220"><template #default="{ row }">{{ row.expected_keywords.join('、') }}</template></el-table-column>
        <el-table-column label="操作" width="80" align="right"><template #default="{ row }"><el-button link type="danger" @click="deleteEvaluationCase(row.id)">删除</el-button></template></el-table-column>
      </el-table>
      <template #footer>
        <span v-if="latestEvaluationRun" class="evaluation-result">最近：{{ latestEvaluationRun.passed_cases }}/{{ latestEvaluationRun.total_cases }}，得分 {{ (latestEvaluationRun.average_score * 100).toFixed(1) }}%</span>
        <el-button @click="evaluationDialog = false">关闭</el-button>
        <el-button type="primary" :icon="DataAnalysis" :loading="runningEvaluation" :disabled="!evaluationCases.length" @click="runEvaluation">运行评测</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Cpu, DataAnalysis, Plus, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { Agent, AgentTool, AgentVersion, EvaluationCase, EvaluationRun } from '../api/types'
import { confirmDestructiveAction } from '../utils/confirm'

interface ConfigTool extends AgentTool {
  allowedRoleValues: string[]
}

const agents = ref<Agent[]>([])
const auth = useAuthStore()
const configDialog = ref(false)
const activeTab = ref('profile')
const activeAgent = ref<Agent | null>(null)
const agentTools = ref<ConfigTool[]>([])
const agentVersions = ref<AgentVersion[]>([])
const saving = ref(false)
const savingDraft = ref(false)
const releaseNote = ref('')
const evaluationDialog = ref(false)
const evaluationCases = ref<EvaluationCase[]>([])
const latestEvaluationRun = ref<EvaluationRun | null>(null)
const runningEvaluation = ref(false)
const evaluationForm = reactive({ name: '', agent_role: '', input_text: '', keywords: '' })
const form = reactive({
  description: '',
  system_prompt: '',
  model: '',
  memory_enable: true,
  knowledge_access: true,
  human_approval_required: false,
  concurrency_limit: 4
})
const validForm = computed(() => Boolean(form.description.trim() && form.system_prompt.trim() && form.model.trim()))
const validEvaluationCase = computed(() => Boolean(
  evaluationForm.name.trim() && evaluationForm.agent_role && evaluationForm.input_text.trim() && evaluationForm.keywords.trim()
))

function tools(agent: Agent) {
  return agent.tools.split(',').map((item) => item.trim()).filter(Boolean)
}

function roleLabel(role: string) {
  return {
    product_manager: '产品与需求',
    project_manager: '项目交付',
    architect: '技术架构',
    test_engineer: '质量保障',
    meeting_summarizer: '会议协作',
    knowledge_admin: '企业知识',
    notification_secretary: '消息触达',
    operations_analyst: '运营洞察'
  }[role] || '专业 Agent'
}

async function loadAgents() {
  const { data } = await api.get<Agent[]>('/agents')
  agents.value = data
}

async function openConfig(agent: Agent) {
  activeAgent.value = agent
  activeTab.value = 'profile'
  releaseNote.value = ''
  Object.assign(form, {
    description: agent.description,
    system_prompt: agent.system_prompt,
    model: agent.model,
    memory_enable: agent.memory_enable,
    knowledge_access: agent.knowledge_access,
    human_approval_required: agent.human_approval_required,
    concurrency_limit: agent.concurrency_limit
  })
  const [toolResponse, versionResponse] = await Promise.all([
    api.get<AgentTool[]>(`/agents/${agent.id}/tools`),
    api.get<AgentVersion[]>(`/agents/${agent.id}/versions`)
  ])
  agentTools.value = toolResponse.data.map((tool) => ({
    ...tool,
    allowedRoleValues: tool.allowed_roles.split(',').map((item) => item.trim()).filter(Boolean)
  }))
  agentVersions.value = versionResponse.data
  configDialog.value = true
}

async function loadVersions() {
  if (!activeAgent.value) return
  const { data } = await api.get<AgentVersion[]>(`/agents/${activeAgent.value.id}/versions`)
  agentVersions.value = data
}

async function saveDraft() {
  if (!activeAgent.value) return
  savingDraft.value = true
  try {
    await api.post(`/agents/${activeAgent.value.id}/versions`, { ...form, release_note: releaseNote.value })
    releaseNote.value = ''
    activeTab.value = 'versions'
    await loadVersions()
    ElMessage.success('Agent 草稿已保存')
  } finally {
    savingDraft.value = false
  }
}

async function publishVersion(versionId: number) {
  if (!activeAgent.value) return
  await api.post(`/agents/${activeAgent.value.id}/versions/${versionId}/publish`)
  await Promise.all([loadAgents(), loadVersions()])
  ElMessage.success('Agent 版本已发布')
}

async function rollbackVersion(version: number) {
  if (!activeAgent.value) return
  if (!await confirmDestructiveAction(`将基于 v${version} 创建新的回滚版本，确认继续吗？`, '回滚 Agent 版本')) return
  await api.post(`/agents/${activeAgent.value.id}/versions/${version}/rollback`)
  await Promise.all([loadAgents(), loadVersions()])
  ElMessage.success(`已从 v${version} 创建回滚版本`)
}

async function openEvaluation() {
  const [casesResponse, runsResponse] = await Promise.all([
    api.get<EvaluationCase[]>('/evaluations/cases'),
    api.get<EvaluationRun[]>('/evaluations/runs')
  ])
  evaluationCases.value = casesResponse.data
  latestEvaluationRun.value = runsResponse.data[0] || null
  evaluationForm.agent_role = agents.value[0]?.role || ''
  evaluationDialog.value = true
}

async function createEvaluationCase() {
  const { data } = await api.post<EvaluationCase>('/evaluations/cases', {
    name: evaluationForm.name,
    agent_role: evaluationForm.agent_role,
    input_text: evaluationForm.input_text,
    expected_keywords: evaluationForm.keywords.split(',').map((item) => item.trim()).filter(Boolean),
    enabled: true
  })
  evaluationCases.value.push(data)
  evaluationForm.name = ''
  evaluationForm.input_text = ''
  evaluationForm.keywords = ''
}

async function deleteEvaluationCase(id: number) {
  if (!await confirmDestructiveAction('删除后无法恢复，确认删除这条评测用例吗？', '删除评测用例')) return
  await api.delete(`/evaluations/cases/${id}`)
  evaluationCases.value = evaluationCases.value.filter((item) => item.id !== id)
}

async function runEvaluation() {
  runningEvaluation.value = true
  try {
    const { data } = await api.post<EvaluationRun>('/evaluations/run')
    latestEvaluationRun.value = data
    ElMessage.success(`评测完成：${data.passed_cases}/${data.total_cases}`)
  } finally {
    runningEvaluation.value = false
  }
}

async function saveAgent() {
  if (!activeAgent.value) return
  saving.value = true
  try {
    await api.patch(`/agents/${activeAgent.value.id}`, form)
    ElMessage.success('Agent 配置已保存')
    configDialog.value = false
    await loadAgents()
  } finally {
    saving.value = false
  }
}

async function updateTool(tool: ConfigTool) {
  if (!tool.allowedRoleValues.length) {
    ElMessage.warning('至少保留一个允许角色')
    const { data } = await api.get<AgentTool[]>(`/agents/${tool.agent_id}/tools`)
    agentTools.value = data.map((item) => ({ ...item, allowedRoleValues: item.allowed_roles.split(',').filter(Boolean) }))
    return
  }
  await api.patch(`/agents/${tool.agent_id}/tools/${tool.id}`, {
    enabled: tool.enabled,
    allowed_roles: tool.allowedRoleValues.join(',')
  })
  ElMessage.success('工具权限已更新')
}

function updateToolRow(row: unknown) {
  return updateTool(row as ConfigTool)
}

onMounted(loadAgents)
</script>
