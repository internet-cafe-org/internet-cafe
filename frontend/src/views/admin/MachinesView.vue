<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'

type Lab = components['schemas']['Lab']
type Machine = components['schemas']['Machine']
type MachinePatch = components['schemas']['MachinePatch']
type MachineStatus = components['schemas']['MachineStatus']
type MachineMode = components['schemas']['MachineMode']

const ONLINE_THRESHOLD_MS = 2 * 60 * 1000 // En línea si el último contacto fue ≤ 2 min

const labs = ref<Lab[]>([])
const machines = ref<Machine[]>([])

const loading = ref(false)
const saving = ref(false)

const labFilter = ref('')
const statusFilter = ref<MachineStatus | ''>('')

const errorMessage = ref('')
const successMessage = ref('')

const activeCount = computed(() => machines.value.filter((m) => m.status === 'active').length)
const pendingCount = computed(
  () => machines.value.filter((m) => m.status === 'pending_enrollment').length,
)
const disabledCount = computed(() => machines.value.filter((m) => m.status === 'disabled').length)

function showError(error: unknown, fallback: string) {
  errorMessage.value = error instanceof Error ? error.message : fallback
  successMessage.value = ''
}

function clearMessages() {
  errorMessage.value = ''
  successMessage.value = ''
}

async function loadLabs() {
  const { data, error } = await api.GET('/api/v1/admin/labs', {
    params: { query: { limit: 100, offset: 0 } },
  })
  if (error) throw new Error('No fue posible cargar las salas.')
  labs.value = data?.items ?? []
}

async function loadMachines() {
  const { data, error } = await api.GET('/api/v1/admin/machines', {
    params: {
      query: {
        limit: 100,
        offset: 0,
        lab_id: labFilter.value || undefined,
        status: statusFilter.value || undefined,
      },
    },
  })
  if (error) throw new Error('No fue posible cargar los equipos.')
  machines.value = data?.items ?? []
}

async function loadData() {
  loading.value = true
  clearMessages()

  try {
    await Promise.all([loadLabs(), loadMachines()])
  } catch (error) {
    showError(error, 'No fue posible cargar la información.')
  } finally {
    loading.value = false
  }
}

watch([labFilter, statusFilter], async () => {
  loading.value = true
  clearMessages()

  try {
    await loadMachines()
  } catch (error) {
    showError(error, 'No fue posible cargar los equipos.')
  } finally {
    loading.value = false
  }
})

async function updateMachine(machine: Machine, patch: MachinePatch) {
  saving.value = true
  clearMessages()

  try {
    const { data, error } = await api.PATCH('/api/v1/admin/machines/{id}', {
      params: { path: { id: machine.id } },
      body: patch,
    })
    if (error) throw new Error('No fue posible actualizar el equipo.')

    if (data) {
      const index = machines.value.findIndex((item) => item.id === machine.id)
      if (index !== -1) machines.value[index] = data
    }

    successMessage.value = `El equipo ${machine.code} se actualizó correctamente.`
  } catch (error) {
    showError(error, 'No fue posible actualizar el equipo.')
  } finally {
    saving.value = false
  }
}

async function assignLab(machine: Machine, event: Event) {
  const target = event.target as HTMLSelectElement
  await updateMachine(machine, { lab_id: target.value || null })
}

async function toggleMode(machine: Machine) {
  const newMode: MachineMode = machine.mode === 'passive' ? 'kiosk' : 'passive'
  await updateMachine(machine, { mode: newMode })
}

async function toggleStatus(machine: Machine) {
  if (machine.status === 'pending_enrollment') return
  const newStatus = machine.status === 'active' ? 'disabled' : 'active'
  await updateMachine(machine, { status: newStatus })
}

function statusLabel(status: MachineStatus): string {
  const labels: Record<MachineStatus, string> = {
    active: 'Activo',
    pending_enrollment: 'Pendiente de enrolamiento',
    disabled: 'Deshabilitado',
  }
  return labels[status]
}

function modeLabel(mode: MachineMode): string {
  return mode === 'passive' ? 'Pasivo' : 'Kiosco'
}

function isOnline(machine: Machine): boolean {
  if (!machine.last_seen_at) return false
  return Date.now() - new Date(machine.last_seen_at).getTime() <= ONLINE_THRESHOLD_MS
}

