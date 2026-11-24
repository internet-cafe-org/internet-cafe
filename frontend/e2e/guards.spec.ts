import { expect, test } from '@playwright/test'

// Sin sesión no se necesita backend: el guard del router decide en el navegador.
test.describe('guards sin sesión', () => {
  test('una ruta privada redirige al login', async ({ page }) => {
    await page.goto('/history')

    await expect(page).toHaveURL(/\/login$/)
    await expect(page.locator('#login-email')).toBeVisible()
  })

  test('una ruta de administración redirige al login', async ({ page }) => {
    await page.goto('/admin/users')

    await expect(page).toHaveURL(/\/login$/)
    await expect(page.locator('#login-email')).toBeVisible()
  })

  test('el enlace /s#token sin sesión lleva al login y no deja el token en la URL', async ({
    page,
  }) => {
    await page.goto('/s#token-de-prueba-123')

    await expect(page).toHaveURL(/\/login$/)
    expect(page.url()).not.toContain('token-de-prueba-123')
  })

  test('una ruta inexistente no manda al login', async ({ page }) => {
    await page.goto('/esta-ruta-no-existe')

    await expect(page).toHaveURL(/\/esta-ruta-no-existe$/)
    await expect(page.locator('#login-email')).toHaveCount(0)
  })
})