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