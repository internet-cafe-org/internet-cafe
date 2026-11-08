
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Aura from '@primeuix/themes/aura'
import 'primeicons/primeicons.css'

import App from './App.vue'
import router from './router'
import { setAuthFailureHandler } from './api/client'
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

  app.use(pinia)
  app.use(router)

  app.use(PrimeVue, {
    theme: {
      preset: Aura,
      options: {
        darkModeSelector: false,
      },
    },
  })

  // Cierra la sesión cuando el refresh token deja de ser válido.
  setAuthFailureHandler(() => {
    const session = useSessionStore(pinia)

    session.clear()

    if (router.currentRoute.value.name !== 'login') {
      void router.replace({ name: 'login' })
    }
  })

  app.mount('#app')
}

void bootstrap()
