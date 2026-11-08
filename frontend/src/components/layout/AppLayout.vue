<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useSignOut } from '@/composables/useSignOut'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const signOut = useSignOut()
const route = useRoute()
const router = useRouter()

const mobileMenuOpen = ref(false)
const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)
const theme = ref<'light' | 'dark'>('light')

interface NavItem {
  label: string
  routeName: string
  icon: string
}

const navItems = computed<NavItem[]>(() => {
  if (session.isAdmin) {
    return [
      { label: 'Salas', routeName: 'admin-labs', icon: 'pi pi-table' },
      { label: 'Equipos', routeName: 'admin-machines', icon: 'pi pi-desktop' },
      { label: 'Accesos', routeName: 'admin-sessions', icon: 'pi pi-history' },
    ]
  }

  return [
    { label: 'Inicio', routeName: 'home', icon: 'pi pi-home' },
    { label: 'Historial', routeName: 'history', icon: 'pi pi-history' },
    { label: 'Perfil', routeName: 'profile', icon: 'pi pi-user' },
  ]
})

/* Sección "Documentación": solo aparece si esas rutas existen en tu router.
   AJUSTAR: nombres de ruta de las páginas del sistema de diseño. */
const docsItems = computed<NavItem[]>(() => {
  if (!session.isAdmin) return []

  const items: NavItem[] = [
    { label: 'Sistema de diseño', routeName: 'design-system', icon: 'pi pi-book' },
    { label: 'Estados y errores', routeName: 'design-states', icon: 'pi pi-check-circle' },
  ]

  return items.filter((item) => router.hasRoute(item.routeName))
})

const userInitials = computed(() => {
  const name = session.fullName || 'Usuario'

  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join('')
})

const roleLabel = computed(() => (session.isAdmin ? 'Administración' : 'Estudiante'))

const userRoleName = computed(() => (session.isAdmin ? 'Administrador' : 'Estudiante'))

const currentLabel = computed(
  () =>
    [...navItems.value, ...docsItems.value].find((item) => item.routeName === route.name)
      ?.label ?? '',
)

/* Fecha y hora del pie, en la zona horaria de la universidad */
const now = ref(new Date())
let clockTimer: number | undefined

const footerDate = computed(() => {
  const day = new Intl.DateTimeFormat('es-CO', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'America/Bogota',
  })
    .format(now.value)
    .replace(/\./g, '')

  const time = new Intl.DateTimeFormat('es-CO', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'America/Bogota',
  }).format(now.value)

  return `${day} · ${time}`
})

function onDocumentClick(event: MouseEvent) {
  if (userMenuOpen.value && !userMenuRef.value?.contains(event.target as Node)) {
    userMenuOpen.value = false
  }
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') userMenuOpen.value = false
}

onMounted(() => {
  clockTimer = window.setInterval(() => {
    now.value = new Date()
  }, 30_000)

  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onDocumentKeydown)
})

onBeforeUnmount(() => {
  window.clearInterval(clockTimer)
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown)
})

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
}

async function handleSignOut() {
  userMenuOpen.value = false
  mobileMenuOpen.value = false
  await signOut()
}
</script>

