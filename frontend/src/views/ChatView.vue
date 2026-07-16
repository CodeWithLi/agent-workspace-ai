<template>
  <section class="chat-page">
    <aside class="agent-pane">
      <div class="pane-heading">
        <h3>AI 员工</h3>
        <el-button :icon="Plus" circle title="新会话" @click="startNewConversation(selectedAgent)" />
      </div>
      <el-select v-model="selectedProjectId" clearable placeholder="关联项目（可选）" class="project-select">
        <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
      </el-select>
      <button class="agent-button" :class="{ active: selectedAgent === null }" @click="startNewConversation(null)">
        <strong>自动分配</strong>
        <span>根据意图路由；会话开始后保持角色一致。</span>
      </button>
      <button
        v-for="agent in agents"
        :key="agent.id"
        class="agent-button"
        :class="{ active: selectedAgent?.id === agent.id }"
        @click="startNewConversation(agent)"
      >
        <strong>{{ agent.name }}</strong>
        <span>{{ agent.description }}</span>
      </button>

      <h3 class="history-title">最近会话</h3>
      <button v-for="item in conversations" :key="item.id" class="history-button" :class="{ active: item.id === conversationId }" @click="openConversation(item)">
        <strong>{{ item.title }}</strong>
        <span>{{ agentName(item.agent_id) }}</span>
      </button>
      <el-empty v-if="!conversations.length" description="暂无会话" :image-size="50" />
    </aside>

    <main class="chat-window">
      <div ref="messagePane" class="messages">
        <div v-if="!messages.length" class="chat-empty">
          <h3>{{ selectedAgent?.name || '自动分配 AI 员工' }}</h3>
          <p>描述你希望完成的工作。关联项目后，Agent 可以读取项目上下文并执行获准工具。</p>
        </div>
        <div v-for="(message, index) in messages" :key="message.id || index" class="message" :class="message.role">
          <strong>{{ message.role === 'user' ? '我' : activeAgentName }}</strong>
          <MarkdownRenderer :content="message.content" />
        </div>
      </div>
      <el-collapse v-if="thinking || toolCalls.length" class="trace-panel">
        <el-collapse-item title="执行记录" name="trace">
          <p>{{ thinking }}</p>
          <div v-for="(tool, index) in toolCalls" :key="index" class="tool-trace">
            <div class="tool-trace-head">
              <strong>{{ String(tool.name || 'tool') }}</strong>
              <el-tag v-if="pendingActionId(tool)" :type="pendingActionStatus(tool) === 'PENDING_APPROVAL' ? 'warning' : 'success'" size="small">
                {{ actionStatusLabel(pendingActionStatus(tool)) }}
              </el-tag>
            </div>
            <pre>{{ JSON.stringify(tool, null, 2) }}</pre>
            <div v-if="pendingActionId(tool) && pendingActionStatus(tool) === 'PENDING_APPROVAL'" class="inline-actions">
              <el-button type="primary" :icon="Check" :loading="decidingActionId === pendingActionId(tool)" @click="decideAction(tool, 'approve')">批准执行</el-button>
              <el-button :icon="Close" :disabled="decidingActionId === pendingActionId(tool)" @click="decideAction(tool, 'reject')">拒绝</el-button>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
      <div class="composer">
        <el-input v-model="input" type="textarea" :rows="3" placeholder="输入需求或问题，Ctrl + Enter 发送" @keydown.ctrl.enter.prevent="send" />
        <el-button type="primary" :icon="Promotion" :loading="sending" :disabled="!input.trim()" @click="send">发送</el-button>
      </div>
    </main>
  </section>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { Check, Close, Plus, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api, refreshAccessToken } from '../api/client'
import type { Agent, AgentAction, ChatMessage, Conversation, Project } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'

const agents = ref<Agent[]>([])
const projects = ref<Project[]>([])
const conversations = ref<Conversation[]>([])
const selectedAgent = ref<Agent | null>(null)
const selectedProjectId = ref<number | null>(null)
const activeAgentName = ref('AI 员工')
const input = ref('')
const sending = ref(false)
const conversationId = ref<number | null>(null)
const messages = ref<ChatMessage[]>([])
const thinking = ref('')
const toolCalls = ref<Record<string, unknown>[]>([])
const decidingActionId = ref<number | null>(null)
const messagePane = ref<HTMLElement | null>(null)
const suppressProjectWatch = ref(false)

async function loadBaseData() {
  const [agentResponse, projectResponse] = await Promise.all([
    api.get<Agent[]>('/agents'),
    api.get<Project[]>('/projects')
  ])
  agents.value = agentResponse.data
  projects.value = projectResponse.data
  await loadConversations()
}

