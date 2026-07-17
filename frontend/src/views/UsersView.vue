<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1>用户与权限</h1>
        <p>管理账号状态、系统角色与最小权限。</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <div class="search-bar">
      <el-input v-model="query" :prefix-icon="Search" clearable placeholder="搜索姓名或邮箱" @keyup.enter="load" />
      <el-button type="primary" @click="load">搜索</el-button>
    </div>

    <el-table :data="users" class="data-table">
      <el-table-column prop="name" label="姓名" min-width="130" />
      <el-table-column prop="email" label="邮箱" min-width="220" />
      <el-table-column label="角色" width="110">
        <template #default="{ row }"><el-tag :type="row.role === 'admin' ? 'danger' : 'info'">{{ row.role }}</el-tag></template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="权限" min-width="300">
        <template #default="{ row }">
          <div class="tool-tags"><el-tag v-for="item in permissionsOfRow(row)" :key="item" size="small">{{ permissionLabel(item) }}</el-tag></div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }"><el-button :icon="Edit" circle aria-label="编辑权限" title="编辑权限" @click="openEditRow(row)" /></template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="编辑用户" width="min(520px, calc(100vw - 32px))">
      <el-form label-position="top">
        <el-form-item label="用户"><el-input :model-value="`${activeUser?.name} <${activeUser?.email}>`" disabled /></el-form-item>
        <el-form-item label="系统角色">
          <el-segmented v-model="form.role" :options="roleOptions" :disabled="activeUser?.id === auth.user?.id" />
        </el-form-item>
        <el-form-item label="账号状态"><el-switch v-model="form.is_active" :disabled="activeUser?.id === auth.user?.id" /></el-form-item>
        <el-form-item label="功能权限">
          <el-checkbox-group v-model="form.permissions">
            <el-checkbox v-for="item in permissionOptions" :key="item.value" :value="item.value">{{ item.label }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :icon="Key" @click="revokeSessions">撤销全部会话</el-button>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Edit, Key, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api } from '../api/client'
import type { User } from '../api/types'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const users = ref<User[]>([])
const query = ref('')
const dialog = ref(false)
const saving = ref(false)
const activeUser = ref<User | null>(null)
const form = reactive({ role: 'member' as User['role'], is_active: true, permissions: [] as string[] })
const roleOptions = [{ label: '成员', value: 'member' }, { label: '管理员', value: 'admin' }]
const permissionOptions = [
  { value: 'agents:read', label: '使用 AI 员工' },
  { value: 'projects:write', label: '写入项目数据' },
  { value: 'knowledge:write', label: '维护知识库' }
]

function permissionsOf(user: User) {
  return user.permissions.split(',').map((item) => item.trim()).filter(Boolean)
}

function permissionsOfRow(row: unknown) {
  return permissionsOf(row as User)
}

function permissionLabel(value: string) {
  return permissionOptions.find((item) => item.value === value)?.label || value
}

async function load() {
  const { data } = await api.get<User[]>('/users', { params: query.value.trim() ? { q: query.value.trim() } : {} })
  users.value = data
}

function openEdit(user: User) {
  activeUser.value = user
  Object.assign(form, { role: user.role, is_active: user.is_active, permissions: permissionsOf(user) })
  dialog.value = true
}

function openEditRow(row: unknown) {
  openEdit(row as User)
}

async function save() {
  if (!activeUser.value) return
  saving.value = true
  try {
    await api.patch(`/users/${activeUser.value.id}`, form)
    ElMessage.success('用户权限已更新')
    dialog.value = false
    await load()
    if (activeUser.value.id === auth.user?.id) await auth.fetchMe()
  } finally {
    saving.value = false
  }
}

async function revokeSessions() {
  if (!activeUser.value) return
  await api.post(`/users/${activeUser.value.id}/revoke-sessions`)
  ElMessage.success('该用户的登录会话已撤销')
}

onMounted(load)
</script>
