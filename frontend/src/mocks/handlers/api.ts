import { http, HttpResponse } from 'msw'
import type { components } from '@/api/schema'

const API_URL = 'http://localhost:8000'

type Lab = components['schemas']['Lab']
type Machine = components['schemas']['Machine']
type MachinePatch = components['schemas']['MachinePatch']

// ============================================================
// ESTADO INICIAL: SIN DATOS PRECARGADOS
// ============================================================

const labs: Lab[] = []

// No se precargan equipos ficticios.
const machines: Machine[] = []

// ============================================================
// ESTADO INICIAL: HISTORIAL DE ACCESOS VACÍO
// ============================================================

interface MockAccessSession {
  id: string
  session_code: string
  student_name: string
  student_email: string
  student_code: string
  machine_id: string
  machine_code: string
  machine_status: string
  machine_mode: string
  machine_last_seen_at: string | null
  lab_id: string
  lab_name: string
  building: string
  started_at: string
  ended_at: string | null
  last_heartbeat_at: string | null
  duration_minutes: number
  status: 'active' | 'closed'
  close_reason: string | null
}

// El historial comienza vacío.
const accessSessions: MockAccessSession[] = []

// ============================================================
// UTILIDADES
// ============================================================

function problem(
  status: number,
  title: string,
  detail: string,
  code: string,
) {
  return HttpResponse.json(
    {
      type: 'about:blank',
      title,
      status,
      detail,
      code,
    },
    {
      status,
      headers: { 'Content-Type': 'application/problem+json' },
    },
  )
}

function filterAccessSessions(url: URL): MockAccessSession[] {
  const student = url.searchParams.get('student')?.trim().toLowerCase()
  const labId = url.searchParams.get('lab_id')
  const machineId = url.searchParams.get('machine_id')
  const status = url.searchParams.get('status')
  const from = url.searchParams.get('from')
  const to = url.searchParams.get('to')

  return accessSessions.filter((session) => {
    if (
      student &&
      session.student_email.toLowerCase() !== student &&
      session.student_code.toLowerCase() !== student
    ) {
      return false
    }

    if (labId && session.lab_id !== labId) return false
    if (machineId && session.machine_id !== machineId) return false
    if (status && session.status !== status) return false

    const sessionDate = session.started_at.slice(0, 10)

    if (from && sessionDate < from) return false
    if (to && sessionDate > to) return false

    return true
  })
}

// ============================================================
// HANDLERS DE LA API SIMULADA
// ============================================================

