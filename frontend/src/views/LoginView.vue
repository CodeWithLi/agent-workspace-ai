<template>
  <main class="login-page">
    <section class="login-panel">
      <div>
        <h1>Agent Workspace AI</h1>
        <p>虚拟 AI 软件研发团队，覆盖需求、架构、任务、测试和知识库。</p>
      </div>
      <el-tabs v-model="mode" stretch>
        <el-tab-pane label="登录" name="login">
          <el-form label-position="top" @submit.prevent>
            <el-form-item label="邮箱">
              <el-input v-model="email" autocomplete="email" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="password" type="password" show-password autocomplete="current-password" />
            </el-form-item>
            <el-button type="primary" :loading="loading" class="full" @click="submit">登录</el-button>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="注册" name="register">
          <el-form label-position="top" @submit.prevent>
            <el-form-item label="姓名">
              <el-input v-model="name" autocomplete="name" />
            </el-form-item>
            <el-form-item label="邮箱">
              <el-input v-model="email" autocomplete="email" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="password" type="password" show-password autocomplete="new-password" />
            </el-form-item>
            <el-button type="primary" :loading="loading" class="full" @click="submit">创建账号</el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
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
