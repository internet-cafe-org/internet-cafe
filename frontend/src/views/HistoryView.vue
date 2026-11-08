<script setup lang="ts">
import { ref } from 'vue'

interface Registro {
  equipo: string
  sala: string
  inicio: string
  fin: string
  duracion: string
}

const registros = ref<Registro[]>([
  {
    equipo: 'LAB3-PC12',
    sala: 'Sala 3',
    inicio: '28/10/2026 · 09:00',
    fin: '28/10/2026 · 10:30',
    duracion: '1 h 30 min',
  },
  {
    equipo: 'LAB2-PC08',
    sala: 'Sala 2',
    inicio: '27/10/2026 · 09:00',
    fin: '27/10/2026 · 10:30',
    duracion: '1 h 30 min',
  },
  {
    equipo: 'LAB1-PC05',
    sala: 'Sala 1',
    inicio: '26/10/2026 · 09:00',
    fin: '26/10/2026 · 10:30',
    duracion: '1 h 30 min',
  },
  {
    equipo: 'LAB3-PC04',
    sala: 'Sala 3',
    inicio: '25/10/2026 · 09:00',
    fin: '25/10/2026 · 10:30',
    duracion: '1 h 30 min',
  },
  {
    equipo: 'LAB3-PC16',
    sala: 'Sala 3',
    inicio: '24/10/2026 · 09:00',
    fin: '24/10/2026 · 10:30',
    duracion: '1 h 30 min',
  },
  {
    equipo: 'LAB2-PC12',
    sala: 'Sala 2',
    inicio: '23/10/2026 · 09:00',
    fin: '23/10/2026 · 10:30',
    duracion: '1 h 30 min',
  },
  {
    equipo: 'LAB1-PC08',
    sala: 'Sala 1',
    inicio: '22/10/2026 · 09:00',
    fin: '22/10/2026 · 10:30',
    duracion: '1 h 30 min',
  },
  {
    equipo: 'LAB3-PC05',
    sala: 'Sala 3',
    inicio: '21/10/2026 · 09:00',
    fin: '21/10/2026 · 10:30',
    duracion: '1 h 30 min',
  },
  {
    equipo: 'LAB3-PC04',
    sala: 'Sala 3',
    inicio: '20/10/2026 · 09:00',
    fin: '20/10/2026 · 10:30',
    duracion: '1 h 30 min',
  },
])

const infoMessage = ref('')

function cargarMas() {
  infoMessage.value =
    'La carga de más registros todavía no está conectada al servicio.'
}
</script>

<template>
  <main class="view">
    <h1 class="title">Historial de accesos</h1>

    <div class="card panel">
      <p class="note">Solo se muestran tus propios accesos.</p>

      <div v-if="infoMessage" class="feedback" role="status">
        <i class="pi pi-info-circle"></i>
        {{ infoMessage }}
      </div>

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
            <tr v-for="registro in registros" :key="registro.inicio">
              <td class="strong">{{ registro.equipo }}</td>
              <td>{{ registro.sala }}</td>
              <td>{{ registro.inicio }}</td>
              <td>{{ registro.fin }}</td>
              <td>{{ registro.duracion }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Móvil -->
      <div class="scroll cards-wrap">
        <dl
          v-for="registro in registros"
          :key="registro.inicio"
          class="item"
        >
          <div>
            <dt>Equipo</dt>
            <dd class="strong">{{ registro.equipo }}</dd>
          </div>

          <div>
            <dt>Sala</dt>
            <dd>{{ registro.sala }}</dd>
          </div>

          <div>
            <dt>Inicio</dt>
            <dd>{{ registro.inicio }}</dd>
          </div>

          <div>
            <dt>Fin</dt>
            <dd>{{ registro.fin }}</dd>
          </div>

          <div>
            <dt>Duración</dt>
            <dd>{{ registro.duracion }}</dd>
          </div>
        </dl>
      </div>

      <footer class="foot">
        <span>Mostrando {{ registros.length }} registros</span>

        <button class="more" type="button" @click="cargarMas">
          Cargar más
        </button>
      </footer>
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

.more:focus-visible {
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