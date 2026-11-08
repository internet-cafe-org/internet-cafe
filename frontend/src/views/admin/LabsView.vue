
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'

type Lab = components['schemas']['Lab']
type Machine = components['schemas']['Machine']
type ViewMode = 'list' | 'create' | 'edit'

const view = ref<ViewMode>('list')
const labs = ref<Lab[]>([])
const machines = ref<Machine[]>([])

const loading = ref(false)
const loadFailed = ref(false)
const saving = ref(false)

const editingLab = ref<Lab | null>(null)
const labName = ref('')
const building = ref('')

const nameError = ref('')
const formError = ref<{ title: string; text: string } | null>(null)
const successMessage = ref('')

const totalLabs = computed(() => labs.value.length)

const uniqueBlocks = computed(() => {
  const blocks = labs.value
    .map((lab) => lab.building?.trim())
    .filter((block): block is string => Boolean(block))

  return new Set(blocks).size
})

const totalAssignedEquipment = computed(
  () => machines.value.filter((machine) => Boolean(machine.lab_id)).length,
)

const isEdit = computed(() => view.value === 'edit')

function equipmentCount(labId: string): number {
  return machines.value.filter((machine) => machine.lab_id === labId).length
}

function clearForm() {
  nameError.value = ''
  formError.value = null
}

async function loadLabs() {
  loading.value = true
  loadFailed.value = false

  try {
    const [labsResult, machinesResult] = await Promise.all([
      api.GET('/api/v1/admin/labs', {
        params: {
          query: {
            limit: 100,
            offset: 0,
          },
        },
      }),
      api.GET('/api/v1/admin/machines', {
        params: {
          query: {
            limit: 100,
            offset: 0,
          },
        },
      }),
    ])

    if (labsResult.error || machinesResult.error) {
      throw new Error('No fue posible cargar la información.')
    }

    labs.value = labsResult.data?.items ?? []
    machines.value = machinesResult.data?.items ?? []
  } catch {
    loadFailed.value = true
    labs.value = []
    machines.value = []
  } finally {
    loading.value = false
  }
}

function goList() {
  view.value = 'list'
  editingLab.value = null
  labName.value = ''
  building.value = ''
  clearForm()
}

function openCreate() {
  successMessage.value = ''
  editingLab.value = null
  labName.value = ''
  building.value = ''
  clearForm()
  view.value = 'create'
}

function openEdit(lab: Lab) {
  successMessage.value = ''
  editingLab.value = lab
  labName.value = lab.name
  building.value = lab.building ?? ''
  clearForm()
  view.value = 'edit'
}

async function saveLab() {
  clearForm()

  const name = labName.value.trim()

  if (!name) {
    nameError.value =
      'El nombre de la sala es obligatorio. Ingresa un nombre para continuar.'
    return
  }

  const duplicated = labs.value.some(
    (lab) =>
      lab.id !== editingLab.value?.id &&
      lab.name.trim().toLocaleLowerCase() === name.toLocaleLowerCase(),
  )

  if (duplicated) {
    nameError.value =
      'Ya existe una sala con este nombre. Ingresa un nombre diferente.'
    return
  }

  saving.value = true

  const body = {
    name,
    building: building.value.trim() || null,
  }

  try {
    // La API todavía no tiene una operación para editar salas.
    // En esta vista de demostración los cambios se aplican localmente.
    if (isEdit.value && editingLab.value) {
      const index = labs.value.findIndex(
        (lab) => lab.id === editingLab.value?.id,
      )

      if (index !== -1) {
        labs.value[index] = {
          ...editingLab.value,
          ...body,
        }
      }

      goList()
      successMessage.value =
        'Cambios aplicados en esta demostración. La API todavía no permite guardar ediciones de salas.'
      return
    }

    // La creación sí está disponible en el contrato de la API.
    const result = await api.POST('/api/v1/admin/labs', {
      body,
    })

    if (result.error) {
      const status = result.response?.status

      if (status === 409) {
        nameError.value =
          'Ya existe una sala con este nombre. Ingresa un nombre diferente.'

        formError.value = {
          title: 'No se pudo guardar la sala',
          text: 'El nombre ya está registrado. Corrígelo e inténtalo nuevamente.',
        }
      } else if (status === 422) {
        formError.value = {
          title: 'Datos no válidos',
          text: 'Revisa la información ingresada e inténtalo nuevamente.',
        }
      } else {
        formError.value = {
          title: 'No se pudo guardar la sala',
          text: 'El servicio no está disponible temporalmente. Tus datos se conservaron en el formulario.',
        }
      }

      return
    }

    goList()
    await loadLabs()

    successMessage.value = 'La sala se registró correctamente.'
  } catch {
    formError.value = {
      title: 'No se pudo guardar la sala',
      text: 'No hay conexión con el servicio. Tus datos se conservaron en el formulario; puedes intentarlo nuevamente.',
    }
  } finally {
    saving.value = false
  }
}

