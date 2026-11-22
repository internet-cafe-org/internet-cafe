<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchMySessions, type StudentSession } from '@/services/me'

const PAGE_SIZE = 20

const sessions = ref<StudentSession[]>([])
const total = ref(0)
const loading = ref(true)
const loadingMore = ref(false)
const errorMessage = ref('')

const hasMore = computed(() => sessions.value.length < total.value)

function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return iso
  }

  const day = String(date.getDate()).padStart(2, '0')
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const year = date.getFullYear()
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')

  return `${day}/${month}/${year} · ${hours}:${minutes}`
}

function formatEnd(session: StudentSession): string {
  if (!session.ended_at) {
    return 'En curso'
  }
  return formatDateTime(session.ended_at)
}

function formatDuration(session: StudentSession): string {
  if (!session.ended_at || session.duration_s == null) {
    return 'En curso'
  }

  if (session.duration_s > 0 && session.duration_s < 60) {
    return 'Menos de 1 min'
  }

  const totalMinutes = Math.max(0, Math.floor(session.duration_s / 60))
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60

  if (hours === 0) {
    return `${minutes} min`
  }
  if (minutes === 0) {
    return `${hours} h`
  }
  return `${hours} h ${minutes} min`
}

async function loadInitial(): Promise<void> {
  loading.value = true
  errorMessage.value = ''

  try {
    const page = await fetchMySessions({ limit: PAGE_SIZE, offset: 0 })
    sessions.value = page.items
    total.value = page.total
  } catch {
    errorMessage.value = 'No pudimos cargar tu historial de accesos. Inténtalo de nuevo.'
  } finally {
    loading.value = false
  }
}

async function cargarMas(): Promise<void> {
  if (loadingMore.value || !hasMore.value) {
    return
  }

  loadingMore.value = true
  errorMessage.value = ''

  try {
    const page = await fetchMySessions({
      limit: PAGE_SIZE,
      offset: sessions.value.length,
    })
    sessions.value = [...sessions.value, ...page.items]
    total.value = page.total
  } catch {
    errorMessage.value = 'No pudimos cargar más registros. Inténtalo de nuevo.'
  } finally {
    loadingMore.value = false
  }
}

onMounted(() => {
  void loadInitial()
})
</script>

