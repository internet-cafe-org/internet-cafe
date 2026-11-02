<template>
  <div class="auth-page">
    <header class="auth-header">
      <span class="auth-header__icon pi pi-qrcode" aria-hidden="true"></span>
      <div>
        <p class="auth-header__title">Acceso universitario</p>
        <p class="auth-header__subtitle">Registro de equipos · QR</p>
      </div>
    </header>
    <main class="auth-main">
      <section class="auth-card">
        <slot />
      </section>
      <p class="auth-footer">Servicio de acceso a computadores</p>
    </main>
  </div>
</template>

<style>
.auth-page {
  --auth-identity: #19365c;
  --auth-action: #2563eb;
  --auth-bg: #f5f8fc;
  --auth-border: #d7e0ec;
  --auth-text-muted: #52647a;
  --auth-error: #b42318;
  --auth-success: #167044;
  --auth-warning: #805500;
  min-height: 100vh;
  background: var(--auth-bg);
  color: var(--auth-identity);
  font-family:
    Inter,
    system-ui,
    -apple-system,
    'Segoe UI',
    Roboto,
    sans-serif;
  font-size: 14px;
  line-height: 1.5;
}
.auth-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: #fff;
  border-bottom: 1px solid var(--auth-border);
}
.auth-header__icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: #edf2fb;
}
.auth-header__title {
  margin: 0;
  font-weight: 600;
}
.auth-header__subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--auth-text-muted);
}
.auth-main {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px 16px 32px;
}
.auth-card {
  box-sizing: border-box;
  width: 100%;
  max-width: 480px;
  padding: 20px;
  background: #fff;
  border: 1px solid var(--auth-border);
  border-radius: 12px;
}
.auth-card h1 {
  margin: 0 0 4px;
  font-size: 22px;
  line-height: 1.3;
  font-weight: 700;
}
.auth-lead {
  margin: 0 0 16px;
  color: var(--auth-text-muted);
}
.auth-footer {
  margin: 16px 0 0;
  font-size: 12px;
  color: var(--auth-text-muted);
}
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.auth-button {
  min-height: 48px;
  border: 0;
  border-radius: 8px;
  background: var(--auth-action);
  color: #fff;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.auth-button:focus-visible {
  outline: 2px solid var(--auth-action);
  outline-offset: 2px;
}
.auth-button:disabled {
  background: #e8edf4;
  color: #7a8799;
  cursor: not-allowed;
}
.auth-switch {
  margin: 0;
  text-align: center;
}
.auth-switch a {
  display: block;
  color: var(--auth-action);
  font-weight: 600;
  text-decoration: none;
}
.auth-switch a:focus-visible {
  outline: 2px solid var(--auth-action);
  outline-offset: 2px;
}
.auth-banner {
  margin: 0 0 16px;
  padding: 12px;
  border-radius: 8px;
}
.auth-banner p {
  margin: 0;
}
.auth-banner--error {
  background: #fff2f0;
  color: var(--auth-error);
}
.auth-banner--success {
  background: #edf8f1;
  color: var(--auth-success);
  font-weight: 600;
}
.auth-banner--warning {
  background: #fff7db;
  color: var(--auth-warning);
}
</style>
