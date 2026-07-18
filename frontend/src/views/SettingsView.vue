<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1>系统设置</h1>
        <p>运行环境：{{ settings?.environment || '-' }}</p>
      </div>
      <div class="inline-actions">
        <el-button :icon="Monitor" @click="openPythonAdmin">管理后台</el-button>
        <el-button type="primary" :icon="Check" :loading="saving" @click="save">保存配置</el-button>
      </div>
    </div>

    <div class="settings-connection-bar">
      <span>连接检查</span>
      <el-button
        v-for="target in connectionTargets"
        :key="target.value"
        size="small"
        :icon="Connection"
        :loading="testingTarget === target.value"
        @click="testConnection(target.value)"
      >{{ target.label }}</el-button>
    </div>

    <el-tabs v-model="activeCategory" class="settings-tabs">
      <el-tab-pane v-for="category in categories" :key="category.value" :label="category.label" :name="category.value">
        <div class="settings-grid">
          <div v-for="item in groupedItems[category.value] || []" :key="item.key" class="setting-row">
            <div class="setting-label">
              <label :for="`setting-${item.key}`">{{ item.label }}</label>
              <div class="setting-meta">
                <el-tag size="small" effect="plain">{{ sourceLabel(item.source) }}</el-tag>
                <el-tag v-if="item.restart_required" size="small" type="warning" effect="plain">需重启</el-tag>
              </div>
            </div>
            <el-switch
              v-if="item.value_type === 'bool'"
              :id="`setting-${item.key}`"
              v-model="draft[item.key]"
            />
            <el-input-number
              v-else-if="['int', 'float'].includes(item.value_type)"
              :id="`setting-${item.key}`"
              v-model="draft[item.key]"
              :min="item.minimum ?? undefined"
              :max="item.maximum ?? undefined"
              :step="item.value_type === 'float' ? 0.1 : 1"
              controls-position="right"
            />
            <el-input
              v-else
              :id="`setting-${item.key}`"
              v-model="draft[item.key]"
              :type="item.secret ? 'password' : 'text'"
              :show-password="item.secret"
              :placeholder="item.secret && !item.configured ? '未配置' : ''"
              autocomplete="off"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Check, Connection, Monitor } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api } from '../api/client'
import type { SystemSettingItem, SystemSettings } from '../api/types'

const settings = ref<SystemSettings>()
const draft = reactive<Record<string, any>>({})
const saving = ref(false)
const testingTarget = ref('')
const activeCategory = ref('model')
const categories = [
  { value: 'model', label: '模型与 Embedding' },
  { value: 'rag', label: '知识检索' },
  { value: 'billing', label: 'Token 计费' },
  { value: 'registration', label: '注册策略' },
  { value: 'notification', label: '通知服务' },
  { value: 'runtime', label: '运行控制' },
  { value: 'observability', label: '可观测性 SLO' }
]
const connectionTargets = [
  { value: 'llm', label: 'LLM' },
  { value: 'embedding', label: 'Embedding' },
  { value: 'reranker', label: 'Reranker' },
  { value: 'docling', label: 'Docling' },
  { value: 'redis', label: 'Redis' },
  { value: 'milvus', label: 'Milvus' },
  { value: 'minio', label: 'MinIO' },
  { value: 'smtp', label: 'SMTP' }
]
const groupedItems = computed(() => {
  const result: Record<string, SystemSettingItem[]> = {}
  for (const item of settings.value?.items || []) {
    ;(result[item.category] ||= []).push(item)
  }
  return result
})

function sourceLabel(source: string) {
  return { database: '运行时', environment: '环境变量', default: '默认值' }[source] || source
}

function hydrate(data: SystemSettings) {
  settings.value = data
  for (const item of data.items) {
    if (item.secret) draft[item.key] = item.configured ? '********' : ''
    else if (item.value_type === 'list') draft[item.key] = Array.isArray(item.value) ? item.value.join(', ') : ''
    else draft[item.key] = item.value
  }
}

async function load() {
  const { data } = await api.get<SystemSettings>('/settings')
  hydrate(data)
}

async function save() {
  if (!settings.value) return
  saving.value = true
  try {
    const values = Object.fromEntries(settings.value.items.map((item) => {
      const value = item.secret && !draft[item.key]
        ? null
        : item.value_type === 'list'
        ? String(draft[item.key] || '').split(',').map((entry) => entry.trim()).filter(Boolean)
        : draft[item.key]
      return [item.key, value]
    }))
    const { data } = await api.patch<SystemSettings>('/settings', { values })
    hydrate(data)
    ElMessage.success('系统配置已更新')
  } finally {
    saving.value = false
  }
}

async function testConnection(target: string) {
  testingTarget.value = target
  try {
    const { data } = await api.post<{ ok: boolean; message: string }>('/settings/test-connection', { target })
    if (data.ok) ElMessage.success(data.message)
    else ElMessage.error(data.message)
  } finally {
    testingTarget.value = ''
  }
}

function openPythonAdmin() {
  window.location.assign('/admin')
}

onMounted(load)
</script>
