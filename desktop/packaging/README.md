# Recursos de packaging del instalador .msi (DSK-14a)

Este directorio contiene los recursos que `jpackage` utiliza para personalizar
el instalador de Windows. Se pasa con la opción `--resource-dir`.

## Archivos incluidos

| Archivo | Descripción |
|---|---|
| `license.rtf` | Texto de licencia que WiX muestra durante la instalación |

## Icono de la aplicación (opcional)

Para personalizar el icono del instalador y del menú Inicio, coloca aquí un
archivo llamado **`Internet Cafe Desktop.ico`** (formato ICO, 256×256 recomendado).

Sin él, `jpackage` usa el icono predeterminado de Java. No es obligatorio para
que el `.msi` se genere correctamente.

Puedes convertir un PNG a ICO con:
- **ImageMagick:** `magick logo.png -define icon:auto-resize="256,128,64,48,32,16" Internet\ Cafe\ Desktop.ico`
- **GIMP:** Archivo → Exportar como → `.ico`

## Generar el instalador localmente

```powershell
# Dev (apunta a localhost)
$env:JAVA_HOME = "C:\Program Files\Java\jdk-21"
.\gradlew.bat -p desktop jpackageMsi

# Producción (URL de Render)
.\gradlew.bat -p desktop jpackageMsi -PapiBaseUrl=https://api-prod.render.com -PappVersion=1.0.0
```

El `.msi` resultante se genera en `desktop/build/installer/`.

## Requisitos

- Windows 10/11
- JDK 21 completo (incluye `jpackage`)
- [WiX Toolset 3.14](https://github.com/wixtoolset/wix3/releases/tag/wix3141rtm) instalado y en el `PATH`

## UUID de upgrade

El `--win-upgrade-uuid` está fijo en `build.gradle`:

```
7F3A1B2C-9D4E-5F60-A7B8-C9D0E1F2A3B4
```

**No cambiar este valor.** Que sea fijo garantiza que reinstalar o actualizar
el `.msi` conserve los datos de `%ProgramData%\InternetCafe` (identidad P-256,
credenciales de enrolamiento, etc.).
