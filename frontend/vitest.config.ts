import { fileURLToPath } from 'node:url'
import { mergeConfig, defineConfig, configDefaults } from 'vitest/config'
import viteConfig from './vite.config.ts'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/__tests__/setup.ts'],
      exclude: [...configDefaults.exclude, 'e2e/**'],
      root: fileURLToPath(new URL('./', import.meta.url)),
      // En tests usamos localhost:8000 para que los handlers de MSW intercepten
      // correctamente. En Vercel no se define esta variable y el cliente usa ''
      // (mismo origen), que el rewrite del vercel.json redirige a Render.
      env: {
        VITE_API_URL: 'http://localhost:8000',
      },
      coverage: {
        provider: 'v8',
        include: ['src/**/*.{ts,vue}'],
        exclude: ['src/main.ts', 'src/**/__tests__/**'],
        thresholds: { lines: 75, functions: 75, statements: 75, branches: 75 },
      },
    },
  }),
)
