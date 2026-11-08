<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'

/* ------------------------------------------------------------------ */
/*  Tipos locales                                                      */
/*  AJUSTAR: si tu schema ya define la sesión de acceso, reemplaza     */
/*  esta interfaz por components['schemas'][...] y quita el `as any`.  */
/* ------------------------------------------------------------------ */
type Lab = components['schemas']['Lab']
type Machine = components['schemas']['Machine']

type SessionStatus = 'active' | 'closed'

interface AccessSession {
  id: string
  session_code?: string | null
  student_name: string
  student_email?: string | null
  student_code: string
  machine_code: string
  machine_status?: string | null
  machine_mode?: string | null
  machine_last_seen_at?: string | null
  lab_name: string
  building?: string | null
  started_at: string
  ended_at?: string | null
  last_heartbeat_at?: string | null
  duration_minutes?: number | null
  status: SessionStatus
  close_reason?: string | null
}

interface Filters {
  student: string
  lab: string
  machine: string
  status: '' | SessionStatus
  from: string
  to: string
}

/* AJUSTAR: rutas del backend para accesos */
const PATHS = {
  list: '/api/v1/admin/access-sessions',
  detail: '/api/v1/admin/access-sessions/{id}',
  forceClose: '/api/v1/admin/access-sessions/{id}/force-close',
  exportCsv: '/api/v1/admin/access-sessions/export',
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const http = api as any

const PAGE_SIZE = 20
const ONLINE_THRESHOLD_MS = 2 * 60 * 1000
const TZ = 'America/Bogota'

/* ------------------------------------------------------------------ */
/*  Estado                                                             */
/* ------------------------------------------------------------------ */
const view = ref<'list' | 'detail'>('list')

const labs = ref<Lab[]>([])
const machines = ref<Machine[]>([])
const sessions = ref<AccessSession[]>([])
const selected = ref<AccessSession | null>(null)

const loading = ref(false)
const loadFailed = ref(false)
const page = ref(0)

const draft = reactive<Filters>({ student: '', lab: '', machine: '', status: '', from: '', to: '' })
const applied = ref<Filters>({ ...draft })
const rangeError = ref(false)

const successMessage = ref('')

// Forzar cierre
const showForceModal = ref(false)
const forcing = ref(false)
const forceError = ref(false)

// Exportar
const showExportModal = ref(false)
const exporting = ref(false)
const exportError = ref(false)

const todayLabel = computed(() => formatDay(new Date().toISOString()))

const machineOptions = computed(() =>
  draft.lab ? machines.value.filter((m) => m.lab_id === draft.lab) : machines.value,
)

const hasFilters = computed(() => Object.values(applied.value).some((v) => v !== ''))
const hasNext = computed(() => sessions.value.length === PAGE_SIZE)

const fromInvalid = computed(() => !!draft.from && !!draft.to && draft.from > draft.to)

watch(
  () => draft.lab,
  () => {
    if (draft.machine && !machineOptions.value.some((m) => m.id === draft.machine)) {
      draft.machine = ''
    }
  },
)

watch([() => draft.from, () => draft.to], () => {
  if (!fromInvalid.value) rangeError.value = false
})

/* ------------------------------------------------------------------ */
/*  Utilidades de formato                                              */
/* ------------------------------------------------------------------ */
function formatDay(date: string): string {
  return new Intl.DateTimeFormat('es-CO', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: TZ,
  })
    .format(new Date(date))
    .replace(/\./g, '')
}

function formatTime(date?: string | null): string {
  if (!date) return '—'
  return new Intl.DateTimeFormat('es-CO', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: TZ,
  }).format(new Date(date))
}

function formatDateTime(date?: string | null): string {
  if (!date) return '—'
  return `${formatDay(date)} · ${formatTime(date)}:${new Intl.DateTimeFormat('es-CO', {
    second: '2-digit',
    timeZone: TZ,
  }).format(new Date(date))}`
}

function durationOf(s: AccessSession): number {
  if (s.duration_minutes != null) return s.duration_minutes
  const end = s.ended_at ? new Date(s.ended_at).getTime() : Date.now()
  return Math.max(0, Math.floor((end - new Date(s.started_at).getTime()) / 60000))
}

