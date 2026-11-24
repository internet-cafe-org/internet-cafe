import { expect, test, type Page } from '@playwright/test'

import {
  apiPorDefecto,
  iniciarSesionPorFormulario,
  loginSimulado,
  sinSesionPrevia,
} from './apoyo'

// API simulada: verifica el flujo del enlace /s#token en un navegador real.
// Las E2E contra la API real van aparte.

const TOKEN_QR = 'token-qr-de-prueba-123'

const VISTA_PREVIA = {
  machine: { code: 'LAB3-PC12', lab: 'Sala 3 · Bloque B' },
  expires_at: '2026-11-20T14:05:00Z',
  active_session: null,
}

const SESION_CREADA = {
  session: {
    id: 's1',
    status: 'active',
    started_at: '2026-11-20T14:04:21Z',
    machine: { id: 'm1', code: 'LAB3-PC12', lab: 'Sala 3 · Bloque B' },
  },
}

// Simula el escaneo y devuelve lo que la web envió a la API.
async function simularEscaneo(page: Page, claim: { status: number; body: unknown }) {
  const visto = { preview: undefined as { token?: string } | undefined, claims: 0 }

  await apiPorDefecto(page)
  await sinSesionPrevia(page)
  await loginSimulado(page)
  await page.route('**/api/v1/scan/preview', async (route) => {
    visto.preview = route.request().postDataJSON() as { token?: string }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(VISTA_PREVIA),
    })
  })
  await page.route('**/api/v1/scan/claim', async (route) => {
    visto.claims += 1
    await route.fulfill({
      status: claim.status,
      contentType: claim.status < 400 ? 'application/json' : 'application/problem+json',
      body: JSON.stringify(claim.body),
    })
  })
  return visto
}

// Abre el enlace del QR sin sesión: lleva al login y, tras entrar, continúa en /s.
async function abrirEnlaceDelQr(page: Page) {
  await page.goto(`/s#${TOKEN_QR}`)
  await expect(page).toHaveURL(/\/login$/)
  await iniciarSesionPorFormulario(page)
  await expect(page.getByRole('heading', { name: 'Confirmar acceso' })).toBeVisible()
}

test.describe('enlace /s#token (API simulada)', () => {
  test('tras iniciar sesión muestra la vista previa sin crear el acceso', async ({ page }) => {
    const visto = await simularEscaneo(page, { status: 201, body: SESION_CREADA })

    await abrirEnlaceDelQr(page)

    const equipo = page.getByRole('region', { name: 'Datos del equipo' })
    await expect(equipo).toContainText('LAB3-PC12')
    await expect(equipo).toContainText('Sala 3 · Bloque B')
    expect(page.url()).not.toContain(TOKEN_QR)
    expect(visto.preview?.token).toBe(TOKEN_QR)
    expect(visto.claims).toBe(0)
  })

  test('confirmar crea el acceso una sola vez', async ({ page }) => {
    const visto = await simularEscaneo(page, { status: 201, body: SESION_CREADA })

    await abrirEnlaceDelQr(page)
    await page.getByRole('button', { name: 'Confirmar', exact: true }).click()

    await expect(page.getByRole('heading', { name: 'Acceso confirmado' })).toBeVisible()
    await expect(page.getByText('Sesión activa en LAB3-PC12.')).toBeVisible()
    expect(visto.claims).toBe(1)
  })

  test('un QR ya usado muestra el aviso y no confirma', async ({ page }) => {
    const visto = await simularEscaneo(page, {
      status: 409,
      body: { code: 'CHALLENGE_ALREADY_USED' },
    })

    await abrirEnlaceDelQr(page)
    await page.getByRole('button', { name: 'Confirmar', exact: true }).click()

    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Acceso confirmado' })).toHaveCount(0)
    expect(visto.claims).toBe(1)
  })

  test('cancelar no crea el acceso', async ({ page }) => {
    const visto = await simularEscaneo(page, { status: 201, body: SESION_CREADA })

    await abrirEnlaceDelQr(page)
    await page.getByRole('button', { name: 'Cancelar' }).click()

    await expect(page).not.toHaveURL(/\/s$/)
    expect(visto.claims).toBe(0)
  })
})