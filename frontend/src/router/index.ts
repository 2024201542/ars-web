import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { guest: true } },
    { path: '/share/:token', name: 'share', component: () => import('@/views/ShareView.vue'), meta: { public: true } },
    { path: '/collab/:token', name: 'collab', component: () => import('@/views/CollabInviteView.vue') },
    { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
    { path: '/session/:id/research', name: 'research', component: () => import('@/views/WorkSessionView.vue'), meta: { skill: 'deep-research' } },
    { path: '/session/:id/paper', name: 'paper', component: () => import('@/views/WorkSessionView.vue'), meta: { skill: 'academic-paper' } },
    { path: '/session/:id/reviewer', name: 'reviewer', component: () => import('@/views/WorkSessionView.vue'), meta: { skill: 'academic-paper-reviewer' } },
    { path: '/session/:id/pipeline', name: 'pipeline', component: () => import('@/views/WorkSessionView.vue'), meta: { skill: 'academic-pipeline' } },
    { path: '/session/:id/kimi', name: 'kimi', component: () => import('@/views/WorkSessionView.vue'), meta: { skill: 'kimi-cnki-search' } },
    { path: '/admin', name: 'admin', component: () => import('@/views/AdminView.vue'), meta: { admin: true } },
  ],
})

// Navigation guard — check auth before entering non-guest routes
router.beforeEach(async (to, from, next) => {
  // Guest-only routes (login page)
  if (to.meta.guest || to.meta.public) {
    return next()
  }

  // Check if we have a stored token
  const token = localStorage.getItem('ars_token')
  if (!token) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }

  // Verify token is still valid (lazy — skip for performance, 401 will redirect)
  next()
})

export default router
