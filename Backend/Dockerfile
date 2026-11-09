FROM python:3.11-slim

WORKDIR /backend

# Instalar dependencias del sistema necesarias para psycopg2 y compilación
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código del backend
COPY . .

# Establecer PYTHONPATH para que Python reconozca 'app' desde cualquier ruta
ENV PYTHONPATH=/backend

# Comando de arranque: un solo worker para el plan free de Render dev.
# El puerto lo inyecta Render mediante la variable de entorno $PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
