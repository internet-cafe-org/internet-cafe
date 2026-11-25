# Plan de pruebas de aceptación (QA-08)

Cómo se demuestra que el MVP cumple los escenarios E-01 a E-06 del SRS (§4.2), con las
desviaciones aprobadas en el backlog (§4). Historia HU-23.

| Uso | Cuándo | Entorno | Tarea |
|---|---|---|---|
| Pre-aceptación | lun 30/11 | dev | QA-15 |
| Aceptación | mié 2/12 y jue 3/12 | producción (`v1.0.0-beta`) | QA-11 |

La pre-aceptación sirve para ensayar este plan y corregir defectos antes de producción. Los
resultados de las dos se registran con la plantilla de la sección 6.

## 1. Criterios de salida

Se toman del SRS §15.4, ajustados al MVP:

1. Los seis escenarios E-01 a E-06 pasan en el piloto, con las desviaciones de la sección 3.
2. Todos los requisitos **Debe** que tocan los escenarios tienen evidencia (casos de la sección 4).
3. Cero defectos **críticos** o **altos** abiertos (sección 7).
4. Los tiempos de la sección 5 se cumplen.

El punto 5 del SRS §15.4 (una semana dentro de las cuotas gratuitas) queda fuera del MVP
(backlog §4, recortes).

## 2. Configuración del piloto

### Equipos

| Equipo | Modo | Windows | Para qué |
|---|---|---|---|
| PC-A | pasivo | 10 (22H2) | E-02, E-03, E-04 (cierre desde el PC) |
| PC-B | pasivo | 11 | E-03 (segundo equipo), E-04 (apagado) |
| PC-C | kiosco | 11 o 10 | E-02 en kiosco, E-05 |

- Los tres en salas reales del piloto (PEND-07), creadas con la semilla del piloto (QA-02b) o
  desde el panel (UI-11).
- Instalados con el `.msi` del release (OPS-14) y enrolados con un código de un solo uso.
- Reloj de Windows sincronizado (S-05) y salida HTTPS al puerto 443 (S-03).
- Cuenta de Windows **sin** privilegios de administrador para los estudiantes (S-04).

### Personas y datos

- **Al menos 10 estudiantes** con celular propio (SRS §15.4): 5 en iOS (Safari) y 5 en Android
  (Chrome), para cubrir RNF-POR-02.
- Un administrador creado con `create-admin` (BE-20).
- Cuentas de **prueba**: correos del dominio institucional permitido, sin datos de personas reales
  en dev. En producción los participantes aceptan el tratamiento de datos al registrarse (RF-AUT-01).
- Ninguna contraseña, código de enrolamiento ni token se escribe en el registro de resultados.

### Material

- Un teléfono adicional que grabe video a **60 fps** (sección 5).
- Un cronómetro.
- Acceso al log de la aplicación de escritorio de cada PC (DSK-08).

## 3. Desviaciones que aplican

Antes de cada sesión se revisa en GitHub qué historias **Debería** quedaron cerradas. La columna
"Si no entró" es lo que se acepta según el backlog §4.

| Escenario | SRS | Si no entró | Historia que lo completa |
|---|---|---|---|
| E-01 | Registro con código de 6 dígitos | Registro sin OTP: la API responde 202 y la web inicia sesión sola; si falla, muestra un mensaje genérico y el enlace "Iniciar sesión" | HU-24 |
| E-02 | El PC muestra los últimos accesos | El PC muestra nombre, código enmascarado, hora de inicio y cronómetro | HU-11 |
| E-04 | Cierre al apagar con `machine_shutdown` | Lo cubre el cierre por inactividad (3 min) | HU-34 |
| E-06 | Filtra y exporta a CSV | Filtra y consulta, sin exportar | HU-33 |
| Kiosco | No se oculta con Alt+Tab ni la tecla Windows | Bloquea Alt+F4, cerrar y minimizar; Alt+Tab, la tecla Windows y Ctrl+Alt+Supr son limitación documentada | — |
| Tiempos | Detección en el PC ≤ 60 s | ≤ 65 s (latido de 60 s más la red) | — |

## 4. Casos

Cada caso se ejecuta en orden. "Resultado esperado" es lo que debe verse; cualquier diferencia es un
defecto (sección 7).

