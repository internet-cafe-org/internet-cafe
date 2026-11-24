import { expect, test, type Page } from '@playwright/test'

import { apiPorDefecto } from './apoyo'

// Guards por rol con la API simulada: la web recupera la sesión al arrancar con
// /auth/refresh y toma el rol del payload del access token. El token es falso y sin
// firma válida: el cliente no verifica la firma, solo lee el rol para los guards.

type Rol = 'student' | 'admin'

function base64Url(valor: object) {
  return Buffer.from(JSON.stringify(valor)).toString('base64url')
}

function tokenFalso(rol: Rol) {
  const cabecera = base64Url({ alg: 'ES256', typ: 'JWT' })
  const payload = base64Url({ sub: 'usuario-e2e', role: rol, full_name: 'Usuario de prueba' })
  return `${cabecera}.${payload}.firma-no-real`
}

async function conSesion(page: Page, rol: Rol) {
  await apiPorDefecto(page)
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: tokenFalso(rol),
        token_type: 'Bearer',
        expires_in: 600,
      }),
    }),
  )
}

test.describe('guards por rol (API simulada)', () => {
  test('un estudiante en /admin/users termina en el inicio', async ({ page }) => {
    await conSesion(page, 'student')

    await page.goto('/admin/users')

    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('heading', { name: 'Inicio' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Usuarios' })).toHaveCount(0)
  })

  test('un administrador entra al panel de usuarios', async ({ page }) => {
    await conSesion(page, 'admin')

    await page.goto('/admin/users')

    await expect(page).toHaveURL(/\/admin\/users$/)
    await expect(page.getByRole('heading', { name: 'Usuarios' })).toBeVisible()
  })

  test('un estudiante sí entra a sus rutas privadas', async ({ page }) => {
    await conSesion(page, 'student')

    await page.goto('/history')

    await expect(page).toHaveURL(/\/history$/)
    await expect(page.locator('#login-email')).toHaveCount(0)
  })
})
