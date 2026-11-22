import { http, HttpResponse } from 'msw'
import type { components } from '@/api/schema'

const API_URL = 'http://localhost:8000'

type MySession = components['schemas']['MySession']

// Sin datos precargados, igual que el resto de los mocks.
export const mySessions: MySession[] = []

export const meHandlers = [
  http.get(`${API_URL}/api/v1/me/sessions/active`, () => {
    const active = mySessions.find((session) => !session.ended_at) ?? null
    return HttpResponse.json({ session: active })
  }),

  http.get(`${API_URL}/api/v1/me/sessions`, ({ request }) => {
    const url = new URL(request.url)
    const limit = Number(url.searchParams.get('limit') ?? 20)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const sorted = [...mySessions].sort((a, b) => b.started_at.localeCompare(a.started_at))

    return HttpResponse.json({
      items: sorted.slice(offset, offset + limit),
      total: sorted.length,
      limit,
      offset,
    })
  }),

  http.post(`${API_URL}/api/v1/me/sessions/:id/end`, ({ params }) => {
    const session = mySessions.find((item) => item.id === params.id)

    if (!session) {
      return HttpResponse.json(
        {
          type: 'about:blank',
          title: 'No encontrado',
          status: 404,
          detail: 'La sesión no existe.',
          code: 'SESSION_NOT_FOUND',
        },
        { status: 404, headers: { 'Content-Type': 'application/problem+json' } },
      )
    }

    // Idempotente: si ya estaba cerrada, devuelve la misma sesión.
    if (!session.ended_at) {
      const endedAt = new Date()
      session.ended_at = endedAt.toISOString()
      session.end_reason = 'user_logout_web'
      session.duration_s = Math.max(
        0,
        Math.floor((endedAt.getTime() - new Date(session.started_at).getTime()) / 1000),
      )
    }

    return HttpResponse.json({ session })
  }),
]