onMounted(loadLabs)
</script>

<template>
  <main class="labs-page">
    <!-- ============ VISTA: LISTA ============ -->
    <template v-if="view === 'list'">
      <header class="page-header">
        <div>
          <h1>Salas</h1>
          <p>Organiza los espacios y su ubicación en el campus.</p>
        </div>

        <button class="primary-button" type="button" @click="openCreate">
          <i class="pi pi-plus"></i>
          Nueva sala
        </button>
      </header>

      <div v-if="successMessage" class="message success-message" role="status">
        <i class="pi pi-check-circle"></i>
        {{ successMessage }}
      </div>

      <section class="summary-grid">
        <article class="summary-card">
          <div>
            <span>Salas registradas</span>
            <strong>{{ loadFailed || loading ? '—' : totalLabs }}</strong>
          </div>
          <i class="pi pi-table summary-icon"></i>
        </article>

        <article class="summary-card">
          <div>
            <span>Bloques / edificios</span>
            <strong>{{ loadFailed || loading ? '—' : uniqueBlocks }}</strong>
          </div>
          <i class="pi pi-building summary-icon"></i>
        </article>

        <article class="summary-card">
          <div>
            <span>Equipos asignados</span>
            <strong>
              {{ loadFailed || loading ? '—' : totalAssignedEquipment }}
            </strong>
          </div>
          <i class="pi pi-desktop summary-icon"></i>
        </article>
      </section>

      <section class="table-card">
        <div class="section-heading">
          <h2>Todas las salas</h2>

          <span class="table-subinfo">
            {{ loadFailed ? 'Sin datos disponibles' : `${totalLabs} salas` }}
            · RF-ADM-01
          </span>
        </div>

        <div v-if="loading" class="empty-state">
          <i class="pi pi-spin pi-spinner"></i>
          <p>Cargando salas...</p>
        </div>

        <div v-else-if="loadFailed" class="empty-state">
          <i class="pi pi-wifi"></i>
          <strong>No se pudieron cargar las salas</strong>
          <p>
            Se perdió la conexión con el servicio. Comprueba tu conexión y
            vuelve a intentarlo.
          </p>

          <button
            class="primary-button"
            type="button"
            @click="loadLabs"
          >
            <i class="pi pi-refresh"></i>
            Reintentar
          </button>
        </div>

        <div v-else-if="labs.length === 0" class="empty-state">
          <i class="pi pi-building"></i>
          <strong>Aún no hay salas</strong>
          <p>Crea la primera sala para organizar tus equipos.</p>

          <button
            class="primary-button"
            type="button"
            @click="openCreate"
          >
            <i class="pi pi-plus"></i>
            Crear primera sala
          </button>
        </div>

        <div v-else class="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Nombre de sala</th>
                <th>Bloque / edificio</th>
                <th>Equipos asignados</th>
                <th class="text-right">Acciones</th>
              </tr>
            </thead>

            <tbody>
              <tr v-for="lab in labs" :key="lab.id">
                <td>
                  <strong>{{ lab.name }}</strong>
                </td>

                <td class="text-muted">
                  {{ lab.building || '—' }}
                </td>

                <td>
                  {{
                    equipmentCount(lab.id)
                      ? `${equipmentCount(lab.id)} equipo${equipmentCount(lab.id) > 1 ? 's' : ''}`
                      : 'Sin equipos'
                  }}
                </td>

                <td class="text-right">
                  <button
                    class="edit-action-button"
                    type="button"
                    @click="openEdit(lab)"
                  >
                    <i class="pi pi-pencil"></i>
                    <span>Editar</span>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <footer class="footer-note">
        {{
          loadFailed
            ? 'No se pudieron consultar los datos. Tus salas no se han eliminado.'
            : 'El nombre identifica cada sala y debe ser único en toda la universidad.'
        }}
      </footer>
    </template>

    <!-- ============ VISTA: NUEVA / EDITAR ============ -->
    <template v-else>
      <header class="page-header">
        <div>
          <h1>{{ isEdit ? 'Editar sala' : 'Nueva sala' }}</h1>

          <p v-if="isEdit">
            Actualiza la información de {{ editingLab?.name }}.
            Los equipos mantienen su asignación.
          </p>

          <p v-else>
            Crea un espacio para asignar tus equipos de la universidad.
          </p>
        </div>

        <button
          class="secondary-button"
          type="button"
          @click="goList"
        >
          <i class="pi pi-arrow-left"></i>
          Volver a salas
        </button>
      </header>

      <div class="form-layout">
        <section class="form-card">
          <div class="section-heading">
            <div>
              <h2>Información de la sala</h2>
              <p class="hint-text">Los campos con * son obligatorios.</p>
            </div>
          </div>

          <div v-if="formError" class="message error-message" role="alert">
            <i class="pi pi-exclamation-circle"></i>

            <div>
              <strong>{{ formError.title }}</strong>
              <p>{{ formError.text }}</p>
            </div>
          </div>

          <form class="lab-form" novalidate @submit.prevent="saveLab">
            <label>
              Nombre de sala *

              <input
                v-model="labName"
                type="text"
                maxlength="80"
                placeholder="Ingresa el nombre de la sala"
                :class="{ 'input-error': nameError }"
                @input="nameError = ''"
              />

              <span v-if="nameError" class="field-error-text">
                {{ nameError }}
              </span>

              <span class="field-hint">
                Nombre corto y único en la universidad · Máximo 80 caracteres
              </span>
            </label>

            <label>
              Bloque / edificio

              <input
                v-model="building"
                type="text"
                maxlength="80"
                placeholder="Ingresa el bloque o edificio"
              />

              <span class="field-hint">
                Opcional · Máximo 80 caracteres
              </span>
            </label>

            <div class="form-actions">
              <button
                class="primary-button"
                type="submit"
                :disabled="saving"
              >
                <i
                  :class="
                    saving
                      ? 'pi pi-spin pi-spinner'
                      : isEdit
                        ? 'pi pi-check'
                        : 'pi pi-check'
                  "
                ></i>

                {{
                  saving
                    ? 'Guardando...'
                    : isEdit
                      ? 'Guardar cambios'
                      : 'Guardar'
                }}
              </button>

              <button
                class="ghost-button"
                type="button"
                @click="goList"
              >
                Cancelar
              </button>
            </div>
          </form>
        </section>

        <aside class="side-card">
          <h2>Una ubicación clara</h2>

          <i class="pi pi-building side-icon"></i>

          <p>
            Usa un nombre breve y reconocible, por ejemplo «Sala 1», y un
            bloque para facilitar su ubicación.
          </p>

          <div class="info-box">
            <i class="pi pi-info-circle"></i>

            <div>
              <strong>Nombres sin duplicados</strong>
              <p>
                Cada sala debe tener un nombre diferente. RF-ADM-01
              </p>
            </div>
          </div>

          <div v-if="isEdit && editingLab" class="linked-equipment">
            <span>Equipos vinculados</span>

            <strong>
              {{
                equipmentCount(editingLab.id)
                  ? `${equipmentCount(editingLab.id)} equipo${equipmentCount(editingLab.id) > 1 ? 's' : ''}`
                  : 'Sin equipos'
              }}
            </strong>
          </div>

          <div v-if="isEdit" class="info-box demo-info">
            <i class="pi pi-info-circle"></i>

            <div>
              <strong>Modo demostración</strong>
              <p>
                Los cambios de edición solo se reflejan temporalmente en
                esta pantalla. La API todavía no permite guardar ediciones.
              </p>
            </div>
          </div>
        </aside>
      </div>

      <footer class="footer-note">
        El nombre identifica cada sala y debe ser único en toda la universidad.
      </footer>
    </template>
  </main>
