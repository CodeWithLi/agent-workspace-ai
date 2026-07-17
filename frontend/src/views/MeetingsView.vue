<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1>会议中心</h1>
        <p>输入会议记录，AI自动生成会议纪要、TODO、负责人和时间。</p>
      </div>
      <el-button type="primary" :loading="loading" @click="createMeeting">生成纪要</el-button>
    </div>
    <el-form label-position="top" class="work-form">
      <el-form-item label="会议标题">
        <el-input v-model="title" />
      </el-form-item>
      <el-form-item label="会议记录">
        <el-input v-model="transcript" type="textarea" :rows="8" />
      </el-form-item>
    </el-form>
    <div class="item-grid">
      <article v-for="meeting in meetings" :key="meeting.id" class="item-card wide">
        <h4>{{ meeting.title }}</h4>
        <MarkdownRenderer :content="meeting.summary" />
        <pre>{{ meeting.action_items }}</pre>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import type { Meeting } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'

const meetings = ref<Meeting[]>([])
const title = ref('项目例会')
const transcript = ref('今天确认需求范围。\n后端负责认证和项目接口。\n前端负责工作台和聊天页面。\n下周完成联调。')
const loading = ref(false)

async function load() {
  const { data } = await api.get<Meeting[]>('/meetings')
  meetings.value = data
}

async function createMeeting() {
  loading.value = true
  try {
    await api.post('/meetings', { title: title.value, transcript: transcript.value })
    await load()
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
