<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { useSignOut } from '@/composables/useSignOut'
import { ApiError } from '@/errors/problem-details'
import {
  downloadBlob,
  exportAdminSessionsCsv,
  forceEndSession,
  getAdminLabs,
  getAdminSessions,
  type AdminSession,
  type LabItem,
} from '@/services/adminSessions'
import { useSessionStore } from '@/stores/session'

const sessionStore = useSessionStore()
const signOut = useSignOut()

// Estado principal
const loading = ref(true)
const labsLoading = ref(true)
const error = ref<string | null>(null)
const successBanner = ref<string | null>(null)
const isExporting = ref(false)
const exportError = ref<string | null>(null)
const labs = ref<LabItem[]>([])
const sessions = ref<AdminSession[]>([])
const totalSessions = ref(0)
const pageLimit = 20
const currentOffset = ref(0)

interface SessionFilters {
  student: string
  lab_id: string
  machine_code: string
  state: '' | 'active' | 'ended'
  started_from: string
  started_to: string
}

// Formulario de filtros
const filters = reactive<SessionFilters>({
  student: '',
  lab_id: '',
  machine_code: '',
  state: '',
  started_from: '',
  started_to: '',
})
const dateValidationError = ref<string | null>(null)

// Modal de confirmación para forzar cierre
const targetSession = ref<AdminSession | null>(null)
const isClosing = ref(false)
const closeError = ref<string | null>(null)

const REASON_LABELS: Record<string, string> = {
  admin_forced: 'Cierre forzado',
  user_logout_pc: 'Cerrada desde el equipo',
  user_logout_web: 'Cerrada desde la web',
  heartbeat_timeout: 'Inactividad (sin latido)',
  superseded: 'Reemplazada por nueva sesión',
  machine_shutdown: 'Apagado del equipo',
}

function formatDate(isoStr?: string | null): string {
  if (!isoStr) return '—'
  try {
    const d = new Date(isoStr)
    if (isNaN(d.getTime())) return isoStr
    return new Intl.DateTimeFormat('es-CO', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(d)
  } catch {
    return isoStr
  }
}

function formatDuration(seconds?: number | null, isActive = false): string {
  if (isActive) return 'En curso'
  if (seconds == null || seconds < 0) return '—'
  const mins = Math.floor(seconds / 60)
  if (mins < 60) return `${mins} min`
  const hours = Math.floor(mins / 60)
  const remainingMins = mins % 60
  return remainingMins > 0 ? `${hours} h ${remainingMins} min` : `${hours} h`
}

function getReasonLabel(reason?: string | null): string {
  if (!reason) return ''
  return REASON_LABELS[reason] ?? reason
}

/**
 * Filtro local por estudiante (coincidencia de código o nombre).
 * El backend actual no soporta query param de estudiante en /admin/sessions,
 * por lo que se aplica en UI respetando la coincidencia exacta o término buscado.
 */
const displayedSessions = computed(() => {
  const query = filters.student.trim().toLowerCase()
  if (!query) return sessions.value

  return sessions.value.filter((s) => {
    const fullName = s.user.full_name.toLowerCase()
    const maskedCode = s.user.student_code_masked.toLowerCase()
    return fullName.includes(query) || maskedCode.includes(query)
  })
})

const currentPage = computed(() => Math.floor(currentOffset.value / pageLimit) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(totalSessions.value / pageLimit)))
const hasNextPage = computed(() => currentOffset.value + pageLimit < totalSessions.value)
const hasPrevPage = computed(() => currentOffset.value > 0)

async function loadLabs() {
  labsLoading.value = true
  try {
    labs.value = await getAdminLabs()
  } catch {
    // Si falla cargar salas, no bloquea la consulta de accesos
    labs.value = []
  } finally {
    labsLoading.value = false
  }
}

