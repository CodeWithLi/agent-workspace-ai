<template>
  <section class="page narrow-page">
    <div class="page-head">
      <div>
        <h2>AI 员工</h2>
        <p>配置 AI 员工的职责、Prompt、模型、工具权限与是否需要人工确认。</p>
      </div>
    </div>

    <div class="agent-card-grid">
      <article v-for="agent in agents" :key="agent.id" class="employee-card">
        <div class="employee-title">
          <el-icon><Briefcase /></el-icon>
          <h3>{{ agent.name }}</h3>
        </div>
        <p>{{ displayDescription(agent) }}</p>
        <div class="employee-meta">
          <span>模型档位：<strong>{{ modelTier(agent) }}</strong></span>
          <span>人工确认：<strong>{{ needsApproval(agent) ? '需要' : '不需要' }}</strong></span>
          <span>Memory：<strong>{{ agent.memory_enable ? '启用' : '关闭' }}</strong></span>
        </div>
        <div class="tool-tags">
          <el-tag v-for="tool in tools(agent)" :key="tool" round>{{ tool }}</el-tag>
        </div>
        <el-button v-if="auth.user?.role === 'admin'" class="card-action" @click="openTools(agent)">配置工具白名单</el-button>
      </article>
    </div>

    <el-dialog v-model="toolDialog" :title="`${activeAgent?.name || ''} 工具白名单`" width="620">
      <el-alert type="info" show-icon :closable="false" title="工具调用会同时经过代码硬白名单和数据库启停白名单校验。" />
      <el-table :data="agentTools" class="data-table">
        <el-table-column prop="name" label="工具" min-width="180" />
        <el-table-column label="允许角色" min-width="180">
          <template #default="{ row }">
            <el-input v-model="row.allowed_roles" size="small" @change="updateToolRow(row)" />
          </template>
        </el-table-column>
        <el-table-column label="启用" width="100">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="updateToolRow(row)" />
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Briefcase } from '@element-plus/icons-vue'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { Agent, AgentTool } from '../api/types'

const agents = ref<Agent[]>([])
const auth = useAuthStore()
const toolDialog = ref(false)
const activeAgent = ref<Agent>()
const agentTools = ref<AgentTool[]>([])

const approvalRoles = new Set(['product_manager', 'project_manager', 'architect', 'meeting_summarizer', 'notification_secretary'])
const fastRoles = new Set(['knowledge_admin', 'notification_secretary'])

function tools(agent: Agent) {
  return agent.tools.split(',').map((item) => item.trim()).filter(Boolean)
}

function modelTier(agent: Agent) {
  return fastRoles.has(agent.role) ? '快/省' : '强指令'
}

function needsApproval(agent: Agent) {
  return approvalRoles.has(agent.role)
}

function displayDescription(agent: Agent) {
  const map: Record<string, string> = {
    product_manager: '把模糊想法变成标准需求：识别、澄清、生成需求卡片与验收标准。',
    project_manager: '任务拆解、里程碑、延期/阻塞识别、日报周报与项目健康评分。',
    architect: '技术方案与系统影响分析、接口草案、数据结构建议、风险评估。',
    test_engineer: '测试用例、验收标准、异常与边界场景、回归清单。',
    meeting_summarizer: '把会议内容转为结构化资产：纪要、待办、决策、风险、需求变更。',
    knowledge_admin: '项目知识沉淀：归档、摘要、分类、打标签、去重、FAQ 生成。',
    notification_secretary: '生成站内信/邮件文案，识别接收人与渠道，跟踪发送与二次提醒。',
    operations_analyst: '项目健康度、团队效率、需求变更与交付质量分析及管理建议。'
  }
  return map[agent.role] || agent.description
}

async function loadAgents() {
  const { data } = await api.get<Agent[]>('/agents')
  agents.value = data
}

async function openTools(agent: Agent) {
  activeAgent.value = agent
  const { data } = await api.get<AgentTool[]>(`/agents/${agent.id}/tools`)
  agentTools.value = data
  toolDialog.value = true
}

async function updateTool(tool: AgentTool) {
  await api.patch(`/agents/${tool.agent_id}/tools/${tool.id}`, {
    enabled: tool.enabled,
    allowed_roles: tool.allowed_roles
  })
}

function updateToolRow(row: unknown) {
  return updateTool(row as AgentTool)
}

onMounted(loadAgents)
</script>
