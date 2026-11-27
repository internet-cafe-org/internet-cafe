<script setup lang="ts">
import { reactive, ref } from 'vue'
import AuthField from '@/components/AuthField.vue'
import AuthLayout from '@/components/AuthLayout.vue'
import { useCooldown } from '@/composables/useCooldown'
import { resendCode, verifyEmail } from '@/services/auth'
import {
  clearPendingVerificationEmail,
  getPendingVerificationEmail,
} from '@/services/pendingVerification'
import { OTP_ERROR_MESSAGES, otpErrorKind, type OtpErrorKind } from '@/utils/otpErrors'
import { loginEmailError, normalizeOtp, otpCodeError } from '@/utils/validation'

const RESEND_COOLDOWN_S = 60

// El correo llega del registro (solo en memoria). Si se recargó la página, se vuelve a pedir.
const knownEmail = getPendingVerificationEmail()
const form = reactive({ email: knownEmail ?? '', code: '' })
const errors = reactive({ email: '', code: '' })
const failure = ref<OtpErrorKind | ''>('')
const resendFailure = ref<OtpErrorKind | ''>('')
const resendSent = ref(false)
const verified = ref(false)
const loading = ref(false)
const resending = ref(false)

const {
  remaining: cooldownLeft,
  active: cooldownActive,
  start: startCooldown,
} = useCooldown(RESEND_COOLDOWN_S)

function validateEmail(): boolean {
  errors.email = knownEmail ? '' : loginEmailError(form.email)
  return errors.email === ''
}

async function onSubmit() {
  failure.value = ''
  resendFailure.value = ''
  resendSent.value = false
  const emailOk = validateEmail()
  errors.code = otpCodeError(form.code)
  if (!emailOk || errors.code) return

  loading.value = true
  try {
    await verifyEmail(form.email.trim(), normalizeOtp(form.code))
    clearPendingVerificationEmail()
    verified.value = true
  } catch (error) {
    failure.value = otpErrorKind(error)
  } finally {
    loading.value = false
  }
}

async function onResend() {
  failure.value = ''
  resendFailure.value = ''
  resendSent.value = false
  if (!validateEmail()) return

  resending.value = true
  try {
    await resendCode(form.email.trim())
    // Respuesta neutra: no confirma si la cuenta existe.
    resendSent.value = true
    startCooldown()
  } catch (error) {
    resendFailure.value = otpErrorKind(error)
  } finally {
    resending.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <h1>Verificar correo</h1>

    <template v-if="verified">
      <div class="auth-banner auth-banner--success" role="status">
        <p>Correo verificado. Tu cuenta ya está activa.</p>
      </div>
      <RouterLink class="auth-button verify-link" :to="{ name: 'login' }">
        Iniciar sesión
      </RouterLink>
    </template>

    <template v-else>
      <p v-if="knownEmail" class="auth-lead">
        Ingresa el código de 6 dígitos que enviamos a <strong>{{ knownEmail }}</strong
        >. Vence en 10 minutos.
      </p>
      <p v-else class="auth-lead">
        Ingresa tu correo institucional y el código de 6 dígitos que te enviamos. Vence en 10
        minutos.
      </p>

      <div v-if="failure" class="auth-banner auth-banner--error" role="alert">
        <p>
          <strong>{{ OTP_ERROR_MESSAGES[failure].title }}</strong>
        </p>
        <p>{{ OTP_ERROR_MESSAGES[failure].text }}</p>
      </div>
      <div v-if="resendFailure" class="auth-banner auth-banner--error" role="alert">
        <p>
          <strong>{{ OTP_ERROR_MESSAGES[resendFailure].title }}</strong>
        </p>
        <p>{{ OTP_ERROR_MESSAGES[resendFailure].text }}</p>
      </div>
      <div v-if="resendSent" class="auth-banner auth-banner--success" role="status">
        <p>Si el correo está registrado, te enviamos un código nuevo.</p>
      </div>

      <form class="auth-form" novalidate @submit.prevent="onSubmit">
        <AuthField
          v-if="!knownEmail"
          id="verify-email"
          v-model="form.email"
          label="Correo institucional"
          type="email"
          autocomplete="email"
          :error="errors.email"
        />
        <AuthField
          id="verify-code"
          v-model="form.code"
          label="Código de verificación"
          autocomplete="one-time-code"
          placeholder="123456"
          :error="errors.code"
        />
        <button class="auth-button" type="submit" :disabled="loading">
          {{ loading ? 'Verificando...' : 'Verificar correo' }}
        </button>
        <button
          class="auth-button verify-secondary"
          type="button"
          :disabled="resending || cooldownActive"
          @click="onResend"
        >
          {{ cooldownActive ? `Reenviar código (${cooldownLeft} s)` : 'Reenviar código' }}
        </button>
      </form>
    </template>
  </AuthLayout>
</template>

<style scoped>
.verify-link {
  display: grid;
  place-items: center;
  margin-top: 16px;
  text-decoration: none;
}
.verify-secondary {
  border: 1px solid #2563eb;
  background: #fff;
  color: #2563eb;
}
.verify-secondary:disabled {
  border-color: transparent;
  background: #e8edf4;
  color: #7a8799;
}
</style>
