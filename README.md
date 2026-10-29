# internet-cafe

## Desktop API configuration

The desktop client reads `API_BASE_URL` from its runtime environment, so each deployment profile (development, staging, or production) can provide its own API origin without changing the build. The local default is `http://localhost:8000`; the client appends `/api/v1` for contract endpoints and uses `/healthz` for the health check. For compatibility, the JVM property `api.base.url` takes precedence over `API_BASE_URL`. Set the URL to the API origin, without a query string or fragment.