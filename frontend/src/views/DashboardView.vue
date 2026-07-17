<template>
  <section class="page dashboard-page">
    <div class="page-head dashboard-heading">
      <div>
        <span class="page-kicker">今日工作概览</span>
        <h1>{{ greeting }}，{{ auth.user?.name || '你好' }}</h1>
        <p>查看项目进展、Agent 团队和待处理事项。</p>
      </div>
      <el-button v-if="auth.hasPermission('projects:write')" type="primary" :icon="Plus" @click="createDialog = true">新建项目</el-button>
    </div>

    <div class="metric-grid">
      <article class="metric-card">
        <span class="metric-icon"><Folder /></span>
        <div><span>我的项目</span><strong>{{ stats?.projects || 0 }}</strong></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon"><Cpu /></span>
        <div><span>AI 员工</span><strong>{{ stats?.agents || 0 }}</strong></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon"><Tickets /></span>
        <div><span>项目任务</span><strong>{{ taskTotal }}</strong></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon"><Files /></span>
        <div><span>知识文档</span><strong>{{ stats?.documents || 0 }}</strong></div>
      </article>
    </div>

    <div class="dashboard-grid">
      <section class="dashboard-section project-section">
        <div class="section-heading">
          <div><h2>我的项目</h2><p>最近创建和参与的项目空间</p></div>
          <el-button link type="primary" @click="router.push('/projects')">查看全部<el-icon><ArrowRight /></el-icon></el-button>
        </div>
        <div class="project-list">
          <button v-for="project in projects.slice(0, 5)" :key="project.id" class="project-row" @click="router.push(`/projects/${project.id}`)">
            <span class="project-symbol"><Folder /></span>
            <span class="project-summary"><strong>{{ project.name }}</strong><small>{{ project.description || '暂无项目描述' }}</small></span>
            <span class="project-date">{{ formatDate(project.created_at) }}</span>
            <el-icon><ArrowRight /></el-icon>
          </button>
          <el-empty v-if="!projects.length" description="还没有项目，创建一个项目开始协作" :image-size="64" />
        </div>
      </section>

      <section class="dashboard-section chart-section">
        <div class="section-heading"><div><h2>任务状态</h2><p>当前项目任务分布</p></div></div>
        <div ref="chartEl" class="chart-card" role="img" :aria-label="taskChartLabel" />
        <div class="task-legend">
          <span v-for="item in taskLegend" :key="item.key"><i :class="`legend-${item.key.toLowerCase()}`" />{{ item.label }} <strong>{{ item.value }}</strong></span>
        </div>
      </section>
    </div>

    <div class="dashboard-grid secondary-grid">
      <section class="dashboard-section team-section">
        <div class="section-heading">
          <div><h2>AI 团队</h2><p>当前可调度的数字员工</p></div>
          <el-button link type="primary" @click="router.push('/agents')">管理团队<el-icon><ArrowRight /></el-icon></el-button>
        </div>
        <div class="team-list">
          <button v-for="agent in agents.slice(0, 6)" :key="agent.id" class="team-member" @click="router.push('/chat')">
            <span class="team-avatar"><Cpu /></span>
            <span><strong>{{ agent.name }}</strong><small>{{ agent.description }}</small></span>
            <span class="online-dot" title="可用" />
          </button>
        </div>
      </section>

      <section class="dashboard-section activity-section">
        <div class="section-heading"><div><h2>最近活动</h2><p>项目和 Agent 的最新变化</p></div></div>
        <div class="activity-list">
          <div v-for="activity in stats?.recent_activities || []" :key="activity" class="activity-row">
            <span class="activity-icon"><Clock /></span><span>{{ activity }}</span>
          </div>
          <el-empty v-if="!stats?.recent_activities?.length" description="暂无最近活动" :image-size="56" />
        </div>
      </section>
    </div>

    <el-dialog v-model="createDialog" title="创建项目" width="480">
      <el-form label-position="top">
        <el-form-item label="项目名称">
          <el-input v-model="form.name" placeholder="校园二手交易平台" />
        </el-form-item>
        <el-form-item label="项目描述">
          <el-input v-model="form.description" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" @click="createProject">创建</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Clock, Cpu, Files, Folder, Plus, Tickets } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { Agent, DashboardStats, Project } from '../api/types'
import type { TaskChart } from '../lib/taskChart'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const projects = ref<Project[]>([])
const agents = ref<Agent[]>([])
const stats = ref<DashboardStats>()
const chartEl = ref<HTMLDivElement>()
const createDialog = ref(false)
const form = reactive({ name: '', description: '', members: '' })
let chart: TaskChart | undefined

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 12) return '早上好'
  if (hour < 18) return '下午好'
  return '晚上好'
})
const taskTotal = computed(() => Object.values(stats.value?.tasks || {}).reduce((sum, value) => sum + value, 0))
const taskLegend = computed(() => [
  { key: 'TODO', label: '待办', value: stats.value?.tasks.TODO || 0 },
  { key: 'RUNNING', label: '进行中', value: stats.value?.tasks.RUNNING || 0 },
  { key: 'DONE', label: '已完成', value: stats.value?.tasks.DONE || 0 },
  { key: 'FAILED', label: '失败', value: stats.value?.tasks.FAILED || 0 }
])
const taskChartLabel = computed(() => taskLegend.value.map((item) => `${item.label} ${item.value}`).join('，'))

async function load() {
  const agentRequest = auth.hasPermission('agents:read')
    ? api.get<Agent[]>('/agents')
    : Promise.resolve({ data: [] as Agent[] })
  const [projectRes, agentRes, statRes] = await Promise.all([
    api.get<Project[]>('/projects'),
    agentRequest,
    api.get<DashboardStats>('/dashboard/stats')
  ])
  projects.value = projectRes.data
  agents.value = agentRes.data
  stats.value = statRes.data
  await nextTick()
  if (chartEl.value) {
    const { renderTaskChart } = await import('../lib/taskChart')
    chart = renderTaskChart(chartEl.value, taskLegend.value.map((item) => ({ name: item.label, value: item.value })))
  }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(new Date(value))
}

function resizeChart() {
  chart?.resize()
}

async function createProject() {
  await api.post('/projects', form)
  createDialog.value = false
  form.name = ''
  form.description = ''
  form.members = ''
  await load()
}

onMounted(() => {
  window.addEventListener('resize', resizeChart)
  load()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
  chart = undefined
})
</script>