<template>
  <div class="app-layout" :data-theme="theme">
    <header class="app-header">
      <button
        class="menu-toggle"
        type="button"
        aria-label="Abrir menú de navegación"
        :aria-expanded="mobileMenuOpen"
        @click="mobileMenuOpen = !mobileMenuOpen"
      >
        <i class="pi pi-bars" aria-hidden="true"></i>
      </button>

      <div class="brand">
        <span class="brand__icon pi pi-qrcode" aria-hidden="true"></span>

        <div>
          <p class="brand__title">Acceso universitario</p>
          <p class="brand__subtitle">Registro de equipos · QR</p>
        </div>
      </div>

      <div class="header-actions">
        <span class="role-pill">
          <span class="role-pill__dot"></span>
          {{ roleLabel }}
        </span>

        <button
          class="theme-button"
          type="button"
          :aria-label="theme === 'light' ? 'Activar modo oscuro' : 'Activar modo claro'"
          @click="toggleTheme"
        >
          <i
            :class="theme === 'light' ? 'pi pi-moon' : 'pi pi-sun'"
            aria-hidden="true"
          ></i>
          <span>{{ theme === 'light' ? 'Modo oscuro' : 'Modo claro' }}</span>
        </button>

        <div ref="userMenuRef" class="user-menu">
          <button
            class="user-avatar"
            type="button"
            aria-haspopup="menu"
            :aria-expanded="userMenuOpen"
            :aria-label="`Menú de usuario: ${userRoleName}`"
            @click="userMenuOpen = !userMenuOpen"
          >
            {{ userInitials }}
          </button>

          <div v-if="userMenuOpen" class="user-menu__panel" role="menu">
            <div class="user-menu__info">
              <strong>{{ userRoleName }}</strong>
            </div>

            <button
              class="user-menu__item"
              type="button"
              role="menuitem"
              @click="handleSignOut"
            >
              <i class="pi pi-sign-out" aria-hidden="true"></i>
              <span>Salir</span>
            </button>
          </div>
        </div>
      </div>
    </header>

    <div class="app-shell">
      <aside class="sidebar" :class="{ 'sidebar--open': mobileMenuOpen }">
        <p class="sidebar__title">
          {{ session.isAdmin ? 'GESTIÓN DE ACCESO' : 'MENÚ PRINCIPAL' }}
        </p>

        <nav class="sidebar__nav" aria-label="Navegación principal">
          <RouterLink
            v-for="item in navItems"
            :key="item.routeName"
            :to="{ name: item.routeName }"
            class="nav-link"
            active-class="nav-link--active"
            @click="mobileMenuOpen = false"
          >
            <i :class="item.icon" aria-hidden="true"></i>
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>

        <template v-if="docsItems.length">
          <p class="sidebar__title sidebar__title--section">DOCUMENTACIÓN</p>

          <nav class="sidebar__nav" aria-label="Documentación">
            <RouterLink
              v-for="item in docsItems"
              :key="item.routeName"
              :to="{ name: item.routeName }"
              class="nav-link"
              active-class="nav-link--active"
              @click="mobileMenuOpen = false"
            >
              <i :class="item.icon" aria-hidden="true"></i>
              <span>{{ item.label }}</span>
            </RouterLink>
          </nav>
        </template>

        <div v-if="session.isAdmin" class="sidebar__footer">
          <i class="pi pi-shield" aria-hidden="true"></i>
          <p>Entorno administrativo<br />Acciones auditadas</p>
          <small>SRS-IC-001 · v1.0</small>
        </div>
      </aside>

      <button
        v-if="mobileMenuOpen"
        class="sidebar-backdrop"
        type="button"
        aria-label="Cerrar menú"
        @click="mobileMenuOpen = false"
      ></button>

      <div class="app-content">
        <nav v-if="currentLabel" class="breadcrumb" aria-label="Ruta de navegación">
          <span>{{ roleLabel }}</span>
          <span class="breadcrumb__sep">/</span>
          <span>{{ currentLabel }}</span>
        </nav>

        <div class="app-content__view">
          <slot />
        </div>

        <footer class="app-footer">
          <span>Acceso universitario · {{ roleLabel }}</span>
          <span class="app-footer__right">
            {{ footerDate }}
            <span class="app-footer__sep"></span>
            Zona horaria de la universidad
          </span>
        </footer>
      </div>
    </div>
  </div>
</template>

<style scoped>
/*
  Tokens del sistema de diseño. Las páginas (Salas, Equipos, Accesos) heredan
  estas variables, así que el cambio de tema se define aquí una sola vez.
*/
.app-layout {
  --page-bg: #f5f8fc;
  --surface: #ffffff;
  --inner: #eef3fa;
  --border: #dce4ef;
  --text: #233e60;
  --muted: #61738b;
  --primary: #2563eb;
  --hover: #edf3fc;
  --success: #157347;
  --success-bg: #e7f5ee;
  --warning: #8a5a00;
  --warning-bg: #fdf1d6;
  --danger: #b42335;
  --danger-bg: #fbe9ec;
  --overlay: rgba(15, 23, 41, 0.5);

  --chrome: #ffffff;
  --nav-active-bg: #e4edfd;
  --nav-active-text: #2563eb;

  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--page-bg);
  color: var(--text);
  font-family:
    Inter,
    system-ui,
    -apple-system,
    'Segoe UI',
    Roboto,
    sans-serif;
  font-size: 14px;
}

.app-layout[data-theme='dark'] {
  --page-bg: #0f1729;
  --surface: #1a2638;
  --inner: #142033;
  --border: #334155;
  --text: #e7edf6;
  --muted: #a2b0c4;
  --primary: #3b82f6;
  --hover: #1d3157;
  --success: #7bdcb0;
  --success-bg: #17382f;
  --warning: #f3c969;
  --warning-bg: #3a2f17;
  --danger: #ffafb5;
  --danger-bg: #4a2229;
  --overlay: rgba(5, 9, 20, 0.7);

  --chrome: #0f1729;
  --nav-active-bg: #1d3361;
  --nav-active-text: #8fb4ff;
}

/* ---- Encabezado ---- */
.app-header {
  position: relative;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 72px;
  padding: 10px 24px;
  background: var(--chrome);
  border-bottom: 1px solid var(--border);
}

.brand,
.header-actions {
  display: flex;
  align-items: center;
}

.brand {
  gap: 12px;
  min-width: 220px;
}

