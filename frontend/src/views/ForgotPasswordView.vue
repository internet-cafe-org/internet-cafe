<script setup lang="ts">
import { reactive, ref } from 'vue'
import AuthField from '@/components/AuthField.vue'
import AuthLayout from '@/components/AuthLayout.vue'
import { useCooldown } from '@/composables/useCooldown'
import { requestPasswordReset, resetPassword } from '@/services/auth'
import { OTP_ERROR_MESSAGES, otpErrorKind, type OtpErrorKind } from '@/utils/otpErrors'
import {
  confirmPasswordError,
  loginEmailError,
  normalizeOtp,
  otpCodeError,
  registerPasswordError,
} from '@/utils/validation'

type Step = 'request' | 'reset' | 'done'

const RESEND_COOLDOWN_S = 60

const step = ref<Step>('request')
const form = reactive({ email: '', code: '', password: '', confirmation: '' })
const errors = reactive({ email: '', code: '', password: '', confirmation: '' })
const failure = ref<OtpErrorKind | ''>('')
const resent = ref(false)
const loading = ref(false)

const {
  remaining: cooldownLeft,
  active: cooldownActive,
  start: startCooldown,
} = useCooldown(RESEND_COOLDOWN_S)

/** Paso 1: pide el código. La API responde 202 exista o no la cuenta. */
async function onRequest() {
  failure.value = ''
  errors.email = loginEmailError(form.email)
  if (errors.email) return

  loading.value = true
  try {
    await requestPasswordReset(form.email.trim())
    step.value = 'reset'
    startCooldown()
  } catch (error) {
    failure.value = otpErrorKind(error)
  } finally {
    loading.value = false
  }
}

async function onResend() {
  failure.value = ''
  resent.value = false
  loading.value = true
  try {
    await requestPasswordReset(form.email.trim())
    resent.value = true
    startCooldown()
  } catch (error) {
    failure.value = otpErrorKind(error)
  } finally {
    loading.value = false
  }
}

/** Paso 2: cambia la contraseña con el código. */
async function onReset() {
  failure.value = ''
  errors.code = otpCodeError(form.code)
  errors.password = registerPasswordError(form.password)
  errors.confirmation = confirmPasswordError(form.password, form.confirmation)
  if (errors.code || errors.password || errors.confirmation) return

  loading.value = true
  try {
    await resetPassword(form.email.trim(), normalizeOtp(form.code), form.password)
    // Nada sensible queda en memoria una vez usado.
    form.password = ''
    form.confirmation = ''
    form.code = ''
    step.value = 'done'
  } catch (error) {
    failure.value = otpErrorKind(error)
  } finally {
    loading.value = false
  }
}

function changeEmail() {
  failure.value = ''
  resent.value = false
  errors.code = ''
  errors.password = ''
  errors.confirmation = ''
  form.code = ''
  form.password = ''
  form.confirmation = ''
  step.value = 'request'
}
</script>

<template>
  <AuthLayout>
    <h1>Recuperar contraseña</h1>

    <template v-if="step === 'done'">
      <div class="auth-banner auth-banner--success" role="status">
        <p>Contraseña actualizada.</p>
        <p>Inicia sesión con tu contraseña nueva.</p>
      </div>
      <RouterLink class="auth-button forgot-link" :to="{ name: 'login' }">
        Iniciar sesión
      </RouterLink>
    </template>

    <template v-else>
      <div v-if="failure" class="auth-banner auth-banner--error" role="alert">
        <p>
          <strong>{{ OTP_ERROR_MESSAGES[failure].title }}</strong>
        </p>
        <p>{{ OTP_ERROR_MESSAGES[failure].text }}</p>
      </div>

      <form v-if="step === 'request'" class="auth-form" novalidate @submit.prevent="onRequest">
        <p class="auth-lead">
          Ingresa tu correo institucional y te enviaremos un código de 6 dígitos.
        </p>
        <AuthField
          id="forgot-email"
          v-model="form.email"
          label="Correo institucional"
          type="email"
          autocomplete="email"
          :error="errors.email"
        />
        <button class="auth-button" type="submit" :disabled="loading">
          {{ loading ? 'Enviando...' : 'Enviar código' }}
        </button>
      </form>

      <form v-else class="auth-form" novalidate @submit.prevent="onReset">
        <p class="auth-lead">
          Si el correo está registrado, te enviamos un código. Vence en 10 minutos.
        </p>
        <div v-if="resent" class="auth-banner auth-banner--success" role="status">
          <p>Si el correo está registrado, te enviamos un código nuevo.</p>
        </div>
        <AuthField
          id="reset-code"
          v-model="form.code"
          label="Código de recuperación"
          autocomplete="one-time-code"
          :error="errors.code"
        />
        <AuthField
          id="reset-password"
          v-model="form.password"
          label="Contraseña nueva"
          type="password"
          autocomplete="new-password"
          hint="Entre 10 y 128 caracteres."
          :error="errors.password"
        />
        <AuthField
          id="reset-confirmation"
          v-model="form.confirmation"
          label="Confirma la contraseña nueva"
          type="password"
          autocomplete="new-password"
          :error="errors.confirmation"
        />
        <button class="auth-button" type="submit" :disabled="loading">
          {{ loading ? 'Guardando...' : 'Cambiar contraseña' }}
        </button>
        <button
          class="auth-button forgot-secondary"
          type="button"
          :disabled="loading || cooldownActive"
          @click="onResend"
        >
          {{ cooldownActive ? `Reenviar código (${cooldownLeft} s)` : 'Reenviar código' }}
        </button>
        <button class="auth-button forgot-secondary" type="button" @click="changeEmail">
          Usar otro correo
        </button>
      </form>
    </template>
  </AuthLayout>
</template>

<style scoped>
.forgot-link {
  display: grid;
  place-items: center;
  margin-top: 16px;
  text-decoration: none;
}
.forgot-secondary {
  border: 1px solid #2563eb;
  background: #fff;
  color: #2563eb;
}
.forgot-secondary:disabled {
  border-color: transparent;
  background: #e8edf4;
  color: #7a8799;
}
</style>