</template>

<style scoped>
.labs-page {
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
}

h2 {
  margin: 0;
  font-size: 17px;
}

.page-header p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.primary-button,
.secondary-button,
.ghost-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  min-height: 40px;
  padding: 0 16px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  font-size: 13px;
}

.primary-button {
  color: #ffffff;
  background: var(--primary);
  border: 1px solid transparent;
  transition: opacity 0.2s;
}

.primary-button:hover {
  opacity: 0.9;
}

.secondary-button {
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
}

.secondary-button:hover {
  background: var(--hover);
}

.ghost-button {
  color: var(--text);
  background: transparent;
  border: 1px solid transparent;
}

.ghost-button:hover {
  background: var(--hover);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.form-card,
.table-card,
.summary-card,
.side-card {
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}

/* ---- Formulario ---- */
.form-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 18px;
  align-items: start;
}

.hint-text {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12px;
}

.lab-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
  margin-top: 18px;
}

.lab-form label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.lab-form input {
  width: 100%;
  min-height: 40px;
  padding: 0 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 7px;
  font-size: 13px;
}

.lab-form input:focus {
  outline: none;
  border: 2px solid var(--primary);
}

.input-error,
.lab-form input.input-error {
  border-color: var(--danger);
}

.field-error-text {
  color: var(--danger);
  font-weight: 500;
}

