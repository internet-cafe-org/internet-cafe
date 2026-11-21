import { useRouter } from 'vue-router'

import { logout } from '@/services/auth'
import { useSessionStore } from '@/stores/session'

/** Cierra la sesión web (revoca refresh token, limpia Pinia y el token en memoria) y redirige al login. */
export function useSignOut() {
  const router = useRouter()
  const session = useSessionStore()

  return async (): Promise<void> => {
    await logout()
    session.clear()
    await router.push({ name: 'login' })
  }
}
