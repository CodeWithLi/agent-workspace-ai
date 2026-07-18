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
        { path: 'requirements', component: () => import('../views/RequirementsView.vue'), meta: { requiresPermission: 'projects:write' } },
        { path: 'prototypes', component: () => import('../views/PrototypeStudioView.vue') },
        { path: 'agents', component: () => import('../views/AgentListView.vue'), meta: { requiresPermission: 'agents:read' } },
        { path: 'evaluations', component: () => import('../views/EvaluationLabView.vue'), meta: { requiresAdmin: true } },
        { path: 'traces', component: () => import('../views/TraceCenterView.vue') },
        { path: 'chat', component: () => import('../views/ChatView.vue'), meta: { requiresPermission: 'agents:read' } },
        { path: 'tasks', component: () => import('../views/TaskBoardView.vue') },
        { path: 'knowledge', component: () => import('../views/KnowledgeView.vue') },
        { path: 'wallet', component: () => import('../views/WalletView.vue') },
        { path: 'meetings', component: () => import('../views/MeetingsView.vue'), meta: { requiresPermission: 'projects:write' } },
        { path: 'reports', component: () => import('../views/ReportsView.vue'), meta: { requiresPermission: 'projects:write' } },
        { path: 'notifications', component: () => import('../views/NotificationsView.vue'), meta: { requiresPermission: 'projects:write' } },
        { path: 'users', component: () => import('../views/UsersView.vue'), meta: { requiresAdmin: true } },
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
  if (to.path !== '/login' && auth.token && (!auth.user || typeof auth.user.ai_token_balance !== 'number')) {
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
  if (typeof to.meta.requiresPermission === 'string' && !auth.hasPermission(to.meta.requiresPermission)) {
    return '/403'
  }
  if (to.path === '/login' && auth.token) {
    return '/'
  }
  return true
})

router.afterEach(() => {
  window.requestAnimationFrame(() => document.getElementById('main-content')?.focus({ preventScroll: true }))
})

export default router
