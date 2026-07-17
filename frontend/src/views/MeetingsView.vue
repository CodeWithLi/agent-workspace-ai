<template>
  <section class="page">
    <div class="page-head">
      <div><h1>会议中心</h1><p>会议纪要与项目行动项。</p></div>
      <el-button type="primary" :loading="loading" :disabled="!title.trim() || !transcript.trim()" @click="createMeeting">生成纪要</el-button>
    </div>
    <el-form label-position="top" class="work-form">
      <el-row :gutter="14">
        <el-col :xs="24" :md="12"><el-form-item label="所属项目"><el-select v-model="projectId" clearable class="full"><el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" /></el-select></el-form-item></el-col>
        <el-col :xs="24" :md="12"><el-form-item label="会议标题"><el-input v-model="title" /></el-form-item></el-col>
      </el-row>
      <el-form-item label="会议记录"><el-input v-model="transcript" type="textarea" :rows="7" /></el-form-item>
    </el-form>
    <div class="filter-bar" aria-label="会议筛选">
      <el-input v-model="filterQuery" clearable placeholder="搜索会议标题、记录或纪要" aria-label="搜索会议" />
      <el-select v-model="filterProjectId" clearable placeholder="全部项目" aria-label="按项目筛选">
        <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
      </el-select>
    </div>
    <div class="item-grid">
      <article v-for="meeting in pagedMeetings" :key="meeting.id" class="item-card wide">
        <div class="item-card-head"><h4>{{ meeting.title }}</h4><div><el-button :icon="Edit" circle aria-label="编辑会议" title="编辑" @click="openEdit(meeting)" /><el-button :icon="Delete" circle aria-label="删除会议" title="删除" @click="remove(meeting.id)" /></div></div>
        <MarkdownRenderer :content="meeting.summary" />
        <div class="meeting-actions"><div v-for="(item, index) in actionItems(meeting)" :key="index"><strong>{{ item.task }}</strong><span>{{ item.owner }} · {{ item.due_date }}</span></div></div>
        <el-button v-if="meeting.project_id && actionItems(meeting).length" :icon="List" @click="createTasks(meeting.id)">转为项目任务</el-button>
      </article>
    </div>
    <el-empty v-if="!filteredMeetings.length" description="没有符合条件的会议" />
    <el-pagination v-if="filteredMeetings.length > pageSize" v-model:current-page="page" class="page-pagination" background layout="prev, pager, next" :page-size="pageSize" :total="filteredMeetings.length" />

    <el-dialog v-model="editDialog" title="编辑会议" width="600">
      <el-form label-position="top">
        <el-form-item label="标题"><el-input v-model="editForm.title" /></el-form-item>
        <el-form-item label="会议记录"><el-input v-model="editForm.transcript" type="textarea" :rows="5" /></el-form-item>
        <el-form-item label="会议纪要"><el-input v-model="editForm.summary" type="textarea" :rows="6" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editDialog = false">取消</el-button><el-button type="primary" @click="saveMeeting">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Delete, Edit, List } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api } from '../api/client'
import type { Meeting, Project } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { containsQuery, paginate } from '../utils/collection'
import { confirmDestructiveAction } from '../utils/confirm'

const meetings = ref<Meeting[]>([])
const projects = ref<Project[]>([])
const projectId = ref<number | null>(null)
const title = ref('项目例会')
const transcript = ref('')
const loading = ref(false)
const editDialog = ref(false)
const activeMeeting = ref<Meeting | null>(null)
const editForm = reactive({ title: '', transcript: '', summary: '' })
const filterQuery = ref('')
const filterProjectId = ref<number | null>(null)
const page = ref(1)
const pageSize = 6
const filteredMeetings = computed(() => meetings.value.filter((meeting) =>
  containsQuery(filterQuery.value, meeting.title, meeting.transcript, meeting.summary)
  && (!filterProjectId.value || meeting.project_id === filterProjectId.value)
))
const pagedMeetings = computed(() => paginate(filteredMeetings.value, page.value, pageSize))

watch([filterQuery, filterProjectId], () => { page.value = 1 })

function actionItems(meeting: Meeting): Array<{ task: string; owner: string; due_date: string }> {
  try { return JSON.parse(meeting.action_items) } catch { return [] }
}

async function load() {
  const [meetingResponse, projectResponse] = await Promise.all([api.get<Meeting[]>('/meetings'), api.get<Project[]>('/projects')])
  meetings.value = meetingResponse.data
  projects.value = projectResponse.data
  projectId.value ||= projectResponse.data[0]?.id || null
}

async function createMeeting() {
  loading.value = true
  try {
    await api.post('/meetings', { title: title.value, transcript: transcript.value, project_id: projectId.value })
    transcript.value = ''
    await load()
  } finally { loading.value = false }
}

function openEdit(meeting: Meeting) {
  activeMeeting.value = meeting
  Object.assign(editForm, { title: meeting.title, transcript: meeting.transcript, summary: meeting.summary })
  editDialog.value = true
}

async function saveMeeting() {
  if (!activeMeeting.value) return
  await api.patch(`/meetings/${activeMeeting.value.id}`, editForm)
  editDialog.value = false
  await load()
}

async function createTasks(id: number) {
  const { data } = await api.post(`/meetings/${id}/tasks`)
  ElMessage.success(`已创建 ${data.length} 个项目任务`)
}

async function remove(id: number) {
  if (!await confirmDestructiveAction('删除后无法恢复，确认删除这场会议及其纪要吗？', '删除会议')) return
  await api.delete(`/meetings/${id}`)
  await load()
}

onMounted(load)
</script>
