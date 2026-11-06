import { useRouter } from 'vue-router'

import { useSessionStore } from '@/stores/session'

/** Cierra la sesión (limpia Pinia y el token privado en memoria) y redirige al login. */
export function useSignOut() {
  const router = useRouter()
  const session = useSessionStore()

  return async (): Promise<void> => {
    session.clear()
    await router.push({ name: 'login' })
  }
}
