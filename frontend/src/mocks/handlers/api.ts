import { http, HttpResponse } from 'msw'

const API_URL = 'http://localhost:8000'

export const apiHandlers = [
  // Crear desafío de una máquina.
  http.post(`${API_URL}/api/v1/machine/challenges`, ({ request }) => {
    const machineCode = request.headers.get('x-machine-code')

    if (!machineCode || machineCode === 'INVALID') {
      return HttpResponse.json(
        {
          type: 'about:blank',
          title: 'No autorizado',
          status: 401,
          detail: 'La firma de la máquina no es válida.',
          code: 'MACHINE_SIGNATURE_INVALID',
        },
        {
          status: 401,
          headers: { 'Content-Type': 'application/problem+json' },
        },
      )
    }

    if (machineCode === 'DISABLED') {
      return HttpResponse.json(
        {
          type: 'about:blank',
          title: 'Máquina deshabilitada',
          status: 403,
          detail: 'La máquina está deshabilitada.',
          code: 'MACHINE_DISABLED',
        },
        {
          status: 403,
          headers: { 'Content-Type': 'application/problem+json' },
        },
      )
    }

    return HttpResponse.json(
      {
        challenge_id: '123e4567-e89b-12d3-a456-426614174000',
        qr_url: 'http://localhost:5173/scan?token=demo-token',
        expires_at: '2026-10-29T18:00:00Z',
        rotate_after_s: 30,
      },
      { status: 201 },
    )
  }),

  // Consultar la información de un escaneo.
  http.post(`${API_URL}/api/v1/scan/preview`, async ({ request }) => {
    const body = (await request.json()) as { token?: string }

    if (!body.token || body.token === 'NOT_FOUND') {
      return HttpResponse.json(
        {
          type: 'about:blank',
          title: 'No encontrado',
          status: 404,
          detail: 'El desafío no existe.',
          code: 'CHALLENGE_NOT_FOUND',
        },
        {
          status: 404,
          headers: { 'Content-Type': 'application/problem+json' },
        },
      )
    }

    if (body.token === 'EXPIRED') {
      return HttpResponse.json(
        {
          type: 'about:blank',
          title: 'Desafío vencido',
          status: 410,
          detail: 'El desafío ha expirado.',
          code: 'CHALLENGE_EXPIRED',
        },
        {
          status: 410,
          headers: { 'Content-Type': 'application/problem+json' },
        },
      )
    }

    if (body.token === 'USED') {
      return HttpResponse.json(
        {
          type: 'about:blank',
          title: 'Desafío utilizado',
          status: 409,
          detail: 'El desafío ya fue utilizado.',
          code: 'CHALLENGE_ALREADY_USED',
        },
        {
          status: 409,
          headers: { 'Content-Type': 'application/problem+json' },
        },
      )
    }

    return HttpResponse.json({
      machine: {
        code: 'PC-001',
        lab: 'Laboratorio 1',
      },
      expires_at: '2026-10-29T18:00:00Z',
      active_session: null,
    })
  }),
]
