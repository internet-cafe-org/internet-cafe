<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  endMySession,
  getActiveSession,
  getRecentSessions,
  type MySession,
} from '@/services/mySessions'
import { formatDateTime } from '@/utils/dateTime'

const router = useRouter()

/** RF-EST-01: la pantalla de inicio muestra los últimos 3 accesos. */
const ULTIMOS_ACCESOS = 3

interface Sesion {
  id: string
  equipo: string
  sala: string
  inicio: string
}

interface AccesoReciente {
  id: string
  equipo: string
  sala: string
  fecha: string
}

interface Paso {
  icon: 'monitor' | 'phone' | 'check'
  texto: string
}

const sesion = ref<Sesion | null>(null)
const ultimos = ref<AccesoReciente[]>([])
const cargando = ref(true)
const loadFailed = ref(false)
const terminando = ref(false)
const infoMessage = ref('')
const infoIsError = ref(false)

const pasos: Paso[] = [
  {
    icon: 'monitor',
    texto: 'Busca el código QR en la pantalla del computador.',
  },
  {
    icon: 'phone',
    texto: 'Escanéalo con la cámara de tu celular.',
  },
  {
    icon: 'check',
    texto: 'Revisa los datos y confirma tu acceso.',
  },
]

function showMessage(text: string, isError: boolean) {
  infoMessage.value = text
  infoIsError.value = isError
}

function toSesion(s: MySession): Sesion {
  return {
    id: s.id,
    equipo: s.machine_code,
    sala: s.lab,
    inicio: formatDateTime(s.started_at),
  }
}

/** Pide uno más y descarta la sesión activa para no repetirla en "Últimos accesos". */
function toAccesos(items: MySession[], activeId?: string): AccesoReciente[] {
  return items
    .filter((s) => s.id !== activeId)
    .slice(0, ULTIMOS_ACCESOS)
    .map((s) => ({
      id: s.id,
      equipo: s.machine_code,
      sala: s.lab,
      fecha: formatDateTime(s.started_at),
    }))
}

async function cargar() {
  cargando.value = true
  loadFailed.value = false
  infoMessage.value = ''

  try {
    const [activa, recientes] = await Promise.all([
      getActiveSession(),
      getRecentSessions(ULTIMOS_ACCESOS + 1),
    ])
    sesion.value = activa ? toSesion(activa) : null
    ultimos.value = toAccesos(recientes, activa?.id)
  } catch {
    loadFailed.value = true
    showMessage(
      'No pudimos cargar tu información. Revisa tu conexión e inténtalo de nuevo.',
      true,
    )
  } finally {
    cargando.value = false
  }
}

async function terminarAcceso() {
  if (!sesion.value || terminando.value) return

  terminando.value = true
  infoMessage.value = ''

  try {
    await endMySession(sesion.value.id)
  } catch {
    showMessage('No pudimos terminar tu acceso. Revisa tu conexión e inténtalo de nuevo.', true)
    terminando.value = false
    return
  }

  sesion.value = null
  showMessage('Terminaste tu acceso. El equipo volverá a mostrar el QR en hasta 1 minuto.', false)

  // El acceso recién cerrado pasa a "Últimos accesos". Si falla, el cierre ya se hizo.
  try {
    ultimos.value = toAccesos(await getRecentSessions(ULTIMOS_ACCESOS))
  } catch {
    // Se conserva la lista anterior.
  } finally {
    terminando.value = false
  }
}

function verHistorial() {
  void router.push({ name: 'history' })
}

onMounted(cargar)
</script>

