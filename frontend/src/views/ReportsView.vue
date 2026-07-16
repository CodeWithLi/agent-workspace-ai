<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h2>项目报告</h2>
        <p>生成日报、周报、风险报告和进度报告。</p>
      </div>
      <div class="inline-actions">
        <el-select v-model="projectId" placeholder="项目" style="width: 220px">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
        <el-select v-model="reportType" style="width: 140px">
          <el-option label="日报" value="daily" />
          <el-option label="周报" value="weekly" />
          <el-option label="风险报告" value="risk" />
          <el-option label="进度报告" value="progress" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="createReport">生成</el-button>
      </div>
    </div>
    <div class="report-list">
      <article v-for="report in reports" :key="report.id" class="report-panel">
        <h3>{{ report.title }}</h3>
        <MarkdownRenderer :content="report.content" />
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import type { Project, Report } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'

const projects = ref<Project[]>([])
const reports = ref<Report[]>([])
const projectId = ref<number>()
const reportType = ref('daily')
const loading = ref(false)

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

onMounted(load)
</script>