### E-01 · Primer uso (registro)

**Requisitos:** RF-AUT-01, RF-AUT-05, RF-AUT-11, RNF-PRI-01.
**Precondición:** el estudiante no tiene cuenta.

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Abrir la web en el celular e ir a "Crear una cuenta" | Formulario con correo, código, nombre, contraseña y aceptación del tratamiento de datos |
| 2 | Enviar con un correo de un dominio no permitido | Error de validación; no se crea la cuenta |
| 3 | Enviar con una contraseña de 9 caracteres | Error de validación por la longitud (10 a 128) |
| 4 | Enviar sin aceptar el tratamiento de datos | No deja continuar |
| 5 | Tocar "Crear cuenta" con datos válidos | Sin HU-24: "Registro exitoso. Iniciando sesión automáticamente..." y queda con la sesión web iniciada. Con HU-24: pide el código de 6 dígitos |
| 6 | Registrar otra vez el mismo correo | Respuesta genérica; no revela que el correo existe y no crea otra cuenta |

### E-02 · Registro de acceso habitual

**Requisitos:** RF-QR-01, RF-QR-02, RF-QR-06, RF-QR-07, RF-QR-09, RF-EQU-09, RNF-USA-04.
**Precondición:** sesión web activa en el celular; PC-A muestra el QR.

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Mirar el PC | QR con código del equipo, sala y cuenta regresiva; se renueva cada 45 s |
| 2 | Escanear con la cámara nativa | Abre la web en `/s` con "Confirmar acceso" y los datos del equipo (equipo, código y sala), sin crear la sesión |
| 3 | Tocar "Confirmar" | "Acceso confirmado" y "Tu acceso se registró correctamente." |
| 4 | Mirar el PC | En menos de 1 s (sección 5): nombre, código enmascarado (nunca el completo ni el correo), hora de inicio y cronómetro. Con HU-11: los últimos 5 accesos |
| 5 | Repetir en PC-C (kiosco) | Antes de confirmar, la ventana ocupa la pantalla y no se cierra con Alt+F4; después de confirmar el equipo queda libre |
| 6 | Escanear un QR con más de 60 s | "QR vencido" y "Este código QR venció. Escanea el código nuevo que aparece en el equipo."; no se crea sesión |
| 7 | Escanear un QR que ya usó otra persona | "QR ya utilizado" y "Este código QR ya fue utilizado. Escanea el código nuevo del equipo."; no se crea sesión |

### E-03 · Cambio de equipo

**Requisitos:** RF-SES-02, RF-QR-06, RN-03.
**Precondición:** el estudiante tiene una sesión activa en PC-A.

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Escanear el QR de PC-B | La vista previa muestra "Cambio de sesión activa" y "Tienes una sesión activa en <PC-A>. Al confirmar, se cerrará esa sesión y se iniciará una nueva en este equipo." |
| 2 | Confirmar | Se abre la sesión en PC-B |
| 3 | Mirar PC-A | Vuelve al QR en 65 s o menos (sección 5) |
| 4 | Revisar el historial en la web | La sesión de PC-A aparece cerrada |

### E-04 · Cierre

**Requisitos:** RF-SES-04 a RF-SES-07, RF-SES-09, RF-EQU-10.

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | En PC-A, tocar "Cerrar sesión" | El PC vuelve al QR; en la web la sesión queda cerrada |
| 2 | Abrir otra sesión y cerrarla desde la web con "Terminar acceso" | El PC vuelve al QR en 65 s o menos; "Terminar acceso" no cierra la sesión web |
| 2b | En el perfil, tocar "Cerrar sesión web" teniendo un acceso activo | La web pide iniciar sesión de nuevo, pero el acceso en el PC sigue abierto ("Cerrar sesión web no termina el acceso que pueda seguir activo en un computador.") |
| 3 | Abrir otra sesión en PC-B y apagar Windows normalmente | Con HU-34: la sesión queda cerrada con motivo `machine_shutdown` |
| 4 | Abrir otra sesión en PC-B y desconectar la red (o cortar la energía) | La sesión se cierra sola en unos 3 min (hasta unos 3 min 30 s) y su hora de fin es la del último latido |

### E-05 · Alta de equipos

