import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/LoginView.vue') },
    { path: '/403', component: () => import('../views/ForbiddenView.vue') },
    {
      path: '/',
      component: () => import('../layouts/AppLayout.vue'),
      children: [
        { path: '', component: () => import('../views/DashboardView.vue') },
        { path: 'projects', component: () => import('../views/DashboardView.vue') },
        { path: 'projects/:id', component: () => import('../views/ProjectView.vue') },
        { path: 'requirements', component: () => import('../views/RequirementsView.vue') },
        { path: 'agents', component: () => import('../views/AgentListView.vue') },
        { path: 'chat', component: () => import('../views/ChatView.vue') },
        { path: 'tasks', component: () => import('../views/TaskBoardView.vue') },
        { path: 'knowledge', component: () => import('../views/KnowledgeView.vue') },
        { path: 'meetings', component: () => import('../views/MeetingsView.vue') },
        { path: 'reports', component: () => import('../views/ReportsView.vue') },
        { path: 'settings', component: () => import('../views/SettingsView.vue'), meta: { requiresAdmin: true } },
        { path: 'audit', component: () => import('../views/AuditView.vue'), meta: { requiresAdmin: true } }
      ]
    }
  ]
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.path !== '/login' && !auth.token) {
    return '/login'
  }
  if (to.path !== '/login' && auth.token && !auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      auth.logout()
      return '/login'
    }
  }
  if (to.meta.requiresAdmin && auth.user?.role !== 'admin') {
    return '/403'
  }
  if (to.path === '/login' && auth.token) {
    return '/'
  }
  return true
})

export default router
