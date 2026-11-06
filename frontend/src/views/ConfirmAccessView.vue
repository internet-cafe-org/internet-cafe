<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AuthLayout from '@/components/AuthLayout.vue'
import { ApiError } from '@/services/auth'
import { takePendingScanToken } from '@/services/pendingScan'
import { claimScan, previewScan, type ScanMachine } from '@/services/scan'

type Failure = 'expired' | 'used' | 'invalid' | 'disabled' | 'busy' | 'error'
type State = 'loading' | 'ready' | 'confirming' | 'success' | Failure

const FAILURES: Record<Failure, { title: string; text: string; action: string }> = {
  expired: {
    title: 'QR vencido',
    text: 'Este código QR venció. Escanea el código nuevo que aparece en el equipo.',
    action: 'Escanear código nuevo',
  },
  used: {
    title: 'QR ya utilizado',
    text: 'Este código QR ya fue utilizado. Escanea el código nuevo del equipo.',
    action: 'Escanear código nuevo',
  },
  invalid: {
    title: 'QR inválido',
    text: 'Este código no es válido o no pertenece al sistema. Escanea el QR que aparece en el equipo.',
    action: 'Volver a escanear',
  },
  disabled: {
    title: 'Equipo deshabilitado',
    text: 'Este equipo está deshabilitado. Contacta al personal de soporte o utiliza otro equipo.',
    action: 'Escanear otro equipo',
  },
  busy: {
    title: 'Equipo en uso',
    text: 'Este equipo ya tiene una sesión activa. Cierra la sesión en el equipo y vuelve a escanear.',
    action: 'Volver a escanear',
  },
  error: {
    title: 'No pudimos completar el acceso',
    text: 'Inténtalo de nuevo en unos minutos o vuelve a escanear el código.',
    action: 'Volver a escanear',
  },
}

const ERROR_CODES: Record<string, Failure> = {
  CHALLENGE_EXPIRED: 'expired',
  CHALLENGE_ALREADY_USED: 'used',
  CHALLENGE_NOT_FOUND: 'invalid',
  MACHINE_DISABLED: 'disabled',
  MACHINE_BUSY: 'busy',
}

// Contacto de soporte (mailto: o URL). Sin definir, el botón no se muestra.
const supportUrl = String(import.meta.env.VITE_SUPPORT_URL ?? '')

const route = useRoute()
const router = useRouter()

const state = ref<State>('loading')
const machine = ref<ScanMachine | null>(null)
const previousMachineCode = ref<string | null>(null)
const heading = ref<HTMLElement | null>(null)
let token: string | null = null

const failure = computed(() => (state.value in FAILURES ? FAILURES[state.value as Failure] : null))
const isReview = computed(() => state.value === 'ready' || state.value === 'confirming')
const showCard = computed(
  () =>
    machine.value !== null &&
    (isReview.value || state.value === 'success' || state.value === 'disabled'),
)
const lead = computed(() => {
  if (failure.value) return 'No se registró ningún acceso. Revisa el mensaje para continuar.'
  if (state.value === 'success') return 'Ya puedes utilizar el equipo indicado.'
  return 'Revisa los datos del equipo antes de registrar tu acceso.'
})

function toFailure(error: unknown): Failure {
  return error instanceof ApiError ? (ERROR_CODES[error.code] ?? 'error') : 'error'
}

onMounted(async () => {
  // El token llega en el fragmento (/s#token) o lo conservó el login (RF-QR-05).
  token = route.hash.length > 1 ? route.hash.slice(1) : takePendingScanToken()
  // Limpia la URL: el token no debe quedar en la barra de direcciones.
  if (route.hash) await router.replace({ name: 'confirm' })

  if (!token) {
    state.value = 'invalid'
    return
  }
  try {
    const preview = await previewScan(token)
    machine.value = preview.machine
    previousMachineCode.value = preview.active_session?.machine_code ?? null
    state.value = 'ready'
  } catch (error) {
    state.value = toFailure(error)
  }
})

// Lleva el foco al título al cambiar de estado, para lectores de pantalla.
watch(state, async () => {
  await nextTick()
  heading.value?.focus()
})

