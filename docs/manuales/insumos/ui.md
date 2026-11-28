# Insumos para los manuales: web (equipo UI)

> **HU-35 · UI-13 (#191).** Materia prima para SM-01 (manual del estudiante y del administrador). No está redactado como manual.
> **Fuente:** código de `develop` (commit `c9dd27e`, 27/11/2026) y capturas del entorno de dev.
> Los textos entre «» son los que aparecen en pantalla, tal cual. Las rutas son las de la web.

## 0. Cómo leer este documento

- **Capturas:** están en `capturas/ui-NN-nombre.png` (junto a este archivo). Cada captura usa una cuenta de prueba de la semilla de dev, sin datos personales.
- **Estados de un botón:** cuando el texto cambia mientras se procesa, se muestra como «Texto normal» → «Texto en proceso».
- **Marca ⚠:** dato por confirmar contra la captura antes de publicar el manual.
- **Pantallas provisionales:** *Verificar correo*, *Recuperar contraseña* y *Usuarios* muestran «Pantalla pendiente de diseño (PEND-01).». No se documentan todavía (llegan con ST-UI-01 y ST-UI-03).

## 1. Datos generales

| Dato | Valor |
|---|---|
| Entorno de las capturas | `https://internet-cafe-dev.vercel.app` |
| Roles | **Estudiante** y **administrador** (cuentas de prueba de la semilla de dev; no se documentan credenciales) |
| Idioma | Español. Las fechas usan la zona horaria de la universidad |
| Título de la pestaña | «Registro de acceso a equipos»; cada pantalla antepone el suyo, por ejemplo «Perfil · Registro de acceso a equipos» |

### 1.1 Estructura de las pantallas

- **Pantallas de acceso** (Iniciar sesión, Crear cuenta): panel con «Acceso universitario», «Registro de equipos · QR» y «Servicio de acceso a computadores». Son siempre claras.
- **Pantallas con sesión:** encabezado con «Acceso universitario · {rol}», botón de tema, botón con las iniciales del usuario y menú lateral.
  - **Botón de tema:** «Modo oscuro» → «Modo claro». Cambia entre claro y oscuro.
  - **Botón de iniciales:** abre el menú del usuario, con «Salir».
  - **Menú del estudiante** («MENÚ PRINCIPAL»): Inicio · Historial · Perfil.
  - **Menú del administrador** («GESTIÓN DE ACCESO»): Salas · Equipos · Accesos.
  - **En móvil:** el menú se abre con el botón «Abrir menú de navegación» y se cierra con «Cerrar menú».
- **Administrador:** el panel indica «Entorno administrativo» y «Acciones auditadas».

### 1.2 Reglas visibles para el usuario

| Regla | Dónde se muestra |
|---|---|
| El registro exige un correo del dominio institucional autorizado | Crear cuenta |
| La contraseña debe tener entre 10 y 128 caracteres | Crear cuenta, Perfil |
| Tras 5 intentos fallidos de inicio de sesión, hay que esperar 15 minutos | Iniciar sesión |
| Solo se registra el acceso al confirmar; cancelar no crea un acceso ni cierra la sesión previa | Confirmar acceso |
| Al confirmar un acceso, se cierra la sesión que el estudiante tuviera en otro equipo | Confirmar acceso |
| Al terminar el acceso, el equipo vuelve a mostrar el QR en hasta 1 minuto | Inicio |
| Al cambiar la contraseña se cierran las otras sesiones web; la actual sigue abierta | Perfil |
| Cerrar la sesión web no termina el acceso que siga activo en un computador | Perfil |
| Un equipo está «En línea» si su último contacto fue de hace 2 minutos o menos | Equipos |
| Un cambio de modo se aplica en el siguiente latido del equipo (60 s como máximo) | Detalle del equipo |
| El código de enrolamiento es de un solo uso, vence a las 24 h y se muestra una sola vez | Detalle del equipo |
| Un cierre forzado es irreversible y queda auditado; el equipo lo detecta en 60 s como máximo | Accesos |

---

## 2. Estudiante

### 2.1 Crear cuenta · `/register`

**Para qué sirve:** registrarse con datos institucionales. No requiere sesión.

**Pasos**
1. Abrir la web y elegir «Crear una cuenta» (enlace en Iniciar sesión).
2. Completar los cuatro campos (todos son obligatorios):

| Campo | Texto de ayuda dentro del campo |
|---|---|
| Nombre completo | «Como aparece en tu matrícula» |
| Código estudiantil | «Tu código estudiantil» |
| Correo institucional | «Tu correo institucional» |
| Contraseña | «Crea tu contraseña» (ayuda: «Entre 10 y 128 caracteres.») |

3. Marcar la casilla: «Autorizo el tratamiento de mis datos personales para gestionar mi registro y el acceso a los equipos. (Obligatorio)».
4. Pulsar **«Crear cuenta»** → «Iniciando sesión...».
5. Aparece «Registro exitoso. Iniciando sesión automáticamente...» y se entra a la web.

**Otros elementos:** «¿Ya tienes una cuenta?» · enlace «Iniciar sesión». El botón del ojo del campo de contraseña se llama «Mostrar contraseña» (ojo tachado = oculta; ojo = visible).

**Mensajes**

| Situación | Texto en pantalla |
|---|---|
| Nombre vacío | «Ingresa tu nombre completo.» |
| Código vacío | «Ingresa tu código estudiantil.» |
| Correo con formato incorrecto | «Ingresa un correo con formato válido.» |
| Correo fuera del dominio autorizado | «Utiliza el dominio institucional autorizado.» |
| Contraseña fuera de 10–128 | «La contraseña debe tener entre 10 y 128 caracteres.» |
| Casilla sin marcar | «Debes autorizar el tratamiento de datos para continuar.» |
| Cada error de campo se muestra como | «Error: {mensaje}» |
| El servidor rechaza el registro | «No pudimos completar el registro. Revisa tus datos e inténtalo de nuevo.» |


### 2.2 Iniciar sesión · `/login`

**Para qué sirve:** entrar con la cuenta institucional. Es la pantalla inicial para quien no tiene sesión.

**Pasos**
1. Escribir el correo institucional (ayuda: «Tu correo institucional») y la contraseña (ayuda: «Tu contraseña»).
2. Opcional: pulsar «Mostrar contraseña» para ver lo escrito.
3. Pulsar **«Iniciar sesión»**.
4. Aparece «Iniciaste sesión correctamente» y «Te estamos redirigiendo al destino correspondiente…» («Espera un momento. No necesitas realizar ninguna acción.»). El destino depende del rol.

**Texto de la pantalla:** título «Iniciar sesión» · «Ingresa con tu cuenta institucional para continuar.» · «¿Aún no tienes una cuenta?» · enlace «Crear una cuenta».

**Mensajes**

| Situación | Título | Texto |
|---|---|---|
| Correo con formato incorrecto | (en el campo) | «Ingresa un correo con formato válido.» |
| Contraseña vacía | (en el campo) | «Ingresa tu contraseña.» |
| Credenciales incorrectas | «No pudimos iniciar sesión.» | «El correo o la contraseña son incorrectos. Revisa tus datos e inténtalo de nuevo.» |
| 5 intentos fallidos | «Acceso bloqueado temporalmente.» | «Alcanzaste 5 intentos fallidos. Espera 15 minutos antes de volver a iniciar sesión.» |
| Sin conexión con el servicio | «No pudimos conectar con el servicio.» | «Inténtalo de nuevo en unos minutos.» |


### 2.3 Inicio · `/`

**Para qué sirve:** ver la sesión actual, terminarla y ver los últimos accesos.

**Texto de la pantalla:** título «Inicio» · «Bienvenido a tu portal de acceso universitario».

**Bloques**
- **«Mi sesión actual»** (solo si hay un acceso activo): etiqueta «Acceso activo», datos «Equipo», «Sala» y «Fecha y hora de inicio», y el texto «Cierra tu sesión desde aquí cuando termines de usar el computador.». Botón **«Terminar acceso»**.
- **«¿Cómo registrar un acceso?»**, en tres pasos:
  1. «Busca el código QR en la pantalla del computador.»
  2. «Escanéalo con la cámara de tu celular.»
  3. «Revisa los datos y confirma tu acceso.»
- **«Últimos accesos»**, con el botón **«Ver historial completo»**. Si no hay accesos: «Aún no tienes accesos. Cuando registres el primero, aparecerá aquí.»

**Mensajes**

| Situación | Texto en pantalla |
|---|---|
| Cargando | «Cargando tu información…» |
| Falla la carga | «No pudimos cargar tu información. Revisa tu conexión e inténtalo de nuevo.» (botón «Reintentar») |
| Terminar acceso correcto | «Terminaste tu acceso. El equipo volverá a mostrar el QR en hasta 1 minuto.» |
| Falla al terminar | «No pudimos terminar tu acceso. Revisa tu conexión e inténtalo de nuevo.» |


### 2.4 Escanear código QR · `/scan`

**Para qué sirve:** escanear el QR del equipo desde la cámara del navegador. La alternativa es usar la cámara del celular.

**Pasos**
1. Elegir «Escanear código QR» o abrir `/scan`. Si el navegador lo pide, **permitir el acceso a la cámara** («Iniciando la cámara… Si el navegador lo pide, permite el acceso.»).
2. Apuntar la cámara al QR de la pantalla del equipo («Apunta la cámara al código QR que aparece en la pantalla del equipo.»).
3. Al reconocerlo, la web abre «Confirmar acceso».

**Alternativa:** «¿Prefieres usar la cámara del celular?» → «Abre la aplicación de cámara de tu celular, apunta al QR del equipo y toca el enlace que aparece. Te traerá directo a la confirmación.»

**«Cómo habilitar la cámara»**
- **Safari (iPhone o iPad):** toca «aA» en la barra de direcciones, elige «Configuración del sitio web», abre «Cámara» y selecciona «Permitir».
- **Chrome (Android):** toca el candado junto a la dirección, entra en «Permisos», abre «Cámara» y selecciona «Permitir».
- **Otros navegadores:** habilita el permiso de cámara para este sitio en la configuración del navegador.

**Botones:** «Intentar de nuevo», «Cancelar».

**Mensajes**

| Situación | Título | Texto |
|---|---|---|
| Permiso denegado | «Permiso de cámara denegado» | «Para escanear necesitamos usar la cámara. Habilita el permiso y vuelve a intentarlo.» |
| Sin cámara | «No encontramos una cámara» | «Este dispositivo no tiene una cámara disponible. Usa la cámara de tu celular.» |
| Cámara ocupada | «La cámara está en uso» | «Otra aplicación está usando la cámara. Ciérrala y vuelve a intentarlo.» |
| Sin HTTPS | «Conexión no segura» | «La cámara solo funciona en una conexión segura (HTTPS). Abre el sitio con https://.» |
| Navegador no compatible | «Navegador no compatible» | «Este navegador no permite usar la cámara desde la web. Usa la cámara de tu celular.» |
| Otro fallo | «No pudimos iniciar la cámara» | «Inténtalo de nuevo o usa la cámara de tu celular.» |
| QR que no es del sistema | «Este código no pertenece al sistema.» | «Escanea el QR que aparece en el equipo.» |


### 2.5 Confirmar acceso · `/s`

**Para qué sirve:** revisar los datos del equipo y confirmar el acceso. Se llega al escanear el QR (o al abrir el enlace con la cámara del celular).

**Pasos**
1. Mientras valida: «Verificando el código QR…».
2. Revisar los datos del equipo: «Equipo», «Código del equipo» y «Sala».
3. Pulsar **«Confirmar»** → «Confirmando…». (**«Cancelar»** no registra nada.)
4. Resultado: «Acceso confirmado» · «Tu acceso se registró correctamente.» · «Sesión activa en {código del equipo}.»

**Cambio de sesión activa:** si el estudiante ya tiene una sesión en otro equipo se avisa con «Cambio de sesión activa»: «Tienes una sesión activa en {equipo}. Al confirmar, se cerrará esa sesión y se iniciará una nueva en este equipo.»
**Notas en pantalla:** «Solo se registra el acceso al confirmar. Cancelar no crea un acceso ni cierra tu sesión previa.» · tras confirmar: «Si tenías una sesión activa en otro equipo, se cerró al confirmar este acceso.»

**Errores** (en todos: «Tu sesión previa, si existe, no se ha modificado.»; hay enlace «Contactar a soporte»)

| Situación | Título | Texto | Botón de acción |
|---|---|---|---|
| QR vencido | «QR vencido» | «Este código QR venció. Escanea el código nuevo que aparece en el equipo.» | «Escanear código nuevo» |
| QR ya usado | «QR ya utilizado» | «Este código QR ya fue utilizado. Escanea el código nuevo del equipo.» | ⚠ ver captura |
| QR inválido | «QR inválido» | «Este código no es válido o no pertenece al sistema. Escanea el QR que aparece en el equipo.» | «Volver a escanear» |
| Equipo deshabilitado | «Equipo deshabilitado» | «Este equipo está deshabilitado. Contacta al personal de soporte o utiliza otro equipo.» | «Escanear otro equipo» |
| Equipo en uso | «Equipo en uso» | «Este equipo ya tiene una sesión activa. Cierra la sesión en el equipo y vuelve a escanear.» | ⚠ ver captura |
| Otro fallo | «No pudimos completar el acceso» | «Inténtalo de nuevo en unos minutos o vuelve a escanear el código.» | ⚠ ver captura |

**Mensajes de estado que anuncia la pantalla:** «No se registró ningún acceso. Revisa el mensaje para continuar.» · «Revisa los datos del equipo antes de registrar tu acceso.»


### 2.6 Historial de accesos · `/history`

**Para qué sirve:** consultar los propios accesos. «Solo se muestran tus propios accesos.»

**Columnas:** Equipo · Sala · Inicio · Fin · Duración (en móvil se muestran como lista con las mismas etiquetas).
**Valores especiales:** «En curso» (acceso sin fin) · «Menos de 1 min» (duración).
**Pie:** «Mostrando {n} de {total} registros» y botón **«Cargar más»** → «Cargando...».

**Mensajes**

| Situación | Texto en pantalla |
|---|---|
| Cargando | «Cargando historial de accesos...» |
| Sin accesos | «Aún no tienes accesos registrados.» |
| Falla la carga | «No pudimos cargar tu historial de accesos. Inténtalo de nuevo.» (botón «Reintentar») |
| Falla «Cargar más» | «No pudimos cargar más registros. Inténtalo de nuevo.» |


### 2.7 Perfil · `/profile`

**Para qué sirve:** ver los datos de la cuenta, cambiar la contraseña y cerrar la sesión web.

**Datos de la cuenta** (solo lectura): «Nombre completo» · «Correo institucional» · «Código estudiantil». Mientras carga: «Cargando datos de tu perfil...». Si falla: «No pudimos cargar los datos de tu perfil. Inténtalo de nuevo.» (botón «Reintentar»).

**Cambiar contraseña**
1. Escribir «Contraseña actual», «Nueva contraseña» y «Confirmar nueva contraseña».
2. Pulsar **«Cambiar contraseña»** → «Cambiando contraseña...».
3. Aparece el mensaje de éxito. La sesión actual sigue abierta y se cierran las otras sesiones web.

| Situación | Texto en pantalla |
|---|---|
| Éxito | «Contraseña actualizada. Se cerraron tus otras sesiones web; esta sigue abierta.» |
| Algún campo vacío | «Completa todos los campos de contraseña.» |
| Nueva fuera de 10–128 | «La contraseña debe tener entre 10 y 128 caracteres.» |
| Confirmación distinta | «Las contraseñas nuevas no coinciden.» |
| Nueva igual a la actual | «La nueva contraseña debe ser diferente a la actual.» |
| Contraseña actual incorrecta (bajo ese campo) | «La contraseña actual no es correcta. Revísala e inténtalo de nuevo.» |
| El servidor rechaza la nueva | «La nueva contraseña no cumple los requisitos: debe tener entre 10 y 128 caracteres y ser distinta de la actual.» |
| Demasiados intentos | «Demasiados intentos. Espera unos minutos e inténtalo de nuevo.» |
| Otro error | «No pudimos cambiar la contraseña. Inténtalo de nuevo.» |

**Cerrar sesión web:** botón **«Cerrar sesión web»** → «Cerrando sesión...». Aviso: «Cerrar sesión web no termina el acceso que pueda seguir activo en un computador.»


### 2.8 Salir (cualquier pantalla con sesión)

Botón con las iniciales del usuario → menú → **«Salir»**. Cierra la sesión web y vuelve a Iniciar sesión.

### 2.9 Página no encontrada · cualquier ruta inexistente

Título «Página no encontrada» · «No encontramos esta página» · «La dirección que abriste no existe o ya no está disponible» · enlace **«Volver al inicio»**.


---

## 3. Administrador

**Acceso:** el administrador inicia sesión en la misma pantalla de Iniciar sesión. Las pantallas de administración (`/admin/...`) solo se abren con rol de administrador; un estudiante que intente abrirlas vuelve a Inicio.
**Menú:** Salas · Equipos · Accesos. «Cerrar sesión» y «Salir» cierran la sesión.

### 3.1 Salas · `/admin/labs`

**Para qué sirve:** organizar las salas (espacios) donde están los equipos.

**Texto de la pantalla:** «Salas» · «Organiza los espacios y su ubicación en el campus.» · indicadores «Salas registradas», «Bloques / edificios», «Equipos asignados» · tabla «Todas las salas» (columnas «Nombre de sala», «Bloque / edificio», «Equipos asignados», «Acciones»; cada fila muestra «{n} equipo(s)» o «Sin equipos»).

**Crear una sala**
1. Pulsar **«Nueva sala»** (si no hay salas: **«Crear primera sala»**).
2. Completar «Nombre de sala *» (ayuda: «Nombre corto y único en la universidad · Máximo 80 caracteres»; ejemplo en el campo: «Ingresa el nombre de la sala») y, opcional, «Bloque / edificio» («Opcional · Máximo 80 caracteres»; «Ingresa el bloque o edificio»). Los campos con * son obligatorios.
3. Pulsar **«Guardar»** → «Guardando...». (**«Cancelar»** o **«Volver a salas»** descartan.)
4. Aparece «La sala se registró correctamente.»

**Editar una sala:** botón **«Editar»** en la fila → título «Editar sala» → **«Guardar cambios»**. Texto: «Actualiza la información de {sala}. Los equipos mantienen su asignación.»
**Limitación conocida:** la edición está en modo demostración. Se muestra «Modo demostración»: «Los cambios de edición solo se reflejan temporalmente en esta pantalla. La API todavía no permite guardar ediciones.» y, al guardar, «Cambios aplicados en esta demostración. La API todavía no permite guardar ediciones de salas.»

**Mensajes**

| Situación | Texto en pantalla |
|---|---|
| Cargando | «Cargando salas...» |
| Falla la carga | «No se pudieron cargar las salas» · «Se perdió la conexión con el servicio. Comprueba tu conexión y vuelve a intentarlo.» (botón «Reintentar») |
| Sin salas | «Aún no hay salas» · «Crea la primera sala para organizar tus equipos.» |
| Nombre vacío | «El nombre de la sala es obligatorio. Ingresa un nombre para continuar.» |
| Nombre repetido | «Ya existe una sala con este nombre. Ingresa un nombre diferente.» · tras guardar: «No se pudo guardar la sala» · «El nombre ya está registrado. Corrígelo e inténtalo nuevamente.» |
| Datos no válidos | «Datos no válidos» · «Revisa la información ingresada e inténtalo nuevamente.» |
| Servicio no disponible | «El servicio no está disponible temporalmente. Tus datos se conservaron en el formulario.» |
| Sin conexión al guardar | «No hay conexión con el servicio. Tus datos se conservaron en el formulario; puedes intentarlo nuevamente.» |


### 3.2 Equipos · `/admin/machines`

**Para qué sirve:** ver y administrar los computadores registrados.

**Texto de la pantalla:** «Equipos» · «Consulta y administra los computadores registrados.» · indicadores «Total de equipos», «Activos», «Pendientes», «Deshabilitados» · «Equipos registrados» · «{n} equipos».
**Filtros:** «Sala» («Todas las salas» o una sala) y «Estado» («Todos los estados», «Activo», «Pendiente de enrolamiento», «Deshabilitado»).
**Tabla:** Equipo · Sala («Sin sala» si no tiene) · Estado · Conexión («En línea» / «Desconectado») · Modo · Último contacto · Acciones. Un equipo sin enrolar muestra «Requiere enrolamiento».
**Acciones por fila**
- **Botón de modo** (muestra «Pasivo» o «Kiosco»): cambia el modo.
- **«Ver / editar»:** abre el detalle.
- **«Deshabilitar»** (si está activo) o **«Activar»** (si no lo está).
**Pie:** «En línea si el último contacto fue ≤ 2 min; es independiente del estado administrativo.»

**Mensajes**

| Situación | Texto en pantalla |
|---|---|
| Cargando | «Cargando equipos...» |
| Sin resultados | «No hay equipos para mostrar» · «Prueba cambiando los filtros.» |
| Actualización correcta | «Cambios guardados» · «El equipo {código} se actualizó correctamente.» |
| Fallo | «No se pudo completar la acción» · «No fue posible actualizar el equipo.» |
| No cargan salas o equipos | «No fue posible cargar las salas.» · «No fue posible cargar los equipos.» · «No fue posible cargar la información.» |


### 3.3 Detalle del equipo · `/admin/machines/:id`

**Para qué sirve:** configurar un equipo, generar su código de enrolamiento, habilitarlo o deshabilitarlo y revocar su clave. Se abre con «Ver / editar» en Equipos; «Volver a equipos» regresa.

**Datos:** «Código» · «Estado» · «Conexión» · «Último contacto» · «Enrolado» · «Versión de la app» («Sin registro» si no hay). Título «{nombre del equipo} · estado y edición» («Sin nombre de equipo» si no tiene).

**Configuración del equipo**
- «Sala asignada» («Sin sala» o una sala).
- «Modo de funcionamiento»: «Pasivo» («Pasivo: registra los accesos sin bloquear el equipo.») o «Kiosco» («Kiosco: pantalla completa hasta que un estudiante inicie sesión.»).
- **«Guardar cambios».** Al cambiar el modo: «Cambios guardados. El equipo aplicará el nuevo modo en su próximo latido (≤ 60 s).»; en otros cambios: «Cambios guardados.»

**Enrolamiento y clave**
1. Pulsar **«Generar código de enrolamiento»**. Texto: «Entrega el código únicamente al personal de TI. Es de un solo uso, vence a las 24 h y no se puede volver a ver. Modo actual: {modo}.»
2. Se muestra «Código de enrolamiento» con «Este código se muestra una sola vez» («Si lo pierdes, tendrás que generar otro.») y «Vence: {fecha}».
3. Pulsar **«Copiar código»** → «Copiado», y después **«Ya guardé el código»** para cerrar.
4. **«Revocar clave»:** pide confirmar con «¿Revocar la clave del equipo?» · «Esta acción queda auditada» · «La clave actual dejará de ser válida. Para volver a conectar {código}, genera un código nuevo y enrólalo.» → botones «Cancelar» y «Revocar clave».

**Estado administrativo**
- **«Deshabilitar equipo»:** «Al deshabilitarlo se cancelan sus retos pendientes y se cierra su sesión abierta.» Pide confirmar con «¿Deshabilitar el equipo?» · «Esta acción queda auditada» · «{código} dejará de registrar accesos, se cancelarán sus retos pendientes y se cerrará su sesión abierta.» → «Cancelar» y «Deshabilitar».
- **«Habilitar equipo»** (si está deshabilitado): «El equipo está deshabilitado y no puede registrar accesos aunque esté en línea.»
- Si el equipo no se enroló: «Requiere enrolamiento antes de administrarlo.» · «Aún no hay una clave que revocar: el equipo no se enroló.»
- Si está deshabilitado: «Habilita el equipo para generar un código de enrolamiento.»

**Mensajes**

| Situación | Texto en pantalla |
|---|---|
| Cargando | «Cargando equipo...» |
| Falla la carga | «No se pudo cargar el equipo» · «Comprueba tu conexión y vuelve a intentarlo.» (botón «Reintentar») |
| No existe | «No encontramos este equipo» · «Puede que se haya eliminado o que el enlace no sea correcto.» / «El equipo ya no existe. Vuelve a la lista de equipos.» |
| Fallo general | «No se pudo completar la acción» · «No fue posible actualizar el equipo. Inténtalo de nuevo.» |
| Habilitar correcto | «Listo» · «El equipo se habilitó correctamente.» |
| Habilitar sin enrolar | «El equipo todavía no se enroló, por eso no se puede activar.» |
| Deshabilitar correcto | «El equipo se deshabilitó correctamente.» |
| Revocar correcto | «La clave se revocó. Para volver a conectar el equipo, genera un código nuevo y enrólalo.» |
| Revocar falla | «No se pudo revocar la clave. Inténtalo de nuevo.» |
| Generar código falla | «No se pudo generar el código. Inténtalo de nuevo.» |
| Código no permitido por el estado | «No se puede generar un código para este equipo en su estado actual.» |
| El servidor no devuelve el código | «El servidor no devolvió un código de enrolamiento válido.» |
| Estados que se muestran | «Pendiente de enrolamiento» · «Sin registro» · «En línea» / «Desconectado» |


### 3.4 Accesos · `/admin/sessions`

**Para qué sirve:** consultar las sesiones de los computadores, exportarlas y forzar el cierre de una sesión activa.
**Aviso:** esta pantalla tiene su propia barra superior con «Salas y equipos», «Accesos», «Usuarios» y «Cerrar sesión», y migas «Administración › Accesos». Es distinta del menú lateral de las demás pantallas.

**Texto de la pantalla:** «Historial de accesos» · «Consulta sesiones de computadores con filtros y gestiona cierres forzados autorizados.»

**Filtros de búsqueda**
- «Estudiante» (ayuda: «Código o nombre...») · «Sala» («Todas las salas») · «Código de equipo» (ejemplo: «Ej: LAB3-PC12») · «Estado» («Todas las sesiones», «Solo activas», «Solo cerradas») · «Fecha desde» · «Fecha hasta».
- Botones **«Aplicar filtros»**, **«Limpiar filtros»** y **«Exportar CSV»** → «Exportando…».
- Si «desde» es posterior a «hasta»: «La fecha "desde" no puede ser posterior a la fecha "hasta".»

**Tabla «Sesiones registradas»:** Estudiante · Equipo · Sala · Inicio · Fin · Duración · Estado («Activa» / «Cerrada») · Acciones. Pie: «Mostrando {n}» · «Página {x} de {y} ({total} totales)» · botones «Anterior» y «Siguiente».
**Motivos de cierre que se muestran:** «En curso» · «Cierre forzado» · «Cerrada desde el equipo» · «Cerrada desde la web» · «Inactividad (sin latido)» · «Reemplazada por nueva sesión» · «Apagado del equipo».

**Forzar el cierre**
1. En una sesión activa, pulsar **«Forzar cierre»**.
2. Diálogo «¿Forzar el cierre de esta sesión?» · «Esta acción es irreversible y queda auditada.» Muestra «Estudiante:», «Equipo:», «Sala:» e «Inicio:», y el texto «Se forzará el cierre inmediato de la sesión en el servidor. El computador de la sala detectará el cierre en su próximo latido (≤ 60 s) y volverá a mostrar el código QR.» «Motivo registrado: `admin_forced`. La hora de fin se fija desde el servidor.»
3. Pulsar **«Forzar cierre»** → «Cerrando sesión…» (o **«Cancelar»**).

**Mensajes**

| Situación | Texto en pantalla |
|---|---|
| Cargando | «Cargando lista de accesos…» |
| Sin resultados | «No hay accesos con estos filtros» · «No se encontraron sesiones que coincidan con los criterios especificados.» (botón «Limpiar filtros») |
| Falla la carga | «Error al cargar accesos» · «No se pudo conectar con el servidor para consultar los accesos. Comprueba tu conexión e inténtalo de nuevo.» / «Error al obtener la lista de accesos.» (botón «Reintentar») |
| Exportación correcta | «Archivo {nombre} descargado con éxito.» |
| Exportación truncada | «Archivo {nombre} descargado. Nota: El resultado superó el límite y fue truncado por el servidor.» |
| Exportación sin sesión | «No autorizado para exportar. Tu sesión puede haber expirado.» |
| Exportación sin permiso | «No tienes permisos de administrador para exportar datos.» |
| Exportación falla | «Error al exportar accesos» · «Error al exportar los datos.» / «No se pudo conectar con el servidor para exportar el archivo. Comprueba tu conexión e inténtalo de nuevo.» |
| Cierre forzado correcto | «Sesión en {equipo} ({estudiante}) cerrada forzadamente con éxito.» |
| La sesión ya no existe | «La sesión indicada no existe o ya no está disponible.» |
| Cierre falla | «No se pudo cerrar la sesión. Inténtalo de nuevo.» / «Error inesperado al forzar el cierre.» |

Los avisos se cierran con el botón «Cerrar notificación».


---

## 4. Observaciones para quien redacte el manual

1. **Edición de salas:** hoy no se guarda en el servidor (modo demostración). Conviene decirlo en el manual del administrador o esperar a que la API lo permita.
2. **Usuarios, Verificar correo y Recuperar contraseña** son pantallas provisionales. El login todavía no tiene enlace de «¿Olvidaste tu contraseña?»; llega con ST-UI-01 (HU-24).
3. **Accesos** usa una barra superior propia y es la única pantalla con «Usuarios» en el menú; las demás usan el menú lateral con Salas, Equipos y Accesos.
4. **Modo oscuro:** solo existe en las pantallas con sesión y en «Página no encontrada»; el inicio de sesión y el registro son siempre claros.
5. **Mensajes con ⚠** (tres botones de acción en «Confirmar acceso»): completarlos al ver la captura de cada error.
6. El código de la web incluye entradas de menú «Sistema de diseño» y «Estados y errores» (grupo «Documentación») que no tienen pantalla. No documentarlas; confirmar que no aparecen en dev.
