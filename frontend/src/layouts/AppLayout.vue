<template>
  <a class="skip-link" href="#main-content">跳到主内容</a>
  <el-container class="shell">
    <el-aside width="236px" class="sidebar" :class="{ 'mobile-open': mobileNav }">
      <div class="brand">
        <span class="brand-mark"><el-icon><Connection /></el-icon></span>
        <span class="brand-copy"><strong>Agent Workspace</strong><small>AI 协作平台</small></span>
      </div>
      <el-menu router :default-active="$route.path" class="menu" aria-label="主导航" @select="mobileNav = false">
        <li class="menu-label" role="presentation">工作空间</li>
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
        <li class="menu-label" role="presentation">智能协作</li>
        <el-menu-item v-if="auth.hasPermission('agents:read')" index="/agents">
          <el-icon><Cpu /></el-icon>
          <span>AI 员工</span>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><Tickets /></el-icon>
          <span>任务看板</span>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><Files /></el-icon>
          <span>知识库</span>
        </el-menu-item>
        <el-menu-item index="/wallet">
          <el-icon><Coin /></el-icon>
          <span>Token 钱包</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('projects:write')" index="/meetings">
          <el-icon><Notebook /></el-icon>
          <span>会议中心</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('projects:write')" index="/reports">
          <el-icon><TrendCharts /></el-icon>
          <span>项目报告</span>
        </el-menu-item>
        <li v-if="auth.user?.role === 'admin'" class="menu-label" role="presentation">平台管理</li>
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
      <div class="sidebar-status"><span class="status-dot" /> Agent 服务已连接</div>
    </el-aside>
    <button v-if="mobileNav" class="sidebar-backdrop" aria-label="关闭导航" @click="mobileNav = false" />
    <el-container>
      <el-header class="topbar">
        <el-button class="mobile-menu-button" :icon="MenuIcon" circle aria-label="打开导航" title="打开导航" @click="mobileNav = true" />
        <div class="top-search">
          <el-input v-model="searchText" :prefix-icon="Search" clearable aria-label="全局搜索" placeholder="搜索项目、需求、任务或知识" @keyup.enter="doSearch" />
          <div v-if="searchResults.length" class="search-popover">
            <button v-for="item in searchResults" :key="`${item.type}-${item.title}`" @click="go(item.url)">
              <strong>{{ item.title }}</strong>
              <span>{{ item.type }} · {{ item.description }}</span>
            </button>
          </div>
        </div>
        <div class="top-actions">
          <el-button v-if="auth.hasPermission('projects:write')" class="quick-create" type="primary" :icon="Plus" @click="router.push('/requirements')">创建需求</el-button>
          <el-button class="token-balance" :icon="Coin" aria-label="AI Token 钱包" title="AI Token 钱包" @click="router.push('/wallet')">{{ auth.user?.ai_token_balance ?? 0 }}</el-button>
          <el-button v-if="auth.hasPermission('projects:write')" class="icon-action" :icon="Bell" circle aria-label="通知中心" title="通知中心" @click="router.push('/notifications')" />
          <el-dropdown trigger="click" @command="handleUserCommand">
            <button class="profile-trigger" aria-label="打开用户菜单">
              <el-avatar :size="36">{{ auth.user?.name?.slice(0, 1) || '我' }}</el-avatar>
              <span class="profile-copy"><strong>{{ auth.user?.name || '当前用户' }}</strong><small>{{ auth.user?.role === 'admin' ? '管理员' : '成员' }}</small></span>
              <el-icon class="profile-arrow"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="auth.user?.role === 'admin'" command="settings" :icon="Setting">系统设置</el-dropdown-item>
                <el-dropdown-item command="wallet" :icon="Coin">Token 钱包</el-dropdown-item>
                <el-dropdown-item command="logout" :icon="SwitchButton" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main id="main-content" class="content" tabindex="-1">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ArrowDown, Bell, ChatDotRound, Coin, Connection, Cpu, Document, Files, Folder, List, Menu as MenuIcon, Monitor, Notebook, Plus, Search, Setting, SwitchButton, Tickets, TrendCharts, User } from '@element-plus/icons-vue'
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

async function handleUserCommand(command: string) {
  if (command === 'logout') return logout()
  if (command === 'wallet') return router.push('/wallet')
  if (command === 'settings') return router.push('/settings')
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