async function loadSessions(resetOffset = false) {
  if (resetOffset) {
    currentOffset.value = 0
  }

  // Validación de rango de fechas
  dateValidationError.value = null
  if (filters.started_from && filters.started_to && filters.started_from > filters.started_to) {
    dateValidationError.value = 'La fecha "desde" no puede ser posterior a la fecha "hasta".'
    return
  }

  loading.value = true
  error.value = null

  // Transformar fechas a formato ISO para la API si fueron ingresadas
  let startedFromIso: string | undefined
  let startedToIso: string | undefined

  if (filters.started_from) {
    startedFromIso = `${filters.started_from}T00:00:00Z`
  }
  if (filters.started_to) {
    startedToIso = `${filters.started_to}T23:59:59Z`
  }

  try {
    const response = await getAdminSessions({
      machine_code: filters.machine_code.trim() || undefined,
      lab_id: filters.lab_id || undefined,
      state: filters.state || undefined,
      started_from: startedFromIso,
      started_to: startedToIso,
      limit: pageLimit,
      offset: currentOffset.value,
    })

    sessions.value = response.items
    totalSessions.value = response.total
  } catch (err) {
    if (err instanceof ApiError) {
      error.value = err.message || 'Error al obtener la lista de accesos.'
    } else if (err instanceof Error) {
      error.value = err.message
    } else {
      error.value = 'No se pudo conectar con el servidor para consultar los accesos.'
    }
    sessions.value = []
    totalSessions.value = 0
  } finally {
    loading.value = false
  }
}

function onApplyFilters() {
  void loadSessions(true)
}

function onClearFilters() {
  filters.student = ''
  filters.lab_id = ''
  filters.machine_code = ''
  filters.state = ''
  filters.started_from = ''
  filters.started_to = ''
  dateValidationError.value = null
  exportError.value = null
  void loadSessions(true)
}

async function onExportCsv() {
  if (isExporting.value) return

  dateValidationError.value = null
  if (filters.started_from && filters.started_to && filters.started_from > filters.started_to) {
    dateValidationError.value = 'La fecha "desde" no puede ser posterior a la fecha "hasta".'
    return
  }

  isExporting.value = true
  exportError.value = null

  let startedFromIso: string | undefined
  let startedToIso: string | undefined

  if (filters.started_from) {
    startedFromIso = `${filters.started_from}T00:00:00Z`
  }
  if (filters.started_to) {
    startedToIso = `${filters.started_to}T23:59:59Z`
  }

  try {
    const result = await exportAdminSessionsCsv({
      machine_code: filters.machine_code.trim() || undefined,
      lab_id: filters.lab_id || undefined,
      state: (filters.state as 'active' | 'ended') || undefined,
      started_from: startedFromIso,
      started_to: startedToIso,
      student: filters.student.trim() || undefined,
    })

    downloadBlob(result.blob, result.filename)

    if (result.truncated) {
      successBanner.value = `Archivo ${result.filename} descargado. Nota: El resultado superó el límite y fue truncado por el servidor.`
    } else {
      successBanner.value = `Archivo ${result.filename} descargado con éxito.`
    }
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 401) {
        exportError.value = 'No autorizado para exportar. Tu sesión puede haber expirado.'
      } else if (err.status === 403) {
        exportError.value = 'No tienes permisos de administrador para exportar datos.'
      } else {
        exportError.value = err.message || 'Error al exportar los datos.'
      }
    } else if (err instanceof Error) {
      exportError.value = err.message
    } else {
      exportError.value = 'No se pudo conectar con el servidor para exportar el archivo.'
    }
  } finally {
    isExporting.value = false
  }
}

function goToNextPage() {
  if (hasNextPage.value) {
    currentOffset.value += pageLimit
    void loadSessions(false)
  }
}

function goToPrevPage() {
  if (hasPrevPage.value) {
    currentOffset.value = Math.max(0, currentOffset.value - pageLimit)
    void loadSessions(false)
  }
}

// Cierre forzado
function openForceCloseDialog(session: AdminSession) {
  targetSession.value = session
  closeError.value = null
}

function cancelForceClose() {
  targetSession.value = null
  closeError.value = null
  isClosing.value = false
}

