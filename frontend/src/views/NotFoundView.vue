
<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <main class="view">
    <h1 class="title">Página no encontrada</h1>

    <div class="card box">
      <p class="code">404</p>
      <h2>No encontramos esta página</h2>
      <p class="msg">
        La dirección que abriste no existe o ya no está disponible
      </p>
      <RouterLink to="/" class="btn">
        Volver al inicio
      </RouterLink>
    </div>
  </main>
</template>

<style scoped>
.view {
  --c-text: #0f172a;
  --c-muted: #64748b;
  --c-card: #ffffff;
  --c-card-border: #e2e8f0;
  --c-row: #f1f5f9;
  --c-row-alt: #f8fafc;
  --c-input: #f8fafc;
  --c-input-border: #e2e8f0;
  --c-primary: #2563eb;
  --c-primary-text: #ffffff;
  --c-link: #2563eb;
  --c-icon-bg: #e8effc;
  --c-ok-bg: #dcfce7;
  --c-ok: #15803d;
  --c-warn-bg: #fef6e4;
  --c-warn: #d97706;

  color: var(--c-text);
}

:global(.dark) .view,
:global([data-theme='dark']) .view {
  --c-text: #e2e8f0;
  --c-muted: #94a3b8;
  --c-card: #243049;
  --c-card-border: #31405c;
  --c-row: #1c2740;
  --c-row-alt: #243049;
  --c-input: #0f1729;
  --c-input-border: #31405c;
  --c-primary: #3b82f6;
  --c-link: #60a5fa;
  --c-icon-bg: #1e3a6e;
  --c-ok-bg: #14352b;
  --c-ok: #4ade80;
  --c-warn-bg: #4a4231;
  --c-warn: #f59e0b;
}

.title {
  font-size: 1.5rem;
  font-weight: 700;
  margin: 0 0 0.5rem;
}

.card {
  background: var(--c-card);
  border: 1px solid var(--c-card-border);
  border-radius: 12px;
  padding: 1.25rem;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border: 0;
  border-radius: 8px;
  background: var(--c-primary);
  color: var(--c-primary-text);
  font: inherit;
  font-weight: 600;
  padding: 0.65rem 1rem;
  cursor: pointer;
}

.btn:hover {
  filter: brightness(1.08);
}

.btn:focus-visible,
.link:focus-visible,
input:focus-visible {
  outline: 2px solid var(--c-link);
  outline-offset: 2px;
}

.link {
  background: none;
  border: 0;
  color: var(--c-link);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
}

.box {
  min-height: 410px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 2rem 1.25rem;
}

.code {
  font-size: 3.5rem;
  font-weight: 800;
  line-height: 1;
  margin: 0 0 0.5rem;
  color: var(--c-primary);
}

h2 {
  font-size: 1.4rem;
  font-weight: 700;
  margin: 0 0 0.5rem;
}

.msg {
  color: var(--c-muted);
  font-size: 0.85rem;
  margin: 0 0 1.25rem;
}

.btn {
  text-decoration: none;
  font-size: 0.85rem;
  padding: 0.7rem 2.5rem;
}

@media (max-width: 767px) {
  .box {
    min-height: 370px;
  }

  .code {
    font-size: 3.2rem;
  }

  .btn {
    width: 100%;
    box-sizing: border-box;
  }
}
</style>
