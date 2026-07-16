<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h2>通知中心</h2>
        <p>站内通知与邮件</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="dialog = true">新建通知</el-button>
    </div>

    <el-table :data="notifications" class="data-table">
      <el-table-column prop="title" label="标题" min-width="180" />
      <el-table-column prop="recipient_email" label="接收人" min-width="200" />
      <el-table-column prop="channel" label="渠道" width="100" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template>
      </el-table-column>
      <el-table-column label="计划时间" min-width="180">
        <template #default="{ row }">{{ formatTime(row.scheduled_for) }}</template>
      </el-table-column>
      <el-table-column label="结果" min-width="220">
        <template #default="{ row }">{{ row.last_error || formatTime(row.sent_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button v-if="['DRAFT', 'FAILED', 'CANCELLED'].includes(row.status)" :icon="Promotion" circle title="立即发送" @click="sendNow(row.id)" />
          <el-button v-if="['DRAFT', 'SCHEDULED'].includes(row.status)" :icon="Close" circle title="取消" @click="cancel(row.id)" />
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="新建通知" width="520">
      <el-form label-position="top">
        <el-form-item label="渠道">
          <el-segmented v-model="form.channel" :options="channelOptions" />
        </el-form-item>
        <el-form-item label="接收邮箱">
          <el-input v-model="form.recipient_email" placeholder="member@company.com" />
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="form.content" type="textarea" :rows="5" /></el-form-item>
        <el-form-item label="计划时间">
          <el-date-picker v-model="form.schedule_at" type="datetime" class="full" placeholder="留空保存为草稿" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :disabled="!form.title || !form.content || !form.recipient_email" @click="create">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Close, Plus, Promotion } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { NotificationItem } from '../api/types'

const notifications = ref<NotificationItem[]>([])
const dialog = ref(false)
const channelOptions = [{ label: '站内', value: 'in_app' }, { label: '邮件', value: 'email' }]
const form = reactive({ channel: 'in_app', recipient_email: '', title: '', content: '', schedule_at: null as Date | null })
let timer: number | undefined

async function load() {
  const { data } = await api.get<NotificationItem[]>('/notifications')
  notifications.value = data
}

async function create() {
  await api.post('/notifications', { ...form, schedule_at: form.schedule_at?.toISOString() || null })
  dialog.value = false
  Object.assign(form, { channel: 'in_app', recipient_email: '', title: '', content: '', schedule_at: null })
  await load()
}

async function sendNow(id: number) {
  await api.post(`/notifications/${id}/send`)
  await load()
}

async function cancel(id: number) {
  await api.post(`/notifications/${id}/cancel`)
  await load()
}

function formatTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-'
}

function statusType(status: string) {
  if (status === 'SENT') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'SCHEDULED' || status === 'SENDING') return 'warning'
  return 'info'
}

onMounted(async () => {
  await load()
  timer = window.setInterval(load, 5000)
})
onBeforeUnmount(() => timer && window.clearInterval(timer))
</script>