.brand__icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 9px;
  background: var(--hover);
  color: var(--primary);
  font-size: 22px;
}

.brand__title,
.brand__subtitle {
  margin: 0;
}

.brand__title {
  font-weight: 700;
  font-size: 15px;
}

.brand__subtitle {
  margin-top: 2px;
  color: var(--muted);
  font-size: 11px;
}

.header-actions {
  justify-content: flex-end;
  gap: 14px;
}

.role-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border-radius: 20px;
  background: var(--hover);
  color: var(--primary);
  font-size: 11px;
  font-weight: 600;
}

.role-pill__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.theme-button,
.menu-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  cursor: pointer;
}

.theme-button:hover {
  background: var(--hover);
}

.theme-button i {
  color: var(--primary);
}

.user-menu {
  position: relative;
}

.user-avatar {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 50%;
  background: var(--hover);
  color: var(--primary);
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.user-avatar:hover,
.user-avatar[aria-expanded='true'] {
  border-color: var(--primary);
}

.user-menu__panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 60;
  min-width: 200px;
  padding: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 12px 30px rgba(15, 23, 41, 0.18);
}

.user-menu__info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px 10px;
  border-bottom: 1px solid var(--border);
}

.user-menu__info strong {
  font-size: 12px;
}

.user-menu__info small {
  color: var(--muted);
  font-size: 11px;
}

.user-menu__item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  margin-top: 6px;
  padding: 9px 10px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.user-menu__item:hover {
  background: var(--hover);
}

.user-menu__item i {
  color: var(--primary);
}

.menu-toggle {
  display: none;
}

/* ---- Estructura ---- */
.app-shell {
  display: flex;
  flex: 1;
  min-height: 0;
}

.sidebar {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: 225px;
  padding: 26px 14px 18px;
  background: var(--chrome);
  border-right: 1px solid var(--border);
}

.sidebar__title {
  margin: 0 0 14px 10px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.8px;
}

.sidebar__title--section {
  margin-top: 28px;
}

.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 40px;
  padding: 0 12px;
  border-radius: 7px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition:
    background 0.15s,
    color 0.15s;
}

.nav-link:hover {
  background: var(--hover);
  color: var(--text);
}

.nav-link--active,
.nav-link--active:hover {
  background: var(--nav-active-bg);
  color: var(--nav-active-text);
  font-weight: 600;
}

.nav-link i {
  font-size: 15px;
}

.sidebar__footer {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 10px;
  margin-top: auto;
  padding: 18px 10px 0;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.5;
}

.sidebar__footer i {
  grid-row: span 2;
  font-size: 14px;
}

.sidebar__footer p {
  margin: 0;
}

.sidebar__footer small {
  grid-column: 1 / -1;
  margin-top: 12px;
  font-size: 10px;
}

.app-content {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  padding: 24px 26px;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
  color: var(--muted);
  font-size: 11px;
}

.app-content__view {
  flex: 1;
  min-width: 0;
}

.app-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 24px;
  padding: 12px 0 0;
  color: var(--muted);
  font-size: 11px;
}

.app-footer__right {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.app-footer__sep {
  width: 1px;
  height: 12px;
  background: var(--border);
}

.sidebar-backdrop {
  display: none;
}

button:focus-visible,
.nav-link:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 3px;
}

@media (max-width: 760px) {
  .app-header {
    min-height: 66px;
    padding: 10px 14px;
    gap: 10px;
  }

  .menu-toggle {
    display: inline-flex;
    width: 38px;
    height: 38px;
    padding: 0;
  }

  .brand {
    flex: 1;
    min-width: 0;
    gap: 8px;
  }

  .brand__icon {
    width: 34px;
    height: 34px;
    font-size: 18px;
  }

  .brand__title {
    font-size: 12px;
  }

  .brand__subtitle {
    font-size: 10px;
  }

  .header-actions {
    gap: 8px;
  }

  .role-pill {
    display: none;
  }

  .theme-button {
    width: 38px;
    height: 38px;
    padding: 0;
  }

  .theme-button span {
    display: none;
  }

  .sidebar {
    position: fixed;
    z-index: 30;
    top: 66px;
    bottom: 0;
    left: 0;
    width: 255px;
    transform: translateX(-105%);
    transition: transform 0.2s ease;
  }

  .sidebar--open {
    transform: translateX(0);
  }

  .sidebar-backdrop {
    position: fixed;
    z-index: 20;
    top: 66px;
    right: 0;
    bottom: 0;
    left: 0;
    display: block;
    width: 100%;
    border: 0;
    background: rgb(15 23 42 / 40%);
  }

  .app-content {
    padding: 16px;
  }

  .app-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sidebar,
  .nav-link {
    transition: none;
  }
}
</style>