[CmdletBinding()]
param(
    [string]$Config,
    [switch]$Once,
    [Nullable[int]]$MaxCycles
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Config)) {
    $Config = Join-Path $Project "config\microduck.sim.toml"
}
elseif (-not [System.IO.Path]::IsPathRooted($Config)) {
    $Config = Join-Path (Get-Location) $Config
}

if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw "MicroDuck brain configuration does not exist: $Config"
}

& uv sync --project $Project --extra vision --extra voice --dev
if ($LASTEXITCODE -ne 0) {
    throw "Remote Brain dependency synchronization failed"
}

$Arguments = @(
    "run", "--project", $Project,
    "microduck-autonomous",
    "--config", $Config
)
if ($Once) {
    $Arguments += "--once"
}
if ($null -ne $MaxCycles) {
    $Arguments += @("--max-cycles", $MaxCycles.Value)
}

& uv @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Autonomous MicroDuck brain failed with exit code $LASTEXITCODE"
}