function agoLabel(date?: string | null): string {
  if (!date) return 'sin registro'
  const secs = Math.max(0, Math.floor((Date.now() - new Date(date).getTime()) / 1000))
  if (secs < 60) return `hace ${secs} s`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `hace ${mins} min`
  return `hace ${Math.floor(mins / 60)} h`
}

/* AJUSTAR: códigos de motivo de cierre según tu backend */
function closeReasonLabel(reason?: string | null): string {
  const labels: Record<string, string> = {
    pc_exit: 'Salida desde PC',
    student_exit: 'Salida desde PC',
    server_exit: 'Salida desde el servidor',
    heartbeat_timeout: 'Sin latido (cierre automático)',
    admin_forced: 'Por cierre administrativo',
  }
  if (!reason) return 'Sin motivo'
  return labels[reason] ?? reason
}

function isMachineOnline(s: AccessSession): boolean {
  if (!s.machine_last_seen_at) return false
  return Date.now() - new Date(s.machine_last_seen_at).getTime() <= ONLINE_THRESHOLD_MS
}

/* ------------------------------------------------------------------ */
/*  Carga de datos                                                     */
/* ------------------------------------------------------------------ */
function buildQuery(f: Filters, extra: Record<string, unknown> = {}) {
  return {
    student: f.student.trim() || undefined,
    lab_id: f.lab || undefined,
    machine_id: f.machine || undefined,
    status: f.status || undefined,
    from: f.from || undefined,
    to: f.to || undefined,
    ...extra,
  }
}

async function loadCatalogs() {
  try {
    const [labsRes, machinesRes] = await Promise.all([
      api.GET('/api/v1/admin/labs', { params: { query: { limit: 100, offset: 0 } } }),
      api.GET('/api/v1/admin/machines', { params: { query: { limit: 100, offset: 0 } } }),
    ])
    labs.value = labsRes.data?.items ?? []
    machines.value = machinesRes.data?.items ?? []
  } catch {
    /* los filtros quedan con "Todos" si el catálogo falla */
  }
}

