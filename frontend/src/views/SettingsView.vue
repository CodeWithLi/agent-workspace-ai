<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h2>系统设置</h2>
        <p>查看当前 LLM Gateway、Embedding、Milvus 配置。</p>
      </div>
    </div>
    <el-descriptions v-if="setting" :column="1" border>
      <el-descriptions-item label="Provider">{{ setting.provider }}</el-descriptions-item>
      <el-descriptions-item label="Base URL">{{ setting.base_url }}</el-descriptions-item>
      <el-descriptions-item label="Model">{{ setting.model }}</el-descriptions-item>
      <el-descriptions-item label="Embedding">{{ setting.embedding_model }}</el-descriptions-item>
      <el-descriptions-item label="Milvus Collection">{{ setting.milvus_collection }}</el-descriptions-item>
      <el-descriptions-item label="Environment">{{ setting.environment }}</el-descriptions-item>
      <el-descriptions-item label="Allow Registration">{{ setting.allow_registration ? '是' : '否' }}</el-descriptions-item>
      <el-descriptions-item label="Registration Domains">{{ setting.registration_email_domains.join(', ') || '未限制' }}</el-descriptions-item>
    </el-descriptions>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import type { SystemSetting } from '../api/types'

const setting = ref<SystemSetting>()

onMounted(async () => {
  const { data } = await api.get<SystemSetting>('/settings')
  setting.value = data
})
</script>
