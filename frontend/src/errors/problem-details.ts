/**
 * Estructura estándar de errores RFC 9457.
 */
export interface ProblemDetails {
  type?: string
  title?: string
  status?: number
  detail?: string
  instance?: string
  code?: string
}

/**
 * Error normalizado para utilizarlo en toda la aplicación.
 */
export class ApiError extends Error {
  status: number
  code: string
  type: string
  instance?: string

  constructor(problem: ProblemDetails) {
    super(problem.detail || problem.title || 'Ha ocurrido un error')

    this.name = 'ApiError'
    this.status = problem.status || 500
    this.code = problem.code || 'UNKNOWN_ERROR'
    this.type = problem.type || 'about:blank'
    this.instance = problem.instance
  }
}

/**
 * Convierte una respuesta de error en un ApiError.
 * Reconoce RFC 9457 y el formato actual de FastAPI.
 */
export function normalizeApiError(status: number, data: unknown): ApiError {
  if (typeof data !== 'object' || data === null) {
    return new ApiError({ status })
  }

  const response = data as Record<string, unknown>

  // Formato RFC 9457.
  if (
    typeof response.title === 'string' ||
    typeof response.type === 'string' ||
    typeof response.instance === 'string'
  ) {
    return new ApiError({
      type: typeof response.type === 'string' ? response.type : undefined,
      title: typeof response.title === 'string' ? response.title : undefined,
      status: typeof response.status === 'number' ? response.status : status,
      detail: typeof response.detail === 'string' ? response.detail : undefined,
      instance: typeof response.instance === 'string' ? response.instance : undefined,
      code: typeof response.code === 'string' ? response.code : undefined,
    })
  }

  // Formato actual de FastAPI.
  const detail = response.detail

  if (typeof detail === 'object' && detail !== null) {
    const fastApiDetail = detail as Record<string, unknown>

    return new ApiError({
      status,
      code: typeof fastApiDetail.code === 'string' ? fastApiDetail.code : undefined,
      detail: typeof fastApiDetail.message === 'string' ? fastApiDetail.message : undefined,
    })
  }

  // Error con detail como texto.
  return new ApiError({
    status,
    detail: typeof detail === 'string' ? detail : undefined,
  })
}