async function loadConversations() {
  const { data } = await api.get<Conversation[]>('/agents/conversations', {
    params: selectedProjectId.value ? { project_id: selectedProjectId.value } : {}
  })
  conversations.value = data
}

function agentName(agentId: number) {
  return agents.value.find((item) => item.id === agentId)?.name || 'AI 员工'
}

function startNewConversation(agent: Agent | null) {
  selectedAgent.value = agent
  activeAgentName.value = agent?.name || 'AI 员工'
  conversationId.value = null
  messages.value = []
  thinking.value = ''
  toolCalls.value = []
}

async function openConversation(conversation: Conversation) {
  const { data } = await api.get<ChatMessage[]>(`/agents/conversations/${conversation.id}/messages`)
  conversationId.value = conversation.id
  suppressProjectWatch.value = true
  selectedProjectId.value = conversation.project_id || null
  selectedAgent.value = agents.value.find((item) => item.id === conversation.agent_id) || null
  activeAgentName.value = agentName(conversation.agent_id)
  messages.value = data
  thinking.value = ''
  toolCalls.value = []
  await nextTick()
  suppressProjectWatch.value = false
  await scrollToBottom()
}

async function scrollToBottom() {
  await nextTick()
  if (messagePane.value) messagePane.value.scrollTop = messagePane.value.scrollHeight
}

async function send() {
  if (!input.value.trim() || sending.value) return
  const content = input.value.trim()
  messages.value.push({ role: 'user', content })
  const target: ChatMessage = { role: 'assistant', content: '' }
  messages.value.push(target)
  thinking.value = ''
  toolCalls.value = []
  input.value = ''
  sending.value = true
  await scrollToBottom()
  try {
    let response = await streamRequest(content)
    if (response.status === 401) {
      await refreshAccessToken()
      response = await streamRequest(content)
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `请求失败 (${response.status})`)
    }
    const reader = response.body?.getReader()
    if (!reader) throw new Error('浏览器无法读取流式响应')
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      for (const event of events) {
        const type = event.match(/^event: (.+)$/m)?.[1]
        const raw = event.match(/^data: (.+)$/m)?.[1] || '{}'
        const data = JSON.parse(raw)
        if (type === 'thinking') {
          thinking.value = data.content
          const matched = String(data.content || '').match(/路由到：([^。]+)/)
          if (matched) activeAgentName.value = matched[1]
        }
        if (type === 'tool') toolCalls.value.push(data)
        if (type === 'token') target.content += data.content
        if (type === 'done') {
          conversationId.value = data.conversation_id
          activeAgentName.value = data.agent_name
          selectedAgent.value = agents.value.find((item) => item.id === data.agent_id) || selectedAgent.value
        }
        if (type === 'error') throw new Error(data.content || '模型服务暂时不可用')
      }
      await scrollToBottom()
    }
    await loadConversations()
  } catch (error) {
    target.content = target.content || '本次请求未完成。'
    ElMessage.error(error instanceof Error ? error.message : '发送失败')
  } finally {
    sending.value = false
  }
}

function streamRequest(content: string) {
  return fetch('/api/v1/agents/chat/stream', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('token') || ''}`
      },
      body: JSON.stringify({
        agent_id: selectedAgent.value?.id,
        message: content,
        project_id: selectedProjectId.value,
        conversation_id: conversationId.value
      })
    })
}

function pendingActionId(tool: Record<string, unknown>) {
  if (!tool.output || typeof tool.output !== 'object') return null
  const id = (tool.output as Record<string, unknown>).action_id
  return typeof id === 'number' ? id : null
}

function pendingActionStatus(tool: Record<string, unknown>) {
  if (!tool.output || typeof tool.output !== 'object') return ''
  return String((tool.output as Record<string, unknown>).status || '')
}

function actionStatusLabel(value: string) {
  if (value === 'PENDING_APPROVAL') return '等待人工确认'
  if (value === 'EXECUTED') return '已执行'
  if (value === 'REJECTED') return '已拒绝'
  return value
}

async function decideAction(tool: Record<string, unknown>, decision: 'approve' | 'reject') {
  const actionId = pendingActionId(tool)
  if (!actionId || decidingActionId.value) return
  decidingActionId.value = actionId
  try {
    const { data } = await api.post<AgentAction>(`/agents/actions/${actionId}/${decision}`)
    tool.output = {
      ...(tool.output as Record<string, unknown>),
      status: data.status,
      result: data.result_json
    }
    ElMessage.success(decision === 'approve' ? '操作已批准并执行' : '操作已拒绝')
  } finally {
    decidingActionId.value = null
  }
}

watch(selectedProjectId, async () => {
  if (suppressProjectWatch.value) return
  startNewConversation(selectedAgent.value)
  await loadConversations()
})

onMounted(loadBaseData)
</script>
