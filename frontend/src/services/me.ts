import { api } from '@/api/client'
import type { components } from '@/api/schema'

export type UserProfile = components['schemas']['Profile']
export type StudentSession = components['schemas']['MySession']
export type StudentSessionsPage = components['schemas']['MySessionsPage']

export async function fetchMyProfile(): Promise<UserProfile> {
  const { data } = await api.GET('/api/v1/me')
  if (!data) {
    throw new Error('No se recibió el perfil del usuario.')
  }
  return data
}

export async function fetchMySessions(params?: {
  limit?: number
  offset?: number
}): Promise<StudentSessionsPage> {
  const { data } = await api.GET('/api/v1/me/sessions', {
    params: {
      query: {
        limit: params?.limit ?? 20,
        offset: params?.offset ?? 0,
      },
    },
  })
  if (!data) {
    throw new Error('No se recibió el historial de accesos.')
  }
  return data
}
