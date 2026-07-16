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
    ElMessage.error('认证失败，请检查输入或先注册账号')
  } finally {
    loading.value = false
  }
}
</script>
