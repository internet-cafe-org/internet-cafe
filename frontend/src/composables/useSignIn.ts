import { useRouter } from 'vue-router'

import { setAccessToken } from '@/api/client'
import type { LoginResponse } from '@/services/auth'
import { useSessionStore } from '@/stores/session'

/** Guarda la sesión (token en memoria, nombre y rol en Pinia) y va al destino provisional. */
export function useSignIn() {
  const router = useRouter()
  const session = useSessionStore()

  return async (response: LoginResponse): Promise<void> => {
    setAccessToken(response.access_token)
    session.setUser(response.user.full_name, response.user.role)
    await router.push({ name: 'redirecting' })
  }
}