async function confirmForceClose() {
  if (!targetSession.value || isClosing.value) return

  isClosing.value = true
  closeError.value = null

  try {
    const updatedSession = await forceEndSession(targetSession.value.id)

    // Actualiza la sesión en la lista actual
    const idx = sessions.value.findIndex((s) => s.id === updatedSession.id)
    if (idx !== -1) {
      sessions.value[idx] = updatedSession
    }

    successBanner.value = `Sesión en ${updatedSession.machine_code} (${updatedSession.user.full_name}) cerrada forzadamente con éxito.`
    targetSession.value = null
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 404) {
        closeError.value = 'La sesión indicada no existe o ya no está disponible.'
      } else {
        closeError.value = err.message || 'Error al intentar forzar el cierre de la sesión.'
      }
    } else if (err instanceof Error) {
      closeError.value = err.message
    } else {
      closeError.value = 'Error inesperado al forzar el cierre.'
    }
  } finally {
    isClosing.value = false
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && targetSession.value) {
    cancelForceClose()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  void loadLabs()
  void loadSessions(true)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="admin-layout">
    <!-- Barra superior de navegación -->
    <header class="admin-header">
      <div class="admin-header__brand">
        <span class="admin-header__icon pi pi-shield" aria-hidden="true"></span>
        <div>
          <p class="admin-header__title">Acceso universitario</p>
          <p class="admin-header__subtitle">Panel de administración</p>
        </div>
      </div>

      <nav class="admin-nav" aria-label="Navegación del panel administrativo">
        <RouterLink class="admin-nav__link" to="/admin/machines">Salas y equipos</RouterLink>
        <RouterLink
          class="admin-nav__link admin-nav__link--active"
          to="/admin/sessions"
          aria-current="page"
        >
          Accesos
        </RouterLink>
        <RouterLink class="admin-nav__link" to="/admin/users">Usuarios</RouterLink>
      </nav>

      <div class="admin-header__user">
        <span class="user-badge" aria-label="Usuario actual">
          <i class="pi pi-user" aria-hidden="true"></i>
          {{ sessionStore.fullName || 'Administrador' }}
        </span>
        <button class="btn-logout" type="button" @click="signOut">
          <i class="pi pi-sign-out" aria-hidden="true"></i>
          Cerrar sesión
        </button>
      </div>
    </header>

    <main class="admin-main">
      <div class="admin-container">
        <!-- Título y descripción -->
        <div class="page-title-area">
          <nav class="breadcrumb" aria-label="Miga de pan">
            <span>Administración</span>
            <span class="breadcrumb__separator">/</span>
            <span class="breadcrumb__current">Accesos</span>
          </nav>
          <h1>Historial de accesos</h1>
          <p class="page-lead">
            Consulta sesiones de computadores con filtros y gestiona cierres forzados autorizados.
          </p>
        </div>

        <!-- Banners de notificación -->
        <div
          v-if="successBanner"
          class="alert-banner alert-banner--success"
          role="status"
          aria-live="polite"
        >
          <div class="alert-banner__content">
            <i class="pi pi-check-circle" aria-hidden="true"></i>
            <span>{{ successBanner }}</span>
          </div>
          <button
            class="alert-banner__close"
            type="button"
            aria-label="Cerrar notificación"
            @click="successBanner = null"
          >
            <i class="pi pi-times" aria-hidden="true"></i>
          </button>
        </div>

        <div
          v-if="error"
          class="alert-banner alert-banner--error"
          role="alert"
          aria-live="assertive"
        >
          <div class="alert-banner__content">
            <i class="pi pi-exclamation-circle" aria-hidden="true"></i>
            <div>
              <strong>Error al cargar accesos</strong>
              <p>{{ error }}</p>
            </div>
          </div>
          <button class="btn-retry" type="button" @click="loadSessions(false)">Reintentar</button>
        </div>

        <div
          v-if="dateValidationError"
          class="alert-banner alert-banner--warning"
          role="alert"
          aria-live="polite"
        >
          <div class="alert-banner__content">
            <i class="pi pi-exclamation-triangle" aria-hidden="true"></i>
            <span>{{ dateValidationError }}</span>
          </div>
        </div>

        <div
          v-if="exportError"
          class="alert-banner alert-banner--error"
          role="alert"
          aria-live="assertive"
        >
          <div class="alert-banner__content">
            <i class="pi pi-exclamation-circle" aria-hidden="true"></i>
            <div>
              <strong>Error al exportar accesos</strong>
              <p>{{ exportError }}</p>
            </div>
          </div>
          <button
            class="alert-banner__close"
            type="button"
            aria-label="Cerrar notificación"
            @click="exportError = null"
          >
            <i class="pi pi-times" aria-hidden="true"></i>
          </button>
        </div>

        <!-- Panel de filtros -->
        <section class="filters-card" aria-labelledby="filters-title">
          <h2 id="filters-title" class="sr-only">Filtros de búsqueda</h2>
          <form class="filters-form" @submit.prevent="onApplyFilters">
            <div class="filters-grid">
              <!-- Filtro: Estudiante -->
              <div class="filter-field">
                <label for="filter-student">Estudiante</label>
                <div class="input-with-icon">
                  <i class="pi pi-search" aria-hidden="true"></i>
                  <input
                    id="filter-student"
                    v-model="filters.student"
                    type="text"
                    placeholder="Código o nombre..."
                  />
                </div>
              </div>

              <!-- Filtro: Sala -->
              <div class="filter-field">
                <label for="filter-lab">Sala</label>
                <select id="filter-lab" v-model="filters.lab_id">
                  <option value="">Todas las salas</option>
                  <option v-for="lab in labs" :key="lab.id" :value="lab.id">
                    {{ lab.name }}
                  </option>
                </select>
              </div>

              <!-- Filtro: Equipo -->
              <div class="filter-field">
                <label for="filter-machine">Código de equipo</label>
                <input
                  id="filter-machine"
                  v-model="filters.machine_code"
                  type="text"
                  placeholder="Ej: LAB3-PC12"
                />
              </div>

              <!-- Filtro: Estado -->
              <div class="filter-field">
                <label for="filter-state">Estado</label>
                <select id="filter-state" v-model="filters.state">
                  <option value="">Todas las sesiones</option>
                  <option value="active">Solo activas</option>
                  <option value="ended">Solo cerradas</option>
                </select>
              </div>

              <!-- Filtro: Fecha desde -->
              <div class="filter-field">
                <label for="filter-from">Fecha desde</label>
                <input id="filter-from" v-model="filters.started_from" type="date" />
              </div>

              <!-- Filtro: Fecha hasta -->
              <div class="filter-field">
                <label for="filter-to">Fecha hasta</label>
                <input id="filter-to" v-model="filters.started_to" type="date" />
              </div>
            </div>

            <div class="filters-actions">
              <button class="btn-primary" type="submit" :disabled="loading || isExporting">
                <i class="pi pi-filter" aria-hidden="true"></i>
                Aplicar filtros
              </button>
              <button
                class="btn-secondary"
                type="button"
                :disabled="loading || isExporting"
                @click="onClearFilters"
              >
                <i class="pi pi-filter-slash" aria-hidden="true"></i>
                Limpiar filtros
              </button>
              <button
                class="btn-export"
                type="button"
                :disabled="loading || isExporting"
                :aria-busy="isExporting"
                @click="onExportCsv"
              >
                <i
                  :class="isExporting ? 'pi pi-spin pi-spinner' : 'pi pi-download'"
                  aria-hidden="true"
                ></i>
                <span>{{ isExporting ? 'Exportando…' : 'Exportar CSV' }}</span>
              </button>
            </div>
          </form>
        </section>

        <!-- Estado de carga -->
        <div v-if="loading" class="state-card state-card--loading" role="status">
          <i class="pi pi-spin pi-spinner state-card__icon" aria-hidden="true"></i>
          <p>Cargando lista de accesos…</p>
        </div>

        <!-- Estado sin resultados -->
        <div
          v-else-if="displayedSessions.length === 0"
          class="state-card state-card--empty"
          role="status"
        >
          <i class="pi pi-inbox state-card__icon" aria-hidden="true"></i>
          <h2>No hay accesos con estos filtros</h2>
          <p>No se encontraron sesiones que coincidan con los criterios especificados.</p>
          <button class="btn-primary" type="button" @click="onClearFilters">Limpiar filtros</button>
        </div>

        <!-- Tabla de accesos -->
        <section v-else class="table-card" aria-labelledby="sessions-table-title">
          <div class="table-card__header">
            <h2 id="sessions-table-title">Sesiones registradas</h2>
            <span class="sessions-counter">
              Mostrando {{ displayedSessions.length }}
              <template v-if="totalSessions > displayedSessions.length">
                de {{ totalSessions }}
              </template>
              sesiones
            </span>
          </div>

          <div class="table-wrapper">
            <table class="sessions-table">
              <thead>
                <tr>
                  <th scope="col">Estudiante</th>
                  <th scope="col">Equipo</th>
                  <th scope="col">Sala</th>
                  <th scope="col">Inicio</th>
                  <th scope="col">Fin</th>
                  <th scope="col">Duración</th>
                  <th scope="col">Estado</th>
                  <th scope="col" class="th-actions">Acciones</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="session in displayedSessions"
                  :key="session.id"
                  :class="{ 'row-active': !session.ended_at }"
                >
                  <!-- Estudiante -->
                  <td>
                    <div class="student-cell">
                      <span class="student-name">{{ session.user.full_name }}</span>
                      <span class="student-code">{{ session.user.student_code_masked }}</span>
                    </div>
                  </td>

                  <!-- Equipo -->
                  <td>
                    <span class="machine-tag">{{ session.machine_code }}</span>
                  </td>

                  <!-- Sala -->
                  <td>{{ session.lab }}</td>

                  <!-- Inicio -->
                  <td>
                    <time :datetime="session.started_at">{{ formatDate(session.started_at) }}</time>
                  </td>

                  <!-- Fin -->
                  <td>
                    <time v-if="session.ended_at" :datetime="session.ended_at">
                      {{ formatDate(session.ended_at) }}
                    </time>
                    <span v-else class="text-muted">—</span>
                  </td>

                  <!-- Duración -->
                  <td>
                    {{ formatDuration(session.duration_s, !session.ended_at) }}
                  </td>

                  <!-- Estado -->
                  <td>
                    <div v-if="!session.ended_at" class="status-badge status-badge--active">
                      <span class="status-dot"></span>
                      Activa
                    </div>
                    <div v-else class="status-badge status-badge--ended">
                      <span>Cerrada</span>
                      <span v-if="session.end_reason" class="status-reason">
                        {{ getReasonLabel(session.end_reason) }}
                      </span>
                    </div>
                  </td>

                  <!-- Acciones -->
                  <td class="td-actions">
                    <button
                      v-if="!session.ended_at"
                      class="btn-force-close"
                      type="button"
                      :aria-label="`Forzar cierre de sesión en ${session.machine_code}`"
                      @click="openForceCloseDialog(session)"
                    >
                      <i class="pi pi-power-off" aria-hidden="true"></i>
                      Forzar cierre
                    </button>
                    <span v-else class="text-muted">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Paginación -->
          <div class="pagination-bar">
            <span class="pagination-info">
              Página {{ currentPage }} de {{ totalPages }} ({{ totalSessions }} totales)
            </span>
            <div class="pagination-controls">
              <button
                class="btn-page"
                type="button"
                :disabled="!hasPrevPage || loading"
                @click="goToPrevPage"
              >
                <i class="pi pi-chevron-left" aria-hidden="true"></i>
                Anterior
              </button>
              <button
                class="btn-page"
                type="button"
                :disabled="!hasNextPage || loading"
                @click="goToNextPage"
              >
                Siguiente
                <i class="pi pi-chevron-right" aria-hidden="true"></i>
              </button>
            </div>
          </div>
        </section>
      </div>
    </main>

    <!-- Modal de confirmación de cierre forzado -->
    <div
      v-if="targetSession"
      class="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dialog-title"
    >
      <div class="modal-card">
        <div class="modal-card__header">
          <div class="modal-icon-container">
            <i class="pi pi-exclamation-triangle" aria-hidden="true"></i>
          </div>
          <div>
            <h2 id="dialog-title">¿Forzar el cierre de esta sesión?</h2>
            <p class="modal-subtitle">Esta acción es irreversible y queda auditada.</p>
          </div>
        </div>

        <div class="modal-card__body">
          <div class="session-summary">
            <div class="summary-item">
              <span class="summary-label">Estudiante:</span>
              <span class="summary-value">
                {{ targetSession.user.full_name }} ({{ targetSession.user.student_code_masked }})
              </span>
            </div>
            <div class="summary-item">
              <span class="summary-label">Equipo:</span>
              <span class="summary-value">{{ targetSession.machine_code }}</span>
            </div>
            <div class="summary-item">
              <span class="summary-label">Sala:</span>
              <span class="summary-value">{{ targetSession.lab }}</span>
            </div>
            <div class="summary-item">
              <span class="summary-label">Inicio:</span>
              <span class="summary-value">{{ formatDate(targetSession.started_at) }}</span>
            </div>
          </div>

          <div class="modal-warning-box">
            <p>
              Se forzará el cierre inmediato de la sesión en el servidor. El computador de la sala
              detectará el cierre en su próximo latido (≤ 60 s) y volverá a mostrar el código QR.
            </p>
            <p class="technical-note">
              Motivo registrado: <code>admin_forced</code>. La hora de fin se fija desde el
              servidor.
            </p>
          </div>

          <div v-if="closeError" class="alert-banner alert-banner--error" role="alert">
            <div class="alert-banner__content">
              <i class="pi pi-times-circle" aria-hidden="true"></i>
              <span>{{ closeError }}</span>
            </div>
          </div>
        </div>

        <div class="modal-card__footer">
          <button
            class="btn-secondary"
            type="button"
            :disabled="isClosing"
            @click="cancelForceClose"
          >
            Cancelar
          </button>
          <button class="btn-danger" type="button" :disabled="isClosing" @click="confirmForceClose">
            <i v-if="isClosing" class="pi pi-spin pi-spinner" aria-hidden="true"></i>
            <i v-else class="pi pi-power-off" aria-hidden="true"></i>
            {{ isClosing ? 'Cerrando sesión…' : 'Forzar cierre' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-layout {
  --admin-primary: #19365c;
  --admin-action: #2563eb;
  --admin-action-hover: #1d4ed8;
  --admin-danger: #b42318;
  --admin-danger-hover: #911c13;
  --admin-success: #167044;
  --admin-warning: #805500;
  --admin-bg: #f5f8fc;
  --admin-card-bg: #ffffff;
  --admin-border: #d7e0ec;
  --admin-text-main: #19365c;
  --admin-text-muted: #52647a;

  min-height: 100vh;
  background-color: var(--admin-bg);
  color: var(--admin-text-main);
  font-family:
    Inter,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    Roboto,
    sans-serif;
  font-size: 14px;
  line-height: 1.5;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border-width: 0;
}

/* Header */
.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  padding: 0.875rem 1.5rem;
  background-color: #ffffff;
  border-bottom: 1px solid var(--admin-border);
  flex-wrap: wrap;
}

.admin-header__brand {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.admin-header__icon {
  display: grid;
  place-items: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 8px;
  background-color: #edf2fb;
  color: var(--admin-action);
  font-size: 1.125rem;
}

.admin-header__title {
  margin: 0;
  font-weight: 600;
  font-size: 0.9375rem;
  color: var(--admin-primary);
}

.admin-header__subtitle {
  margin: 0;
  font-size: 0.75rem;
  color: var(--admin-text-muted);
}

/* Nav */
.admin-nav {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.admin-nav__link {
  padding: 0.5rem 0.875rem;
  border-radius: 6px;
  color: var(--admin-text-muted);
  text-decoration: none;
  font-weight: 500;
  transition: all 0.15s ease-in-out;
}

.admin-nav__link:hover {
  background-color: #edf2fb;
  color: var(--admin-action);
}

.admin-nav__link--active {
  background-color: #edf2fb;
  color: var(--admin-action);
  font-weight: 600;
}

/* User & Logout */
.admin-header__user {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.user-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--admin-text-muted);
  background-color: #f1f5f9;
  padding: 0.375rem 0.625rem;
  border-radius: 6px;
}

.btn-logout {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  background: transparent;
  border: 1px solid var(--admin-border);
  padding: 0.375rem 0.75rem;
  border-radius: 6px;
  font-size: 0.8125rem;
  color: var(--admin-text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.btn-logout:hover {
  background-color: #fee4e2;
  border-color: #fecdca;
  color: var(--admin-danger);
}

/* Main Content */
.admin-main {
  padding: 1.5rem;
}

.admin-container {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* Breadcrumb & Heading */
.page-title-area {
  margin-bottom: 0.25rem;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  color: var(--admin-text-muted);
  margin-bottom: 0.375rem;
}

.breadcrumb__separator {
  color: #94a3b8;
}

.breadcrumb__current {
  color: var(--admin-action);
  font-weight: 600;
}

.page-title-area h1 {
  margin: 0 0 0.25rem 0;
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--admin-primary);
}

.page-lead {
  margin: 0;
  font-size: 0.875rem;
  color: var(--admin-text-muted);
}

/* Alerts */
.alert-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.875rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
}

.alert-banner__content {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.alert-banner--success {
  background-color: #ecfdf3;
  border: 1px solid #a6f4c5;
  color: var(--admin-success);
}

.alert-banner--error {
  background-color: #fef3f2;
  border: 1px solid #fecdca;
  color: var(--admin-danger);
}

.alert-banner--warning {
  background-color: #fffaeb;
  border: 1px solid #fedf89;
  color: var(--admin-warning);
}

.alert-banner__close {
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  padding: 0.25rem;
  font-size: 1rem;
}

.btn-retry {
  background: var(--admin-danger);
  color: #fff;
  border: none;
  padding: 0.375rem 0.75rem;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.8125rem;
  font-weight: 500;
}

/* Filters Card */
.filters-card {
  background: var(--admin-card-bg);
  border: 1px solid var(--admin-border);
  border-radius: 10px;
  padding: 1.25rem;
}

.filters-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.filters-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
}

.filter-field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.filter-field label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--admin-primary);
}

.filter-field input,
.filter-field select {
  height: 2.25rem;
  padding: 0 0.625rem;
  border: 1px solid var(--admin-border);
  border-radius: 6px;
  font-size: 0.875rem;
  color: var(--admin-text-main);
  background-color: #fff;
  box-sizing: border-box;
}

.filter-field input:focus,
.filter-field select:focus {
  outline: none;
  border-color: var(--admin-action);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
}

.input-with-icon {
  position: relative;
  display: flex;
  align-items: center;
}

.input-with-icon i {
  position: absolute;
  left: 0.625rem;
  color: #94a3b8;
  font-size: 0.8125rem;
  pointer-events: none;
}

.input-with-icon input {
  padding-left: 2rem;
  width: 100%;
}

.filters-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  justify-content: flex-end;
  border-top: 1px solid #f1f5f9;
  padding-top: 0.875rem;
}

/* Buttons */
.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background-color: var(--admin-action);
  color: #ffffff;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s;
}

