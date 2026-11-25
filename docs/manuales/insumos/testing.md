# Insumos de Testing para los manuales (QA-19)

Contenido para los manuales del estudiante, del administrador y de TI que redacta el Scrum Master
(SM-01 y SM-02): preguntas frecuentes, problemas conocidos y una lista para validar el manual en la
regresión. Sale de lo que cubren las pruebas (QA-04, QA-05, QA-07a, QA-10) y de los límites
aprobados del MVP (backlog §4). Los mensajes están copiados del código, tal como aparecen en
pantalla.

Las reglas visibles, los códigos de error y el CLI están en `backend.md` (BE-22). Las pantallas y sus
capturas las entregan UI (UI-13) y Desktop (DSK-16).

Los textos entre «» son mensajes de la aplicación, y la prueba
`Backend/tests/unit/test_insumos_testing.py` comprueba que sigan existiendo en el código de la web o
del escritorio; `<equipo>` marca un dato que cambia. Los textos entre comillas normales son de
Windows u otros programas.

## 1. Preguntas frecuentes del estudiante

| Pregunta | Qué ve | Qué hacer | Comprobado en |
|---|---|---|---|
| ¿Cómo registro mi acceso? | En la web: «Busca el código QR en la pantalla del computador.», «Escanéalo con la cámara de tu celular.», «Revisa los datos y confirma tu acceso.» | Escanear el QR con la cámara del celular, revisar el equipo y la sala, y tocar «Confirmar». | E2E `confirmacion.spec.ts` |
| Escaneé y me pide iniciar sesión | La pantalla «Iniciar sesión» | Es normal si no había sesión web. Al iniciar sesión, la web sigue con el mismo QR sin volver a escanear, siempre que no hayan pasado 60 s. | E2E `guards.spec.ts`, `confirmacion.spec.ts` |
| El QR dice que venció | «QR vencido» · «Este código QR venció. Escanea el código nuevo que aparece en el equipo.» | Escanear el QR que muestra ahora el equipo. Cada QR dura 60 s. | QA-05 |
| El QR dice que ya se usó | «QR ya utilizado» · «Este código QR ya fue utilizado. Escanea el código nuevo del equipo.» | Escanear el QR nuevo. Cada QR sirve una sola vez. | QA-05, E2E |
| El equipo está en uso | «Equipo en uso» · «Este equipo ya tiene una sesión activa. Cierra la sesión en el equipo y vuelve a escanear.» | Cerrar la sesión en el equipo (o pedir a quien lo usa que la cierre) y escanear de nuevo. | QA-05 |
| Tenía una sesión abierta en otro equipo | «Cambio de sesión activa» · «Tienes una sesión activa en <equipo>. Al confirmar, se cerrará esa sesión y se iniciará una nueva en este equipo.» | Confirmar si se quiere cambiar de equipo. Solo se puede tener una sesión activa. | QA-05 |
| Escaneé pero no quiero entrar | La vista previa del equipo | Cancelar. Escanear o mirar la vista previa no registra ningún acceso. | E2E "cancelar no crea el acceso" |
| ¿Cómo termino mi acceso? | En el equipo: «Cerrar sesión». En la web: «Terminar acceso» → «Terminaste tu acceso. El equipo volverá a mostrar el QR en hasta 1 minuto.» | Cualquiera de los dos. Desde la web, el equipo tarda hasta 1 minuto en volver al QR. | QA-07a |
| ¿«Cerrar sesión web» termina mi acceso? | «Cerrar sesión web no termina el acceso que pueda seguir activo en un computador.» | No. Para liberar el equipo hay que usar «Terminar acceso» o «Cerrar sesión» en el equipo. | QA-07a |
| Me fui sin cerrar la sesión | — | La sesión se cierra sola unos 3 minutos después de que el equipo se apaga o pierde la red. | QA-05 |
| No puedo iniciar sesión | «No pudimos iniciar sesión.» · «El correo o la contraseña son incorrectos. Revisa tus datos e inténtalo de nuevo.» | Revisar el correo institucional y la contraseña. El mensaje es el mismo si el correo no existe. | QA-04, E2E |
| Mi cuenta quedó bloqueada | «Acceso bloqueado temporalmente.» · «Alcanzaste 5 intentos fallidos. Espera 15 minutos antes de volver a iniciar sesión.» | Esperar 15 minutos. Durante el bloqueo, ni la contraseña correcta funciona. | `test_bloqueo_y_limites.py` |
| Olvidé mi contraseña | La pantalla «Recuperar contraseña» todavía no tiene contenido | En el MVP no hay recuperación por correo (HU-24 no entró). Pedir ayuda al administrador. Ver el problema conocido 3.6. | Backlog §4 |
| Quiero cambiar mi contraseña | «Contraseña actualizada. Se cerraron tus otras sesiones web; esta sigue abierta.» | Perfil → «Cambiar contraseña». La nueva debe tener de 10 a 128 caracteres y ser distinta de la actual. | Código de `ProfileView` |
| La web dice que no hay conexión | «No pudimos conectar con el servicio.» · «Inténtalo de nuevo en unos minutos.» | Revisar la conexión del celular y reintentar. Ver el problema conocido 3.4. | E2E |
| ¿Mi sesión web caduca? | — | Se renueva sola mientras se use; después de 7 días sin uso hay que iniciar sesión de nuevo. | QA-04, SEC-03a |

### Cámara (escáner dentro de la web)

Si se usa el escáner propio de la web en lugar de la cámara del celular:

