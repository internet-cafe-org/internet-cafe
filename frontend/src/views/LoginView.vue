<script setup lang="ts">
import { onBeforeUnmount, reactive, ref } from 'vue'

import AuthField from '@/components/AuthField.vue'
import AuthLayout from '@/components/AuthLayout.vue'
import { useSignIn } from '@/composables/useSignIn'
import { ApiError, login } from '@/services/auth'
import { loginEmailError, loginPasswordError } from '@/utils/validation'

const LOCK_MS = 15 * 60 * 1000

const signIn = useSignIn()
const form = reactive({ email: '', password: '' })
const errors = reactive({ email: '', password: '' })
const banner = ref<'' | 'credentials' | 'service'>('')
const locked = ref(false)
const loading = ref(false)
let lockTimer: ReturnType<typeof setTimeout> | undefined

onBeforeUnmount(() => clearTimeout(lockTimer))

async function onSubmit() {
  banner.value = ''
  errors.email = loginEmailError(form.email)
  errors.password = loginPasswordError(form.password)
  if (errors.email || errors.password) return

  loading.value = true
  try {
    await signIn(await login(form.email.trim(), form.password))
  } catch (error) {
    if (error instanceof ApiError && error.status === 423) {
      locked.value = true
      lockTimer = setTimeout(() => (locked.value = false), LOCK_MS)
    } else if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
      banner.value = 'service'
    } else {
      // Respuesta genérica: no revela si la cuenta existe (RF-AUT-05).
      banner.value = 'credentials'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <h1>Iniciar sesión</h1>
    <p class="auth-lead">Ingresa con tu cuenta institucional para continuar.</p>

    <div v-if="locked" class="auth-banner auth-banner--warning" role="alert">
      <p><strong>Acceso bloqueado temporalmente.</strong></p>
      <p>Alcanzaste 5 intentos fallidos. Espera 15 minutos antes de volver a iniciar sesión.</p>
    </div>
    <div v-else-if="banner === 'credentials'" class="auth-banner auth-banner--error" role="alert">
      <p><strong>No pudimos iniciar sesión.</strong></p>
      <p>El correo o la contraseña son incorrectos. Revisa tus datos e inténtalo de nuevo.</p>
    </div>
    <div v-else-if="banner === 'service'" class="auth-banner auth-banner--error" role="alert">
      <p><strong>No pudimos conectar con el servicio.</strong></p>
      <p>Inténtalo de nuevo en unos minutos.</p>
    </div>

    <form class="auth-form" novalidate @submit.prevent="onSubmit">
      <AuthField
        id="login-email"
        v-model="form.email"
        label="Correo institucional"
        type="email"
        placeholder="Tu correo institucional"
        autocomplete="username"
        :error="errors.email"
        :disabled="locked"
      />
      <AuthField
        id="login-password"
        v-model="form.password"
        label="Contraseña"
        type="password"
        placeholder="Tu contraseña"
        autocomplete="current-password"
        :error="errors.password"
        :disabled="locked"
      />
      <button class="auth-button" type="submit" :disabled="locked || loading">
        Iniciar sesión
      </button>
      <p class="auth-switch">
        ¿Aún no tienes una cuenta?
        <RouterLink :to="{ name: 'register' }">Crear una cuenta</RouterLink>
      </p>
    </form>
  </AuthLayout>
</template>