.btn-primary:hover:not(:disabled) {
  background-color: var(--admin-action-hover);
}

.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background-color: #ffffff;
  color: var(--admin-primary);
  border: 1px solid var(--admin-border);
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-secondary:hover:not(:disabled) {
  background-color: #f8fafc;
}

.btn-export {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background-color: #ffffff;
  color: var(--admin-action);
  border: 1px solid var(--admin-action);
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-export:hover:not(:disabled) {
  background-color: #eff6ff;
  border-color: var(--admin-action-hover);
  color: var(--admin-action-hover);
}

.btn-danger {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background-color: var(--admin-danger);
  color: #ffffff;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s;
}

.btn-danger:hover:not(:disabled) {
  background-color: var(--admin-danger-hover);
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* States: loading / empty */
.state-card {
  background: var(--admin-card-bg);
  border: 1px solid var(--admin-border);
  border-radius: 10px;
  padding: 3rem 1.5rem;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}

.state-card__icon {
  font-size: 2.25rem;
  color: #94a3b8;
}

.state-card h2 {
  margin: 0;
  font-size: 1.125rem;
  color: var(--admin-primary);
}

.state-card p {
  margin: 0;
  color: var(--admin-text-muted);
}

/* Table Card */
.table-card {
  background: var(--admin-card-bg);
  border: 1px solid var(--admin-border);
  border-radius: 10px;
  overflow: hidden;
}

.table-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--admin-border);
}

