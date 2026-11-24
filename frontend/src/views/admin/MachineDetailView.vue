<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { ApiError } from '@/errors/problem-details'
import {
  createEnrollmentCode,
  revokeMachineKey,
  type EnrollmentCode,
} from '@/services/adminMachines'

type Lab = components['schemas']['Lab']
type Machine = components['schemas']['Machine']
type MachineMode = components['schemas']['MachineMode']
type MachinePatch = components['schemas']['MachinePatch']
type MachineStatus = components['schemas']['MachineStatus']
type ConfirmKind = 'revoke' | 'disable'

const ONLINE_THRESHOLD_MS = 2 * 60 * 1000 // En línea si el último contacto fue ≤ 2 min

const route = useRoute()
const router = useRouter()
const machineId = String(route.params.id)

const machine = ref<Machine | null>(null)
const labs = ref<Lab[]>([])
const labId = ref('')
const mode = ref<MachineMode>('passive')

const loading = ref(true)
const loadFailed = ref(false)
const notFound = ref(false)
const busy = ref(false)

const errorMessage = ref('')
const successMessage = ref('')

// El código solo se muestra una vez: al cerrar el aviso se descarta de memoria.
const enrollment = ref<EnrollmentCode | null>(null)
const copied = ref(false)
const confirming = ref<ConfirmKind | null>(null)

const isDisabled = computed(() => machine.value?.status === 'disabled')
const isPending = computed(() => machine.value?.status === 'pending_enrollment')
const dirty = computed(
  () =>
    !!machine.value &&
    (labId.value !== (machine.value.lab_id ?? '') || mode.value !== machine.value.mode),
)

function applyMachine(data: Machine) {
  machine.value = data
  labId.value = data.lab_id ?? ''
  mode.value = data.mode
}

function clearMessages() {
  errorMessage.value = ''
  successMessage.value = ''
}

function fail(error: unknown, fallback: string, conflict?: string) {
  successMessage.value = ''
  if (error instanceof ApiError && error.status === 409 && conflict) {
    errorMessage.value = conflict
  } else if (error instanceof ApiError && error.status === 404) {
    errorMessage.value = 'El equipo ya no existe. Vuelve a la lista de equipos.'
  } else {
    errorMessage.value = fallback
  }
}

