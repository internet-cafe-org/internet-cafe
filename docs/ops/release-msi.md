# Release del instalador `.msi` (OPS-14)

El workflow `release-msi` construye el instalador de escritorio de DSK-14a (`jpackageMsi`)
con la URL de la API de prod y lo publica en GitHub Releases.

| Evento | Qué hace |
|---|---|
| Etiqueta `v*` | Construye el `.msi` de prod y lo publica con su SHA-256. Corre en el environment `prod`, así que espera la aprobación del PO o el SM. |
| PR que toca `desktop/` o el workflow | Construye un `.msi` de prueba (API en `localhost`) y lo deja como artefacto por 3 días. No publica nada. |

## Requisitos

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

## Pendiente

El `.msi` sale **sin firma Authenticode** hasta que TI entregue el certificado (PEND-08,
SRS T-14). Windows SmartScreen puede advertir al instalarlo.