.table-card__header h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--admin-primary);
}

.sessions-counter {
  font-size: 0.8125rem;
  color: var(--admin-text-muted);
}

.table-wrapper {
  overflow-x: auto;
}

.sessions-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 0.875rem;
}

.sessions-table th {
  background-color: #f8fafc;
  color: var(--admin-text-muted);
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--admin-border);
}

.sessions-table td {
  padding: 0.875rem 1rem;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}

.sessions-table tr:hover {
  background-color: #fbfdff;
}

.row-active {
  background-color: #fafcff;
}

/* Cell content */
.student-cell {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.student-name {
  font-weight: 600;
  color: var(--admin-primary);
}

.student-code {
  font-size: 0.75rem;
  color: var(--admin-text-muted);
  font-family: monospace;
}

.machine-tag {
  display: inline-block;
  background-color: #edf2fb;
  color: var(--admin-primary);
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-weight: 600;
  font-size: 0.8125rem;
}

.status-badge {
  display: inline-flex;
  flex-direction: column;
  gap: 0.125rem;
}

.status-badge--active {
  display: inline-flex;
  flex-direction: row;
  align-items: center;
  gap: 0.375rem;
  background-color: #ecfdf3;
  color: var(--admin-success);
  padding: 0.25rem 0.5rem;
  border-radius: 999px;
  font-weight: 600;
  font-size: 0.75rem;
  width: fit-content;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--admin-success);
}

