<template>
  <main class="login-page">
    <section class="login-shell">
      <aside class="login-context">
        <div class="login-brand"><span class="brand-mark"><el-icon><Connection /></el-icon></span><strong>Agent Workspace</strong></div>
        <div class="login-message">
          <span class="page-kicker">AI DIGITAL TEAM</span>
          <h1>让专业 Agent<br>进入同一个项目空间</h1>
          <p>从需求、架构、计划到测试，保留上下文、过程记录与人工决策。</p>
        </div>
        <ul>
          <li><el-icon><CircleCheck /></el-icon> 多 Agent 协作工作流</li>
          <li><el-icon><CircleCheck /></el-icon> 企业知识库与可追溯引用</li>
          <li><el-icon><CircleCheck /></el-icon> 权限、审批和运行审计</li>
        </ul>
      </aside>
      <section class="login-panel">
        <div class="login-panel-head">
          <span class="mobile-login-brand"><span class="brand-mark"><el-icon><Connection /></el-icon></span>Agent Workspace</span>
          <h2>{{ mode === 'login' ? '欢迎回来' : '创建工作空间账号' }}</h2>
          <p>{{ mode === 'login' ? '登录后继续管理项目和 AI 团队。' : '注册即获得用于体验的 AI Token。' }}</p>
        </div>
        <el-tabs v-model="mode" stretch>
          <el-tab-pane label="登录" name="login">
            <el-form label-position="top" @submit.prevent>
              <el-form-item label="邮箱">
                <el-input v-model.trim="email" type="email" autocomplete="email" placeholder="name@company.com" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="password" type="password" show-password autocomplete="current-password" placeholder="输入登录密码" />
              </el-form-item>
              <el-button type="primary" :loading="loading" :disabled="!email || !password" class="full" @click="submit">登录工作空间</el-button>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="注册" name="register">
            <el-form label-position="top" @submit.prevent>
              <el-form-item label="姓名">
                <el-input v-model.trim="name" autocomplete="name" placeholder="你的姓名" />
              </el-form-item>
              <el-form-item label="邮箱">
                <el-input v-model.trim="email" type="email" autocomplete="email" placeholder="name@company.com" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="password" type="password" show-password autocomplete="new-password" placeholder="至少 8 位，包含字母和数字" />
              </el-form-item>
              <el-button type="primary" :loading="loading" :disabled="!name || !email || !password" class="full" @click="submit">创建账号</el-button>
            </el-form>
          </el-tab-pane>
        </el-tabs>
        <p class="login-legal">登录即表示你同意企业数据与安全策略。</p>
      </section>
    </section>
  </main>
</template>

<script setup lang="ts">
import axios from 'axios'
import { ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { CircleCheck, Connection } from '@element-plus/icons-vue'

const auth = useAuthStore()
const router = useRouter()
const mode = ref<'login' | 'register'>('login')
const email = ref('demo@example.com')
const name = ref('演示用户')
const password = ref('password123')
const loading = ref(false)

function authenticationError(error: unknown) {
  if (!axios.isAxiosError(error) || !error.response) return '无法连接服务，请稍后重试'
  if (error.response.status === 409) return '该邮箱已注册，请直接登录'
  if (error.response.status === 401) return '邮箱或密码错误'
  if (error.response.status === 422) {
    return mode.value === 'register'
      ? '请检查邮箱格式、姓名和密码，密码至少 8 位且需包含字母与数字'
      : '请检查邮箱和密码格式'
  }
  const detail = error.response.data?.detail
  return typeof detail === 'string' ? detail : '认证失败，请稍后重试'
}

async function submit() {
  loading.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(email.value, password.value)
    } else {
      await auth.register(email.value, name.value, password.value)
    }
    router.push('/')
  } catch (error) {
    ElMessage.error(authenticationError(error))
  } finally {
    loading.value = false
  }
}
</script>