.field-hint {
  color: var(--muted);
  font-weight: 400;
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* ---- Panel lateral ---- */
.side-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.side-card p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

.side-icon {
  color: var(--primary);
  font-size: 20px;
}

.info-box {
  display: flex;
  gap: 10px;
  padding: 12px;
  background: var(--hover);
  border-radius: 8px;
  font-size: 12px;
}

.info-box i {
  color: var(--primary);
  margin-top: 2px;
}

.info-box strong {
  display: block;
  margin-bottom: 2px;
}

.linked-equipment span {
  display: block;
  color: var(--muted);
  font-size: 11px;
}

.linked-equipment strong {
  font-size: 12px;
}

.demo-info {
  border: 1px dashed var(--border);
}

/* ---- Mensajes ---- */
.message {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 15px;
  margin-top: 16px;
  border-radius: 8px;
  font-size: 13px;
}

.message p {
  margin: 2px 0 0;
  font-size: 12px;
}

.error-message {
  color: var(--danger);
  background: var(--danger-bg);
  border: 1px solid var(--danger);
}

.error-message p {
  color: var(--text);
}

.success-message {
  align-items: center;
  margin-top: 0;
  color: var(--success);
  background: var(--success-bg);
  border: 1px solid var(--success);
}

/* ---- Resumen y tabla ---- */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 15px;
}

.summary-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.summary-card span,
.summary-card strong {
  display: block;
}

.summary-card span {
  color: var(--muted);
  font-size: 12px;
}

.summary-card strong {
  margin-top: 4px;
  font-size: 27px;
}

.summary-icon {
  color: var(--primary);
  font-size: 20px;
}

.table-subinfo {
  color: var(--muted);
  font-size: 12px;
}

.table-wrapper {
  width: 100%;
  margin-top: 20px;
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
  padding: 15px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}

.text-muted {
  color: var(--muted);
}

.text-right {
  text-align: right;
}

.edit-action-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: transparent;
  color: var(--primary);
  border: none;
  border-radius: 6px;
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
}

.edit-action-button:hover {
  background: var(--hover);
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

.footer-note {
  color: var(--muted);
  font-size: 11px;
}

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .form-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .page-header,
  .section-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }
}
</style>
