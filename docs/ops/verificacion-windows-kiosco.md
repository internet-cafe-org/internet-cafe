# Verificación en Windows y kiosco (DSK-15)

Tarea: [#118](https://github.com/internet-cafe-org/internet-cafe/issues/118) · Historia: #51 (HU-39)

Estado: **en curso**. La instancia única está probada en Windows 10, y el kiosco está probado en parte en
Windows 10. Falta Windows 11 y varias transiciones del kiosco, marcadas como pendientes.

## Instaladores usados

Todos se construyeron en local con `gradle -p desktop jpackageMsi` (API `http://localhost:8000`), no con el
workflow `release-msi`.

| Instalador | SHA-256 | Código que contiene |
|---|---|---|
| `antes-del-arreglo-0.1.0.msi` | `30C0F8A273D9C6E0CF9779652ACC64FDEDAA0B772F9D5C4E08D90D54123B899C` | `develop` en `39ee4b3`. `AppLock` existe pero `Main` no lo usa |
| `despues-del-arreglo-0.1.0.msi` | `D088C940A981E5A3AFBA99AD526163113A07261B9BEA882A8508684571290E6D` | `AppLock` conectado en `Main.main()`; la segunda instancia termina con `System.exit(0)` |

Hubo un instalador intermedio (`9561D6E8…97AC03`) con el candado conectado pero sin `System.exit(0)`. Se
descartó; ver el hallazgo más abajo.

Los dos instaladores tienen versión 0.1.0 y el mismo `--win-upgrade-uuid`, así que no se instalan uno sobre
otro: hay que desinstalar antes de cambiar de uno al otro.

## Equipos de prueba

| Equipo | Estado | Responsable |
|---|---|---|
| Windows 10 (portátil) | Probado el 27/11/2026 | Quien ejecuta DSK-15 |
| Windows 11 | **Pendiente** (no hay equipo ni máquina virtual disponible) | Por asignar |

## Instancia única

Procedimiento: instalar el `.msi`, lanzar `Internet Cafe Desktop.exe` dos veces con 8 s de diferencia y
consultar los procesos y las ventanas abiertas. El equipo no estaba enrolado, así que la app muestra el aviso
"Equipo no disponible" y espera a que se cierre; no entra en modo kiosco.

| Instalador | Procesos tras la segunda ejecución | Ventanas |
|---|---|---|
| Antes del arreglo | 4 (dos pares lanzador → app) | 2 |
| Después del arreglo | 2 (un par lanzador → app) | 1 |

Hallazgo: con el candado conectado pero sin `System.exit(0)`, la segunda instancia escribía en el log
`Ya hay otra instancia ... esta se cierra`, pero su proceso seguía vivo. Se añadió `System.exit(0)` y con eso
el proceso termina.

Evidencia: capturas de las dos ventanas "antes" y de la ventana única "después", por adjuntar al PR.

## Transiciones del kiosco

Cómo se probó: con el runtime del `.msi` "después" instalado, lanzando `java.exe` con
`-Dapp.profile=dev -Ddev.mode=kiosk` y sin servidor en `localhost:8000`. Una tarea aparte terminaba el proceso
a los 7 minutos como salida de emergencia, y otra registraba cada 15 s si el proceso seguía vivo. Es el mismo
código y el mismo runtime del instalador, pero **sin un equipo enrolado** (ver limitaciones).

| Prueba | Windows 10 | Windows 11 |
|---|---|---|
| Arranque en modo kiosco: pantalla completa y bloqueada | OK | Pendiente |
| Alt+F4 con el kiosco bloqueado | OK: no cierra. El proceso siguió vivo los 7 min (28 de 28 comprobaciones) | Pendiente |
| Minimizar (Windows+D): la ventana se restaura | OK: vuelve sola | Pendiente |
| Pérdida de conexión: aparece la pantalla sin conexión | OK | Pendiente |
| Pérdida de conexión: desbloqueo del kiosco a los 3 min (fail-open) | Pendiente (no se observó) | Pendiente |
| Reconexión: vuelve al QR | Pendiente | Pendiente |
| Sesión aprobada: pasa al tablero y vuelve al QR al cerrar | Pendiente | Pendiente |
| Modo pasivo (omitir) y regreso al modo kiosco desde la bandeja | Pendiente | Pendiente |
| Instancia única con el equipo en kiosco | Pendiente | Pendiente |
| Evasión con la tecla Windows | Sale al escritorio (limitación conocida) | Pendiente |
| Evasión con Ctrl+Alt+Supr | Aparece y abre el Administrador de tareas (limitación conocida) | Pendiente |

Nota: en una primera corrida sin monitoreo del proceso se anotó que Alt+F4 cerraba la app y que la pantalla
sin conexión no aparecía. No coincidía con el log (el proceso siguió escribiendo hasta que se terminó a mano)
y se repitió con el proceso monitoreado; los resultados de la tabla son los de la repetición.

## Limitaciones conocidas

- **El kiosco se evade con la tecla Windows y con Ctrl+Alt+Supr.** Es una limitación de JavaFX ya listada en
  el backlog (riesgos) y debe ir al manual de TI para la universidad. En Windows 10 se confirmó en esta prueba.
- El kiosco se probó con el perfil de desarrollo, que salta la carga de la identidad enrolada. El camino con un
  equipo enrolado de verdad no se ha probado aquí.
- El candado vive en `%APPDATA%\InternetCafe\internet-cafe-desktop.lock`, que es distinto para cada usuario
  de Windows. Dos usuarios distintos del mismo PC podrían abrir una instancia cada uno. Por confirmar si
  aplica al equipo kiosco.
- Si no se puede crear o abrir el archivo del candado (`IOException`), la app arranca sin instancia única y
  deja una advertencia en el log. Se eligió así para que un fallo de disco o permisos no deje el kiosco sin
  abrir.
- El `.msi` sale sin firma Authenticode hasta que TI entregue el certificado (PEND-08).
