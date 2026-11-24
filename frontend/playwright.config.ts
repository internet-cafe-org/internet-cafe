import { defineConfig, devices } from '@playwright/test'

// Sin E2E_BASE_URL, Playwright compila la web y la sirve en local (vite preview).
// Con E2E_BASE_URL (por ejemplo la web de dev en Vercel), prueba contra esa URL.
const urlExterna = process.env.E2E_BASE_URL
const baseURL = urlExterna ?? 'http://localhost:4173'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      // Móvil primero (RNF-USA-01): 360 px de ancho.
      name: 'movil',
      use: { ...devices['Pixel 7'], viewport: { width: 360, height: 740 } },
    },
  ],
  webServer: urlExterna
    ? undefined
    : {
        // Se prueba el sitio compilado: en producción no arranca MSW (solo en `vite dev`),
        // así que page.route puede interceptar la API.
        command: 'npm run build && npm run preview -- --port 4173 --strictPort',
        url: 'http://localhost:4173',
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
        // Mismo origen y sin filtro de dominios, igual que Vercel: no dependen del .env.local de cada quien.
        env: { VITE_API_URL: '', VITE_ALLOWED_EMAIL_DOMAINS: '' },
      },
})