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

  // Listar salas para admin
  http.get(`${API_URL}/api/v1/admin/labs`, () => {
    return HttpResponse.json({
      items: [
        { id: 'lab-001', name: 'Sala 1', building: 'Bloque A' },
        { id: 'lab-002', name: 'Sala 2', building: 'Bloque B' },
        { id: 'lab-003', name: 'Sala 3', building: 'Bloque B' },
      ],
      total: 3,
      limit: 100,
      offset: 0,
    })
  }),

  // Listar accesos para admin
  http.get(`${API_URL}/api/v1/admin/sessions`, ({ request }) => {
    const url = new URL(request.url)
    const machineCode = url.searchParams.get('machine_code')
    const labId = url.searchParams.get('lab_id')
    const state = url.searchParams.get('state')
    const startedFrom = url.searchParams.get('started_from')
    const startedTo = url.searchParams.get('started_to')
    const limit = Number(url.searchParams.get('limit') ?? '20')
    const offset = Number(url.searchParams.get('offset') ?? '0')

    const allSessions = [
      {
        id: 'sess-001',
        user: {
          id: 'user-001',
          full_name: 'Ana Pérez',
          student_code_masked: '2021****34',
        },
        machine_code: 'LAB3-PC12',
        lab: 'Sala 3',
        started_at: '2026-11-20T10:00:00Z',
        last_heartbeat_at: '2026-11-20T10:20:00Z',
        ended_at: null,
        end_reason: null,
        duration_s: null,
      },
      {
        id: 'sess-002',
        user: {
          id: 'user-002',
          full_name: 'Carlos Gómez',
          student_code_masked: '2022****56',
        },
        machine_code: 'LAB1-PC05',
        lab: 'Sala 1',
        started_at: '2026-11-19T08:30:00Z',
        last_heartbeat_at: '2026-11-19T09:30:00Z',
        ended_at: '2026-11-19T09:30:00Z',
        end_reason: 'user_logout_pc',
        duration_s: 3600,
      },
      {
        id: 'sess-003',
        user: {
          id: 'user-003',
          full_name: 'Beatriz Silva',
          student_code_masked: '2020****12',
        },
        machine_code: 'LAB2-PC01',
        lab: 'Sala 2',
        started_at: '2026-11-18T14:00:00Z',
        last_heartbeat_at: '2026-11-18T14:45:00Z',
        ended_at: '2026-11-18T14:45:00Z',
        end_reason: 'admin_forced',
        duration_s: 2700,
      },
    ]

    let filtered = [...allSessions]
    if (machineCode) {
      filtered = filtered.filter((s) => s.machine_code === machineCode)
    }
    if (labId) {
      const labMap: Record<string, string> = {
        'lab-001': 'Sala 1',
        'lab-002': 'Sala 2',
        'lab-003': 'Sala 3',
      }
      filtered = filtered.filter((s) => s.lab === labMap[labId])
    }
    if (state === 'active') {
      filtered = filtered.filter((s) => s.ended_at === null)
    } else if (state === 'ended') {
      filtered = filtered.filter((s) => s.ended_at !== null)
    }
    if (startedFrom) {
      filtered = filtered.filter((s) => s.started_at >= startedFrom)
    }
    if (startedTo) {
      filtered = filtered.filter((s) => s.started_at < startedTo)
    }

    const items = filtered.slice(offset, offset + limit)
    return HttpResponse.json({
      items,
      total: filtered.length,
      limit,
      offset,
    })
  }),

  // Forzar cierre de sesión
  http.post(`${API_URL}/api/v1/admin/sessions/:id/end`, ({ params }) => {
    const { id } = params

    if (id === 'not-found') {
      return HttpResponse.json(
        {
          type: 'about:blank',
          title: 'Sesión no encontrada',
          status: 404,
          detail: 'La sesión no existe.',
          code: 'SESSION_NOT_FOUND',
        },
        {
          status: 404,
          headers: { 'Content-Type': 'application/problem+json' },
        },
      )
    }

    return HttpResponse.json({
      session: {
        id: String(id),
        user: {
          id: 'user-001',
          full_name: 'Ana Pérez',
          student_code_masked: '2021****34',
        },
        machine_code: 'LAB3-PC12',
        lab: 'Sala 3',
        started_at: '2026-11-20T10:00:00Z',
        last_heartbeat_at: '2026-11-20T10:20:00Z',
        ended_at: '2026-11-20T10:25:00Z',
        end_reason: 'admin_forced',
        duration_s: 1500,
      },
    })
  }),
]
