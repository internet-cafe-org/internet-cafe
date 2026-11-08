<script setup lang="ts">
import { reactive, ref } from 'vue'

interface Cuenta {
  nombre: string
  correo: string
  codigo: string
}

const cuenta: Cuenta = {
  nombre: 'Estudiante de ejemplo',
  correo: 'estudiante@example.edu',
  codigo: '••••••42',
}

const form = reactive({
  actual: '',
  nueva: '',
  confirmar: '',
})

const infoMessage = ref('')
const errorMessage = ref('')

function cambiarContrasena() {
  infoMessage.value = ''
  errorMessage.value = ''

  if (
    !form.actual.trim() ||
    !form.nueva.trim() ||
    !form.confirmar.trim()
  ) {
    errorMessage.value = 'Completa todos los campos de contraseña.'
    return
  }

  if (form.nueva !== form.confirmar) {
    errorMessage.value = 'Las contraseñas nuevas no coinciden.'
    return
  }

  if (form.nueva.length < 8) {
    errorMessage.value =
      'La nueva contraseña debe tener al menos 8 caracteres.'
    return
  }

  infoMessage.value =
    'Los campos se validaron correctamente, pero el cambio de contraseña todavía no está conectado al servicio.'
}

function cerrarSesionWeb() {
  infoMessage.value =
    'El cierre de sesión web todavía no está conectado al servicio.'
}
</script>

<template>
  <main class="view">
    <h1 class="title">Mi perfil</h1>

    <div class="card">
      <h2>Datos de la cuenta</h2>

      <div class="fields">
        <div class="field">
          <label for="nombre">Nombre completo</label>
          <input
            id="nombre"
            class="ro"
            :value="cuenta.nombre"
            readonly
          />
          <p class="ro-text">{{ cuenta.nombre }}</p>
        </div>

        <div class="field">
          <label for="correo">Correo institucional</label>
          <input
            id="correo"
            class="ro"
            :value="cuenta.correo"
            readonly
          />
          <p class="ro-text">{{ cuenta.correo }}</p>
        </div>

        <div class="field">
          <label for="codigo">Código estudiantil</label>
          <input
            id="codigo"
            class="ro"
            :value="cuenta.codigo"
            readonly
          />
          <p class="ro-text">{{ cuenta.codigo }}</p>
        </div>
      </div>

      <form class="pass" @submit.prevent="cambiarContrasena">
        <h2>Cambiar contraseña</h2>

        <div class="field">
          <label for="actual">Contraseña actual</label>
          <input
            id="actual"
            v-model="form.actual"
            type="password"
            autocomplete="current-password"
            required
          />
        </div>

        <div class="field">
          <label for="nueva">Nueva contraseña</label>
          <input
            id="nueva"
            v-model="form.nueva"
            type="password"
            autocomplete="new-password"
            minlength="8"
            required
          />
        </div>

        <div class="field">
          <label for="confirmar">Confirmar nueva contraseña</label>
          <input
            id="confirmar"
            v-model="form.confirmar"
            type="password"
            autocomplete="new-password"
            minlength="8"
            required
          />
        </div>

        <div v-if="errorMessage" class="feedback error" role="alert">
          <i class="pi pi-exclamation-circle"></i>
          {{ errorMessage }}
        </div>

        <div v-if="infoMessage" class="feedback" role="status">
          <i class="pi pi-info-circle"></i>
          {{ infoMessage }}
        </div>

        <button class="btn change" type="submit">
          Cambiar contraseña
        </button>
      </form>

      <button
        class="btn logout"
        type="button"
        @click="cerrarSesionWeb"
      >
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

        Cerrar sesión web
      </button>

      <aside class="warn" role="note">
        <svg
          viewBox="0 0 24 24"
          width="20"
          height="20"
          fill="none"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path
            d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z"
          />
          <path d="M12 9v4M12 17h.01" />
        </svg>

        <div>
          <strong>Aviso</strong>
          <p>
            Cerrar sesión web no termina el acceso que pueda seguir activo
            en un computador.
          </p>
        </div>
      </aside>
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

h2 {
  font-size: 1.1rem;
  font-weight: 700;
  margin: 0 0 1rem;
}

.fields {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.field {
  display: grid;
  gap: 0.35rem;
  margin-bottom: 0.9rem;
}

.fields .field {
  margin-bottom: 0;
}

label {
  font-size: 0.8rem;
  font-weight: 600;
}

input {
  width: 100%;
  box-sizing: border-box;
  font: inherit;
  font-size: 0.85rem;
  color: var(--c-text);
  background: var(--c-input);
  border: 1px solid var(--c-input-border);
  border-radius: 6px;
  padding: 0.7rem 0.75rem;
}

.ro-text {
  display: none;
  margin: 0;
  font-size: 0.85rem;
}

.pass {
  border: 1px solid var(--c-card-border);
  border-radius: 10px;
  padding: 1.25rem;
  margin-bottom: 1.25rem;
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

.btn:focus-visible,
input:focus-visible {
  outline: 2px solid var(--c-link);
  outline-offset: 2px;
}

.change {
  font-size: 0.85rem;
  padding: 0.65rem 1.1rem;
}

.logout {
  margin-bottom: 1.25rem;
}

.feedback {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  margin-bottom: 0.9rem;
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

.warn {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
  background: var(--c-warn-bg);
  border-radius: 8px;
  padding: 0.9rem 1rem;
  font-size: 0.85rem;
}

.warn svg {
  flex: none;
  stroke: var(--c-warn);
}

.warn p {
  margin: 0.15rem 0 0;
}

@media (max-width: 767px) {
  .fields {
    grid-template-columns: 1fr;
    gap: 0.75rem;
  }

  .ro {
    display: none;
  }

  .ro-text {
    display: block;
  }

  .change,
  .logout {
    width: 100%;
  }
}
</style>