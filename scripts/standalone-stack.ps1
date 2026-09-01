[CmdletBinding()]
param(
    [ValidateSet("start", "status", "logs", "stop")]
    [string]$Action = "start",
    [switch]$WithAutonomy
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
$Compose = Join-Path $Project "compose.yaml"

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running. Start it, then retry this command."
}

$Arguments = @("compose", "--file", $Compose)
if ($WithAutonomy) {
    $Arguments += @("--profile", "autonomy")
}

switch ($Action) {
    "start" {
        & docker @Arguments up --detach --build --wait
        if ($LASTEXITCODE -ne 0) { throw "The standalone stack failed to start." }
        Write-Host "Telemetry: http://localhost:8780"
        Write-Host "robotd contract: 127.0.0.1:8765"
        Write-Host "Simulator oracle: 127.0.0.1:7801"
    }
    "status" { & docker @Arguments ps }
    "logs" { & docker @Arguments logs --follow --tail 100 }
    "stop" { & docker @Arguments down }
}

if ($LASTEXITCODE -ne 0) {
    throw "docker compose $Action failed with exit code $LASTEXITCODE"
}