async function confirm() {
  if (!token || state.value !== 'ready') return
  state.value = 'confirming'
  try {
    const result = await claimScan(token)
    machine.value = result.session.machine
    token = null
    state.value = 'success'
  } catch (error) {
    state.value = toFailure(error)
  }
}

function cancel() {
  token = null
  void router.push({ name: 'home' })
}

function rescan() {
  token = null
  void router.push({ name: 'scan' })
}
</script>

<template>
  <AuthLayout>
    <h1 ref="heading" tabindex="-1">
      {{ state === 'success' ? 'Acceso confirmado' : 'Confirmar acceso' }}
    </h1>
    <p class="auth-lead">{{ lead }}</p>

    <p v-if="state === 'loading'" role="status">Verificando el código QR…</p>

    <div v-if="failure" class="auth-banner auth-banner--error" role="alert">
      <p>
        <strong>{{ failure.title }}</strong>
      </p>
      <p>{{ failure.text }}</p>
    </div>
    <div v-if="state === 'success'" class="auth-banner auth-banner--success" role="status">
      <p>Tu acceso se registró correctamente.</p>
      <p>Sesión activa en {{ machine?.code }}.</p>
    </div>

    <section v-if="showCard && machine" class="machine" aria-label="Datos del equipo">
      <span class="machine__icon pi pi-desktop" aria-hidden="true"></span>
      <div class="machine__data">
        <p class="machine__label">Equipo</p>
        <p class="machine__name">{{ machine.name ?? machine.code }}</p>
        <p class="machine__label">Código del equipo</p>
        <p class="machine__value">{{ machine.code }}</p>
        <p class="machine__label">Sala</p>
        <p class="machine__value">{{ machine.lab }}</p>
      </div>
    </section>

    <div
      v-if="isReview && previousMachineCode"
      class="auth-banner auth-banner--warning"
      role="status"
    >
      <p>
        <strong>Cambio de sesión activa</strong>
      </p>
      <p>
        Tienes una sesión activa en {{ previousMachineCode }}. Al confirmar, se cerrará esa sesión y
        se iniciará una nueva en este equipo.
      </p>
    </div>

    <div v-if="isReview" class="actions">
      <button class="auth-button" type="button" :disabled="state === 'confirming'" @click="confirm">
        {{ state === 'confirming' ? 'Confirmando…' : 'Confirmar' }}
      </button>
      <button class="auth-button auth-button--secondary" type="button" @click="cancel">
        Cancelar
      </button>
      <p class="note">
        Solo se registra el acceso al confirmar. Cancelar no crea un acceso ni cierra tu sesión
        previa.
      </p>
    </div>

    <div v-else-if="failure" class="actions">
      <a
        v-if="state === 'disabled' && supportUrl"
        class="auth-button actions__link"
        :href="supportUrl"
      >
        Contactar a soporte
      </a>
      <button
        class="auth-button"
        :class="{ 'auth-button--secondary': state === 'disabled' && supportUrl }"
        type="button"
        @click="rescan"
      >
        {{ failure.action }}
      </button>
      <p class="note">Tu sesión previa, si existe, no se ha modificado.</p>
    </div>

    <p v-else-if="state === 'success'" class="note">
      Si tenías una sesión activa en otro equipo, se cerró al confirmar este acceso.
    </p>
  </AuthLayout>
</template>

<style scoped>
h1:focus {
  outline: none;
}
.machine {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  padding: 16px;
  background: #f5f8fc;
  border: 1px solid #d7e0ec;
  border-radius: 8px;
}
.machine__icon {
  font-size: 20px;
}
.machine__data p {
  margin: 0;
}
.machine__label {
  margin-top: 8px;
  font-size: 12px;
  color: #52647a;
}
.machine__label:first-child {
  margin-top: 0;
}
.machine__name {
  font-size: 18px;
  font-weight: 500;
}
.machine__value {
  font-weight: 700;
}
.actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.actions__link {
  display: flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
}
.auth-button--secondary {
  background: #fff;
  color: #19365c;
  border: 1px solid #d7e0ec;
}
.note {
  margin: 4px 0 0;
  font-size: 12px;
  color: #52647a;
}
</style>
