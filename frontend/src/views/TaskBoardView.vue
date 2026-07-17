<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1>任务看板</h1>
        <p>按项目查看 TODO、RUNNING、DONE、FAILED 状态。</p>
      </div>
      <el-select v-model="projectId" placeholder="选择项目" class="page-select" @change="loadTasks">
        <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
      </el-select>
    </div>
    <div class="kanban">
      <section v-for="status in statuses" :key="status" class="kanban-col">
        <div class="kanban-heading"><h2>{{ statusLabel(status) }}</h2><span>{{ grouped[status].length }}</span></div>
        <article v-for="task in grouped[status]" :key="task.id" class="task-card">
          <strong>{{ task.title }}</strong>
          <p>{{ task.description }}</p>
          <el-select v-model="task.status" size="small" @change="updateTask(task)">
            <el-option v-for="item in statuses" :key="item" :label="item" :value="item" />
          </el-select>
        </article>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'
import type { Project, Task } from '../api/types'

const statuses = ['TODO', 'RUNNING', 'DONE', 'FAILED']
const projects = ref<Project[]>([])
const projectId = ref<number>()
const tasks = ref<Task[]>([])

const grouped = computed<Record<string, Task[]>>(() => {
  const result: Record<string, Task[]> = { TODO: [], RUNNING: [], DONE: [], FAILED: [] }
  tasks.value.forEach((task) => result[task.status]?.push(task))
  return result
})

function statusLabel(status: string) {
  return { TODO: '待办', RUNNING: '进行中', DONE: '已完成', FAILED: '失败' }[status] || status
}

async function loadTasks() {
  if (!projectId.value) return
  const { data } = await api.get<Task[]>(`/projects/${projectId.value}/tasks`)
  tasks.value = data
}

async function updateTask(task: Task) {
  await api.patch(`/projects/${task.project_id}/tasks/${task.id}`, { status: task.status })
}

onMounted(async () => {
  const { data } = await api.get<Project[]>('/projects')
  projects.value = data
  projectId.value = data[0]?.id
  await loadTasks()
})
</script>
