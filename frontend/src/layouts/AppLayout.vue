<template>
  <el-container class="shell">
    <el-aside width="236px" class="sidebar" :class="{ 'mobile-open': mobileNav }">
      <div class="brand">Agent Workspace AI</div>
      <el-menu router :default-active="$route.path" class="menu" @select="mobileNav = false">
        <el-menu-item index="/">
          <el-icon><Monitor /></el-icon>
          <span>工作台</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('agents:read')" index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>AI 对齐室</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><Folder /></el-icon>
          <span>项目空间</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('projects:write')" index="/requirements">
          <el-icon><Document /></el-icon>
          <span>需求中心</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('agents:read')" index="/agents">
          <el-icon><UserFilled /></el-icon>
          <span>AI员工列表</span>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><Tickets /></el-icon>
          <span>任务看板</span>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><Files /></el-icon>
          <span>知识库</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('projects:write')" index="/meetings">
          <el-icon><Notebook /></el-icon>
          <span>会议中心</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('projects:write')" index="/reports">
          <el-icon><TrendCharts /></el-icon>
          <span>项目报告</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('projects:write')" index="/notifications">
          <el-icon><Bell /></el-icon>
          <span>通知中心</span>
        </el-menu-item>
        <el-menu-item v-if="auth.user?.role === 'admin'" index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
        <el-menu-item v-if="auth.user?.role === 'admin'" index="/users">
          <el-icon><User /></el-icon>
          <span>用户与权限</span>
        </el-menu-item>
        <el-menu-item v-if="auth.user?.role === 'admin'" index="/audit">
          <el-icon><List /></el-icon>
          <span>审计日志</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <button v-if="mobileNav" class="sidebar-backdrop" aria-label="关闭导航" @click="mobileNav = false" />
    <el-container>
      <el-header class="topbar">
        <el-button class="mobile-menu-button" :icon="MenuIcon" circle title="打开导航" @click="mobileNav = true" />
        <div class="top-search">
          <el-input v-model="searchText" :prefix-icon="Search" placeholder="搜索项目、需求、任务、知识..." @keyup.enter="doSearch" />
          <div v-if="searchResults.length" class="search-popover">
            <button v-for="item in searchResults" :key="`${item.type}-${item.title}`" @click="go(item.url)">
              <strong>{{ item.title }}</strong>
              <span>{{ item.type }} · {{ item.description }}</span>
            </button>
          </div>
        </div>
        <div class="top-actions">
          <el-button class="quick-create" :icon="Plus" @click="router.push('/requirements')">创建需求</el-button>
          <el-button :icon="Bell" circle title="通知中心" @click="router.push('/notifications')" />
          <el-avatar>{{ auth.user?.name?.slice(0, 1) || '我' }}</el-avatar>
          <el-button class="logout-button" :icon="SwitchButton" title="退出" @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main class="content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { Bell, ChatDotRound, Document, Files, Folder, List, Menu as MenuIcon, Monitor, Notebook, Plus, Search, Setting, SwitchButton, Tickets, TrendCharts, User, UserFilled } from '@element-plus/icons-vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { api } from '../api/client'
import type { GlobalSearchResult } from '../api/types'

const auth = useAuthStore()
const router = useRouter()
const searchText = ref('')
const searchResults = ref<GlobalSearchResult[]>([])
const mobileNav = ref(false)

async function logout() {
  await auth.logout()
  router.push('/login')
}

async function doSearch() {
  if (!searchText.value.trim()) {
    searchResults.value = []
    return
  }
  const { data } = await api.get<{ results: GlobalSearchResult[] }>('/search', { params: { q: searchText.value } })
  searchResults.value = data.results
}

function go(url: string) {
  searchResults.value = []
  router.push(url)
}
</script>
