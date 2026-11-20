import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Aura from '@primeuix/themes/aura'
import 'primeicons/primeicons.css'

import App from './App.vue'
import router from './router'
import { restoreSession } from './services/auth'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)

// Recupera la sesión al arrancar mediante /auth/refresh (HU-31 / UI-04c).
await restoreSession()

app.use(router)
app.use(PrimeVue, {
  theme: { preset: Aura, options: { darkModeSelector: false } },
})
app.mount('#app')
