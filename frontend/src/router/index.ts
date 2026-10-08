import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/components/layout/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          redirect: '/dashboard',
        },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
        },
        // 差旅助手（统一对话入口：查票/订酒店/导航/报销意图识别）
        {
          path: 'chat',
          name: 'chat',
          component: () => import('@/views/TravelChatView.vue'),
        },
        // 报销单管理
        {
          path: 'reimbursements',
          name: 'reimbursements',
          component: () => import('@/views/reimbursement/ReimbursementListView.vue'),
        },
        {
          path: 'reimbursements/new',
          name: 'reimbursement-new',
          component: () => import('@/views/reimbursement/ReimbursementEditView.vue'),
        },
        {
          path: 'reimbursements/:id',
          name: 'reimbursement-detail',
          component: () => import('@/views/reimbursement/ReimbursementDetailView.vue'),
        },
        // 发票上传解析
        {
          path: 'invoice',
          name: 'invoice',
          component: () => import('@/views/reimbursement/InvoiceParseView.vue'),
        },
        // 审批管理（manager/admin）
        {
          path: 'approvals',
          name: 'approvals',
          component: () => import('@/views/approval/ApprovalListView.vue'),
          meta: { requiresApprove: true },
        },
        // 数据分析
        {
          path: 'analytics',
          name: 'analytics',
          component: () => import('@/views/AnalyticsView.vue'),
        },
        // 个人中心
        {
          path: 'profile',
          name: 'profile',
          component: () => import('@/views/ProfileView.vue'),
        },
        // 系统管理（仅 admin）
        {
          path: 'system',
          name: 'system',
          component: () => import('@/views/SystemManageView.vue'),
          meta: { requiresAdmin: true },
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard',
    },
  ],
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (auth.isLoggedIn && to.name === 'login') return next('/dashboard')
    return next()
  }

  if (!auth.isLoggedIn) return next('/login')

  if (to.meta.requiresApprove && !auth.canApprove) return next('/dashboard')
  if (to.meta.requiresAdmin && !auth.isAdmin) return next('/dashboard')

  next()
})

export default router
