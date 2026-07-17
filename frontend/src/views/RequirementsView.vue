<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1>需求中心</h1>
        <p>把模糊想法沉淀为需求卡片、PRD要点和验收标准。</p>
      </div>
      <el-button type="primary" @click="dialog = true">创建需求</el-button>
    </div>
    <div class="item-grid">
      <article v-for="item in requirements" :key="item.id" class="item-card wide">
        <h4>{{ item.title }}</h4>
        <el-tag>{{ item.status }}</el-tag>
        <p>{{ item.content }}</p>
        <MarkdownRenderer :content="item.analysis" />
      </article>
    </div>
    <el-dialog v-model="dialog" title="创建需求" width="560">
      <el-form label-position="top">
        <el-form-item label="需求标题">
          <el-input v-model="form.title" placeholder="例如：项目知识库检索优化" />
        </el-form-item>
        <el-form-item label="需求描述">
          <el-input v-model="form.content" type="textarea" :rows="6" placeholder="描述用户、场景、问题和期望结果" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="loading" @click="createRequirement">生成需求卡片</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'
import type { Requirement } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'

const requirements = ref<Requirement[]>([])
const dialog = ref(false)
const loading = ref(false)
const form = reactive({ title: '', content: '' })

async function load() {
  const { data } = await api.get<Requirement[]>('/requirements')
  requirements.value = data
}

async function createRequirement() {
  loading.value = true
  try {
    await api.post('/requirements', form)
    form.title = ''
    form.content = ''
    dialog.value = false
    await load()
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
