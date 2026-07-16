<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h2>工作台</h2>
        <p>管理项目空间和默认 AI 员工。</p>
      </div>
      <el-button v-if="auth.hasPermission('projects:write')" type="primary" :icon="Plus" @click="createDialog = true">新建项目</el-button>
    </div>

    <el-row :gutter="20">
      <el-col :span="24">
        <div class="stat-grid">
          <div class="stat-card"><strong>{{ stats?.projects || 0 }}</strong><span>我的项目</span></div>
          <div class="stat-card"><strong>{{ stats?.agents || 0 }}</strong><span>AI员工</span></div>
          <div class="stat-card"><strong>{{ stats?.documents || 0 }}</strong><span>知识库文档</span></div>
          <div ref="chartEl" class="chart-card" />
        </div>
      </el-col>
      <el-col :span="14">
        <h3>我的项目</h3>
        <div class="item-grid">
          <article v-for="project in projects" :key="project.id" class="item-card" @click="router.push(`/projects/${project.id}`)">
            <h4>{{ project.name }}</h4>
            <p>{{ project.description || '暂无描述' }}</p>
            <span>{{ new Date(project.created_at).toLocaleString() }}</span>
          </article>
        </div>
      </el-col>
      <el-col :span="10">
        <h3>AI员工</h3>
        <div class="agent-list">
          <div v-for="agent in agents" :key="agent.id" class="agent-row">
            <strong>{{ agent.name }}</strong>
            <span>{{ agent.description }}</span>
          </div>
        </div>
      </el-col>
      <el-col :span="24">
        <h3>最近活动</h3>
        <div class="agent-list">
          <div v-for="activity in stats?.recent_activities || []" :key="activity" class="agent-row">{{ activity }}</div>
        </div>
      </el-col>
    </el-row>

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
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import { PieChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api/client'
import type { Agent, DashboardStats, Project } from '../api/types'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const projects = ref<Project[]>([])
const agents = ref<Agent[]>([])
const stats = ref<DashboardStats>()
const chartEl = ref<HTMLDivElement>()
const createDialog = ref(false)
const form = reactive({ name: '', description: '', members: '' })
let chart: echarts.ECharts | undefined

echarts.use([PieChart, TooltipComponent, CanvasRenderer])

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
    chart ||= echarts.init(chartEl.value)
    chart.setOption({
      tooltip: {},
      series: [
        {
          type: 'pie',
          radius: ['45%', '70%'],
          data: Object.entries(stats.value.tasks).map(([name, value]) => ({ name, value }))
        }
      ]
    })
  }
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
