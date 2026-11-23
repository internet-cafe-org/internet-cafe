import { expect, test, type Page } from '@playwright/test'

// Estas pruebas SIMULAN la API con page.route: verifican el flujo en el navegador
// (formulario, redirección y dónde queda el token). Las E2E contra la API real van aparte.

const SESION = {
  access_token: 'token-de-prueba-no-real',
  token_type: 'Bearer',
  expires_in: 600,
  user: { id: '1', full_name: 'Ana Pérez', role: 'student' },
}

// La web intenta recuperar la sesión al arrancar (/auth/refresh): aquí no hay sesión previa.
async function sinSesionPrevia(page: Page) {
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/problem+json',
      body: JSON.stringify({ code: 'AUTH_INVALID_CREDENTIALS' }),
    }),
  )
}

test.describe('login (API simulada)', () => {
  test('camino feliz: sale del login y no guarda el token en el almacenamiento', async ({
    page,
  }) => {
    await sinSesionPrevia(page)
    const capturado: { cuerpo?: { email: string; password: string } } = {}
    await page.route('**/api/v1/auth/login', async (route) => {
      capturado.cuerpo = route.request().postDataJSON() as { email: string; password: string }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SESION),
      })
    })

    await page.goto('/login')
    await page.locator('#login-email').fill('ana@universidad.example')
    await page.locator('#login-password').fill('contraseña-de-prueba')
    await page.locator('form button[type="submit"]').click()

    await expect(page).not.toHaveURL(/\/login$/)
    expect(capturado.cuerpo?.email).toBe('ana@universidad.example')

    const almacenado = await page.evaluate(() =>
      JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]),
    )
    expect(almacenado).not.toContain(SESION.access_token)
  })

  test('credenciales incorrectas: se queda en el login', async ({ page }) => {
    await sinSesionPrevia(page)
    await page.route('**/api/v1/auth/login', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/problem+json',
        body: JSON.stringify({ code: 'AUTH_INVALID_CREDENTIALS' }),
      }),
    )

    await page.goto('/login')
    await page.locator('#login-email').fill('ana@universidad.example')
    await page.locator('#login-password').fill('contraseña-incorrecta')
    const respuesta = page.waitForResponse('**/api/v1/auth/login')
    await page.locator('form button[type="submit"]').click()
    await respuesta

    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('alert')).toContainText(
      'El correo o la contraseña son incorrectos',
    )
  })
})

test.describe('registro (API simulada)', () => {
  test('camino feliz: envía el registro con consentimiento y entra solo', async ({ page }) => {
    await sinSesionPrevia(page)
    const capturado: { registro?: Record<string, unknown> } = {}
    await page.route('**/api/v1/auth/register', async (route) => {
      capturado.registro = route.request().postDataJSON() as Record<string, unknown>
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'Solicitud recibida.' }),
      })
    })
    await page.route('**/api/v1/auth/login', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SESION),
      }),
    )

    await page.goto('/register')
    await page.locator('#register-name').fill('Andrea Martínez López')
    await page.locator('#register-code').fill('202610248')
    await page.locator('#register-email').fill('andrea@universidad.example')
    await page.locator('#register-password').fill('contraseña-de-prueba')
    await page.locator('input[type="checkbox"]').check()
    await page.locator('form button[type="submit"]').click()

    await expect(page).not.toHaveURL(/\/register$/)
    expect(capturado.registro).toMatchObject({
      email: 'andrea@universidad.example',
      student_code: '202610248',
      full_name: 'Andrea Martínez López',
      privacy_consent: true,
    })
  })
})