<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { QrcodeStream, type DetectedBarcode, type EmittedError } from 'vue-qrcode-reader'

import AuthLayout from '@/components/AuthLayout.vue'
import { configureQrWasm } from '@/services/zxing'
import { parseScanUrl, type ScanTarget } from '@/utils/qrUrl'

type Failure = 'denied' | 'no-camera' | 'in-use' | 'insecure' | 'unsupported' | 'error'
type State = 'starting' | 'scanning' | Failure

const FAILURES: Record<Failure, { title: string; text: string; retry: boolean }> = {
  denied: {
    title: 'Permiso de cámara denegado',
    text: 'Para escanear necesitamos usar la cámara. Habilita el permiso y vuelve a intentarlo.',
    retry: true,
  },
  'no-camera': {
    title: 'No encontramos una cámara',
    text: 'Este dispositivo no tiene una cámara disponible. Usa la cámara de tu celular.',
    retry: true,
  },
  'in-use': {
    title: 'La cámara está en uso',
    text: 'Otra aplicación está usando la cámara. Ciérrala y vuelve a intentarlo.',
    retry: true,
  },
  insecure: {
    title: 'Conexión no segura',
    text: 'La cámara solo funciona en una conexión segura (HTTPS). Abre el sitio con https://.',
    retry: false,
  },
  unsupported: {
    title: 'Navegador no compatible',
    text: 'Este navegador no permite usar la cámara desde la web. Usa la cámara de tu celular.',
    retry: false,
  },
  error: {
    title: 'No pudimos iniciar la cámara',
    text: 'Inténtalo de nuevo o usa la cámara de tu celular.',
    retry: true,
  },
}

// Los errores de la librería definen `name` (ver vue-qrcode-reader/misc/errors).
const ERROR_STATES: Record<string, Failure> = {
  NotAllowedError: 'denied',
  NotFoundError: 'no-camera',
  OverconstrainedError: 'no-camera',
  NotReadableError: 'in-use',
  InsecureContextError: 'insecure',
  StreamApiNotSupportedError: 'unsupported',
}

const INVALID_MESSAGE_MS = 4000

configureQrWasm()

const router = useRouter()
const state = ref<State>('starting')
const attempt = ref(0)
const invalidShown = ref(false)
const heading = ref<HTMLElement | null>(null)
let navigating = false
let invalidTimer: ReturnType<typeof setTimeout> | undefined

const failure = computed(() => (state.value in FAILURES ? FAILURES[state.value as Failure] : null))

onBeforeUnmount(() => clearTimeout(invalidTimer))

function showInvalid() {
  invalidShown.value = true
  clearTimeout(invalidTimer)
  invalidTimer = setTimeout(() => (invalidShown.value = false), INVALID_MESSAGE_MS)
}

function onDetect(codes: DetectedBarcode[]) {
  if (navigating || codes.length === 0) return
  const valid = codes
    .map((code) => parseScanUrl(code.rawValue))
    .find((target): target is Extract<ScanTarget, { ok: true }> => target.ok)

  if (!valid) {
    showInvalid() // Otro dominio u otra ruta: no se navega (RF-QR-03).
    return
  }
  navigating = true
  void router.push({ name: 'confirm', hash: `#${valid.token}` })
}

function onCameraOn() {
  if (!failure.value) state.value = 'scanning'
}

function onError(error: EmittedError) {
  state.value = ERROR_STATES[error.name] ?? 'error'
}

function retry() {
  state.value = 'starting'
  attempt.value += 1
}

function cancel() {
  void router.push({ name: 'home' })
}

// Lleva el foco al título cuando aparece un error, para lectores de pantalla.
watch(failure, async (value) => {
  if (!value) return
  await nextTick()
  heading.value?.focus()
})
</script>

<template>
  <AuthLayout>
    <h1 ref="heading" tabindex="-1">Escanear código QR</h1>
    <p class="auth-lead">Apunta la cámara al código QR que aparece en la pantalla del equipo.</p>

    <div v-if="failure" class="auth-banner auth-banner--error" role="alert">
      <p>
        <strong>{{ failure.title }}</strong>
      </p>
      <p>{{ failure.text }}</p>
    </div>
    <div v-else-if="invalidShown" class="auth-banner auth-banner--warning" role="alert">
      <p>
        <strong>Este código no pertenece al sistema.</strong>
      </p>
      <p>Escanea el QR que aparece en el equipo.</p>
    </div>
    <p v-else-if="state === 'starting'" class="note" role="status">
      Iniciando la cámara… Si el navegador lo pide, permite el acceso.
    </p>

    <div v-if="!failure" class="viewfinder">
      <QrcodeStream
        :key="attempt"
        :formats="['qr_code']"
        @detect="onDetect"
        @camera-on="onCameraOn"
        @error="onError"
      />
      <span class="viewfinder__frame" aria-hidden="true"></span>
    </div>

    <section v-if="state === 'denied'" class="help" aria-labelledby="help-title">
      <h2 id="help-title">Cómo habilitar la cámara</h2>
      <ul>
        <li>
          <strong>Safari (iPhone o iPad):</strong> toca «aA» en la barra de direcciones, elige
          «Configuración del sitio web», abre «Cámara» y selecciona «Permitir».
        </li>
        <li>
          <strong>Chrome (Android):</strong> toca el candado junto a la dirección, entra en
          «Permisos», abre «Cámara» y selecciona «Permitir».
        </li>
        <li>
          <strong>Otros navegadores:</strong> habilita el permiso de cámara para este sitio en la
          configuración del navegador.
        </li>
      </ul>
    </section>

    <div class="actions">
      <button v-if="failure?.retry" class="auth-button" type="button" @click="retry">
        Intentar de nuevo
      </button>
      <button class="auth-button auth-button--secondary" type="button" @click="cancel">
        Cancelar
      </button>
    </div>

    <section class="native" aria-labelledby="native-title">
      <h2 id="native-title">¿Prefieres usar la cámara del celular?</h2>
      <p>
        Abre la aplicación de cámara de tu celular, apunta al QR del equipo y toca el enlace que
        aparece. Te traerá directo a la confirmación.
      </p>
    </section>
  </AuthLayout>
</template>

<style scoped>
h1:focus {
  outline: none;
}
h2 {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 700;
}
.note {
  margin: 0 0 16px;
  font-size: 12px;
  color: #61738b;
}
.viewfinder {
  position: relative;
  aspect-ratio: 1 / 1;
  max-height: 60vh;
  margin: 0 auto 16px;
  overflow: hidden;
  border-radius: 12px;
  background: #233e60;
}
.viewfinder__frame {
  position: absolute;
  inset: 20%;
  border: 3px solid #fff;
  border-radius: 12px;
  box-shadow: 0 0 0 9999px rgb(35 62 96 / 35%);
  pointer-events: none;
}
.help {
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid #dce4ef;
  border-radius: 8px;
  background: #f5f8fc;
}
.help ul {
  margin: 0;
  padding-left: 18px;
}
.help li + li {
  margin-top: 8px;
}
.actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}
.auth-button--secondary {
  border: 1px solid #dce4ef;
  background: #fff;
  color: #233e60;
}
.native {
  padding-top: 12px;
  border-top: 1px solid #dce4ef;
  color: #61738b;
}
.native p {
  margin: 0;
  font-size: 12px;
}
</style>
