<template>
  <section class="page">
    <div class="page-head">
      <div><h1>任务看板</h1><p>{{ selectedProject?.name || '选择项目' }}</p></div>
      <div class="inline-actions">
        <el-select v-model="projectId" placeholder="选择项目" class="page-select" @change="changeProject">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
        <el-button v-if="canWrite" type="primary" :icon="Plus" @click="openTask()">创建任务</el-button>
      </div>
    </div>
    <div class="kanban">
      <section v-for="status in statuses" :key="status" class="kanban-col">
        <div class="kanban-heading"><h2>{{ statusLabel(status) }}</h2><span>{{ grouped[status].length }}</span></div>
        <article v-for="task in grouped[status]" :key="task.id" class="task-card">
          <div class="task-card-head"><strong>{{ task.title }}</strong><el-button v-if="canWrite" :icon="Edit" circle aria-label="编辑任务" title="编辑" @click="openTask(task)" /></div>
          <p>{{ task.description || '暂无描述' }}</p>
          <div class="task-meta"><span>{{ assigneeName(task.assignee_user_id) }}</span><time>{{ task.due_at ? new Date(task.due_at).toLocaleDateString() : '无截止日期' }}</time></div>
          <el-select v-model="task.status" size="small" :disabled="!canWrite" @change="updateTaskStatus(task)">
            <el-option v-for="item in statuses" :key="item" :label="statusLabel(item)" :value="item" />
          </el-select>
        </article>
      </section>
    </div>

    <el-dialog v-model="taskDialog" :title="activeTask ? '编辑任务' : '创建任务'" width="560">
      <el-form label-position="top">
        <el-form-item label="任务标题"><el-input v-model="taskForm.title" /></el-form-item>
        <el-form-item label="任务描述"><el-input v-model="taskForm.description" type="textarea" :rows="3" /></el-form-item>
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12"><el-form-item label="优先级"><el-select v-model="taskForm.priority" class="full"><el-option label="高" value="HIGH" /><el-option label="中" value="MEDIUM" /><el-option label="低" value="LOW" /></el-select></el-form-item></el-col>
          <el-col :xs="24" :sm="12"><el-form-item label="状态"><el-select v-model="taskForm.status" class="full"><el-option v-for="item in statuses" :key="item" :label="statusLabel(item)" :value="item" /></el-select></el-form-item></el-col>
          <el-col :xs="24" :sm="12"><el-form-item label="负责人"><el-select v-model="taskForm.assignee_user_id" clearable class="full"><el-option v-for="member in members" :key="member.user_id" :label="member.name" :value="member.user_id" /></el-select></el-form-item></el-col>
          <el-col :xs="24" :sm="12"><el-form-item label="截止时间"><el-date-picker v-model="taskForm.due_at" type="datetime" class="full" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <section v-if="activeTask" class="task-comments">
        <h3>评论</h3>
        <div v-for="comment in comments" :key="comment.id" class="task-comment"><strong>{{ comment.user_name }}</strong><span>{{ comment.content }}</span></div>
        <div class="comment-composer"><el-input v-model="commentText" placeholder="添加评论" @keyup.enter="addComment" /><el-button :icon="Promotion" :disabled="!commentText.trim()" @click="addComment">发送</el-button></div>
      </section>
      <template #footer>
        <el-button v-if="activeTask" type="danger" plain @click="removeTask">删除</el-button>
        <el-button @click="taskDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!taskForm.title.trim()" @click="saveTask">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Edit, Plus, Promotion } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { Project, ProjectMember, Task, TaskComment } from '../api/types'
import { confirmDestructiveAction } from '../utils/confirm'

const statuses = ['TODO', 'RUNNING', 'DONE', 'FAILED']
const projects = ref<Project[]>([])
const members = ref<ProjectMember[]>([])
const projectId = ref<number>()
const tasks = ref<Task[]>([])
const taskDialog = ref(false)
const activeTask = ref<Task | null>(null)
const comments = ref<TaskComment[]>([])
const commentText = ref('')
const saving = ref(false)
const taskForm = reactive<any>({ title: '', description: '', priority: 'MEDIUM', status: 'TODO', assignee_user_id: null, due_at: null })
const selectedProject = computed(() => projects.value.find((item) => item.id === projectId.value))
const canWrite = computed(() => selectedProject.value?.current_user_role !== 'viewer')
const grouped = computed<Record<string, Task[]>>(() => {
  const result: Record<string, Task[]> = { TODO: [], RUNNING: [], DONE: [], FAILED: [] }
  tasks.value.forEach((task) => result[task.status]?.push(task))
  return result
})

function statusLabel(status: string) {
  return { TODO: '待办', RUNNING: '进行中', DONE: '已完成', FAILED: '失败' }[status] || status
}

function assigneeName(userId?: number | null) {
  return members.value.find((item) => item.user_id === userId)?.name || '未指派'
}

async function loadTasks() {
  if (!projectId.value) return
  const [taskResponse, memberResponse] = await Promise.all([
    api.get<Task[]>(`/projects/${projectId.value}/tasks`),
    api.get<ProjectMember[]>(`/projects/${projectId.value}/members`)
  ])
  tasks.value = taskResponse.data
  members.value = memberResponse.data
}

async function changeProject() {
  taskDialog.value = false
  await loadTasks()
}

async function updateTaskStatus(task: Task) {
  await api.patch(`/projects/${task.project_id}/tasks/${task.id}`, { status: task.status })
}

async function openTask(task?: Task) {
  activeTask.value = task || null
  Object.assign(taskForm, task
    ? { title: task.title, description: task.description, priority: task.priority, status: task.status, assignee_user_id: task.assignee_user_id ?? null, due_at: task.due_at ? new Date(task.due_at) : null }
    : { title: '', description: '', priority: 'MEDIUM', status: 'TODO', assignee_user_id: null, due_at: null })
  comments.value = []
  if (task) {
    const { data } = await api.get<TaskComment[]>(`/projects/${task.project_id}/tasks/${task.id}/comments`)
    comments.value = data
  }
  taskDialog.value = true
}

async function saveTask() {
  if (!projectId.value) return
  saving.value = true
  try {
    if (activeTask.value) await api.patch(`/projects/${projectId.value}/tasks/${activeTask.value.id}`, taskForm)
    else await api.post(`/projects/${projectId.value}/tasks`, taskForm)
    taskDialog.value = false
    await loadTasks()
  } finally {
    saving.value = false
  }
}

async function removeTask() {
  if (!projectId.value || !activeTask.value) return
  if (!await confirmDestructiveAction('删除后任务及其评论无法恢复，确认继续吗？', '删除任务')) return
  await api.delete(`/projects/${projectId.value}/tasks/${activeTask.value.id}`)
  taskDialog.value = false
  await loadTasks()
}

async function addComment() {
  if (!activeTask.value || !commentText.value.trim()) return
  const { data } = await api.post<TaskComment>(`/projects/${activeTask.value.project_id}/tasks/${activeTask.value.id}/comments`, { content: commentText.value })
  comments.value.push(data)
  commentText.value = ''
}

onMounted(async () => {
  const { data } = await api.get<Project[]>('/projects')
  projects.value = data
  projectId.value = data[0]?.id
  await loadTasks()
})
</script>
