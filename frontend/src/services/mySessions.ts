/**
 * Sesiones del estudiante (UI-08). Contrato v0.2: SRS §10.3.
 * Usa el cliente tipado de src/api, que añade el token y renueva la sesión.
 * Ante un error HTTP el cliente lanza ApiError (RFC 9457).
 */
import { api } from '@/api/client'
import type { components } from '@/api/schema'

export type MySession = components['schemas']['MySession']

/** Sesión activa del estudiante o `null` (GET /me/sessions/active). */
export async function getActiveSession(): Promise<MySession | null> {
  const { data } = await api.GET('/api/v1/me/sessions/active')
  return data?.session ?? null
}

/** Sesiones más recientes primero (GET /me/sessions). El máximo del servidor es 50. */
export async function getRecentSessions(limit: number): Promise<MySession[]> {
  const { data } = await api.GET('/api/v1/me/sessions', { params: { query: { limit } } })
  return data?.items ?? []
}

/** "Terminar acceso": cierra con motivo user_logout_web. No cierra la sesión web. */
export async function endMySession(id: string): Promise<void> {
  await api.POST('/api/v1/me/sessions/{id}/end', { params: { path: { id } } })
}
