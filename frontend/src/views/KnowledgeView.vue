<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h2>知识库</h2>
        <p>上传 PDF、Word、Markdown，并进行上下文增强搜索。</p>
      </div>
      <el-upload :http-request="upload" :show-file-list="false">
        <el-button type="primary" :icon="Upload">上传文件</el-button>
      </el-upload>
    </div>

    <div class="search-bar">
      <el-input v-model="query" placeholder="搜索企业知识库" @keyup.enter="search" />
      <el-button :icon="Search" type="primary" @click="search">搜索</el-button>
    </div>

    <el-row :gutter="20">
      <el-col :span="10">
        <h3>文档</h3>
        <el-table :data="documents" class="data-table">
          <el-table-column prop="filename" label="文件名" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link type="danger" @click="remove(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-col>
      <el-col :span="14">
        <h3>搜索结果</h3>
        <div class="answer">{{ answer }}</div>
        <div v-for="result in results" :key="`${result.document_id}-${result.content}`" class="result-row">
          <strong>{{ result.filename }}</strong>
          <el-tag size="small">{{ result.citation }}</el-tag>
          <p>{{ result.content }}</p>
        </div>
      </el-col>
    </el-row>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Search, Upload } from '@element-plus/icons-vue'
import type { UploadRequestOptions } from 'element-plus'
import { api } from '../api/client'
import type { KnowledgeDocument } from '../api/types'

const documents = ref<KnowledgeDocument[]>([])
const query = ref('')
const answer = ref('')
const results = ref<{ document_id: number; filename: string; content: string; score: number; citation: string }[]>([])

async function load() {
  const { data } = await api.get<KnowledgeDocument[]>('/knowledge/documents')
  documents.value = data
}

async function upload(options: UploadRequestOptions) {
  const form = new FormData()
  form.append('file', options.file)
  await api.post('/knowledge/upload', form)
  await load()
}

async function search() {
  const { data } = await api.post('/knowledge/search', { query: query.value, top_k: 5 })
  answer.value = data.answer
  results.value = data.results
}

async function remove(id: number) {
  await api.delete(`/knowledge/documents/${id}`)
  await load()
}

onMounted(load)
</script>