.status-badge--ended {
  color: var(--admin-text-muted);
  font-size: 0.8125rem;
}

.status-reason {
  font-size: 0.6875rem;
  color: #64748b;
  display: block;
}

.btn-force-close {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  background-color: #fee4e2;
  color: var(--admin-danger);
  border: 1px solid #fecdca;
  padding: 0.375rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-force-close:hover {
  background-color: var(--admin-danger);
  color: #ffffff;
  border-color: var(--admin-danger);
}

.th-actions,
.td-actions {
  text-align: right;
}

.text-muted {
  color: #94a3b8;
}

/* Pagination */
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.875rem 1.25rem;
  background-color: #f8fafc;
  border-top: 1px solid var(--admin-border);
  flex-wrap: wrap;
  gap: 0.75rem;
}

.pagination-info {
  font-size: 0.8125rem;
  color: var(--admin-text-muted);
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.btn-page {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  background-color: #ffffff;
  border: 1px solid var(--admin-border);
  padding: 0.375rem 0.625rem;
  border-radius: 6px;
  font-size: 0.8125rem;
  color: var(--admin-primary);
  cursor: pointer;
}

.btn-page:hover:not(:disabled) {
  background-color: #f1f5f9;
}

/* Modal */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background-color: rgba(15, 23, 42, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  z-index: 1000;
  backdrop-filter: blur(2px);
}

.modal-card {
  background-color: #ffffff;
  border-radius: 12px;
  max-width: 500px;
  width: 100%;
  box-shadow:
    0 20px 25px -5px rgba(0, 0, 0, 0.1),
    0 8px 10px -6px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  animation: modalIn 0.15s ease-out;
}

@keyframes modalIn {
  from {
    opacity: 0;
    transform: scale(0.96);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.modal-card__header {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1.25rem;
  border-bottom: 1px solid #f1f5f9;
}

.modal-icon-container {
  display: grid;
  place-items: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 50%;
  background-color: #fee4e2;
  color: var(--admin-danger);
  font-size: 1.25rem;
  flex-shrink: 0;
}

.modal-card__header h2 {
  margin: 0 0 0.25rem 0;
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--admin-primary);
}

.modal-subtitle {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--admin-danger);
  font-weight: 500;
}

.modal-card__body {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.session-summary {
  background-color: #f8fafc;
  border: 1px solid var(--admin-border);
  border-radius: 8px;
  padding: 0.875rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.summary-item {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  font-size: 0.8125rem;
}

.summary-label {
  color: var(--admin-text-muted);
  font-weight: 500;
}

.summary-value {
  color: var(--admin-primary);
  font-weight: 600;
  text-align: right;
}

.modal-warning-box {
  background-color: #fff9f5;
  border-left: 3px solid #f97316;
  padding: 0.75rem 1rem;
  border-radius: 0 6px 6px 0;
  font-size: 0.8125rem;
  color: #7c2d12;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.modal-warning-box p {
  margin: 0;
}

.technical-note {
  font-size: 0.75rem;
  color: #9a3412;
}

.technical-note code {
  background-color: #ffedd5;
  padding: 0.125rem 0.25rem;
  border-radius: 4px;
  font-family: monospace;
}

.modal-card__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  background-color: #f8fafc;
  border-top: 1px solid var(--admin-border);
}

@media (max-width: 768px) {
  .admin-header {
    flex-direction: column;
    align-items: stretch;
    gap: 0.75rem;
  }

  .admin-nav {
    overflow-x: auto;
    padding-bottom: 0.25rem;
  }

  .filters-grid {
    grid-template-columns: 1fr;
  }

  .filters-actions {
    flex-direction: column;
  }

  .btn-primary,
  .btn-secondary,
  .btn-export {
    width: 100%;
    justify-content: center;
  }
}
</style>