function formatDate(date: string | null | undefined): string {
  if (!date) return 'Sin registro'

  return new Intl.DateTimeFormat('es-CO', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(date))
}

onMounted(loadData)
</script>

<template>
  <main class="machines-page">
    <header class="page-header">
      <div>
        <h1>Equipos</h1>
        <p>Consulta y administra los computadores registrados.</p>
      </div>
    </header>

    <div v-if="errorMessage" class="message error-message" role="alert">
      <i class="pi pi-exclamation-circle"></i>
      <div>
        <strong>No se pudo completar la acción</strong>
        <p>{{ errorMessage }}</p>
      </div>
    </div>

    <div v-if="successMessage" class="message success-message" role="status">
      <i class="pi pi-check-circle"></i>
      <div>
        <strong>Cambios guardados</strong>
        <p>{{ successMessage }}</p>
      </div>
    </div>

    <section class="summary-grid">
      <article class="summary-card">
        <div>
          <span>Total de equipos</span>
          <strong>{{ machines.length }}</strong>
        </div>
        <i class="pi pi-desktop summary-icon"></i>
      </article>

      <article class="summary-card">
        <div>
          <span>Activos</span>
          <strong>{{ activeCount }}</strong>
        </div>
        <i class="pi pi-check-circle summary-icon success"></i>
      </article>

      <article class="summary-card">
        <div>
          <span>Pendientes</span>
          <strong>{{ pendingCount }}</strong>
        </div>
        <i class="pi pi-clock summary-icon warning"></i>
      </article>

      <article class="summary-card">
        <div>
          <span>Deshabilitados</span>
          <strong>{{ disabledCount }}</strong>
        </div>
        <i class="pi pi-ban summary-icon danger"></i>
      </article>
    </section>

    <section class="table-card">
      <div class="section-heading">
        <div>
          <h2>Equipos registrados</h2>
          <p>Consulta y administra los equipos disponibles.</p>
        </div>
        <span class="table-subinfo">{{ machines.length }} equipos</span>
      </div>

      <div class="filters">
        <label>
          <span>Sala</span>
          <select v-model="labFilter">
            <option value="">Todas las salas</option>
            <option v-for="lab in labs" :key="lab.id" :value="lab.id">
              {{ lab.name }}{{ lab.building ? ` · ${lab.building}` : '' }}
            </option>
          </select>
        </label>

        <label>
          <span>Estado</span>
          <select v-model="statusFilter">
            <option value="">Todos los estados</option>
            <option value="active">Activo</option>
            <option value="pending_enrollment">Pendiente de enrolamiento</option>
            <option value="disabled">Deshabilitado</option>
          </select>
        </label>
      </div>

      <div v-if="loading" class="empty-state">
        <i class="pi pi-spin pi-spinner"></i>
        <p>Cargando equipos...</p>
      </div>

      <div v-else-if="machines.length === 0" class="empty-state">
        <i class="pi pi-desktop"></i>
        <strong>No hay equipos para mostrar</strong>
        <p>Prueba cambiando los filtros.</p>
      </div>

      <div v-else class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Equipo</th>
              <th>Sala</th>
              <th>Estado</th>
              <th>Conexión</th>
              <th>Modo</th>
              <th>Último contacto</th>
              <th>Acciones</th>
            </tr>
          </thead>

          <tbody>
            <tr v-for="machine in machines" :key="machine.id">
              <td>
                <strong>{{ machine.code }}</strong>
                <small>{{ machine.hostname || 'Sin nombre de equipo' }}</small>
              </td>

              <td>
                <select
                  class="table-select"
                  :value="machine.lab_id || ''"
                  :disabled="saving"
                  :aria-label="`Asignar sala a ${machine.code}`"
                  @change="assignLab(machine, $event)"
                >
                  <option value="">Sin sala</option>
                  <option v-for="lab in labs" :key="lab.id" :value="lab.id">
                    {{ lab.name }}
                  </option>
                </select>
              </td>

              <td>
                <span class="chip" :class="machine.status">
                  <span class="dot"></span>
                  {{ statusLabel(machine.status) }}
                </span>
              </td>

              <td>
                <span class="chip" :class="isOnline(machine) ? 'online' : 'offline'">
                  <span class="dot"></span>
                  {{ isOnline(machine) ? 'En línea' : 'Desconectado' }}
                </span>
              </td>

              <td>
                <button
                  class="mode-button"
                  type="button"
                  :disabled="saving"
                  :aria-label="`Cambiar modo de ${machine.code}`"
                  @click="toggleMode(machine)"
                >
                  {{ modeLabel(machine.mode) }}
                  <i class="pi pi-sync"></i>
                </button>
              </td>

              <td class="date-cell">{{ formatDate(machine.last_seen_at) }}</td>

              <td>
                <button
                  v-if="machine.status !== 'pending_enrollment'"
                  class="action-button"
                  :class="machine.status === 'active' ? 'danger-action' : 'primary-action'"
                  type="button"
                  :disabled="saving"
                  @click="toggleStatus(machine)"
                >
                  {{ machine.status === 'active' ? 'Deshabilitar' : 'Activar' }}
                </button>

                <span v-else class="pending-action">Requiere enrolamiento</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <footer class="footer-note">
      En línea si el último contacto fue ≤ 2 min; es independiente del estado administrativo.
      <br />
      <i class="pi pi-info-circle"></i>
      En desarrollo se muestran datos simulados mediante MSW.
    </footer>
  </main>
