<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import AuthLayout from '@/components/AuthLayout.vue'
import { takePendingScanToken } from '@/services/pendingScan'
import { useSessionStore } from '@/stores/session'

const REDIRECT_DELAY_MS = 1200

const router = useRouter()
const session = useSessionStore()
let timer: ReturnType<typeof setTimeout> | undefined

function go() {
  // QR de origen → Confirmar acceso (la vigencia la comprueba esa pantalla).
  const token = takePendingScanToken()
  if (token) {
    void router.replace({ name: 'confirm', hash: `#${token}` })
    return
  }
  // Sin QR: destino según el rol (aún sin diseño propio).
  void router.replace({ name: session.isAdmin ? 'admin-machines' : 'home' })
}

onMounted(() => {
  timer = setTimeout(go, REDIRECT_DELAY_MS)
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <AuthLayout>
    <div class="auth-banner auth-banner--success" role="status">
      <p>Iniciaste sesión correctamente</p>
    </div>
    <div class="redirect">
      <span class="redirect__spinner" aria-hidden="true"></span>
      <h1>Te estamos redirigiendo al destino correspondiente…</h1>
      <p class="auth-lead">Espera un momento. No necesitas realizar ninguna acción.</p>
    </div>
  </AuthLayout>
</template>

<style scoped>
.redirect {
  text-align: center;
}
.redirect__spinner {
  display: block;
  width: 40px;
  height: 40px;
  margin: 8px auto 16px;
  border: 4px solid #d7e0ec;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .redirect__spinner {
    animation: none;
  }
}
</style>
