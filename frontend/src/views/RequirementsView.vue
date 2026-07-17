<template>
  <section class="page">
    <div class="page-head">
      <div><h1>需求中心</h1><p>需求卡片、分析结论与验收状态。</p></div>
      <el-button type="primary" :icon="Plus" @click="openCreate">创建需求</el-button>
    </div>
    <div class="filter-bar" aria-label="需求筛选">
      <el-input v-model="filterQuery" clearable placeholder="搜索标题或内容" aria-label="搜索需求" />
      <el-select v-model="filterStatus" clearable placeholder="全部状态" aria-label="按状态筛选">
        <el-option v-for="status in requirementStatuses" :key="status" :label="status" :value="status" />
      </el-select>
      <el-select v-model="filterProjectId" clearable placeholder="全部项目" aria-label="按项目筛选">
        <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
      </el-select>
    </div>
    <div class="item-grid">
      <article v-for="item in pagedRequirements" :key="item.id" class="item-card wide">
        <div class="item-card-head"><h4>{{ item.title }}</h4><div><el-button :icon="Edit" circle aria-label="编辑需求" title="编辑" @click="openEdit(item)" /><el-button :icon="Delete" circle aria-label="删除需求" title="删除" @click="remove(item.id)" /></div></div>
        <el-tag>{{ item.status }}</el-tag>
        <p>{{ item.content }}</p>
        <MarkdownRenderer :content="item.analysis" />
      </article>
    </div>
    <el-empty v-if="!filteredRequirements.length" description="没有符合条件的需求" />
    <el-pagination v-if="filteredRequirements.length > pageSize" v-model:current-page="page" class="page-pagination" background layout="prev, pager, next" :page-size="pageSize" :total="filteredRequirements.length" />
    <el-dialog v-model="dialog" :title="activeRequirement ? '编辑需求' : '创建需求'" width="560">
      <el-form label-position="top">
        <el-form-item v-if="!activeRequirement" label="所属项目"><el-select v-model="form.project_id" clearable class="full"><el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" /></el-select></el-form-item>
        <el-form-item label="需求标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="需求描述"><el-input v-model="form.content" type="textarea" :rows="6" /></el-form-item>
        <el-form-item v-if="activeRequirement" label="状态"><el-select v-model="form.status" class="full"><el-option v-for="status in requirementStatuses" :key="status" :label="status" :value="status" /></el-select></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="loading" :disabled="!form.title.trim() || !form.content.trim()" @click="saveRequirement">{{ activeRequirement ? '保存' : '生成需求卡片' }}</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Delete, Edit, Plus } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { Project, Requirement } from '../api/types'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { containsQuery, paginate } from '../utils/collection'
import { confirmDestructiveAction } from '../utils/confirm'

const requirements = ref<Requirement[]>([])
const projects = ref<Project[]>([])
const dialog = ref(false)
const loading = ref(false)
const activeRequirement = ref<Requirement | null>(null)
const requirementStatuses = ['NEW', 'ANALYZED', 'APPROVED', 'REJECTED', 'DONE']
const form = reactive<any>({ title: '', content: '', project_id: null, status: 'NEW' })
const filterQuery = ref('')
const filterStatus = ref('')
const filterProjectId = ref<number | null>(null)
const page = ref(1)
const pageSize = 8
const filteredRequirements = computed(() => requirements.value.filter((item) =>
  containsQuery(filterQuery.value, item.title, item.content, item.analysis)
  && (!filterStatus.value || item.status === filterStatus.value)
  && (!filterProjectId.value || item.project_id === filterProjectId.value)
))
const pagedRequirements = computed(() => paginate(filteredRequirements.value, page.value, pageSize))

watch([filterQuery, filterStatus, filterProjectId], () => { page.value = 1 })

async function load() {
  const [requirementResponse, projectResponse] = await Promise.all([
    api.get<Requirement[]>('/requirements'),
    api.get<Project[]>('/projects')
  ])
  requirements.value = requirementResponse.data
  projects.value = projectResponse.data
}

function openCreate() {
  activeRequirement.value = null
  Object.assign(form, { title: '', content: '', project_id: projects.value[0]?.id || null, status: 'NEW' })
  dialog.value = true
}

function openEdit(item: Requirement) {
  activeRequirement.value = item
  Object.assign(form, { title: item.title, content: item.content, project_id: item.project_id || null, status: item.status })
  dialog.value = true
}

async function saveRequirement() {
  loading.value = true
  try {
    if (activeRequirement.value) {
      await api.patch(`/requirements/${activeRequirement.value.id}`, { title: form.title, content: form.content, status: form.status })
    } else {
      await api.post('/requirements', { title: form.title, content: form.content, project_id: form.project_id })
    }
    dialog.value = false
    await load()
  } finally {
    loading.value = false
  }
}

async function remove(id: number) {
  if (!await confirmDestructiveAction('删除后无法恢复，确认删除这条需求吗？', '删除需求')) return
  await api.delete(`/requirements/${id}`)
  await load()
}

onMounted(load)
</script>