</template>

<style scoped>
.machines-page {
  display: flex;
  flex-direction: column;
  gap: 22px;
  color: var(--text);
}

.page-header,
.section-heading {
  display: flex;
  align-items: center;
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
  font-size: 18px;
  line-height: 26px;
}

.page-header p,
.section-heading p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.table-card,
.summary-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.table-card {
  padding: 20px;
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

.message p {
  margin: 2px 0 0;
  font-size: 13px;
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

.success-message p,
.error-message p {
  color: var(--text);
}

/* ---- Resumen ---- */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 15px;
}

.summary-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px;
}

.summary-card span {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.summary-card strong {
  display: block;
  margin-top: 4px;
  font-size: 27px;
}

.summary-icon {
  color: var(--primary);
  font-size: 20px;
}

.summary-icon.success {
  color: var(--success);
}

.summary-icon.warning {
  color: var(--warning);
}

.summary-icon.danger {
  color: var(--danger);
}

.table-subinfo {
  color: var(--muted);
  font-size: 12px;
}

/* ---- Filtros / campos ---- */
.filters {
  display: flex;
  gap: 14px;
  margin: 20px 0;
}

.filters label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 240px;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}

.filters select,
.table-select {
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.filters select {
  width: 100%;
  min-height: 40px;
  padding: 0 11px;
  font-size: 13px;
}

.filters select:focus,
.table-select:focus {
  outline: none;
  border: 2px solid var(--primary);
}

.table-select {
  max-width: 155px;
  min-height: 34px;
  padding: 0 7px;
  font-size: 12px;
}

/* ---- Tabla ---- */
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
  padding: 13px 12px;
  color: var(--muted);
  background: var(--inner);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

td {
  padding: 14px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
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

.date-cell {
  color: var(--muted);
}

/* ---- Chips con punto ---- */
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
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

.chip.active {
  color: var(--primary);
  background: var(--hover);
}

.chip.pending_enrollment {
  color: var(--warning);
  background: var(--warning-bg);
}

.chip.disabled {
  color: var(--danger);
  background: var(--danger-bg);
}

.chip.online {
  color: var(--success);
  background: var(--success-bg);
}

.chip.offline {
  color: var(--muted);
  background: var(--inner);
}

/* ---- Botones ---- */
.mode-button,
.action-button {
  min-height: 32px;
  padding: 0 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.mode-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
}

.mode-button:hover {
  background: var(--hover);
}

.action-button {
  background: var(--surface);
  border: 1px solid;
}

.danger-action {
  color: var(--danger);
  border-color: var(--danger);
}

.danger-action:hover {
  background: var(--danger-bg);
}

.primary-action {
  color: #ffffff;
  background: var(--primary);
  border-color: var(--primary);
}

.primary-action:hover {
  opacity: 0.9;
}

.pending-action {
  color: var(--muted);
  font-size: 11px;
}

/* ---- Estados vacíos y pie ---- */
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

.footer-note {
  color: var(--muted);
  font-size: 11px;
  line-height: 1.6;
}

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .page-header,
  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .filters {
    flex-direction: column;
  }

  .filters label {
    width: 100%;
  }
}
</style>