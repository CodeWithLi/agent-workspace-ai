<template>
  <section class="chat-page">
    <aside class="agent-pane">
      <div class="pane-heading">
        <h3>{{ workspaceMode === 'team' ? '讨论团队' : 'AI 员工' }}</h3>
        <el-button :icon="Plus" circle aria-label="新会话" title="新会话" @click="startNewConversation(workspaceMode === 'single' ? selectedAgent : null)" />
      </div>
      <el-segmented v-model="workspaceMode" class="chat-mode-switch" :options="modeOptions" aria-label="AI 协作模式" />
      <el-select v-model="selectedProjectId" clearable placeholder="关联项目（可选）" class="project-select">
        <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
      </el-select>
      <template v-if="workspaceMode === 'single'">
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
      </template>
      <div v-else class="discussion-roster" aria-label="团队讨论参与者">
        <div v-for="(agent, index) in discussionAgents" :key="agent.id" class="discussion-roster-item">
          <span>{{ index + 1 }}</span>
          <div><strong>{{ agent.name }}</strong><small>{{ discussionStageLabels[index] }}</small></div>
        </div>
      </div>

      <h3 class="history-title">最近会话</h3>
      <button v-for="item in conversations" :key="item.id" class="history-button" :class="{ active: item.id === conversationId }" @click="openConversation(item)">
        <strong>{{ item.title }}</strong>
        <span>{{ item.mode === 'TEAM' ? '团队讨论' : agentName(item.agent_id) }}</span>
      </button>
      <el-empty v-if="!conversations.length" description="暂无会话" :image-size="50" />
    </aside>

    <main class="chat-window">
      <header class="chat-context-bar">
        <div class="chat-context-agent">
          <span class="online-dot" />
          <strong>{{ activeAgentName }}</strong>
          <span>{{ workspaceMode === 'team' ? '多 AI 评审' : 'AI 员工' }}</span>
        </div>
        <span v-if="selectedProjectName" class="chat-context-project">{{ selectedProjectName }}</span>
      </header>

      <div ref="messagePane" class="messages">
        <div class="messages-inner">
          <div v-if="workspaceMode === 'team' && discussionTotal" class="discussion-progress" role="status" aria-live="polite">
            <div><strong>{{ discussionStatusText }}</strong><span>{{ discussionStep }} / {{ discussionTotal }}</span></div>
            <el-progress :percentage="discussionProgress" :show-text="false" />
          </div>
          <div v-if="!messages.length" class="chat-empty">
            <span class="chat-empty-icon"><el-icon><component :is="workspaceMode === 'team' ? Connection : Cpu" /></el-icon></span>
            <h1>{{ workspaceMode === 'team' ? '多 AI 方案评审' : (selectedAgent?.name || 'AI 协作助手') }}</h1>
            <p>{{ workspaceMode === 'team' ? '产品、架构、质量、运营与项目管理团队已就绪。' : (selectedAgent?.description || '准备好开始新的协作。') }}</p>
          </div>
          <article v-for="(message, index) in messages" :key="message.id || message.client_id || index" class="message" :class="[message.role, { 'discussion-final': message.stage === 'final' }]">
            <span v-if="message.role !== 'user'" class="message-avatar"><el-icon><Cpu /></el-icon></span>
            <div class="message-content">
              <div v-if="message.role !== 'user'" class="message-author">
                <strong>{{ messageAgentName(message) }}</strong>
                <span>{{ stageLabel(message.stage) }}</span>
              </div>
              <div class="message-bubble">
                <MarkdownRenderer v-if="message.content" :content="message.content" />
                <span v-else-if="sending && index === messages.length - 1" class="typing-indicator" aria-label="正在生成">
                  <i /><i /><i />
                </span>
              </div>
              <div v-if="message.role === 'assistant' && message.id" class="message-actions">
                <el-button :icon="DocumentCopy" circle aria-label="复制回答" title="复制" @click="copyMessage(message.content)" />
                <el-button v-if="workspaceMode === 'single' || message.stage === 'final'" :class="{ active: message.feedback === 1 }" :icon="Top" circle aria-label="回答有帮助" title="有帮助" @click="submitFeedback(message, 1)" />
                <el-button v-if="workspaceMode === 'single' || message.stage === 'final'" :class="{ active: message.feedback === -1 }" :icon="Bottom" circle aria-label="回答需改进" title="需改进" @click="submitFeedback(message, -1)" />
                <el-button v-if="workspaceMode === 'single'" :icon="RefreshRight" circle aria-label="重新生成回答" title="重新生成" :loading="regeneratingMessageId === message.id" @click="regenerateMessage(message)" />
              </div>
            </div>
          </article>

          <el-collapse v-if="workspaceMode === 'single' && (thinking || toolCalls.length)" class="trace-panel">
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
        </div>
      </div>

      <div class="composer-shell">
        <div class="composer">
          <el-input
            v-model="input"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 6 }"
            resize="none"
            :aria-label="workspaceMode === 'team' ? '发送给 AI 团队的需求' : '发送给 AI 员工的消息'"
            :placeholder="workspaceMode === 'team' ? '输入需要团队评审的需求' : '向 AI 员工发送消息'"
            @keydown.ctrl.enter.prevent="send"
          />
          <el-button type="primary" :icon="Promotion" circle aria-label="发送消息" title="发送" :loading="sending" :disabled="!input.trim()" @click="send" />
        </div>
        <div class="composer-meta">
          <span>{{ selectedProjectName || '未关联项目' }}</span>
          <span>AI 生成内容，请核对重要信息</span>
        </div>
      </div>
    </main>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'