<template>
  <main class="view">
    <h1 class="title">Inicio</h1>
    <p class="subtitle">Bienvenido a tu portal de acceso universitario</p>

    <div v-if="infoMessage" class="feedback" :role="infoIsError ? 'alert' : 'status'">
      <i class="pi pi-info-circle"></i>
      <span>{{ infoMessage }}</span>
      <button v-if="loadFailed" class="link" type="button" @click="cargar">Reintentar</button>
    </div>

    <p v-if="cargando" class="subtitle" role="status">Cargando tu información…</p>

    <template v-else-if="!loadFailed">
      <div class="top">
        <article v-if="sesion" class="card">
          <header class="card-head">
            <h2>Mi sesión actual</h2>

            <span class="badge">
              <i class="dot"></i>
              Acceso activo
            </span>
          </header>

          <!-- Escritorio -->
          <dl class="info">
            <div>
              <dt>Equipo</dt>
              <dd>{{ sesion.equipo }}</dd>
            </div>

            <div>
              <dt>Sala</dt>
              <dd>{{ sesion.sala }}</dd>
            </div>

            <div>
              <dt>Fecha y hora de inicio</dt>
              <dd>{{ sesion.inicio }}</dd>
            </div>
          </dl>

          <p class="hint">Cierra tu sesión desde aquí cuando termines de usar el computador.</p>

          <!-- Móvil -->
          <div class="info-mobile">
            <strong>{{ sesion.equipo }}</strong>
            <span>{{ sesion.sala }}</span>
            <span>Inicio: {{ sesion.inicio }}</span>
          </div>

          <button class="btn block" type="button" :disabled="terminando" @click="terminarAcceso">
            <svg
              viewBox="0 0 24 24"
              width="18"
              height="18"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <path d="m16 17 5-5-5-5" />
              <path d="M21 12H9" />
            </svg>

            Terminar acceso
          </button>
        </article>

        <article class="card">
          <h2>¿Cómo registrar un acceso?</h2>

          <ul class="steps">
            <li v-for="paso in pasos" :key="paso.icon">
              <span class="ico">
                <svg
                  v-if="paso.icon === 'monitor'"
                  viewBox="0 0 24 24"
                  width="18"
                  height="18"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <rect x="2" y="3" width="20" height="14" rx="2" />
                  <path d="M8 21h8M12 17v4" />
                </svg>

                <svg
                  v-else-if="paso.icon === 'phone'"
                  viewBox="0 0 24 24"
                  width="18"
                  height="18"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <rect x="7" y="2" width="10" height="20" rx="2" />
                  <path d="M11 18h2" />
                </svg>

                <svg
                  v-else
                  viewBox="0 0 24 24"
                  width="18"
                  height="18"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path d="M21.8 10A10 10 0 1 1 17 3.3" />
                  <path d="m9 11 3 3L22 4" />
                </svg>
              </span>

              <span>{{ paso.texto }}</span>
            </li>
          </ul>
        </article>
      </div>

      <article class="card recents">
        <header class="card-head">
          <h2>Últimos accesos</h2>

          <button class="link" type="button" @click="verHistorial">Ver historial completo</button>
        </header>

        <p v-if="ultimos.length === 0" class="empty">
          Aún no tienes accesos. Cuando registres el primero, aparecerá aquí.
        </p>

        <ul v-else class="list">
          <li v-for="acceso in ultimos" :key="acceso.id">
            <span>
              <strong>{{ acceso.equipo }}</strong>
              <small>{{ acceso.sala }}</small>
            </span>

            <time>{{ acceso.fecha }}</time>
          </li>
        </ul>
      </article>
    </template>
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
  --c-icon-bg: var(--hover, #e8effc);
  --c-ok-bg: var(--success-bg, #dcfce7);
  --c-ok: var(--success, #15803d);

  /* Solo se usan en Perfil */
  --c-input: var(--inner, #f8fafc);
  --c-input-border: var(--border, #e2e8f0);
  --c-warn-bg: var(--warning-bg, #fef6e4);
  --c-warn: var(--warning, #d97706);
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

.subtitle {
  color: var(--c-muted);
  margin: 0 0 1.25rem;
}

.card {
  background: var(--c-card);
  border: 1px solid var(--c-card-border);
  border-radius: 12px;
  padding: 1.25rem;
}

.feedback {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  margin-bottom: 1rem;
  padding: 0.85rem 1rem;
  border: 1px solid var(--c-card-border);
  border-radius: 8px;
  color: var(--c-muted);
  background: var(--c-row-alt);
  font-size: 0.8rem;
}

.feedback .link {
  margin-left: auto;
}

.top {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-bottom: 1rem;
}

h2 {
  font-size: 1rem;
  font-weight: 700;
  margin: 0;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: var(--c-ok-bg);
  color: var(--c-ok);
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.25rem 0.6rem;
  border-radius: 999px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.info {
  margin: 0;
  display: grid;
  gap: 0.6rem;
}

.info > div {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  font-size: 0.85rem;
}

.info dt {
  color: var(--c-muted);
}

.info dd {
  margin: 0;
  font-weight: 500;
  text-align: right;
}

.hint {
  color: var(--c-muted);
  font-size: 0.8rem;
  margin: 0.75rem 0 0.5rem;
}

.info-mobile {
  display: none;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border: 0;
  border-radius: 8px;
  background: var(--c-primary);
  color: var(--c-primary-text);
  font: inherit;
  font-weight: 600;
  padding: 0.65rem 1rem;
  cursor: pointer;
}

.btn:hover {
  filter: brightness(1.08);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  filter: none;
}

.block {
  width: 100%;
  margin-top: 0.5rem;
}

.link {
  background: none;
  border: 0;
  color: var(--c-link);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
}

.btn:focus-visible,
.link:focus-visible {
  outline: 2px solid var(--c-link);
  outline-offset: 2px;
}

.steps,
.list {
  list-style: none;
  margin: 0.75rem 0 0;
  padding: 0;
  display: grid;
  gap: 0.6rem;
}

.steps li {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: var(--c-row);
  border-radius: 8px;
  padding: 0.75rem;
  font-size: 0.8rem;
}

.ico {
  flex: none;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--c-icon-bg);
  color: var(--c-primary);
}

.list {
  gap: 0.35rem;
  margin-top: 0;
}

.list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  background: var(--c-row);
  border-radius: 6px;
  padding: 0.45rem 0.75rem;
  font-size: 0.85rem;
}

.list small {
  color: var(--c-muted);
  margin-left: 0.6rem;
  font-size: 0.75rem;
}

.list time {
  color: var(--c-muted);
  font-size: 0.8rem;
}

.empty {
  color: var(--c-muted);
  font-size: 0.85rem;
  margin: 0;
}

@media (max-width: 767px) {
  .top {
    grid-template-columns: 1fr;
  }

  .info,
  .hint {
    display: none;
  }

  .info-mobile {
    display: grid;
    gap: 0.25rem;
    margin-bottom: 0.75rem;
    font-size: 0.85rem;
  }

  .info-mobile strong {
    font-size: 0.95rem;
  }

  .steps li {
    background: none;
    padding: 0;
    font-size: 0.95rem;
  }

  .list li {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.15rem;
  }
}
</style>
