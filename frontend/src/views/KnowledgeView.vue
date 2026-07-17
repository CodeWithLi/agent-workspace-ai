<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1>知识库</h1>
        <p>{{ activeScopeLabel }}</p>
      </div>
      <div class="inline-actions">
        <el-select v-model="scopeProjectId" class="page-select" @change="changeScope">
          <el-option label="个人知识库" :value="0" />
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
        <el-button v-if="auth.hasPermission('knowledge:write')" type="primary" :icon="Upload" @click="uploadDialog = true">上传文件</el-button>
      </div>
    </div>

    <div class="search-bar">
      <el-input v-model="query" clearable placeholder="搜索当前知识库" @keyup.enter="search" />
      <el-button :icon="Search" type="primary" :loading="searching" :disabled="!query.trim()" @click="search">搜索</el-button>
    </div>

    <el-row :gutter="20">
      <el-col :xs="24" :lg="11">
        <h2 class="section-title">文档</h2>
        <div class="compact-filter-bar" aria-label="文档筛选">
          <el-input v-model="documentQuery" clearable placeholder="搜索文件名、来源或标签" aria-label="搜索文档" />
          <el-select v-model="documentStatus" clearable placeholder="全部状态" aria-label="按索引状态筛选">
            <el-option v-for="status in documentStatuses" :key="status" :label="statusLabel(status)" :value="status" />
          </el-select>
        </div>
        <el-table v-loading="loading" :data="pagedDocuments" class="data-table">
          <el-table-column label="文档" min-width="190">
            <template #default="{ row }">
              <strong>{{ row.filename }}</strong>
              <div class="document-meta">{{ row.source_label }} · v{{ row.version }} · {{ documentTags(row).join(' / ') || '无标签' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="105">
            <template #default="{ row }">
              <el-tooltip v-if="row.error" :content="row.error" placement="top">
                <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </el-tooltip>
              <el-tag v-else :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="auth.hasPermission('knowledge:write')" label="操作" width="138" align="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'FAILED'" link type="primary" @click="documentAction(row.id, 'retry')">重试</el-button>
              <el-button v-if="['INDEXED', 'EMPTY', 'FAILED'].includes(row.status)" link @click="documentAction(row.id, 'reindex')">重建</el-button>
              <el-button link type="danger" @click="remove(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!loading && !filteredDocuments.length" description="当前筛选条件下暂无文档" />
        <el-pagination v-if="filteredDocuments.length > documentPageSize" v-model:current-page="documentPage" class="page-pagination" background layout="prev, pager, next" :page-size="documentPageSize" :total="filteredDocuments.length" />
      </el-col>
      <el-col :xs="24" :lg="13">
        <h2 class="section-title">搜索结果</h2>
        <div v-if="answer" class="answer">{{ answer }}</div>
        <el-empty v-else-if="!searching && !results.length" description="输入关键词检索当前知识库" />
        <div v-for="result in results" :key="`${result.document_id}-${result.chunk_index}`" class="result-row">
          <div class="result-row-head">
            <strong>{{ result.filename }}</strong>
            <el-button link type="primary" @click="openCitation(result)">{{ result.citation }}</el-button>
          </div>
          <p>{{ result.content }}</p>
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="uploadDialog" title="上传知识文档" width="520">
      <el-form label-position="top">
        <el-form-item label="文件">
          <el-upload v-model:file-list="uploadFiles" drag :auto-upload="false" :limit="1" accept=".pdf,.docx,.md,.markdown,.txt">
            <el-icon><Upload /></el-icon>
            <div>选择 PDF、Word、Markdown 或 TXT</div>
          </el-upload>
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="uploadSource" placeholder="例如：产品手册、运维手册" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="uploadTags" placeholder="使用逗号分隔" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialog = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!uploadFiles.length" @click="uploadSelected">上传并索引</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="citationDialog" :title="citation?.citation || '引用内容'" width="680">
      <pre class="citation-content">{{ citation?.content }}</pre>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Search, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import type { UploadUserFile } from 'element-plus'
import { api } from '../api/client'
import type { KnowledgeDocument, Project } from '../api/types'
import { useAuthStore } from '../stores/auth'
import { containsQuery, paginate } from '../utils/collection'
import { confirmDestructiveAction } from '../utils/confirm'

interface SearchResult {
  document_id: number
  filename: string
  chunk_index: number
  content: string
  score: number
  citation: string
}

interface Citation {
  citation: string
  content: string
}

const auth = useAuthStore()
const projects = ref<Project[]>([])
const scopeProjectId = ref(0)
const documents = ref<KnowledgeDocument[]>([])
const query = ref('')
const answer = ref('')
const results = ref<SearchResult[]>([])
const loading = ref(false)
const searching = ref(false)
const uploadDialog = ref(false)
const uploadFiles = ref<UploadUserFile[]>([])
const uploadSource = ref('upload')
const uploadTags = ref('')
const uploading = ref(false)
const citationDialog = ref(false)
const citation = ref<Citation | null>(null)
const documentQuery = ref('')
const documentStatus = ref('')
const documentStatuses = ['QUEUED', 'INDEXING', 'INDEXED', 'EMPTY', 'FAILED']
const documentPage = ref(1)
const documentPageSize = 8
let refreshTimer: number | undefined
const activeScopeLabel = computed(() => scopeProjectId.value
  ? `${projects.value.find((item) => item.id === scopeProjectId.value)?.name || '项目'}知识库`
  : '个人知识库')
const filteredDocuments = computed(() => documents.value.filter((document) =>
  containsQuery(documentQuery.value, document.filename, document.source_label, ...documentTags(document))
  && (!documentStatus.value || document.status === documentStatus.value)
))
const pagedDocuments = computed(() => paginate(filteredDocuments.value, documentPage.value, documentPageSize))

watch([documentQuery, documentStatus], () => { documentPage.value = 1 })

function scopeParams() {
  return scopeProjectId.value ? { project_id: scopeProjectId.value } : {}
}

function documentTags(row: unknown) {
  const document = row as KnowledgeDocument
  try {
    const metadata = JSON.parse(document.metadata_json)
    return Array.isArray(metadata.tags) ? metadata.tags : []
  } catch {
    return []
  }
}

function statusLabel(value: string) {
  return { QUEUED: '等待索引', INDEXING: '索引中', INDEXED: '可检索', EMPTY: '无文本', FAILED: '失败' }[value] || value
}

function statusTagType(value: string) {
  return { QUEUED: 'info', INDEXING: 'primary', INDEXED: 'success', EMPTY: 'warning', FAILED: 'danger' }[value] as 'primary' | 'success' | 'warning' | 'info' | 'danger' | undefined
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const { data } = await api.get<KnowledgeDocument[]>('/knowledge/documents', { params: scopeParams() })
    documents.value = data
  } finally {
    loading.value = false
  }
}

async function changeScope() {
  query.value = ''
  answer.value = ''
  results.value = []
  documentPage.value = 1
  await load()
}

async function uploadSelected() {
  const file = uploadFiles.value[0]?.raw
  if (!file) return
  uploading.value = true
  try {
    const form = new FormData()
    form.append('file', file)
    if (scopeProjectId.value) form.append('project_id', String(scopeProjectId.value))
    form.append('source_label', uploadSource.value || 'upload')
    form.append('tags', uploadTags.value)
    await api.post('/knowledge/upload', form)
    uploadDialog.value = false
    uploadFiles.value = []
    uploadSource.value = 'upload'
    uploadTags.value = ''
    ElMessage.success('文档已进入索引队列')
    await load()
  } finally {
    uploading.value = false
  }
}

async function search() {
  if (!query.value.trim()) return
  searching.value = true
  try {
    const { data } = await api.post('/knowledge/search', { query: query.value, ...scopeParams() })
    answer.value = data.answer
    results.value = data.results
  } finally {
    searching.value = false
  }
}

async function documentAction(id: number, action: 'retry' | 'reindex') {
  await api.post(`/knowledge/documents/${id}/${action}`, { request_id: crypto.randomUUID() })
  ElMessage.success(action === 'retry' ? '文档已重新入队' : '文档已进入重建队列')
  await load(true)
}

async function remove(id: number) {
  if (!await confirmDestructiveAction('删除后文档及其索引将无法恢复，确认继续吗？', '删除知识文档')) return
  await api.delete(`/knowledge/documents/${id}`)
  await load()
}

async function openCitation(result: SearchResult) {
  const { data } = await api.get<Citation>(`/knowledge/documents/${result.document_id}/chunks/${result.chunk_index}`)
  citation.value = data
  citationDialog.value = true
}

onMounted(async () => {
  const { data } = await api.get<Project[]>('/projects')
  projects.value = data
  await load()
  refreshTimer = window.setInterval(() => {
    if (documents.value.some((item) => ['QUEUED', 'INDEXING'].includes(item.status))) void load(true)
  }, 2500)
})
onBeforeUnmount(() => window.clearInterval(refreshTimer))
</script>