import { Bottom, Check, Close, Connection, Cpu, DocumentCopy, Plus, Promotion, RefreshRight, Top } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api, apiBaseURL, refreshAccessToken } from '../api/client'
import type { Agent, AgentAction, ChatMessage, Conversation, Project } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { useAuthStore } from '../stores/auth'
import { parseSseChunk } from '../utils/sse'

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
const regeneratingMessageId = ref<number | null>(null)
const messagePane = ref<HTMLElement | null>(null)
const suppressProjectWatch = ref(false)
const suppressModeWatch = ref(false)
const workspaceMode = ref<'single' | 'team'>('single')
const modeOptions = [{ label: '单人对话', value: 'single' }, { label: '团队讨论', value: 'team' }]
const discussionRoleOrder = ['product_manager', 'architect', 'test_engineer', 'operations_analyst', 'project_manager']
const discussionStageLabels = ['需求与范围', '技术架构', '质量审查', '发布运营', '最终方案']
const discussionStep = ref(0)
const discussionTotal = ref(0)
const discussionParticipants = ref<Array<{ agent_id: number; agent_name: string; role: string }>>([])
const auth = useAuthStore()
const router = useRouter()
const selectedProjectName = computed(() => projects.value.find((item) => item.id === selectedProjectId.value)?.name || '')
const discussionAgents = computed(() => discussionRoleOrder
  .map((role) => agents.value.find((agent) => agent.role === role))
  .filter((agent): agent is Agent => Boolean(agent)))
const discussionProgress = computed(() => discussionTotal.value
  ? Math.round((discussionStep.value / discussionTotal.value) * 100)
  : 0)
const discussionStatusText = computed(() => {
  if (discussionStep.value === 0) return '准备团队讨论'
  if (!sending.value && discussionStep.value === discussionTotal.value) return '最终方案已生成'
  return discussionStageLabels[discussionStep.value - 1] || '准备团队讨论'
})

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

function messageAgentName(message: ChatMessage) {
  if (message.agent_id) return agentName(message.agent_id)
  return activeAgentName.value
}

function stageLabel(stage?: string) {
  return {
    product: '需求与范围',
    architecture: '技术架构',
    quality: '质量审查',
    operations: '发布运营',
    final: '最终方案',
    answer: 'AI 员工'
  }[stage || 'answer'] || 'AI 员工'
}

function startNewConversation(agent: Agent | null) {
  selectedAgent.value = workspaceMode.value === 'team' ? null : agent
  activeAgentName.value = workspaceMode.value === 'team' ? '多 AI 讨论组' : (agent?.name || 'AI 员工')
  conversationId.value = null
  messages.value = []
  thinking.value = ''
  toolCalls.value = []
  discussionStep.value = 0
  discussionTotal.value = 0
  discussionParticipants.value = []
}

async function openConversation(conversation: Conversation) {
  const { data } = await api.get<ChatMessage[]>(`/agents/conversations/${conversation.id}/messages`)
  conversationId.value = conversation.id
  suppressProjectWatch.value = true
  suppressModeWatch.value = true
  workspaceMode.value = conversation.mode === 'TEAM' ? 'team' : 'single'
  selectedProjectId.value = conversation.project_id || null
  selectedAgent.value = workspaceMode.value === 'single' ? agents.value.find((item) => item.id === conversation.agent_id) || null : null
  activeAgentName.value = workspaceMode.value === 'team' ? '多 AI 讨论组' : agentName(conversation.agent_id)
  messages.value = data
  thinking.value = ''
  toolCalls.value = []
  if (workspaceMode.value === 'team') {
    discussionTotal.value = discussionRoleOrder.length
    discussionStep.value = discussionRoleOrder.length
  } else {
    discussionTotal.value = 0
    discussionStep.value = 0
  }
  await nextTick()
  suppressProjectWatch.value = false
  suppressModeWatch.value = false
  await scrollToBottom()
}