export const apiHandlers = [
  // ----------------------------------------------------------
  // CREAR DESAFÍO DE UNA MÁQUINA
  // ----------------------------------------------------------

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

  // ----------------------------------------------------------
  // CONSULTAR LA INFORMACIÓN DE UN ESCANEO
  // ----------------------------------------------------------

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

    return problem(
      404,
      'No encontrado',
      'El desafío no existe.',
      'CHALLENGE_NOT_FOUND',
    )
  }),

  // ----------------------------------------------------------
  // W-13: CONSULTAR HISTORIAL DE ACCESOS
  // ----------------------------------------------------------

  http.get(`${API_URL}/api/v1/admin/access-sessions`, ({ request }) => {
    const url = new URL(request.url)
    const filtered = filterAccessSessions(url)

    const requestedLimit = Number(url.searchParams.get('limit') ?? 20)
    const requestedOffset = Number(url.searchParams.get('offset') ?? 0)

    const limit =
      Number.isFinite(requestedLimit) && requestedLimit > 0
        ? requestedLimit
        : 20

    const offset =
      Number.isFinite(requestedOffset) && requestedOffset >= 0
        ? requestedOffset
        : 0

    return HttpResponse.json({
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      limit,
      offset,
    })
  }),

  // ----------------------------------------------------------
  // W-13: EXPORTAR HISTORIAL DE ACCESOS EN CSV
  // ----------------------------------------------------------

  http.get(
    `${API_URL}/api/v1/admin/access-sessions/export`,
    ({ request }) => {
      const url = new URL(request.url)
      const filtered = filterAccessSessions(url)

      const columns = [
        'estudiante',
        'codigo',
        'equipo',
        'sala',
        'inicio',
        'fin',
        'duracion_minutos',
        'motivo_cierre',
      ]

      function csvCell(value: string | number | null): string {
        const text = String(value ?? '')
        return `"${text.replace(/"/g, '""')}"`
      }

      const rows = filtered.map((session) =>
        [
          session.student_name,
          session.student_code,
          session.machine_code,
          session.lab_name,
          session.started_at,
          session.ended_at,
          session.duration_minutes,
          session.close_reason,
        ]
          .map(csvCell)
          .join(','),
      )

      const csv = [columns.map(csvCell).join(','), ...rows].join('\r\n')

      return new HttpResponse(`\uFEFF${csv}`, {
        headers: {
          'Content-Type': 'text/csv; charset=utf-8',
          'Content-Disposition': 'attachment; filename="accesos.csv"',
        },
      })
    },
  ),

  // ----------------------------------------------------------
  // W-13: CONSULTAR DETALLE DE UNA SESIÓN
  // ----------------------------------------------------------

  http.get(
    `${API_URL}/api/v1/admin/access-sessions/:id`,
    ({ params }) => {
      const session = accessSessions.find((item) => item.id === params.id)

      if (!session) {
        return problem(
          404,
          'No encontrado',
          'La sesión de acceso no existe.',
          'ACCESS_SESSION_NOT_FOUND',
        )
      }

      return HttpResponse.json(session)
    },
  ),

  // ----------------------------------------------------------
  // W-13: FORZAR CIERRE DE UNA SESIÓN
  // ----------------------------------------------------------

  http.post(
    `${API_URL}/api/v1/admin/access-sessions/:id/force-close`,
    ({ params }) => {
      const session = accessSessions.find((item) => item.id === params.id)

      if (!session) {
        return problem(
          404,
          'No encontrado',
          'La sesión de acceso no existe.',
          'ACCESS_SESSION_NOT_FOUND',
        )
      }

      if (session.status === 'closed') {
        return problem(
          409,
          'Conflicto',
          'La sesión ya está cerrada.',
          'ACCESS_SESSION_ALREADY_CLOSED',
        )
      }

      const endedAt = new Date()

      session.status = 'closed'
      session.ended_at = endedAt.toISOString()
      session.close_reason = 'admin_forced'
      session.duration_minutes = Math.max(
        0,
        Math.floor(
          (endedAt.getTime() - new Date(session.started_at).getTime()) / 60000,
        ),
      )

      return HttpResponse.json(session)
    },
  ),

  // ----------------------------------------------------------
  // W-10: CONSULTAR SALAS
  // ----------------------------------------------------------

  http.get(`${API_URL}/api/v1/admin/labs`, ({ request }) => {
    const url = new URL(request.url)
    const limit = Number(url.searchParams.get('limit') ?? 20)
    const offset = Number(url.searchParams.get('offset') ?? 0)

    return HttpResponse.json({
      items: labs.slice(offset, offset + limit),
      total: labs.length,
      limit,
      offset,
    })
  }),

  // ----------------------------------------------------------
  // W-10: CREAR UNA SALA
  // ----------------------------------------------------------

  http.post(`${API_URL}/api/v1/admin/labs`, async ({ request }) => {
    const body = (await request.json()) as {
      name?: string
      building?: string | null
    }

    const name = body.name?.trim()

    if (!name) {
      return problem(
        422,
        'Error de validación',
        'El nombre de la sala es obligatorio.',
        'VALIDATION_ERROR',
      )
    }

    const exists = labs.some(
      (lab) => lab.name.toLowerCase() === name.toLowerCase(),
    )

    if (exists) {
      return problem(
        409,
        'Conflicto',
        'Ya existe una sala con ese nombre.',
        'LAB_ALREADY_EXISTS',
      )
    }

    const lab: Lab = {
      id: crypto.randomUUID(),
      name,
      building: body.building?.trim() || null,
    }

    labs.push(lab)

    return HttpResponse.json(lab, { status: 201 })
  }),

  // ----------------------------------------------------------
  // W-10: CONSULTAR EQUIPOS
  // ----------------------------------------------------------

  http.get(`${API_URL}/api/v1/admin/machines`, ({ request }) => {
    const url = new URL(request.url)
    const labId = url.searchParams.get('lab_id')
    const status = url.searchParams.get('status')
    const limit = Number(url.searchParams.get('limit') ?? 20)
    const offset = Number(url.searchParams.get('offset') ?? 0)

    let filtered = [...machines]

    if (labId) {
      filtered = filtered.filter((machine) => machine.lab_id === labId)
    }

    if (status) {
      filtered = filtered.filter((machine) => machine.status === status)
    }

    return HttpResponse.json({
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      limit,
      offset,
    })
  }),

  // ----------------------------------------------------------
  // W-10: ACTUALIZAR UN EQUIPO
  // ----------------------------------------------------------

  http.patch(
    `${API_URL}/api/v1/admin/machines/:id`,
    async ({ params, request }) => {
      const machine = machines.find((item) => item.id === params.id)

      if (!machine) {
        return problem(
          404,
          'No encontrado',
          'El equipo no existe.',
          'MACHINE_NOT_FOUND',
        )
      }

      const patch = (await request.json()) as MachinePatch

      if (Object.keys(patch).length === 0) {
        return problem(
          422,
          'Error de validación',
          'Debe proporcionar al menos un campo para actualizar.',
          'VALIDATION_ERROR',
        )
      }

      if (
        patch.status === 'active' &&
        machine.status === 'pending_enrollment'
      ) {
        return problem(
          409,
          'Conflicto',
          'No se puede activar un equipo que todavía no está enrolado.',
          'MACHINE_NOT_ENROLLED',
        )
      }

      if (patch.lab_id !== undefined) {
        const lab = labs.find((item) => item.id === patch.lab_id)

        if (patch.lab_id !== null && !lab) {
          return problem(
            404,
            'Sala no encontrada',
            'La sala indicada no existe.',
            'LAB_NOT_FOUND',
          )
        }

        machine.lab_id = patch.lab_id
        machine.lab = lab?.name ?? null
      }

      if (patch.mode !== undefined) {
        machine.mode = patch.mode
      }

      if (patch.status !== undefined) {
        machine.status = patch.status
      }

      return HttpResponse.json(machine)
    },
  ),
]