async function load() {
  loading.value = true
  loadFailed.value = false
  notFound.value = false

  try {
    const query = { limit: 100, offset: 0 }
    const [labsResult, machinesResult] = await Promise.all([
      api.GET('/api/v1/admin/labs', { params: { query } }),
      api.GET('/api/v1/admin/machines', { params: { query } }),
    ])

    labs.value = labsResult.data?.items ?? []
    // La API no tiene GET por id: se busca el equipo en el listado.
    const found = machinesResult.data?.items.find((item) => item.id === machineId)

    if (found) applyMachine(found)
    else notFound.value = true
  } catch {
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

async function patchMachine(body: MachinePatch, ok: string, conflict?: string) {
  busy.value = true
  clearMessages()

  try {
    const { data } = await api.PATCH('/api/v1/admin/machines/{id}', {
      params: { path: { id: machineId } },
      body,
    })
    if (data) applyMachine(data)
    successMessage.value = ok
  } catch (error) {
    fail(error, 'No fue posible actualizar el equipo. Inténtalo de nuevo.', conflict)
  } finally {
    busy.value = false
  }
}

async function saveConfig() {
  if (!machine.value) return

  // Solo se envía lo que cambió.
  const body: MachinePatch = {}
  if (labId.value !== (machine.value.lab_id ?? '')) body.lab_id = labId.value || null
  if (mode.value !== machine.value.mode) body.mode = mode.value

  const modeChanged = body.mode !== undefined
  await patchMachine(
    body,
    modeChanged
      ? 'Cambios guardados. El equipo aplicará el nuevo modo en su próximo latido (≤ 60 s).'
      : 'Cambios guardados.',
  )
}

function enableMachine() {
  return patchMachine(
    { status: 'active' },
    'El equipo se habilitó correctamente.',
    'El equipo todavía no se enrolló, por eso no se puede activar.',
  )
}

async function generateCode() {
  busy.value = true
  clearMessages()
  copied.value = false

  try {
    enrollment.value = await createEnrollmentCode(machineId)
  } catch (error) {
    fail(
      error,
      'No se pudo generar el código. Inténtalo de nuevo.',
      'No se puede generar un código para este equipo en su estado actual.',
    )
  } finally {
    busy.value = false
  }
}

async function copyCode() {
  if (!enrollment.value) return

  try {
    await navigator.clipboard.writeText(enrollment.value.code)
    copied.value = true
  } catch {
    copied.value = false
  }
}

function closeCode() {
  enrollment.value = null
  copied.value = false
}

async function runConfirmed() {
  const kind = confirming.value
  confirming.value = null

  if (kind === 'disable') {
    await patchMachine({ status: 'disabled' }, 'El equipo se deshabilitó correctamente.')
    return
  }

  if (kind === 'revoke') {
    busy.value = true
    clearMessages()

    try {
      await revokeMachineKey(machineId)
      await load()
      successMessage.value =
        'La clave se revocó. Para volver a conectar el equipo, genera un código nuevo y enrólalo.'
    } catch (error) {
      fail(error, 'No se pudo revocar la clave. Inténtalo de nuevo.')
    } finally {
      busy.value = false
    }
  }
}

function statusLabel(status: MachineStatus): string {
  const labels: Record<MachineStatus, string> = {
    active: 'Activo',
    pending_enrollment: 'Pendiente de enrolamiento',
    disabled: 'Deshabilitado',
  }
  return labels[status]
}

function modeLabel(value: MachineMode): string {
  return value === 'passive' ? 'Pasivo' : 'Kiosco'
}

function isOnline(item: Machine): boolean {
  if (!item.last_seen_at) return false
  return Date.now() - new Date(item.last_seen_at).getTime() <= ONLINE_THRESHOLD_MS
}

function formatDate(date: string | null | undefined): string {
  if (!date) return 'Sin registro'

  return new Intl.DateTimeFormat('es-CO', { dateStyle: 'short', timeStyle: 'short' }).format(
    new Date(date),
  )
}

onMounted(load)
</script>

<template>
  <main class="detail-page">
    <header class="page-header">
      <div>
        <h1>{{ machine?.code ?? 'Equipo' }}</h1>
        <p>
          {{
            machine
              ? `${machine.hostname || 'Sin nombre de equipo'} · estado y edición`
              : 'Detalle del equipo'
          }}
        </p>
      </div>

      <button
        class="secondary-button"
        type="button"
        @click="router.push({ name: 'admin-machines' })"
      >
        <i aria-hidden="true" class="pi pi-arrow-left"></i>
        Volver a equipos
      </button>
    </header>

    <div v-if="loading" class="empty-state">
      <i aria-hidden="true" class="pi pi-spin pi-spinner"></i>
      <p>Cargando equipo...</p>
    </div>

    <div v-else-if="loadFailed" class="empty-state">
      <i aria-hidden="true" class="pi pi-wifi"></i>
      <strong>No se pudo cargar el equipo</strong>
      <p>Comprueba tu conexión y vuelve a intentarlo.</p>
      <button class="primary-button" type="button" data-test="retry" @click="load">
        <i aria-hidden="true" class="pi pi-refresh"></i>
        Reintentar
      </button>
    </div>

    <div v-else-if="notFound || !machine" class="empty-state">
      <i aria-hidden="true" class="pi pi-desktop"></i>
      <strong>No encontramos este equipo</strong>
      <p>Puede que se haya eliminado o que el enlace no sea correcto.</p>
    </div>

    <template v-else>
      <div v-if="errorMessage" class="message error-message" role="alert">
        <i aria-hidden="true" class="pi pi-exclamation-circle"></i>
        <div>
          <strong>No se pudo completar la acción</strong>
          <p data-test="error">{{ errorMessage }}</p>
        </div>
      </div>

      <div v-if="successMessage" class="message success-message" role="status">
        <i aria-hidden="true" class="pi pi-check-circle"></i>
        <div>
          <strong>Listo</strong>
          <p data-test="success">{{ successMessage }}</p>
        </div>
      </div>

      <div class="detail-layout">
        <section class="card">
          <h2>Configuración del equipo</h2>

          <dl class="facts">
            <div>
              <dt>Código</dt>
              <dd>{{ machine.code }}</dd>
            </div>
            <div>
              <dt>Estado</dt>
              <dd>
                <span class="chip" :class="machine.status" data-test="status">
                  <span class="dot"></span>{{ statusLabel(machine.status) }}
                </span>
              </dd>
            </div>
            <div>
              <dt>Conexión</dt>
              <dd>
                <span class="chip" :class="isOnline(machine) ? 'online' : 'offline'">
                  <span class="dot"></span>{{ isOnline(machine) ? 'En línea' : 'Desconectado' }}
                </span>
              </dd>
            </div>
            <div>
              <dt>Último contacto</dt>
              <dd>{{ formatDate(machine.last_seen_at) }}</dd>
            </div>
            <div>
              <dt>Enrolado</dt>
              <dd>{{ formatDate(machine.enrolled_at) }}</dd>
            </div>
            <div>
              <dt>Versión de la app</dt>
              <dd>{{ machine.app_version || 'Sin registro' }}</dd>
            </div>
          </dl>

          <form class="config-form" novalidate @submit.prevent="saveConfig">
            <label>
              Sala asignada
              <select v-model="labId" :disabled="busy" data-test="lab-select">
                <option value="">Sin sala</option>
                <option v-for="lab in labs" :key="lab.id" :value="lab.id">
                  {{ lab.name }}{{ lab.building ? ` · ${lab.building}` : '' }}
                </option>
              </select>
            </label>

            <label>
              Modo de funcionamiento
              <select v-model="mode" :disabled="busy" data-test="mode-select">
                <option value="passive">Pasivo</option>
                <option value="kiosk">Kiosco</option>
              </select>
              <span class="field-hint">
                {{
                  mode === 'passive'
                    ? 'Pasivo: registra los accesos sin bloquear el equipo.'
                    : 'Kiosco: pantalla completa hasta que un estudiante inicie sesión.'
                }}
                El cambio llega al equipo en ≤ 60 s.
              </span>
            </label>

            <div class="form-actions">
              <button
                class="primary-button"
                type="submit"
                data-test="save-config"
                :disabled="busy || !dirty"
              >
                <i aria-hidden="true" :class="busy ? 'pi pi-spin pi-spinner' : 'pi pi-check'"></i>
                Guardar cambios
              </button>
            </div>
          </form>
        </section>

        <aside class="side-column">
          <section class="card">
            <h2>Enrolamiento y clave</h2>
            <p class="muted">
              Entrega el código únicamente al personal de TI. Es de un solo uso, vence a las 24 h y
              no se puede volver a ver. Modo actual: {{ modeLabel(machine.mode) }}.
            </p>

            <div class="stack">
              <button
                class="primary-button"
                type="button"
                data-test="gen-code"
                :disabled="busy || isDisabled"
                @click="generateCode"
              >
                <i aria-hidden="true" class="pi pi-key"></i>
                Generar código de enrolamiento
              </button>

              <button
                class="danger-button"
                type="button"
                data-test="revoke"
                :disabled="busy || isPending"
                @click="confirming = 'revoke'"
              >
                <i aria-hidden="true" class="pi pi-ban"></i>
                Revocar clave
              </button>
            </div>

            <p v-if="isDisabled" class="field-hint">
              Habilita el equipo para generar un código de enrolamiento.
            </p>
            <p v-else-if="isPending" class="field-hint">
              Aún no hay una clave que revocar: el equipo no se enroló.
            </p>
          </section>

          <section class="card">
            <h2>Estado administrativo</h2>

            <template v-if="isDisabled">
              <p class="muted">
                El equipo está deshabilitado y no puede registrar accesos aunque esté en línea.
              </p>
              <button
                class="primary-button"
                type="button"
                data-test="enable"
                :disabled="busy"
                @click="enableMachine"
              >
                Habilitar equipo
              </button>
            </template>

            <template v-else>
              <p class="muted">
                Al deshabilitarlo se cancelan sus retos pendientes y se cierra su sesión abierta.
              </p>
              <button
                class="danger-button"
                type="button"
                data-test="disable"
                :disabled="busy || isPending"
                @click="confirming = 'disable'"
              >
                <i aria-hidden="true" class="pi pi-ban"></i>
                Deshabilitar equipo
              </button>
              <p v-if="isPending" class="field-hint">
                Requiere enrolamiento antes de administrarlo.
              </p>
            </template>
          </section>
        </aside>
      </div>
    </template>

    <!-- Código de enrolamiento: se muestra una sola vez -->
    <div
      v-if="enrollment"
      class="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="enroll-title"
    >
      <div class="modal">
        <h2 id="enroll-title">Código de enrolamiento</h2>
        <p class="muted">{{ machine?.code }}</p>

        <div class="message warning-message" role="alert">
          <i aria-hidden="true" class="pi pi-exclamation-triangle"></i>
          <div>
            <strong>Este código se muestra una sola vez</strong>
            <p>Si lo pierdes, tendrás que generar otro.</p>
          </div>
        </div>

        <code class="code-box" data-test="enroll-code">{{ enrollment.code }}</code>
        <p class="muted">Vence: {{ formatDate(enrollment.expires_at) }}</p>

        <div class="modal-actions">
          <button class="secondary-button" type="button" data-test="copy-code" @click="copyCode">
            <i aria-hidden="true" :class="copied ? 'pi pi-check' : 'pi pi-copy'"></i>
            {{ copied ? 'Copiado' : 'Copiar código' }}
          </button>
          <button class="primary-button" type="button" data-test="close-code" @click="closeCode">
            Ya guardé el código
          </button>
        </div>
      </div>
    </div>

    <!-- Confirmaciones -->
    <div
      v-if="confirming"
      class="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
    >
      <div class="modal">
        <h2 id="confirm-title">
          {{
            confirming === 'revoke' ? '¿Revocar la clave del equipo?' : '¿Deshabilitar el equipo?'
          }}
        </h2>

        <div class="message error-message">
          <i aria-hidden="true" class="pi pi-exclamation-circle"></i>
          <div>
            <strong>Esta acción queda auditada</strong>
            <p v-if="confirming === 'revoke'">
              La clave actual dejará de ser válida. Para volver a conectar {{ machine?.code }},
              genera un código nuevo y enrólalo.
            </p>
            <p v-else>
              {{ machine?.code }} dejará de registrar accesos, se cancelarán sus retos pendientes y
              se cerrará su sesión abierta.
            </p>
          </div>
        </div>

        <div class="modal-actions">
          <button
            class="secondary-button"
            type="button"
            data-test="cancel"
            @click="confirming = null"
          >
            Cancelar
          </button>
          <button class="danger-button" type="button" data-test="confirm" @click="runConfirmed">
            {{ confirming === 'revoke' ? 'Revocar clave' : 'Deshabilitar' }}
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.detail-page {
  display: flex;
  flex-direction: column;
  gap: 22px;
  color: var(--text);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

h1 {
  margin: 0 0 5px;
  font-size: 27px;
}

h2 {
  margin: 0;
  font-size: 17px;
}

.page-header p,
.muted {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.primary-button,
.secondary-button,
.danger-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  min-height: 40px;
  padding: 0 16px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
}

.primary-button {
  color: #ffffff;
  background: var(--primary-solid);
  border: 1px solid transparent;
}

.secondary-button {
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
}

.danger-button {
  color: var(--danger);
  background: transparent;
  border: 1px solid var(--danger);
}

.primary-button:hover:not(:disabled),
.secondary-button:hover:not(:disabled) {
  opacity: 0.9;
}

.danger-button:hover:not(:disabled) {
  background: var(--danger-bg);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 18px;
  align-items: start;
}

.side-column,
.stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.stack {
  gap: 10px;
}

.card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 14px;
  margin: 0;
}

.facts dt {
  color: var(--muted);
  font-size: 11px;
}

.facts dd {
  margin: 3px 0 0;
  font-size: 13px;
  font-weight: 600;
}

.config-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.config-form label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
}

.config-form select {
  min-height: 40px;
  padding: 0 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 7px;
  font-size: 13px;
}

.config-form select:focus {
  outline: none;
  border: 2px solid var(--primary);
}

.field-hint {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
}

.form-actions {
  display: flex;
  gap: 10px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 999px;
  background: var(--hover);
  font-size: 11px;
  font-weight: 600;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--muted);
}

.chip.active .dot,
.chip.online .dot {
  background: var(--success);
}

.chip.pending_enrollment .dot {
  background: var(--warning);
}

.chip.disabled .dot {
  background: var(--danger);
}

.message {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 15px;
  border-radius: 8px;
  font-size: 13px;
}

.message p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--text);
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

.warning-message {
  color: var(--warning);
  background: var(--warning-bg);
  border: 1px solid var(--warning);
}

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

.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(0, 0, 0, 0.5);
}

.modal {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: min(440px, 100%);
  padding: 22px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.code-box {
  display: block;
  padding: 14px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  background: var(--inner);
  font-size: 22px;
  letter-spacing: 0.12em;
  text-align: center;
  user-select: all;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 900px) {
  .detail-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
