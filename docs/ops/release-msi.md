# Release del instalador `.msi` (OPS-14)

El workflow `release-msi` construye el instalador de escritorio de DSK-14a (`jpackageMsi`)
con la URL de la API de prod y lo publica en GitHub Releases.

| Evento | Qué hace |
|---|---|
| Etiqueta `v*` | Construye el `.msi` de prod y lo publica con su SHA-256. La etiqueta debe apuntar a un commit de `main`. Corre en el environment `prod`, así que espera la aprobación del PO o el SM. |
| PR que toca `desktop/` o el workflow | Construye un `.msi` de prueba con la URL ficticia `https://api.prueba.invalid`, lo verifica y lo deja como artefacto por 3 días. No publica nada. |

## Verificación antes de publicar

`.github/scripts/verificar-msi.ps1` corre después de construir el instalador y antes de subirlo:

1. Exige exactamente un `.msi` en `desktop/build/installer/`.
2. Lo extrae sin instalarlo (`msiexec /a`).
3. Exige que la configuración del lanzador (`app\Internet Cafe Desktop.cfg`) tenga la línea
   `java-options=-Dapi.base.url=<URL pedida>`, una sola vez. Es la propiedad que lee `AppConfig`
   al arrancar.

Si algo falla, el workflow se detiene y no publica nada. Así nunca sale un instalador que busque
la API en otra dirección (por ejemplo, `localhost`). Con `--runtime-image`, jpackage crea su propio
lanzador y no hereda los `jvmArgs` del lanzador de `jlink`: la URL tiene que llegar a jpackage
con `--java-options` desde la tarea `jpackageMsi` de `desktop/build.gradle`.

## Permisos

El job que construye solo lee el repositorio y no deja el token en la configuración de git. El
permiso `contents: write` queda en el job `publicar`, que baja el artefacto, comprueba el SHA-256
y no ejecuta Gradle.

## Requisitos

- Environment `prod` creado en GitHub **con revisores obligatorios** (ver `docs/ops/produccion.md`).
  Si no existe, GitHub lo crea sin protección con la primera etiqueta y no pide aprobación; el
  workflow fallaría por falta de `PROD_API_URL`.
- Variable `PROD_API_URL` en el environment `prod`: `https://<host de Render prod>`, sin `/`
  final (ver `docs/ops/produccion.md`). El instalador la deja fija al construirse.
- El runner `windows-2022` trae WiX 3.14, que jpackage necesita para el `.msi`.

## Versión

Windows solo acepta versiones numéricas `X.Y.Z` (máximo `255.255.65535`), y `-beta` o `-rc.1`
no cuentan. El `.msi` usa `X.Y` de la etiqueta y el número de ejecución del workflow como
tercer campo. Así cada versión candidata actualiza a la anterior sin desinstalar, porque el
`--win-upgrade-uuid` de DSK-14a es fijo:

| Etiqueta | Release | Versión del `.msi` (ejemplo) |
|---|---|---|
| `v1.0.0-beta` | prerelease | `1.0.41` |
| `v1.0.0-rc.1` | prerelease | `1.0.47` |
| `v1.0.0` | release | `1.0.52` |

Las etiquetas con sufijo (`-beta`, `-rc.N`) se publican como prerelease.

## Verificar un instalador descargado

```powershell
Get-FileHash .\internet-cafe-desktop-v1.0.0.msi -Algorithm SHA256
```

El valor debe coincidir con el archivo `.sha256` del release.

Para ver a qué API apunta, extráelo sin instalarlo y revisa el lanzador:

```powershell
msiexec /a .\internet-cafe-desktop-v1.0.0.msi /qn TARGETDIR="$env:TEMP\msi-revision"
Get-ChildItem "$env:TEMP\msi-revision" -Recurse -Filter *.cfg | Get-Content
```

Debe aparecer `java-options=-Dapi.base.url=<URL de prod>`.

## Pendiente

El `.msi` sale **sin firma Authenticode** hasta que TI entregue el certificado (PEND-08,
SRS T-14). Windows SmartScreen puede advertir al instalarlo.
