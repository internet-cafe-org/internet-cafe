import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Aura from '@primeuix/themes/aura'
import 'primeicons/primeicons.css'

import App from './App.vue'
import router from './router'
import { setAuthFailureHandler } from './api/client'
import { restoreSession } from './services/auth'
import { useSessionStore } from './stores/session'

async function enableMocks(): Promise<void> {
  if (import.meta.env.DEV) {
    const { worker } = await import('./mocks/browser')

    await worker.start({
      onUnhandledRequest: 'bypass',
    })
  }
}

async function bootstrap(): Promise<void> {
  await enableMocks()

  const app = createApp(App)
  const pinia = createPinia()

  // Pinia debe estar activa antes de restaurar la sesión.
  app.use(pinia)

  // Cierra la sesión cuando el refresh token deja de ser válido.
  setAuthFailureHandler(() => {
    const session = useSessionStore(pinia)

    session.clear()

    if (router.currentRoute.value.name !== 'login') {
      void router.replace({ name: 'login' })
    }
  })

  // Recupera la sesión al arrancar mediante /auth/refresh (HU-31 / UI-04c).
  // Va antes del router para que los guards vean la sesión ya restaurada.
  await restoreSession()

  app.use(router)

  app.use(PrimeVue, {
    theme: {
      preset: Aura,
      options: {
        darkModeSelector: false,
      },
    },
  })

  app.mount('#app')
}

void bootstrap()