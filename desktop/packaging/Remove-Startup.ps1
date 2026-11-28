#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Elimina la tarea programada de arranque automatico de Internet Cafe Desktop (DSK-14b).

.DESCRIPTION
    Borra la tarea programada "Internet Cafe Desktop" registrada por Register-Startup.ps1.
    Debe ejecutarse con privilegios de administrador.
    Si la tarea no existe, termina sin error (operacion idempotente).

.EXAMPLE
    .\Remove-Startup.ps1
    Elimina la tarea de arranque automatico si existe.

.NOTES
    Tarea programada eliminada : "Internet Cafe Desktop"
    Issue                      : #107  HU-18  DSK-14b
#>

[CmdletBinding(SupportsShouldProcess)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TaskName = "Internet Cafe Desktop"

function Get-StartupTaskQuery {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        $output = & schtasks.exe /Query /TN $TaskName /FO LIST 2>$null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    [PSCustomObject]@{
        Output   = $output
        ExitCode = $exitCode
    }
}

Write-Host ""
Write-Host "=== Internet Cafe Desktop — Eliminar arranque automatico ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Comprobar si la tarea existe
# ---------------------------------------------------------------------------
$query = Get-StartupTaskQuery
if ($query.ExitCode -ne 0) {
    Write-Host "[INFO] La tarea '$TaskName' no esta registrada. No hay nada que eliminar." -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

Write-Host "[INFO] Tarea encontrada:"
Write-Host $query.Output
Write-Host ""

# ---------------------------------------------------------------------------
# 2. Eliminar la tarea
# ---------------------------------------------------------------------------
if ($PSCmdlet.ShouldProcess("schtasks", "Eliminar tarea '$TaskName'")) {
    $result = & schtasks.exe /Delete /TN $TaskName /F 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "schtasks fallo al eliminar la tarea (codigo $LASTEXITCODE): $result"
        exit $LASTEXITCODE
    }

    Write-Host $result
}

# ---------------------------------------------------------------------------
# 3. Verificar que la tarea ya no existe
# ---------------------------------------------------------------------------
Write-Host "[INFO] Verificando eliminacion..."
$query = Get-StartupTaskQuery
if ($query.ExitCode -eq 0) {
    Write-Warning "La tarea '$TaskName' todavia parece existir despues de la eliminacion."
    Write-Host $query.Output
    exit 1
}

Write-Host ""
Write-Host "=== Tarea eliminada con exito ===" -ForegroundColor Green
Write-Host ""
Write-Host "La aplicacion 'Internet Cafe Desktop' ya NO se iniciara automaticamente al iniciar sesion."
Write-Host ""
