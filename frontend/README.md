# Frontend · Registro de acceso a equipos por QR

Vue 3 + Vite + TypeScript + Vue Router + Pinia + PrimeVue. Ver SRS-IC-001 §7 y §9.1.

## Requisitos
Node 22.18+ (o 24.12+) y npm.

## Arranque
```bash
cd frontend
npm install
npm run dev
```

## Scripts
| Comando | Qué hace |
|---|---|
| `npm run dev` | Servidor de desarrollo |
| `npm run build` | Type-check y build de producción |
| `npm run lint` | ESLint (0 warnings permitidos) |
| `npm run format` / `format:check` | Prettier |
| `npm run type-check` | `vue-tsc` |
| `npm test` / `npm run test:cov` | Vitest (cobertura mínima 75 %) |

## Estructura
- `src/api/` cliente HTTP; el access token vive solo aquí (nunca en localStorage ni Pinia).
- `src/stores/` Pinia; solo nombre y rol del usuario.
- `src/router/` rutas y guards (`public` / `user` / `admin`).
- `src/views/` pantallas W-01 a W-13 (placeholders hasta tener mockups, PEND-01).

## Reglas
Mobile-first desde 360 px, interfaz en español, sin secretos en el repo.

---

## Despliegue en Vercel (OPS-04)

El proyecto se despliega en Vercel desde la raíz `frontend/`. La configuración está
en [`vercel.json`](./vercel.json).

### Cómo funciona el routing de API

El cliente HTTP no tiene URL del backend hardcodeada. En desarrollo local usa
`VITE_API_URL=http://localhost:8000` (definido en `.env.local`). En Vercel esa
variable no existe, así que el cliente apunta a mismo origen (`''`) y el rewrite
del `vercel.json` se encarga de reenviar `/api/*` al backend en Render:

```
Navegador → https://internet-cafe-dev.vercel.app/api/v1/... 
  → Vercel rewrite →
    https://internet-cafe-backend-dev.onrender.com/api/v1/...
```

### Configurar el proyecto en Vercel

1. Crear un proyecto nuevo en [vercel.com](https://vercel.com) e importar el repo `internet-cafe-org/internet-cafe`.
2. En **Build & Development Settings** → **Root Directory**: `frontend`.
3. Vercel detecta el `vercel.json` y aplica rewrites, cabeceras e Ignored Build Step automáticamente.
4. **Auto-deploy**: activo por defecto para la rama principal. Las ramas de feature generan previews.
5. No hace falta definir variables de entorno: `VITE_API_URL` solo se usa en desarrollo local.

### Previews sin contraseña (PEND-03)

Por defecto Vercel protege las previews con autenticación de Vercel (requiere cuenta).
Para desactivarla y que cualquier colaborador pueda ver el preview sin login:

1. Ir a **Vercel Dashboard → proyecto → Settings → Deployment Protection**.
2. En la sección **Vercel Authentication**, desactivar la protección para **Preview** deployments.
3. Guardar. Las nuevas previews serán accesibles públicamente sin necesidad de cuenta Vercel.

> **Nota:** el campo `"public": true` en `vercel.json` **no** configura esto; lo que hace
> es exponer `/_src` (código fuente) y `/_logs` (logs de build). Por eso no se usa.

### Ignored Build Step

El `ignoreCommand` del `vercel.json` hace que Vercel saltee el build si el único
cambio es en archivos `.md` o en la carpeta `docs/`. Así los commits de documentación
no consumen minutos de build innecesarios.

### Content Security Policy

Las cabeceras CSP permiten `style-src 'self' 'unsafe-inline'` porque PrimeVue
inyecta estilos inline en algunos componentes. El resto de directivas son restrictivas
(`default-src 'self'`, `frame-ancestors 'none'`, etc.).

Si en el futuro se integra un lector de QR basado en WebAssembly o Web Workers,
habrá que agregar `worker-src 'self'` y posiblemente `'wasm-unsafe-eval'` a la CSP.
Verificarlo en el preview antes de fusionar.