async function loadSessions() {
  loading.value = true
  loadFailed.value = false

  try {
    const { data, error } = await http.GET(PATHS.list, {
      params: {
        query: buildQuery(applied.value, { limit: PAGE_SIZE, offset: page.value * PAGE_SIZE }),
      },
    })
    if (error) throw new Error('load')
    sessions.value = (data?.items ?? []) as AccessSession[]
  } catch {
    loadFailed.value = true
    sessions.value = []
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  if (fromInvalid.value) {
    rangeError.value = true
    return
  }
  rangeError.value = false
  successMessage.value = ''
  applied.value = { ...draft }
  page.value = 0
  loadSessions()
}

function clearFilters() {
  Object.assign(draft, { student: '', lab: '', machine: '', status: '', from: '', to: '' })
  rangeError.value = false
  applied.value = { ...draft }
  page.value = 0
  loadSessions()
}

function goPage(delta: number) {
  page.value = Math.max(0, page.value + delta)
  loadSessions()
}

/* ------------------------------------------------------------------ */
/*  Detalle                                                            */
/* ------------------------------------------------------------------ */
async function openDetail(session: AccessSession) {
  successMessage.value = ''
  forceError.value = false
  selected.value = session
  view.value = 'detail'
  await refreshDetail()
}

async function refreshDetail() {
  if (!selected.value) return
  try {
    const { data, error } = await http.GET(PATHS.detail, {
      params: { path: { id: selected.value.id } },
    })
    if (!error && data) selected.value = data as AccessSession
  } catch {
    /* se conserva lo que ya se muestra */
  }
}

function backToList() {
  view.value = 'list'
  selected.value = null
  forceError.value = false
}

function openForceModal() {
  forceError.value = false
  showForceModal.value = true
}

async function forceClose() {
  if (!selected.value) return
  forcing.value = true
  forceError.value = false

  try {
    const { data, error } = await http.POST(PATHS.forceClose, {
      params: { path: { id: selected.value.id } },
    })
    if (error) throw new Error('force')

    selected.value = (data as AccessSession) ?? {
      ...selected.value,
      status: 'closed',
      close_reason: 'admin_forced',
      ended_at: new Date().toISOString(),
    }
    showForceModal.value = false
    successMessage.value = `Sesión de ${selected.value.student_name} cerrada por la administración.`
    loadSessions()
  } catch {
    showForceModal.value = false
    forceError.value = true
  } finally {
    forcing.value = false
  }
}

/* ------------------------------------------------------------------ */
/*  Exportar CSV                                                       */
/* ------------------------------------------------------------------ */
function openExportModal() {
  exportError.value = false
  showExportModal.value = true
}

async function downloadCsv() {
  exporting.value = true
  exportError.value = false

  try {
    const { data, error } = await http.GET(PATHS.exportCsv, {
      params: { query: buildQuery(applied.value) },
      parseAs: 'blob',
    })
    if (error || !data) throw new Error('export')

    const url = URL.createObjectURL(data as Blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `accesos_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)

    showExportModal.value = false
    successMessage.value = 'El archivo CSV se descargó correctamente.'
  } catch {
    exportError.value = true
  } finally {
    exporting.value = false
  }
}

function closeModals() {
  if (forcing.value || exporting.value) return
  showForceModal.value = false
  showExportModal.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeModals()
}

/* resumen de filtros para el modal de exportación */
const exportSummary = computed(() => {
  const f = applied.value
  const lab = labs.value.find((l) => l.id === f.lab)?.name
  const machine = machines.value.find((m) => m.id === f.machine)?.code
  const statusText = f.status === 'active' ? 'Activas' : f.status === 'closed' ? 'Cerradas' : 'Todas · Activas y cerradas'
  const period =
    f.from || f.to
      ? `${f.from ? formatDay(f.from) : 'Inicio'} – ${f.to ? formatDay(f.to) : 'Hoy'}`
      : 'Todo el historial'
  return {
    student: f.student || 'Todos',
    labMachine: `${lab ?? 'Todas'} / ${machine ?? 'Todos'}`,
    period,
    status: statusText,
  }
})

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  loadCatalogs()
  loadSessions()
})

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <main class="access-page">
    <!-- ============ VISTA: HISTORIAL ============ -->
    <template v-if="view === 'list'">
      <header class="page-header">
        <div>
          <h1>Historial de accesos</h1>
          <p>Consulta sesiones con filtros precisos y exporta los resultados autorizados.</p>
        </div>

        <button class="secondary-button" type="button" @click="openExportModal">
          <i class="pi pi-download"></i>
          Exportar CSV
        </button>
      </header>

      <div v-if="successMessage" class="message success-message" role="status">
        <i class="pi pi-check-circle"></i>
        <div>
          <strong>Cambios guardados</strong>
          <p>{{ successMessage }}</p>
        </div>
      </div>

      <!-- Filtros -->
      <section class="card filters-card">
        <form class="filters-grid" novalidate @submit.prevent="applyFilters">
          <label class="field">
            <span>Estudiante · correo o código EXACTO</span>
            <input v-model="draft.student" type="text" placeholder="ana.perez@universidad.example" />
          </label>

          <label class="field">
            <span>Sala</span>
            <select v-model="draft.lab">
              <option value="">Todas</option>
              <option v-for="lab in labs" :key="lab.id" :value="lab.id">{{ lab.name }}</option>
            </select>
          </label>

          <label class="field">
            <span>Equipo</span>
            <select v-model="draft.machine">
              <option value="">Todos</option>
              <option v-for="m in machineOptions" :key="m.id" :value="m.id">{{ m.code }}</option>
            </select>
          </label>

          <label class="field">
            <span>Estado · Activo / Cerrado</span>
            <select v-model="draft.status">
              <option value="">Todos</option>
              <option value="active">Activo</option>
              <option value="closed">Cerrado</option>
            </select>
          </label>

          <label class="field">
            <span>Fecha desde</span>
            <input v-model="draft.from" type="date" :class="{ 'input-error': rangeError }" />
            <small v-if="rangeError" class="field-error">Debe ser anterior o igual a la fecha hasta.</small>
          </label>

          <label class="field">
            <span>Fecha hasta</span>
            <input v-model="draft.to" type="date" :class="{ 'input-error': rangeError }" />
            <small v-if="rangeError" class="field-error">Elige un día igual o posterior a la fecha desde.</small>
          </label>

          <div class="filter-actions">
            <button class="primary-button" type="submit" :disabled="loading">
              <i class="pi pi-filter"></i>
              Aplicar filtros
            </button>
            <button class="ghost-button" type="button" @click="clearFilters">Limpiar</button>
          </div>

          <p class="filter-note">
            Coincidencia exacta por estudiante. No se admite búsqueda parcial.
          </p>
        </form>
      </section>

      <div v-if="rangeError" class="message error-message" role="alert">
        <i class="pi pi-exclamation-circle"></i>
        <div>
          <strong>El rango de fechas no es válido</strong>
          <p>Corrige las fechas y vuelve a aplicar los filtros. Se conserva el último resultado válido.</p>
        </div>
      </div>

      <div class="meta-row">
        <span>{{ todayLabel }} · Zona horaria de la universidad</span>
        <span v-if="loadFailed">Última consulta fallida</span>
        <span v-else>Horas del servidor · {{ sessions.length }} resultados visibles</span>
      </div>

      <section class="card table-card">
        <!-- Cargando: esqueleto -->
        <div v-if="loading" class="skeleton-table" aria-busy="true" aria-label="Cargando accesos">
          <div v-for="n in 4" :key="n" class="skeleton-row">
            <span v-for="m in 4" :key="m" class="skeleton-bar"></span>
          </div>
          <p class="skeleton-note">Los datos se están cargando. No se han modificado.</p>
        </div>

        <!-- Error de carga -->
        <div v-else-if="loadFailed" class="empty-state">
          <i class="pi pi-wifi"></i>
          <strong>No se pudieron cargar los accesos</strong>
          <p>Se perdió la conexión con el servidor. Vuelve a intentarlo.</p>
          <button class="primary-button" type="button" @click="loadSessions">
            <i class="pi pi-refresh"></i>
            Reintentar
          </button>
        </div>

        <!-- Sin resultados -->
        <div v-else-if="sessions.length === 0" class="empty-state">
          <i class="pi pi-search"></i>
          <strong>No hay accesos con estos filtros</strong>
          <p>Prueba con otros criterios o elimina los filtros aplicados.</p>
          <button v-if="hasFilters" class="primary-button" type="button" @click="clearFilters">
            <i class="pi pi-filter-slash"></i>
            Limpiar filtros
          </button>
        </div>

        <div v-else class="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Estudiante / código</th>
                <th>Equipo</th>
                <th>Sala</th>
                <th>Inicio</th>
                <th>Fin</th>
                <th>Duración min</th>
                <th>Estado</th>
                <th>Detalle / motivo de cierre</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in sessions" :key="s.id">
                <td>
                  <strong>{{ s.student_name }}</strong>
                  <small>{{ s.student_code }}</small>
                </td>
                <td>{{ s.machine_code }}</td>
                <td>{{ s.lab_name }}</td>
                <td>{{ formatTime(s.started_at) }}</td>
                <td>{{ formatTime(s.ended_at) }}</td>
                <td>{{ durationOf(s) }}</td>
                <td>
                  <span class="chip" :class="s.status === 'active' ? 'online' : 'closed'">
                    <span class="dot"></span>
                    {{ s.status === 'active' ? 'Activa' : 'Cerrada' }}
                  </span>
                </td>
                <td>
                  <button class="link-button" type="button" @click="openDetail(s)">
                    Ver{{ s.status === 'closed' ? ` · ${closeReasonLabel(s.close_reason)}` : ' detalle' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <footer class="list-footer">
        <p class="footer-note">
          Una sesión activa no tiene hora de fin; la duración se calcula hasta la consulta.
        </p>
        <div class="pagination">
          <button
            v-if="page > 0"
            class="secondary-button"
            type="button"
            :disabled="loading"
            @click="goPage(-1)"
          >
            <i class="pi pi-arrow-left"></i>
            Anterior
          </button>
          <button
            class="secondary-button"
            type="button"
            :disabled="loading || !hasNext"
            @click="goPage(1)"
          >
            Siguiente
            <i class="pi pi-arrow-right"></i>
          </button>
        </div>
      </footer>
    </template>

    <!-- ============ VISTA: DETALLE ============ -->
    <template v-else-if="selected">
      <header class="page-header">
        <div>
          <h1>Detalle de acceso</h1>
          <p>Información de sesión y tiempos registrados por el servidor.</p>
        </div>

        <button class="secondary-button" type="button" @click="backToList">
          <i class="pi pi-arrow-left"></i>
          Volver al historial
        </button>
      </header>

      <div v-if="successMessage" class="message success-message" role="status">
        <i class="pi pi-check-circle"></i>
        <div>
          <strong>Cambios guardados</strong>
          <p>{{ successMessage }}</p>
        </div>
      </div>

      <div class="detail-layout">
        <section class="card detail-card">
          <div class="section-heading">
            <div>
              <h2>{{ selected.status === 'active' ? 'Sesión activa' : 'Sesión cerrada' }}</h2>
              <p class="hint-text">
                Acceso de demostración · Identificador {{ selected.session_code || selected.id }}
              </p>
            </div>
            <span class="chip" :class="selected.status === 'active' ? 'online' : 'closed'">
              <span class="dot"></span>
              {{ selected.status === 'active' ? 'Activa' : 'Cerrada' }}
            </span>
          </div>

          <div class="student-block">
            <strong>{{ selected.student_name }}</strong>
            <span>{{ selected.student_email || 'Sin correo registrado' }}</span>
          </div>

          <dl class="detail-grid">
            <div>
              <dt>Código de estudiante</dt>
              <dd>{{ selected.student_code }}</dd>
            </div>
            <div>
              <dt>Equipo</dt>
              <dd>{{ selected.machine_code }}</dd>
            </div>
            <div>
              <dt>Sala</dt>
              <dd>{{ selected.lab_name }}{{ selected.building ? ` · ${selected.building}` : '' }}</dd>
            </div>
            <div>
              <dt>Inicio</dt>
              <dd>{{ formatDateTime(selected.started_at) }}</dd>
            </div>
            <div>
              <dt>Último latido</dt>
              <dd>{{ formatDateTime(selected.last_heartbeat_at) }}</dd>
            </div>
            <div>
              <dt>{{ selected.status === 'active' ? 'Duración al consultar' : 'Duración' }}</dt>
              <dd>{{ durationOf(selected) }} minutos</dd>
            </div>
            <div v-if="selected.status === 'closed'">
              <dt>Fin</dt>
              <dd>{{ formatDateTime(selected.ended_at) }}</dd>
            </div>
            <div v-if="selected.status === 'closed'">
              <dt>Motivo de cierre</dt>
              <dd>{{ closeReasonLabel(selected.close_reason) }}</dd>
            </div>
          </dl>

          <div class="info-box">
            <i class="pi pi-info-circle"></i>
            <div v-if="selected.status === 'active'">
              <strong>La sesión continúa activa</strong>
              <p>
                Todavía no tiene hora de fin ni motivo de cierre. Las horas provienen del servidor y
                se muestran en la hora de la universidad.
              </p>
            </div>
            <div v-else>
              <strong>La sesión ya está cerrada</strong>
              <p>
                La hora final se registró desde el servidor y se muestra en la hora de la
                universidad.
              </p>
            </div>
          </div>

          <p v-if="selected.status === 'active'" class="footer-note">
            Si pasan 3 min sin latido, la sesión se cierra automáticamente y el equipo vuelve a la
            pantalla QR en ≤60 s.
          </p>
        </section>

        <aside class="detail-side">
          <section class="card side-card">
            <h2>Intervención administrativa</h2>

            <template v-if="selected.status === 'active'">
              <p>
                Cierra esta sesión solo cuando sea necesario. La operación es irreversible y queda
                auditada.
              </p>

              <div v-if="forceError" class="message error-message compact" role="alert">
                <i class="pi pi-exclamation-circle"></i>
                <div>
                  <strong>No se pudo forzar el cierre</strong>
                  <p>
                    El servidor no respondió a la solicitud. No se ha confirmado ningún cambio en la
                    sesión.
                  </p>
                </div>
              </div>

              <button class="danger-button" type="button" @click="openForceModal">
                <i :class="forceError ? 'pi pi-refresh' : 'pi pi-power-off'"></i>
                {{ forceError ? 'Reintentar cierre' : 'Forzar cierre' }}
              </button>

              <button v-if="forceError" class="ghost-button" type="button" @click="refreshDetail">
                <i class="pi pi-refresh"></i>
                Actualizar estado
              </button>
            </template>

            <p v-else>Esta sesión ya está cerrada; no requiere intervención.</p>
          </section>

          <section class="card side-card">
            <h2>Estado del equipo</h2>
            <span class="chip" :class="isMachineOnline(selected) ? 'online' : 'offline'">
              <span class="dot"></span>
              {{ isMachineOnline(selected) ? 'En línea' : 'Desconectado' }}
            </span>
            <p>
              {{ selected.machine_code }}
              <template v-if="selected.machine_status"> · {{ selected.machine_status }}</template>
              <template v-if="selected.machine_mode"> · {{ selected.machine_mode }}</template>
              <br />
              Último contacto {{ agoLabel(selected.machine_last_seen_at) }}.
            </p>
          </section>
        </aside>
      </div>
    </template>

    <!-- ============ MODAL: FORZAR CIERRE ============ -->
    <div v-if="showForceModal && selected" class="modal-overlay" @click.self="closeModals">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="force-title">
        <header class="modal-header">
          <div>
            <h2 id="force-title" class="danger-title">¿Forzar el cierre de esta sesión?</h2>
            <p class="hint-text">{{ selected.student_name }} · {{ selected.student_code }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="Cerrar" @click="closeModals">
            <i class="pi pi-times"></i>
          </button>
        </header>

        <div class="modal-summary">
          <div>
            <span>Equipo</span>
            <strong>{{ selected.machine_code }}</strong>
          </div>
          <div>
            <span>Sala</span>
            <strong>{{ selected.lab_name }}{{ selected.building ? ` · ${selected.building}` : '' }}</strong>
          </div>
        </div>

        <div class="message error-message compact" role="alert">
          <i class="pi pi-exclamation-circle"></i>
          <div>
            <strong>Esta acción es irreversible y queda auditada</strong>
            <p>Se cerrará la sesión activa. El equipo volverá a la pantalla QR en ≤60 s.</p>
          </div>
        </div>

        <p class="modal-text">
          Motivo de cierre: Cierre administrativo · admin_forced. La hora final se registra desde
          el servidor.
        </p>

        <footer class="modal-actions">
          <button class="secondary-button" type="button" :disabled="forcing" @click="closeModals">
            Cancelar
          </button>
          <button class="danger-button" type="button" :disabled="forcing" @click="forceClose">
            <i class="pi pi-power-off"></i>
            {{ forcing ? 'Cerrando...' : 'Forzar cierre' }}
          </button>
        </footer>
      </div>
    </div>

    <!-- ============ MODAL: EXPORTAR CSV ============ -->
    <div v-if="showExportModal" class="modal-overlay" @click.self="closeModals">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="export-title">
        <header class="modal-header">
          <div>
            <h2 id="export-title">Exportar resultados a CSV</h2>
            <p class="hint-text">
              Se exportan todos los resultados filtrados, no solo los que ves en esta pantalla.
            </p>
          </div>
          <button class="icon-button" type="button" aria-label="Cerrar" @click="closeModals">
            <i class="pi pi-times"></i>
          </button>
        </header>

        <div v-if="exportError" class="message error-message compact" role="alert">
          <i class="pi pi-exclamation-circle"></i>
          <div>
            <strong>No se pudo exportar el archivo</strong>
            <p>
              El servicio de exportación no está disponible temporalmente. No se descargó ningún
              archivo. Reintenta con los mismos filtros o cancela para volver al historial.
            </p>
          </div>
        </div>

        <div class="modal-summary grid-2">
          <div>
            <span>Estudiante · coincidencia exacta</span>
            <strong>{{ exportSummary.student }}</strong>
          </div>
          <div>
            <span>Sala / Equipo</span>
            <strong>{{ exportSummary.labMachine }}</strong>
          </div>
          <div>
            <span>Período</span>
            <strong>{{ exportSummary.period }}</strong>
          </div>
          <div>
            <span>Estado de sesión</span>
            <strong>{{ exportSummary.status }}</strong>
          </div>
        </div>

        <p class="modal-text">
          <strong>Columnas del archivo, en este orden:</strong><br />
          estudiante, código, equipo, sala, inicio, fin, duración en minutos, motivos de cierre
        </p>

        <div class="info-box">
          <i class="pi pi-info-circle"></i>
          <div>
            <strong>CSV UTF-8 con BOM · Separador coma</strong>
            <p>
              Horas del servidor en la zona horaria de la universidad. Las sesiones activas tienen
              fin y motivo de cierre vacíos.
            </p>
          </div>
        </div>

        <p class="footer-note">
          Contiene datos de estudiantes. Comparte el archivo solo con personal autorizado y guárdalo
          de forma segura.
        </p>

        <footer class="modal-actions">
          <button class="secondary-button" type="button" :disabled="exporting" @click="closeModals">
            Cancelar
          </button>
          <button class="primary-button" type="button" :disabled="exporting" @click="downloadCsv">
            <i :class="exportError ? 'pi pi-refresh' : 'pi pi-download'"></i>
            {{ exporting ? 'Preparando...' : exportError ? 'Reintentar' : 'Descargar CSV' }}
          </button>
        </footer>
      </div>
    </div>
  </main>
</template>

<style scoped>
.access-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  color: var(--text);
}

/* ---- Encabezados ---- */
.page-header,
.section-heading,
.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

h1 {
  margin: 0 0 5px;
  font-size: 27px;
  line-height: 1.2;
}

h2 {
  margin: 0;
  font-size: 17px;
  line-height: 24px;
}

.page-header p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.hint-text {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12px;
}

.card {
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}

/* ---- Botones ---- */
.primary-button,
.secondary-button,
.ghost-button,
.danger-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.primary-button {
  color: #ffffff;
  background: var(--primary);
  border: 1px solid var(--primary);
}

.primary-button:hover {
  opacity: 0.9;
}

.secondary-button {
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
}

.secondary-button:hover,
.ghost-button:hover {
  background: var(--hover);
}

.ghost-button {
  color: var(--text);
  background: transparent;
  border: 1px solid transparent;
}

.danger-button {
  color: var(--danger);
  background: var(--surface);
  border: 1px solid var(--danger);
}

.danger-button:hover {
  background: var(--danger-bg);
}

.link-button {
  padding: 0;
  color: var(--primary);
  background: transparent;
  border: 0;
  font-size: 12px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.link-button:hover {
  text-decoration: underline;
}

.icon-button {
  width: 34px;
  height: 34px;
  color: var(--muted);
  background: transparent;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.icon-button:hover {
  background: var(--hover);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

/* ---- Avisos ---- */
.message {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 8px;
  font-size: 13px;
}

.message.compact {
  padding: 12px 14px;
}

.message p {
  margin: 2px 0 0;
  color: var(--text);
  font-size: 12px;
  line-height: 1.5;
}

.message i {
  margin-top: 2px;
}

.error-message {
  color: var(--danger);
  background: var(--danger-bg);
  border: 1px solid var(--danger);
}

.success-message {
  color: var(--success);
  background: var(--success-bg);
  border: 1px solid var(--success);
}

.info-box {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  background: var(--hover);
  border-radius: 8px;
  font-size: 12px;
}

.info-box i {
  margin-top: 2px;
  color: var(--primary);
}

.info-box strong {
  display: block;
  margin-bottom: 2px;
}

.info-box p {
  margin: 0;
  color: var(--muted);
  line-height: 1.5;
}

/* ---- Filtros ---- */
.filters-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr 1fr;
  gap: 14px 16px;
  align-items: start;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 12px;
  font-weight: 600;
}

.field input,
.field select {
  width: 100%;
  min-height: 40px;
  padding: 0 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}

.field input:focus,
.field select:focus {
  outline: none;
  border: 2px solid var(--primary);
}

.field .input-error {
  border: 1px solid var(--danger);
}

.field-error {
  color: var(--danger);
  font-size: 11px;
  font-weight: 500;
}

.filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  align-self: end;
}

.filter-note {
  grid-column: 4;
  margin: 0;
  align-self: end;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  font-size: 11px;
}

/* ---- Tabla ---- */
.table-card {
  padding: 8px 12px;
}

.table-wrapper {
  width: 100%;
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  white-space: nowrap;
}

th {
  padding: 12px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  border-bottom: 1px solid var(--border);
}

td {
  padding: 14px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}

tbody tr:last-child td {
  border-bottom: 0;
}

tbody tr:hover {
  background: var(--hover);
}

td strong,
td small {
  display: block;
}

td small {
  margin-top: 4px;
  color: var(--muted);
}

/* ---- Chips ---- */
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  background: var(--hover);
}

.chip .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.chip.online {
  color: var(--success);
  background: var(--success-bg);
}

.chip.closed,
.chip.offline {
  color: var(--muted);
  background: var(--inner);
}

/* ---- Estados vacíos / esqueleto ---- */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 45px 15px;
  color: var(--muted);
  text-align: center;
}

.empty-state > i {
  font-size: 27px;
}

.empty-state strong {
  color: var(--text);
}

.empty-state p {
  margin: 0;
  font-size: 12px;
}

.skeleton-table {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 4px;
}

.skeleton-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.skeleton-bar {
  height: 14px;
  border-radius: 6px;
  background: linear-gradient(90deg, var(--inner), var(--hover), var(--inner));
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite linear;
}

@keyframes shimmer {
  from {
    background-position: 200% 0;
  }
  to {
    background-position: -200% 0;
  }
}

.skeleton-note {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 11px;
}

/* ---- Pie / paginación ---- */
.list-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.footer-note {
  margin: 0;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
}

.pagination {
  display: flex;
  gap: 8px;
}

/* ---- Detalle ---- */
.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 18px;
  align-items: start;
}

.detail-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.student-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.student-block strong {
  font-size: 20px;
}

.student-block span {
  color: var(--muted);
  font-size: 12px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin: 0;
}

.detail-grid dt {
  color: var(--muted);
  font-size: 11px;
}

.detail-grid dd {
  margin: 4px 0 0;
  font-size: 13px;
  font-weight: 600;
}

.detail-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.side-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
}

.side-card p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

.side-card .message {
  width: 100%;
}

/* ---- Modales ---- */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: var(--overlay);
}

.modal {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  max-width: 540px;
  max-height: calc(100vh - 40px);
  padding: 22px;
  overflow-y: auto;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.25);
}

.danger-title {
  color: var(--danger);
}

.modal-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 14px;
  background: var(--inner);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.modal-summary span {
  display: block;
  color: var(--muted);
  font-size: 11px;
}

.modal-summary strong {
  display: block;
  margin-top: 3px;
  font-size: 12px;
}

.modal-text {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}

.modal-text strong {
  color: var(--text);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}

/* ---- Responsive ---- */
@media (max-width: 1000px) {
  .filters-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filter-note {
    grid-column: auto;
  }

  .detail-layout {
    grid-template-columns: 1fr;
  }

  .detail-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .page-header,
  .section-heading,
  .list-footer,
  .meta-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .filters-grid,
  .modal-summary {
    grid-template-columns: 1fr;
  }

  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>