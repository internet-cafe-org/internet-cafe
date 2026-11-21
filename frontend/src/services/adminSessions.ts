import { api } from '@/api/client'
import type { components } from '@/api/schema'

export type AdminSession = components['schemas']['AdminSession']
export type AdminSessionsPage = components['schemas']['AdminSessionsPage']
export type SessionEndReason = components['schemas']['SessionEndReason']
export type LabItem = components['schemas']['Lab']

export interface AdminSessionsQuery {
  machine_code?: string
  lab_id?: string
  state?: 'active' | 'ended'
  started_from?: string
  started_to?: string
  limit?: number
  offset?: number
}

/**
 * Consulta la lista paginada de accesos con filtros según contrato v0.2.1 (RF-ADM-05).
 */
export async function getAdminSessions(query?: AdminSessionsQuery): Promise<AdminSessionsPage> {
  const { data } = await api.GET('/api/v1/admin/sessions', {
    params: {
      query: {
        machine_code: query?.machine_code || undefined,
        lab_id: query?.lab_id || undefined,
        state: query?.state || undefined,
        started_from: query?.started_from || undefined,
        started_to: query?.started_to || undefined,
        limit: query?.limit ?? 20,
        offset: query?.offset ?? 0,
      },
    },
  })

  if (!data) {
    throw new Error('No se recibieron datos de sesiones.')
  }

  return data
}

/**
 * Forzar el cierre de una sesión activa (RF-ADM-07, RF-SES-08).
 * Cierra con motivo `admin_forced`. Idempotente.
 */
export async function forceEndSession(sessionId: string): Promise<AdminSession> {
  const { data } = await api.POST('/api/v1/admin/sessions/{id}/end', {
    params: {
      path: {
        id: sessionId,
      },
    },
  })

  if (!data?.session) {
    throw new Error('No se recibió la información de la sesión cerrada.')
  }

  return data.session
}

/**
 * Obtiene el listado de salas para alimentar el filtro de selección.
 */
export async function getAdminLabs(): Promise<LabItem[]> {
  const { data } = await api.GET('/api/v1/admin/labs', {
    params: {
      query: {
        limit: 100,
        offset: 0,
      },
    },
  })

  return data?.items ?? []
}
