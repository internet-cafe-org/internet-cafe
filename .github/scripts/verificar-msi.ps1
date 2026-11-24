<#
.SYNOPSIS
    Verifica el instalador .msi del escritorio antes de publicarlo (OPS-14).

.DESCRIPTION
    1. Exige exactamente un .msi en la carpeta de salida de jpackageMsi.
    2. Lo extrae sin instalarlo (msiexec /a, instalación administrativa).
    3. Exige que la configuración del lanzador (app\*.cfg) lleve
       -Dapi.base.url=<URL esperada>, que es la que AppConfig lee al arrancar.
       Si falta, el equipo instalado buscaría la API en otra dirección. Debe haber
       exactamente una línea, porque con dos ganaría la última.
    Escribe la ruta del .msi en la salida "msi" del paso de GitHub Actions.

.PARAMETER Directorio
    Carpeta donde jpackageMsi deja el .msi (desktop/build/installer).

.PARAMETER UrlEsperada
    URL de la API que debe quedar fija en el instalador, sin "/" final.
#>
param(
    [Parameter(Mandatory = $true)][string]$Directorio,
    [Parameter(Mandatory = $true)][string]$UrlEsperada
)

$ErrorActionPreference = 'Stop'

function Fallar([string]$mensaje) {
    Write-Output "::error::$mensaje"
    exit 1
}

$msis = @(Get-ChildItem -Path $Directorio -Filter '*.msi' -File -ErrorAction SilentlyContinue)
if ($msis.Count -ne 1) {
    Fallar "Se esperaba exactamente un .msi en $Directorio y hay $($msis.Count)."
}
$msi = $msis[0].FullName

$destino = Join-Path $env:RUNNER_TEMP 'msi-extraido'
if (Test-Path $destino) {
    Remove-Item -Recurse -Force $destino
}
$registro = Join-Path $env:RUNNER_TEMP 'msi-extraido.log'
$proceso = Start-Process -FilePath 'msiexec.exe' -Wait -PassThru -ArgumentList @(
    '/a', "`"$msi`"", '/qn', "TARGETDIR=`"$destino`"", '/L*v', "`"$registro`""
)
if ($proceso.ExitCode -ne 0) {
    Fallar "msiexec no pudo extraer el .msi (código $($proceso.ExitCode)). Detalle en $registro."
}

$configs = @(Get-ChildItem -Path $destino -Recurse -Filter '*.cfg' -File |
    Where-Object { $_.Directory.Name -eq 'app' })
if ($configs.Count -ne 1) {
    Fallar "Se esperaba un archivo de configuración del lanzador (app\*.cfg) y hay $($configs.Count)."
}

$contenido = Get-Content -Raw -Path $configs[0].FullName
Write-Output "Configuración del lanzador ($($configs[0].Name)):"
Write-Output $contenido

$patron = '(?m)^java-options=-Dapi\.base\.url=' + [regex]::Escape($UrlEsperada) + '\s*$'
if ($contenido -notmatch $patron) {
    Fallar ("El lanzador del .msi no fija -Dapi.base.url=$UrlEsperada. jpackage con " +
        "--runtime-image crea su propio lanzador y no hereda los jvmArgs de jlink: " +
        "jpackageMsi (desktop/build.gradle) debe pasar --java-options con la URL.")
}

$lineas = [regex]::Matches($contenido, '(?m)^java-options=-Dapi\.base\.url=').Count
if ($lineas -ne 1) {
    Fallar "El lanzador debe fijar -Dapi.base.url una sola vez y lo hace $lineas veces."
}

Write-Output "OK: el .msi fija -Dapi.base.url=$UrlEsperada"
"msi=$msi" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