<template>
  <main class="view">
    <h1 class="title">Historial de accesos</h1>

    <div class="card panel">
      <p class="note">Solo se muestran tus propios accesos.</p>

      <div v-if="errorMessage" class="feedback error" role="alert">
        <i class="pi pi-exclamation-circle"></i>
        <div class="feedback-body">
          <span>{{ errorMessage }}</span>
          <button
            class="retry"
            type="button"
            @click="sessions.length === 0 ? loadInitial() : cargarMas()"
          >
            Reintentar
          </button>
        </div>
      </div>

      <div v-if="loading" class="state" role="status" aria-live="polite">
        Cargando historial de accesos...
      </div>

      <div v-else-if="sessions.length === 0 && !errorMessage" class="state" role="status">
        Aún no tienes accesos registrados.
      </div>

      <template v-else-if="sessions.length > 0">
        <!-- Escritorio -->
        <div class="scroll table-wrap">
          <table>
            <thead>
              <tr>
                <th>Equipo</th>
                <th>Sala</th>
                <th>Inicio</th>
                <th>Fin</th>
                <th>Duración</th>
              </tr>
            </thead>

            <tbody>
              <tr v-for="session in sessions" :key="session.id">
                <td class="strong">{{ session.machine_code }}</td>
                <td>{{ session.lab }}</td>
                <td>{{ formatDateTime(session.started_at) }}</td>
                <td>{{ formatEnd(session) }}</td>
                <td>{{ formatDuration(session) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Móvil -->
        <div class="scroll cards-wrap">
          <dl v-for="session in sessions" :key="session.id" class="item">
            <div>
              <dt>Equipo</dt>
              <dd class="strong">{{ session.machine_code }}</dd>
            </div>

            <div>
              <dt>Sala</dt>
              <dd>{{ session.lab }}</dd>
            </div>

            <div>
              <dt>Inicio</dt>
              <dd>{{ formatDateTime(session.started_at) }}</dd>
            </div>

            <div>
              <dt>Fin</dt>
              <dd>{{ formatEnd(session) }}</dd>
            </div>

            <div>
              <dt>Duración</dt>
              <dd>{{ formatDuration(session) }}</dd>
            </div>
          </dl>
        </div>

        <footer class="foot">
          <span>Mostrando {{ sessions.length }} de {{ total }} registros</span>

          <button
            v-if="hasMore"
            class="more"
            type="button"
            :disabled="loadingMore"
            @click="cargarMas"
          >
            {{ loadingMore ? 'Cargando...' : 'Cargar más' }}
          </button>
        </footer>
      </template>
    </div>
  </main>
</template>

<style scoped>
.view {
  --c-text: var(--text, #0f172a);
  --c-muted: var(--muted, #64748b);
  --c-card: var(--surface, #ffffff);
  --c-card-border: var(--border, #e2e8f0);
  --c-row: var(--inner, #f1f5f9);
  --c-row-alt: var(--inner, #f8fafc);
  --c-primary: var(--primary, #2563eb);
  --c-primary-text: #ffffff;
  --c-link: var(--primary, #2563eb);
  --c-error-bg: var(--danger-bg, #fee2e2);
  --c-error-border: var(--danger, #fecaca);
  --c-error: var(--danger, #b91c1c);

  color: var(--c-text);
}

.title {
  font-size: 1.5rem;
  font-weight: 700;
  margin: 0 0 0.5rem;
}

.card {
  background: var(--c-card);
  border: 1px solid var(--c-card-border);
  border-radius: 12px;
  padding: 1.25rem;
}

.panel {
  padding: 0;
  overflow: hidden;
}

.note {
  margin: 0;
  padding: 0.9rem 1.25rem;
  font-size: 0.75rem;
  color: var(--c-muted);
  background: var(--c-row-alt);
  border-bottom: 1px solid var(--c-card-border);
}

.state {
  padding: 2rem 1.25rem;
  text-align: center;
  font-size: 0.85rem;
  color: var(--c-muted);
}

.feedback {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  margin: 0.75rem 1.25rem;
  padding: 0.75rem;
  color: var(--c-muted);
  background: var(--c-row-alt);
  border: 1px solid var(--c-card-border);
  border-radius: 8px;
  font-size: 0.8rem;
}

.feedback.error {
  color: var(--c-error);
  background: var(--c-error-bg);
  border-color: var(--c-error-border);
}

.feedback-body {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex: 1;
}

.retry {
  background: none;
  border: 1px solid currentColor;
  color: inherit;
  font: inherit;
  font-weight: 600;
  border-radius: 6px;
  padding: 0.25rem 0.65rem;
  cursor: pointer;
}

.scroll {
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--c-card-border) transparent;
}

.scroll::-webkit-scrollbar {
  width: 6px;
}

.scroll::-webkit-scrollbar-track {
  background: transparent;
}

.scroll::-webkit-scrollbar-thumb {
  background: var(--c-card-border);
  border-radius: 999px;
}

.scroll::-webkit-scrollbar-thumb:hover {
  background: var(--c-muted);
}

.scroll::-webkit-scrollbar-button {
  display: none;
}

.table-wrap {
  max-height: 370px;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}

th {
  text-align: left;
  font-weight: 600;
  padding: 0.75rem 1.25rem;
  position: sticky;
  top: 0;
  background: var(--c-card);
  border-bottom: 1px solid var(--c-card-border);
}

td {
  padding: 0.8rem 1.25rem;
  border-bottom: 1px solid var(--c-card-border);
}

tr:last-child td {
  border-bottom: 0;
}

.strong {
  font-weight: 700;
}

.cards-wrap {
  display: none;
}

.foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--c-card-border);
  font-size: 0.75rem;
  color: var(--c-muted);
}

.more {
  background: none;
  border: 1px solid var(--c-card-border);
  color: var(--c-link);
  font: inherit;
  font-weight: 600;
  border-radius: 8px;
  padding: 0.5rem 1rem;
  cursor: pointer;
}

.more:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.more:focus-visible,
.retry:focus-visible {
  outline: 2px solid var(--c-link);
  outline-offset: 2px;
}

@media (max-width: 767px) {
  .table-wrap {
    display: none;
  }

  .cards-wrap {
    display: grid;
    gap: 0.75rem;
    max-height: 540px;
    padding: 0.75rem;
  }

  .item {
    margin: 0;
    border: 1px solid var(--c-card-border);
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    font-size: 0.75rem;
  }

  .item > div {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.3rem 0;
  }

  .item dt {
    color: var(--c-muted);
  }

  .item dd {
    margin: 0;
    text-align: right;
  }
}
</style>
