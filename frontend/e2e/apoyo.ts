import type { Page } from '@playwright/test'

export const SESION_ESTUDIANTE = {
  access_token: 'token-de-prueba-no-real',
  token_type: 'Bearer',
  expires_in: 600,
  user: { id: '1', full_name: 'Ana Pérez', role: 'student' },
}

const problema = (code: string) => JSON.stringify({ code })

// Toda llamada a la API sin mock propio responde 404. Los mocks más específicos se
// registran después y tienen prioridad (Playwright usa primero el último registrado).
export async function apiPorDefecto(page: Page) {
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({
      status: 404,
      contentType: 'application/problem+json',
      body: problema('NOT_FOUND'),
    }),
  )
}

// La web intenta recuperar la sesión al arrancar (/auth/refresh): aquí no hay sesión previa.
export async function sinSesionPrevia(page: Page) {
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/problem+json',
      body: problema('AUTH_INVALID_CREDENTIALS'),
    }),
  )
}

export async function loginSimulado(page: Page, sesion = SESION_ESTUDIANTE) {
  await page.route('**/api/v1/auth/login', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(sesion),
    }),
  )
}

export async function iniciarSesionPorFormulario(page: Page) {
  await page.locator('#login-email').fill('ana@universidad.example')
  await page.locator('#login-password').fill('contraseña-de-prueba')
  await page.locator('form button[type="submit"]').click()
}