<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1>审计日志</h1>
        <p>查看认证、权限、Agent 工具、知识库和工作流的关键操作记录。</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>
    <div class="filter-bar" aria-label="审计日志筛选">
      <el-input v-model="query" clearable placeholder="搜索动作、资源、用户或 IP" aria-label="搜索审计日志" />
      <el-input v-model="projectId" clearable inputmode="numeric" placeholder="项目 ID" aria-label="按项目 ID 筛选" />
    </div>
    <el-table v-loading="loading" :data="pagedLogs" class="data-table">
      <el-table-column prop="created_at" label="时间" min-width="180">
        <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
      </el-table-column>
      <el-table-column prop="action" label="动作" min-width="180" />
      <el-table-column prop="user_id" label="用户 ID" width="100" />
      <el-table-column prop="project_id" label="项目 ID" width="100" />
      <el-table-column label="资源" min-width="160">
        <template #default="{ row }">{{ row.resource_type }} {{ row.resource_id }}</template>
      </el-table-column>
      <el-table-column prop="ip_address" label="IP" min-width="130" />
      <el-table-column label="详情" min-width="260">
        <template #default="{ row }"><code>{{ formatDetails(row.details) }}</code></template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !filteredLogs.length" description="没有符合条件的审计记录" />
    <el-pagination v-if="filteredLogs.length > pageSize" v-model:current-page="page" class="page-pagination" background layout="prev, pager, next" :page-size="pageSize" :total="filteredLogs.length" />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { AuditLog } from '../api/types'
import { containsQuery, paginate } from '../utils/collection'

const logs = ref<AuditLog[]>([])
const loading = ref(false)
const query = ref('')
const projectId = ref('')
const page = ref(1)
const pageSize = 15
const filteredLogs = computed(() => logs.value.filter((log) =>
  containsQuery(query.value, log.action, log.resource_type, log.resource_id, log.user_id, log.ip_address, log.details)
  && (!projectId.value.trim() || String(log.project_id ?? '') === projectId.value.trim())
))
const pagedLogs = computed(() => paginate(filteredLogs.value, page.value, pageSize))

watch([query, projectId], () => { page.value = 1 })

async function load() {
  loading.value = true
  try {
    const { data } = await api.get<AuditLog[]>('/audit', { params: { limit: 200 } })
    logs.value = data
  } finally {
    loading.value = false
  }
}

function formatDetails(raw: string) {
  try {
    return JSON.stringify(JSON.parse(raw))
  } catch {
    return raw
  }
}

onMounted(load)
</script>
