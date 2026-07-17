<template>
  <section class="page narrow-page">
    <div class="page-head">
      <div>
        <span class="page-kicker">数字员工团队</span>
        <h1>AI 员工</h1>
        <p>配置职责、Prompt、模型、工具权限与人工确认策略。</p>
      </div>
      <span class="page-count">{{ agents.length }} 名员工</span>
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
      </el-tabs>
      <template #footer>
        <el-button @click="configDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!form.description.trim() || !form.system_prompt.trim() || !form.model.trim()" @click="saveAgent">保存配置</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Cpu, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { Agent, AgentTool } from '../api/types'

interface ConfigTool extends AgentTool {
  allowedRoleValues: string[]
}

const agents = ref<Agent[]>([])
const auth = useAuthStore()
const configDialog = ref(false)
const activeTab = ref('profile')
const activeAgent = ref<Agent | null>(null)
const agentTools = ref<ConfigTool[]>([])
const saving = ref(false)
const form = reactive({
  description: '',
  system_prompt: '',
  model: '',
  memory_enable: true,
  knowledge_access: true,
  human_approval_required: false,
  concurrency_limit: 4
})

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
  Object.assign(form, {
    description: agent.description,
    system_prompt: agent.system_prompt,
    model: agent.model,
    memory_enable: agent.memory_enable,
    knowledge_access: agent.knowledge_access,
    human_approval_required: agent.human_approval_required,
    concurrency_limit: agent.concurrency_limit
  })
  const { data } = await api.get<AgentTool[]>(`/agents/${agent.id}/tools`)
  agentTools.value = data.map((tool) => ({
    ...tool,
    allowedRoleValues: tool.allowed_roles.split(',').map((item) => item.trim()).filter(Boolean)
  }))
  configDialog.value = true
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
