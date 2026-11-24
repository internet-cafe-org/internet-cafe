#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registra Internet Cafe Desktop para arranque automatico al iniciar sesion (DSK-14b).

.DESCRIPTION
    Crea una tarea programada con schtasks que lanza la aplicacion Internet Cafe Desktop
    automaticamente cuando el usuario especificado inicia sesion en Windows.

    Debe ejecutarse con privilegios de administrador (lo exige #Requires).
    Es idempotente: si la tarea ya existe, la sobreescribe con la misma configuracion.

.PARAMETER UserAccount
    Cuenta de Windows que ejecutara la aplicacion al iniciar sesion.
    Por defecto usa el usuario actualmente en sesion (USERDOMAIN\USERNAME).
    Ejemplos: "DOMINIO\usuario", "PC-SALA01\alumno", ".\alumno"

.PARAMETER ApiBaseUrl
    URL base de la API a la que se conectara la aplicacion.
    Si no se especifica, la aplicacion usa su valor por defecto (API_BASE_URL del instalador
    o http://localhost:8000 si no se configuro).
    Ejemplo: "https://api.internet-cafe.example.com"

.EXAMPLE
    .\Register-Startup.ps1
    Registra la app para el usuario actual sin URL personalizada.

.EXAMPLE
    .\Register-Startup.ps1 -UserAccount "SALA01\alumno" -ApiBaseUrl "https://api.example.com"
    Registra la app para el usuario "alumno" del dominio/equipo "SALA01"
    apuntando a la URL de la API indicada.

.NOTES
    Tarea programada registrada : "Internet Cafe Desktop"
    Disparador               : ONLOGON (al iniciar sesion del usuario especificado)
    Ejecutable esperado       : %ProgramFiles%\Internet Cafe Desktop\Internet Cafe Desktop.exe
    Issue                     : #107  HU-18  DSK-14b
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $false)]
    [string]$UserAccount = "$env:USERDOMAIN\$env:USERNAME",

    [Parameter(Mandatory = $false)]
    [string]$ApiBaseUrl = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
$TaskName  = "Internet Cafe Desktop"
$ExePath   = Join-Path $env:ProgramFiles "Internet Cafe Desktop\Internet Cafe Desktop.exe"

# ---------------------------------------------------------------------------
# 1. Verificar que el ejecutable este instalado
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== Internet Cafe Desktop — Registro de arranque automatico ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    Write-Error @"
No se encontro el ejecutable de la aplicacion en:
  $ExePath

Asegurese de que el instalador .msi se haya ejecutado antes de registrar el arranque.
"@
    exit 1
}

Write-Host "[OK] Ejecutable encontrado:" -ForegroundColor Green
Write-Host "     $ExePath"
Write-Host ""

# ---------------------------------------------------------------------------
# 2. Construir los argumentos de la tarea
# ---------------------------------------------------------------------------
$TaskRun = "`"$ExePath`""

if ($ApiBaseUrl -ne "") {
    # La app lee --api-base-url=<url> en Main.applyApiBaseUrlArg() y lo fija como
    # propiedad api.base.url con prioridad sobre la URL embebida en el MSI.
    $TaskRun = "`"$ExePath`" --api-base-url `"$ApiBaseUrl`""
    Write-Host "[INFO] URL de la API configurada: $ApiBaseUrl"
}

# ---------------------------------------------------------------------------
# 3. Registrar la tarea programada (idempotente con /F)
# ---------------------------------------------------------------------------
Write-Host "[INFO] Registrando tarea programada..."
Write-Host "       Nombre   : $TaskName"
Write-Host "       Usuario  : $UserAccount"
Write-Host "       Comando  : $TaskRun"
Write-Host ""

if ($PSCmdlet.ShouldProcess("schtasks", "Crear tarea '$TaskName' para '$UserAccount'")) {
    $schtasksArgs = @(
        '/Create',
        '/TN', $TaskName,
        '/TR', $TaskRun,
        '/SC', 'ONLOGON',
        '/RU', $UserAccount,
        '/RL', 'HIGHEST',
        '/F'          # Sobreescribir si ya existe (idempotente)
    )

    $result = & schtasks.exe @schtasksArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "schtasks fallo (codigo $LASTEXITCODE): $result"
        exit $LASTEXITCODE
    }

    Write-Host $result
}

# ---------------------------------------------------------------------------
# 4. Verificar que la tarea quedo registrada
# ---------------------------------------------------------------------------
Write-Host "[INFO] Verificando registro..."
$query = & schtasks.exe /Query /TN $TaskName /FO LIST 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warning "La tarea se creo pero no pudo consultarse: $query"
} else {
    Write-Host $query
}

Write-Host ""
Write-Host "=== Registro completado con exito ===" -ForegroundColor Green
Write-Host ""
Write-Host "La aplicacion 'Internet Cafe Desktop' se iniciara automaticamente"
Write-Host "cuando '$UserAccount' inicie sesion en este equipo."
Write-Host ""
Write-Host "Para eliminar el arranque automatico ejecute Remove-Startup.ps1"
Write-Host ""
