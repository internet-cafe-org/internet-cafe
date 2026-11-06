<script setup lang="ts">
import { reactive, ref } from 'vue'

import AuthField from '@/components/AuthField.vue'
import AuthLayout from '@/components/AuthLayout.vue'
import { useSignIn } from '@/composables/useSignIn'
import { login, register } from '@/services/auth'
import {
  consentError,
  parseAllowedDomains,
  registerEmailError,
  registerPasswordError,
  requiredError,
} from '@/utils/validation'

// Dominios permitidos (PEND-06). Vacío = solo valida el servidor.
const allowedDomains = parseAllowedDomains(String(import.meta.env.VITE_ALLOWED_EMAIL_DOMAINS ?? ''))

const signIn = useSignIn()
const form = reactive({ fullName: '', studentCode: '', email: '', password: '', consent: false })
const errors = reactive({ fullName: '', studentCode: '', email: '', password: '', consent: '' })
const failed = ref(false)
const succeeded = ref(false)
const loading = ref(false)

function validate(): boolean {
  errors.fullName = requiredError(form.fullName, 'Ingresa tu nombre completo.')
  errors.studentCode = requiredError(form.studentCode, 'Ingresa tu código estudiantil.')
  errors.email = registerEmailError(form.email, allowedDomains)
  errors.password = registerPasswordError(form.password)
  errors.consent = consentError(form.consent)
  return Object.values(errors).every((message) => message === '')
}

async function onSubmit() {
  failed.value = false
  if (!validate()) return

  loading.value = true
  try {
    await register({
      email: form.email.trim(),
      student_code: form.studentCode.trim(),
      full_name: form.fullName.trim(),
      password: form.password,
      privacy_consent: form.consent,
    })
    succeeded.value = true
    // Inicio de sesión automático, sin OTP (decisión de alcance del diseño).
    await signIn(await login(form.email.trim(), form.password))
  } catch {
    // Respuesta genérica: no revela si el correo o el código ya existen (RF-AUT-01).
    succeeded.value = false
    failed.value = true
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <h1>Crear una cuenta</h1>
    <p class="auth-lead">Completa tus datos institucionales. Todos los campos son obligatorios.</p>

    <div v-if="succeeded" class="auth-banner auth-banner--success" role="status">
      <p>Registro exitoso. Iniciando sesión automáticamente...</p>
    </div>
    <div v-else-if="failed" class="auth-banner auth-banner--error" role="alert">
      <p>No pudimos completar el registro. Revisa tus datos e inténtalo de nuevo.</p>
    </div>

    <form class="auth-form" novalidate @submit.prevent="onSubmit">
      <AuthField
        id="register-name"
        v-model="form.fullName"
        label="Nombre completo"
        placeholder="Como aparece en tu matrícula"
        autocomplete="name"
        :error="errors.fullName"
        :disabled="succeeded"
      />
      <AuthField
        id="register-code"
        v-model="form.studentCode"
        label="Código estudiantil"
        placeholder="Tu código estudiantil"
        :error="errors.studentCode"
        :disabled="succeeded"
      />
      <AuthField
        id="register-email"
        v-model="form.email"
        label="Correo institucional"
        type="email"
        placeholder="Tu correo institucional"
        autocomplete="email"
        :error="errors.email"
        :disabled="succeeded"
      />
      <AuthField
        id="register-password"
        v-model="form.password"
        label="Contraseña"
        type="password"
        placeholder="Crea tu contraseña"
        autocomplete="new-password"
        hint="Entre 10 y 128 caracteres."
        :error="errors.password"
        :disabled="succeeded"
      />

      <div class="consent">
        <label class="consent__label">
          <input
            v-model="form.consent"
            type="checkbox"
            :disabled="succeeded"
            :aria-invalid="errors.consent ? 'true' : undefined"
            :aria-describedby="errors.consent ? 'register-consent-error' : undefined"
          />
          <span>
            Autorizo el tratamiento de mis datos personales para gestionar mi registro y el acceso a
            los equipos. (Obligatorio)
          </span>
        </label>
        <p v-if="errors.consent" id="register-consent-error" class="consent__error">
          Error: {{ errors.consent }}
        </p>
      </div>

      <button class="auth-button" type="submit" :disabled="succeeded || loading">
        {{ succeeded ? 'Iniciando sesión...' : 'Crear cuenta' }}
      </button>
      <p class="auth-switch">
        ¿Ya tienes una cuenta?
        <RouterLink :to="{ name: 'login' }">Iniciar sesión</RouterLink>
      </p>
    </form>
  </AuthLayout>
</template>

<style scoped>
.consent__label {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.consent__label input {
  flex: none;
  width: 20px;
  height: 20px;
  margin-top: 2px;
}
.consent__error {
  margin: 4px 0 0;
  font-size: 12px;
  color: #b42318;
}
</style>
