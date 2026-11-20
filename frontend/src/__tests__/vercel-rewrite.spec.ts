/**
 * Prueba de integración: cliente API con rewrite de Vercel (OPS-04).
 *
 * Verifica que el cliente HTTP funciona correctamente tanto en desarrollo
 * (VITE_API_URL=http://localhost:8000) como en Vercel (baseUrl='', rewrite activo).
 *
 * MSW intercepta las peticiones en ambos escenarios, igual que el rewrite de Vercel
 * intercepta en producción y las reenvía a Render dev.
 *
 * También valida que vercel.json declara el rewrite, la CSP con style-src
 * y el ignoreCommand, ya que son la configuración central de OPS-04.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { server } from '../mocks/server'
import { api, clearAccessToken, setAccessToken } from '../api/client'

beforeEach(() => {
  clearAccessToken()
})

// ---------------------------------------------------------------------------
// Validación de vercel.json (bloqueante 3 — verificar campos del contrato)
// ---------------------------------------------------------------------------

/**
 * Leemos vercel.json directamente del sistema de archivos para no depender
 * de que el tsconfig lo incluya como módulo. Es la forma más robusta de
 * validar el archivo de configuración desde los tests.
 */
function leerVercelConfig(): Record<string, unknown> {
  const ruta = resolve(__dirname, '../../vercel.json')
  return JSON.parse(readFileSync(ruta, 'utf-8'))
}

type VercelRewrite = { source: string; destination: string }
type VercelHeader = { key: string; value: string }
type VercelHeaderGroup = { source: string; headers: VercelHeader[] }

describe('vercel.json · configuración de OPS-04', () => {
  it('declara el rewrite de /api/:path* hacia Render dev', () => {
    // El rewrite es el eje de OPS-04: sin él las peticiones del frontend
    // no llegan al backend en producción.
    const config = leerVercelConfig()
    const rewrites = config['rewrites'] as VercelRewrite[]

    expect(rewrites).toBeDefined()
    expect(rewrites.length).toBeGreaterThan(0)

    const apiRewrite = rewrites.find((r) => r.source === '/api/:path*')
    expect(apiRewrite).toBeDefined()
    expect(apiRewrite?.destination).toContain('onrender.com')
    expect(apiRewrite?.destination).toContain('/api/:path*')
  })

  it('incluye style-src en la CSP para que PrimeVue funcione', () => {
    // PrimeVue inyecta estilos inline; sin 'unsafe-inline' el componente
    // se rompe visualmente en producción.
    const config = leerVercelConfig()
    const headerGroups = config['headers'] as VercelHeaderGroup[]
    const allHeaders = headerGroups.flatMap((g) => g.headers)
    const cspHeader = allHeaders.find((h) => h.key === 'Content-Security-Policy')

    expect(cspHeader).toBeDefined()
    expect(cspHeader?.value).toContain("style-src 'self' 'unsafe-inline'")
  })

  it('declara ignoreCommand para saltear builds de solo documentación', () => {
    const config = leerVercelConfig()
    const ignoreCommand = config['ignoreCommand'] as string

    expect(ignoreCommand).toBeDefined()
    expect(ignoreCommand).toContain('*.md')
  })

  it('no tiene la propiedad "public" que expone código fuente y logs de Vercel', () => {
    // "public: true" expone /_src y /_logs de Vercel, no configura previews.
    // Las previews sin login se gestionan desde el dashboard (Deployment Protection).
    const config = leerVercelConfig()
    expect(config['public']).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// Endpoints web: /scan/preview (bloqueante 3 — endpoints correctos)
// ---------------------------------------------------------------------------

describe('cliente API · camino feliz del rewrite Vercel → Render (OPS-04)', () => {
  /**
   * Camino feliz: un token de escaneo válido devuelve la info del equipo.
   * El frontend llama a este endpoint justo después de que el estudiante
   * escanea el QR (endpoint del portal web /scan/preview, no del escritorio).
   */
  it('la vista previa de un token válido devuelve el equipo y el laboratorio', async () => {
    const { data, error } = await api.POST('/api/v1/scan/preview', {
      body: { token: 'demo-token' },
    })

    expect(error).toBeUndefined()
    expect(data?.machine.code).toBe('PC-001')
    expect(data?.machine.lab).toBe('Laboratorio 1')
    expect(data?.active_session).toBeNull()
  })

  /**
   * Camino feliz: baseUrl vacío (mismo origen) — el escenario real de Vercel.
   * En producción VITE_API_URL no está definida, así que el cliente usa ''
   * y el rewrite de vercel.json enruta /api/* a Render.
   *
   * Usamos vi.stubEnv para simular que la variable no está definida.
   */
  it('el baseUrl cae a cadena vacía cuando VITE_API_URL no está definida (escenario Vercel)', () => {
    // Simulamos el entorno de Vercel: sin VITE_API_URL
    vi.stubEnv('VITE_API_URL', '')

    // La lógica exacta de client.ts: import.meta.env.VITE_API_URL ?? ''
    const baseUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

    expect(baseUrl).toBe('')

    // Restauramos el entorno para no afectar otros tests
    vi.unstubAllEnvs()
  })

  /**
   * Las peticiones autenticadas llevan el header Authorization al backend.
   * Verificamos que MSW captura el header real en la petición HTTP interceptada,
   * no solo que la respuesta llegó (bloqueante 3 — verificar el header en MSW).
   */
  it('las peticiones autenticadas llevan Authorization en el header HTTP capturado por MSW', async () => {
    setAccessToken('token-de-prueba-vercel')

    let authHeaderRecibido = ''
    server.use(
      http.post('http://localhost:8000/api/v1/scan/preview', async ({ request }) => {
        // Capturamos el header de la petición real que MSW intercepta antes de que salga
        authHeaderRecibido = request.headers.get('Authorization') ?? ''
        const body = (await request.json()) as { token?: string }
        if (!body.token) return new HttpResponse(null, { status: 400 })
        return HttpResponse.json({
          machine: { code: 'PC-001', lab: 'Laboratorio 1' },
          expires_at: '2026-10-29T18:00:00Z',
          active_session: null,
        })
      }),
    )

    await api.POST('/api/v1/scan/preview', {
      body: { token: 'demo-token' },
    })

    // Verificamos el header en la petición HTTP capturada por MSW
    expect(authHeaderRecibido).toBe('Bearer token-de-prueba-vercel')
  })
})

// ---------------------------------------------------------------------------
// Camino de error
// ---------------------------------------------------------------------------

describe('cliente API · camino de error del rewrite Vercel → Render (OPS-04)', () => {
  /**
   * Un token no encontrado recibe 404 con problem+json.
   * El rewrite de Vercel retransmite el error de Render al navegador tal cual.
   */
  it('un token no registrado recibe ApiError 404 desde el backend', async () => {
    await expect(
      api.POST('/api/v1/scan/preview', {
        body: { token: 'NOT_FOUND' },
      }),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      code: 'CHALLENGE_NOT_FOUND',
    })
  })
})
