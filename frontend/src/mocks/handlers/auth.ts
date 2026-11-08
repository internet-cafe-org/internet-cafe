
import { http, HttpResponse } from 'msw'

const API_URL = 'http://localhost:8000'

export const authHandlers = [
  // Renovar access token (simulación MSW).
  http.post(`${API_URL}/api/v1/auth/refresh`, () => {
    return HttpResponse.json(
      {
        access_token: 'mock-access-token-renovado',
        token_type: 'bearer',
        expires_in: 600,
      },
      {
        status: 200,
        headers: {
          'Cache-Control': 'no-store',
        },
      },
    )
  }),
]
