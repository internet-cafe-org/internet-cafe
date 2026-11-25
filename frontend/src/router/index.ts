import { createRouter, createWebHistory, type RouteRecordRaw, type RouterHistory } from 'vue-router'

import { setPendingScanToken } from '@/services/pendingScan'
import { useSessionStore } from '@/stores/session'

const APP_TITLE = 'Registro de acceso a equipos'

declare module 'vue-router' {
  interface RouteMeta {
    /** public: sin sesión · user: requiere sesión · admin: requiere rol admin */
    access?: 'public' | 'user' | 'admin'
    /** Título de la página (WCAG 2.4.2); se muestra en document.title. */
    title?: string
  }
}

export const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { access: 'public', title: 'Iniciar sesión' },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { access: 'public', title: 'Crear cuenta' },
  },
  {
    path: '/verify-email',
    name: 'verify-email',
    component: () => import('@/views/VerifyEmailView.vue'),
    meta: { access: 'public', title: 'Verificar correo' },
  },
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('@/views/ForgotPasswordView.vue'),
    meta: { access: 'public', title: 'Recuperar contraseña' },
  },
  {
    path: '/redirigiendo',
    name: 'redirecting',
    component: () => import('@/views/RedirectingView.vue'),
    meta: { access: 'user', title: 'Redirigiendo' },
  },
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { access: 'user', title: 'Inicio' },
  },
  {
    path: '/scan',
    name: 'scan',
    component: () => import('@/views/ScanView.vue'),
    meta: { access: 'user', title: 'Escanear código QR' },
  },
  // El QR abre /s#token (SRS RF-QR-01)
  {
    path: '/s',
    name: 'confirm',
    component: () => import('@/views/ConfirmAccessView.vue'),
    meta: { access: 'user', title: 'Confirmar acceso' },
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/views/HistoryView.vue'),
    meta: { access: 'user', title: 'Historial' },
  },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/views/ProfileView.vue'),
    meta: { access: 'user', title: 'Perfil' },
  },
  {
    path: '/admin/labs',
    name: 'admin-labs',
    component: () => import('@/views/admin/LabsView.vue'),
    meta: { access: 'admin', title: 'Salas' },
  },
  {
    path: '/admin/machines',
    name: 'admin-machines',
    component: () => import('@/views/admin/MachinesView.vue'),
    meta: { access: 'admin', title: 'Equipos' },
  },
  {
    path: '/admin/machines/:id',
    name: 'admin-machine-detail',
    component: () => import('@/views/admin/MachineDetailView.vue'),
    meta: { access: 'admin', title: 'Detalle del equipo' },
  },
  {
    path: '/admin/sessions',
    name: 'admin-sessions',
    component: () => import('@/views/admin/SessionsView.vue'),
    meta: { access: 'admin', title: 'Sesiones' },
  },
  {
    path: '/admin/users',
    name: 'admin-users',
    component: () => import('@/views/admin/UsersView.vue'),
    meta: { access: 'admin', title: 'Usuarios' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { access: 'public', title: 'Página no encontrada' },
  },
]

export function createAppRouter(history: RouterHistory) {
  const router = createRouter({ history, routes })

  router.beforeEach((to) => {
    const session = useSessionStore()
    const access = to.meta.access ?? 'public'

    if (access === 'public') return true
    if (!session.isAuthenticated) {
      // Conserva el token del QR en memoria para continuar tras el login (RF-QR-05).
      if (to.name === 'confirm' && to.hash.length > 1) setPendingScanToken(to.hash.slice(1))
      return { name: 'login' }
    }
    if (access === 'admin' && !session.isAdmin) return { name: 'home' }
    return true
  })

  router.afterEach((to) => {
    const title = to.meta.title
    document.title = title ? `${title} · ${APP_TITLE}` : APP_TITLE
  })

  return router
}

export default createAppRouter(createWebHistory(import.meta.env.BASE_URL))
