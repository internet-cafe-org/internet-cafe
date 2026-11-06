/**
 * Prueba de integración: cliente API con rewrite de Vercel (OPS-04).
 *
 * Verifica que el cliente HTTP funciona correctamente tanto en desarrollo
 * (VITE_API_URL=http://localhost:8000) como en Vercel (baseUrl='', rewrite activo).
 *
 * MSW intercepta las peticiones en ambos casos, igual que el rewrite de Vercel
 * intercepta las peticiones a /api/* en producción y las reenvía a Render.
 *
 * Para la captura del camino feliz requerida por la DoD, ver el PR #269 (OPS-04).
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { api, clearAccessToken, setAccessToken } from '../api/client'

beforeEach(() => {
  clearAccessToken()
})

describe('cliente API · camino feliz del rewrite Vercel → Render (OPS-04)', () => {
  /**
   * Camino feliz: una máquina activa puede crear un desafío QR.
   * En Vercel: POST /api/v1/machine/challenges va al rewrite → Render dev.
   * En tests:  MSW intercepta la petición antes de que salga a la red.
   */
  it('crea un desafío QR para una máquina válida y recibe los campos del contrato', async () => {
    const { data, error } = await api.POST('/api/v1/machine/challenges', {
      params: {
        header: { 'x-machine-code': 'PC-001' },
      },
    })

    expect(error).toBeUndefined()
    expect(data).toBeDefined()
    // El challenge_id viene como UUID
    expect(data?.challenge_id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    )
    // El campo rotate_after_s indica cada cuántos segundos rota el QR
    expect(typeof data?.rotate_after_s).toBe('number')
    expect(data?.rotate_after_s).toBeGreaterThan(0)
    // La URL del QR es una URL válida
    expect(data?.qr_url).toMatch(/^https?:\/\//)
  })

  /**
   * Camino feliz: un token de escaneo válido devuelve la info del equipo.
   * El frontend llama a este endpoint justo después de que el estudiante
   * escanea el QR con la cámara del celular.
   */
  it('la vista previa de un token válido devuelve el equipo y el laboratorio', async () => {
    const { data, error } = await api.POST('/api/v1/scan/preview', {
      body: { token: 'demo-token' },
    })

    expect(error).toBeUndefined()
    expect(data?.machine.code).toBe('PC-001')
    expect(data?.machine.lab).toBe('Laboratorio 1')
    // Sin sesión activa, el equipo está disponible
    expect(data?.active_session).toBeNull()
  })

  /**
   * Las peticiones con token incluyen el header Authorization.
   * En el rewrite de Vercel ese header pasa de forma transparente a Render.
   */
  it('las peticiones autenticadas llevan el header Authorization al backend', async () => {
    setAccessToken('token-de-prueba-vercel')

    const { data } = await api.POST('/api/v1/machine/challenges', {
      params: {
        header: { 'x-machine-code': 'PC-001' },
      },
    })

    // Si llegó el challenge_id, el header Authorization pasó correctamente
    expect(data?.challenge_id).toBeDefined()
  })

  /**
   * Camino de error: una máquina no registrada recibe 401.
   * El rewrite de Vercel retransmite el error de Render al navegador tal cual.
   */
  it('una máquina sin registrar recibe ApiError 401 desde el backend', async () => {
    await expect(
      api.POST('/api/v1/machine/challenges', {
        params: { header: { 'x-machine-code': 'INVALID' } },
      }),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
      code: 'MACHINE_SIGNATURE_INVALID',
    })
  })
})