| Qué ve | Qué hacer |
|---|---|
| «Permiso de cámara denegado» · «Para escanear necesitamos usar la cámara. Habilita el permiso y vuelve a intentarlo.» | Dar permiso de cámara al navegador en la configuración del celular. |
| «La cámara está en uso» · «Otra aplicación está usando la cámara. Ciérrala y vuelve a intentarlo.» | Cerrar la otra aplicación. |
| «Navegador no compatible» · «Este navegador no permite usar la cámara desde la web. Usa la cámara de tu celular.» | Escanear con la cámara del celular, que siempre funciona. |

## 2. Preguntas frecuentes del administrador y de TI

| Pregunta | Qué ve | Qué hacer |
|---|---|---|
| El código de enrolamiento no funciona | En el equipo: «El código no es válido, ya se usó o venció.» | Generar un código nuevo en el panel. Cada código sirve una vez y dura 24 h. |
| El enrolamiento pide permisos | «Cierra la aplicación e iníciala con permisos de administrador para enrolar.» | Abrir la aplicación como administrador de Windows solo para enrolar. |
| El equipo no se conecta | «Equipo no disponible» · «El sistema intentará restablecer la conexión automáticamente.» | Revisar la red y la salida HTTPS (puerto 443). La aplicación reintenta sola. |
| El kiosco liberó el equipo | «Modo fail-open activo» · «La API no ha respondido durante 3 minutos. Se ha liberado el equipo según la configuración.» | Es lo esperado si la API no responde 3 minutos. El equipo vuelve a bloquearse cuando la conexión regresa. |
| En modo pasivo, ¿qué hace «Omitir»? | «Omitir minimiza a la bandeja y pausa la generación de QR.» | Elegir «Registrar acceso» en la bandeja para volver al QR. |
| Cambié el modo del equipo en el panel | — | El equipo lo aplica en su próximo latido, en hasta 65 s, sin reinstalar. |
| ¿Cómo bloqueo una cuenta? | — | Con el CLI `block-user` (ver `backend.md`, sección 3.3). La pantalla de usuarios llega con HU-26. |

## 3. Problemas conocidos

| # | Problema | Causa | Alternativa |
|---|---|---|---|
| 3.1 | Windows SmartScreen advierte al instalar el `.msi` | El instalador no tiene firma Authenticode (PEND-08) | Instalar con "Más información" → "Ejecutar de todas formas", solo con el `.msi` descargado del release oficial y con su SHA-256 verificado (`docs/ops/release-msi.md`). |
| 3.2 | En modo kiosco, Alt+Tab, la tecla Windows y Ctrl+Alt+Supr siguen funcionando | Limitación aprobada del MVP (backlog §4, SRS T-16) | La aplicación bloquea Alt+F4, cerrar y minimizar. El control de las salas lo hace el personal. |
| 3.3 | El equipo tarda hasta 1 minuto en enterarse de un cierre o un cambio de modo | El equipo consulta su estado en cada latido (cada 60 s) | Esperar hasta 65 s. Es el tiempo aprobado. |
| 3.4 | El primer acceso del día tarda más | El plan gratuito de Render suspende la API tras 15 min sin tráfico; el primer pedido la despierta | Esperar y reintentar. En producción lo mitiga el pinger (OPS-06). |
| 3.5 | El cierre por inactividad puede tardar hasta unos 3 min 30 s | El servidor revisa las sesiones cada 30 s | Ninguna; la hora de fin registrada es la del último latido. |
| 3.6 | No hay recuperación de contraseña ni verificación de correo, aunque la pantalla «Recuperar contraseña» aparece | HU-24 no entró (falta el dominio de correo, PEND-02); la pantalla es un marcador sin contenido | El administrador ayuda; las cuentas quedan activas al registrarse. |
| 3.7 | El PC solo muestra nombre, código enmascarado, inicio y cronómetro | Los últimos 5 accesos llegan con HU-11 | Ver el historial en la web. Revisar el estado de HU-11 antes de redactar. |

Resuelto antes de la beta: en Windows en español el equipo no podía enrolarse porque buscaba los
grupos de Windows por su nombre en inglés. Se corrigió en el PR #330 (grupos por SID).

## 4. Lista para validar el manual en la regresión

En la regresión final (vie 4/12) se sigue cada manual paso a paso sobre la versión candidata y se
marca cada punto. Un punto que no coincide es un defecto del manual o de la aplicación.

### Manual del estudiante

- [ ] Cada paso de registro, inicio de sesión, escaneo y confirmación coincide con la web.
- [ ] Los textos de botones y mensajes del manual son idénticos a los de la pantalla.
- [ ] Están los casos de la sección 1: QR vencido, QR ya usado, equipo en uso y cambio de equipo.
- [ ] Explica la diferencia entre «Terminar acceso» y «Cerrar sesión web».
- [ ] Indica el bloqueo de 15 minutos tras 5 intentos fallidos.
- [ ] Las capturas son de la versión candidata, no de una anterior.
- [ ] No hay datos personales reales en capturas ni ejemplos.

### Manual del administrador

- [ ] Crear salas y equipos, generar el código de enrolamiento y cambiar el modo coinciden con el panel.
- [ ] La consulta de accesos con filtros coincide; la exportación CSV solo si HU-33 entró.
- [ ] El bloqueo de cuentas está descrito con el CLI o con la pantalla, según si HU-26 entró.
- [ ] Indica que el cambio de modo tarda hasta 65 s en el equipo.

### Manual de TI

- [ ] La instalación del `.msi` y la verificación del SHA-256 funcionan como dice el manual.
- [ ] Explica la advertencia de SmartScreen (problema conocido 3.1).
- [ ] El enrolamiento funciona en Windows 10 y 11 en español.
- [ ] Explica el modo kiosco, el fail-open de 3 minutos y sus limitaciones (3.2).
- [ ] El script de arranque (DSK-14b) deja la aplicación abierta al iniciar sesión en Windows.
- [ ] La solución de problemas cubre «Equipo no disponible» y el código de enrolamiento inválido.
