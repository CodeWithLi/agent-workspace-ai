<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1>项目报告</h1>
        <p>生成日报、周报、风险报告和进度报告。</p>
      </div>
      <div class="inline-actions">
        <el-select v-model="projectId" placeholder="项目" class="page-select compact-select">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
        <el-select v-model="reportType" class="page-select type-select">
          <el-option label="日报" value="daily" />
          <el-option label="周报" value="weekly" />
          <el-option label="风险报告" value="risk" />
          <el-option label="进度报告" value="progress" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="createReport">生成</el-button>
      </div>
    </div>
    <div class="filter-bar" aria-label="报告筛选">
      <el-input v-model="filterQuery" clearable placeholder="搜索报告标题或内容" aria-label="搜索报告" />
      <el-select v-model="filterProjectId" clearable placeholder="全部项目" aria-label="按项目筛选">
        <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
      </el-select>
      <el-select v-model="filterType" clearable placeholder="全部类型" aria-label="按类型筛选">
        <el-option label="日报" value="daily" />
        <el-option label="周报" value="weekly" />
        <el-option label="风险报告" value="risk" />
        <el-option label="进度报告" value="progress" />
      </el-select>
    </div>
    <div class="report-list">
      <article v-for="report in pagedReports" :key="report.id" class="report-panel">
        <div class="item-card-head"><h3>{{ report.title }}</h3><div><el-button :icon="Edit" circle aria-label="编辑报告" title="编辑" @click="openEdit(report)" /><el-button :icon="Delete" circle aria-label="删除报告" title="删除" @click="remove(report.id)" /></div></div>
        <MarkdownRenderer :content="report.content" />
      </article>
    </div>
    <el-empty v-if="!filteredReports.length" description="没有符合条件的报告" />
    <el-pagination v-if="filteredReports.length > pageSize" v-model:current-page="page" class="page-pagination" background layout="prev, pager, next" :page-size="pageSize" :total="filteredReports.length" />
    <el-dialog v-model="editDialog" title="编辑报告" width="680">
      <el-form label-position="top">
        <el-form-item label="标题"><el-input v-model="editForm.title" /></el-form-item>
        <el-form-item label="类型"><el-input v-model="editForm.report_type" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="editForm.content" type="textarea" :rows="12" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editDialog = false">取消</el-button><el-button type="primary" @click="saveReport">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Delete, Edit } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { Project, Report } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { containsQuery, paginate } from '../utils/collection'
import { confirmDestructiveAction } from '../utils/confirm'

const projects = ref<Project[]>([])
const reports = ref<Report[]>([])
const projectId = ref<number>()
const reportType = ref('daily')
const loading = ref(false)
const editDialog = ref(false)
const activeReport = ref<Report | null>(null)
const editForm = reactive({ title: '', report_type: '', content: '' })
const filterQuery = ref('')
const filterProjectId = ref<number | null>(null)
const filterType = ref('')
const page = ref(1)
const pageSize = 6
const filteredReports = computed(() => reports.value.filter((report) =>
  containsQuery(filterQuery.value, report.title, report.content)
  && (!filterProjectId.value || report.project_id === filterProjectId.value)
  && (!filterType.value || report.report_type === filterType.value)
))
const pagedReports = computed(() => paginate(filteredReports.value, page.value, pageSize))

watch([filterQuery, filterProjectId, filterType], () => { page.value = 1 })

async function load() {
  const [projectRes, reportRes] = await Promise.all([api.get<Project[]>('/projects'), api.get<Report[]>('/reports')])
  projects.value = projectRes.data
  reports.value = reportRes.data
  projectId.value ||= projectRes.data[0]?.id
}

async function createReport() {
  if (!projectId.value) return
  loading.value = true
  try {
    await api.post('/reports', { project_id: projectId.value, report_type: reportType.value })
    await load()
  } finally {
    loading.value = false
  }
}

function openEdit(report: Report) {
  activeReport.value = report
  Object.assign(editForm, { title: report.title, report_type: report.report_type, content: report.content })
  editDialog.value = true
}

async function saveReport() {
  if (!activeReport.value) return
  await api.patch(`/reports/${activeReport.value.id}`, editForm)
  editDialog.value = false
  await load()
}

async function remove(id: number) {
  if (!await confirmDestructiveAction('删除后无法恢复，确认删除这份报告吗？', '删除报告')) return
  await api.delete(`/reports/${id}`)
  await load()
}

onMounted(load)
</script>
