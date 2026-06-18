import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat', component: () => import('@/views/Chat.vue') },
    { path: '/report/:taskId', name: 'report', component: () => import('@/views/Report.vue') },
    { path: '/dashboard', name: 'dashboard', component: () => import('@/views/Dashboard.vue') },
    { path: '/rag', name: 'rag', component: () => import('@/views/RagUpload.vue') },
  ]
})

export default router
