<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h2>审计日志</h2>
        <p>查看认证、权限、Agent 工具、知识库和工作流的关键操作记录。</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>
    <el-table :data="logs" class="data-table">
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
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { AuditLog } from '../api/types'

const logs = ref<AuditLog[]>([])

async function load() {
  const { data } = await api.get<AuditLog[]>('/audit', { params: { limit: 200 } })
  logs.value = data
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