async function scrollToBottom() {
  await nextTick()
  if (messagePane.value) messagePane.value.scrollTop = messagePane.value.scrollHeight
}

async function send() {
  if (!input.value.trim() || sending.value) return
  const content = input.value.trim()
  const requestId = crypto.randomUUID()
  messages.value.push({ role: 'user', content })
  const target: ChatMessage | null = workspaceMode.value === 'single'
    ? { role: 'assistant', content: '', client_id: requestId }
    : null
  if (target) messages.value.push(target)
  let discussionTarget: ChatMessage | null = null
  thinking.value = ''
  toolCalls.value = []
  discussionStep.value = 0
  discussionTotal.value = workspaceMode.value === 'team' ? discussionRoleOrder.length : 0
  input.value = ''
  sending.value = true
  await scrollToBottom()
  try {
    let response = await streamRequest(content, requestId)
    if (response.status === 401) {
      await refreshAccessToken()
      response = await streamRequest(content, requestId)
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
      const parsed = parseSseChunk(buffer, decoder.decode(value, { stream: true }))
      buffer = parsed.buffer
      for (const { type, data } of parsed.events) {
        if (type === 'thinking') {
          thinking.value = data.content
          const matched = String(data.content || '').match(/路由到：([^。]+)/)
          if (matched) activeAgentName.value = matched[1]
        }
        if (type === 'tool') toolCalls.value.push(data)
        if (type === 'discussion_start') {
          conversationId.value = data.conversation_id
          discussionTotal.value = data.total_steps
          discussionParticipants.value = data.participants || []
        }
        if (type === 'speaker_start') {
          discussionStep.value = data.index
          activeAgentName.value = data.agent_name
          discussionTarget = {
            role: 'assistant',
            content: '',
            agent_id: data.agent_id,
            stage: data.stage,
            client_id: `${requestId}-${data.stage}`
          }
          messages.value.push(discussionTarget)
        }
        if (type === 'token') {
          if (workspaceMode.value === 'team' && discussionTarget) discussionTarget.content += data.content
          else if (target) target.content += data.content
        }
        if (type === 'speaker_done' && discussionTarget) discussionTarget.id = data.message_id
        if (type === 'done') {
          if (target) target.id = data.message_id
          conversationId.value = data.conversation_id
          activeAgentName.value = workspaceMode.value === 'team' ? '多 AI 讨论组' : data.agent_name
          if (workspaceMode.value === 'single') {
            selectedAgent.value = agents.value.find((item) => item.id === data.agent_id) || selectedAgent.value
          }
          if (typeof data.token_balance === 'number') auth.setTokenBalance(data.token_balance)
        }
        if (type === 'error') throw new Error(data.content || '模型服务暂时不可用')
      }
      await scrollToBottom()
    }
    await loadConversations()
  } catch (error) {
    if (target) target.content = target.content || '本次请求未完成。'
    if (discussionTarget) discussionTarget.content = discussionTarget.content || '本轮讨论未完成。'
    const message = error instanceof Error ? error.message : '发送失败'
    ElMessage.error(message)
    if (message.includes('Insufficient AI Token')) await router.push('/wallet')
  } finally {
    sending.value = false
  }
}

async function copyMessage(content: string) {
  await navigator.clipboard.writeText(content)
  ElMessage.success('回答已复制')
}

async function submitFeedback(message: ChatMessage, rating: 1 | -1) {
  if (!message.id) return
  await api.post(`/agents/messages/${message.id}/feedback`, { rating, comment: '' })
  message.feedback = rating
  ElMessage.success('反馈已记录')
}

async function regenerateMessage(message: ChatMessage) {
  if (!message.id || regeneratingMessageId.value) return
  regeneratingMessageId.value = message.id
  try {
    const { data } = await api.post<{ message: ChatMessage; token_balance: number }>(
      `/agents/messages/${message.id}/regenerate`,
      { request_id: crypto.randomUUID() }
    )
    messages.value.push(data.message)
    auth.setTokenBalance(data.token_balance)
    await scrollToBottom()
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 402) await router.push('/wallet')
    else throw error
  } finally {
    regeneratingMessageId.value = null
  }
}

function streamRequest(content: string, requestId: string) {
  const teamMode = workspaceMode.value === 'team'
  return fetch(`${apiBaseURL}/agents/${teamMode ? 'discussion' : 'chat'}/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('token') || ''}`
      },
      body: JSON.stringify({
        ...(teamMode ? {} : { agent_id: selectedAgent.value?.id }),
        message: content,
        project_id: selectedProjectId.value,
        conversation_id: conversationId.value,
        request_id: requestId
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

watch(workspaceMode, async () => {
  if (suppressModeWatch.value) return
  startNewConversation(workspaceMode.value === 'single' ? selectedAgent.value : null)
  await loadConversations()
})

onMounted(loadBaseData)
</script>