**Requisitos:** RF-ADM-02, RF-ADM-03, RF-EQU-01, RF-EQU-05, RF-ADM-09.
**Precondición:** sesión de administrador en el panel; PC-C sin la aplicación.

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Crear el equipo en el panel con su sala y modo kiosco | Aparece en la lista como pendiente de enrolamiento |
| 2 | Generar el código de enrolamiento | Se muestra una sola vez; vence en 24 h |
| 3 | Instalar el `.msi` en PC-C e ingresar el código | El equipo pasa a activo y muestra el QR en modo kiosco |
| 4 | Ingresar otra vez el mismo código en otro PC | Lo rechaza (código ya usado) |
| 5 | Cambiar el modo de PC-C a pasivo desde el panel | El PC lo aplica en 65 s o menos sin reinstalar |
| 6 | Revisar la auditoría | Cada acción del administrador quedó registrada, sin datos personales |

### E-06 · Consulta (y exportación)

**Requisitos:** RF-ADM-05, RF-ADM-06.
**Precondición:** existen las sesiones de E-02 a E-04.

| # | Paso | Resultado esperado |
|---|---|---|
| 1 | Filtrar los accesos por sala y por rango de fechas | Solo aparecen las sesiones de esa sala y ese rango |
| 2 | Filtrar por un estudiante con su correo exacto | Aparecen sus sesiones; una búsqueda parcial no devuelve resultados |
| 3 | Con HU-33: exportar a CSV | CSV en UTF-8 con BOM, separado por comas, con las columnas del RF-ADM-06 y horas en la zona de la universidad |

## 5. Medición de tiempos

| Qué | Meta | Método |
|---|---|---|
| Confirmar → tablero en el PC | p95 ≤ 1 s (RF-QR-09, RNF-REN-02) | Video a **60 fps** que muestre a la vez el celular y la pantalla del PC. **20 corridas en caliente** (la API ya despierta). En cada una se cuentan los cuadros entre el toque de "Confirmar" y el tablero visible, y se divide entre 60. Se ordenan las 20 medidas y el **p95 es la corrida 19** |
| Escaneo → tablero (con sesión web activa) | Mediana ≤ 10 s (O-01) | Las mismas 20 corridas, desde que la cámara enfoca el QR hasta el tablero. Mediana = promedio de las medidas 10 y 11 ordenadas |
| Cierre remoto o cambio de modo → PC | ≤ 65 s | Cronómetro desde el toque en la web o el panel hasta el cambio en el PC, contrastado con la línea `Cierre remoto detectado: sesion=..., motivo=..., a las ...` del log de la aplicación (DSK-08) |
| Cierre por inactividad | ≈ 3 min (hasta 3 min 30 s) | Hora de la desconexión contra la hora en que la sesión aparece cerrada en el panel |

"En caliente" significa que la API respondió en los 10 minutos anteriores. La primera petición
después de una suspensión de Render no cuenta como corrida.

## 6. Registro de resultados

Una fila por paso ejecutado. No se registran contraseñas, códigos de enrolamiento, tokens ni datos
personales.

| Caso y paso | Equipo | Navegador y versión | Resultado (pasa / falla / bloqueado) | Evidencia (video, captura, línea de log) | Defecto |
|---|---|---|---|---|---|
| E-02 · 4 | PC-A | Safari iOS 17 | | | |

Para los tiempos se guarda la tabla de las 20 corridas con la medida de cada una.

## 7. Defectos

Cada defecto se abre como issue con el caso y el paso, lo esperado, lo obtenido y la evidencia.

| Severidad | Criterio | Ejemplo |
|---|---|---|
| Crítica | Impide completar un escenario o pone en riesgo datos o seguridad | No se puede confirmar ningún acceso |
| Alta | Un requisito Debe no se cumple y no hay alternativa | El PC no vuelve al QR tras un cierre remoto |
| Media | Se cumple con una alternativa o fuera del tiempo meta | El tablero tarda 1,5 s en el p95 |
| Baja | Textos, estilo o detalles sin efecto en el escenario | Una tilde faltante en un mensaje |

Durante la semana del 30/11 los defectos se revisan cada día en el triaje (PO y líder de Seguridad y
Testing). Un escenario solo cuenta como aprobado si no le queda ningún defecto crítico ni alto.
