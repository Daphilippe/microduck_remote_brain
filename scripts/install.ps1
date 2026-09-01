[CmdletBinding()]
param(
    [switch]$Voice
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
}

$Arguments = @("sync", "--project", $Project, "--dev")
if ($Voice) {
    $Arguments += @("--extra", "voice")
}

Write-Host "Synchronizing MicroDuck Remote Brain dependencies..."
& uv @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Dependency synchronization failed with exit code $LASTEXITCODE"
}

Write-Host "Installation complete. Run: uv run pytest"