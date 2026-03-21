import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
  { path: '/agents', name: 'agents', component: () => import('../views/AgentsView.vue') },
  { path: '/monitoring', name: 'monitoring', component: () => import('../views/MonitoringView.vue') },
  { path: '/infrastructure', name: 'infrastructure', component: () => import('../views/InfrastructureView.vue') },
  { path: '/automations', name: 'automations', component: () => import('../views/AutomationsView.vue') },
  { path: '/logs', name: 'logs', component: () => import('../views/LogsView.vue') },
  { path: '/security', name: 'security', component: () => import('../views/SecurityView.vue') },
  { path: '/settings/:tab?', name: 'settings', component: () => import('../views/SettingsView.vue') },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && !auth.authenticated) return { name: 'login' }
  if (to.name === 'login' && auth.authenticated) return { name: 'dashboard' }
})

export default router
