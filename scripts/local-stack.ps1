[CmdletBinding()]
param(
    [ValidateSet("start", "status", "text", "stop")]
    [string]$Action = "start",
    [string]$Scene = "apartment",
    [string]$OllamaModel = "qwen3-vl:8b",
    [string]$Microphone = "1",
    [ValidateSet("auto", "gamepad", "keyboard")]
    [string]$Trigger = "auto",
    [int]$GamepadButton = 128,
    [int]$TelemetryPort = 8780,
    [string]$Text,
    [switch]$NoVoice
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
$Workspace = Split-Path -Parent $Project
$VolumeRoot = Split-Path -Qualifier $Workspace
$AiRoot = Join-Path $VolumeRoot "IA\LLM"
$Drive = $Workspace.Substring(0, 1).ToLowerInvariant()
$RelativeWorkspace = $Workspace.Substring(2).Replace("\", "/")
$WorkspaceWsl = "/mnt/$Drive$RelativeWorkspace"
$Brain = "$WorkspaceWsl/microduck_remote_brain"
$Distro = "Ubuntu-22.04"
$LocalState = Join-Path $Project ".local"
$StopRequest = Join-Path $LocalState "stop-requested"

function Invoke-WslStack {
    param(
        [Parameter(Mandatory)][ValidateSet("start", "status", "stop")]
        [string]$StackAction
    )
    & wsl.exe -d $Distro -- /bin/bash "$Brain/scripts/local-stack-wsl.sh" $StackAction $Scene $WorkspaceWsl $TelemetryPort
    if ($LASTEXITCODE -ne 0) {
        throw "WSL stack action '$StackAction' failed with exit code $LASTEXITCODE"
    }
}

function Test-XInputGamepad {
    $Python = Join-Path $Project ".venv\Scripts\python.exe"
    if (-not (Test-Path $Python)) {
        return $false
    }
    $Result = & $Python -c "from microduck_remote_brain.xinput import is_connected; print(int(is_connected()))"
    return $LASTEXITCODE -eq 0 -and $Result[-1] -eq "1"
}

function Get-LanAddress {
    $Address = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.InterfaceAlias -match "^Ethernet( \d+)?$"
        } |
        Select-Object -First 1 -ExpandProperty IPAddress
    return $Address
}

function Ensure-TelemetryFirewallRule {
    $RuleName = "MicroDuck Telemetry TCP $TelemetryPort"
    try {
        if ($null -eq (Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue)) {
            $RuleCommand = "New-NetFirewallRule -Name '$RuleName' -DisplayName '$RuleName' -Direction Inbound -Action Allow -Profile Private -Protocol TCP -LocalPort $TelemetryPort"
            Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-Command", $RuleCommand) | Out-Null
        }
    }
    catch {
        Write-Warning "Windows Firewall was not updated. Run PowerShell as Administrator once to allow TCP port $TelemetryPort on Private networks."
    }
}

function Show-TelemetryEndpoint {
    $LanAddress = Get-LanAddress
    Ensure-TelemetryFirewallRule
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$TelemetryPort/api/health" -TimeoutSec 2
            if ($Health.status -eq "ok") { break }
        }
        catch {
        }
        [System.Threading.Thread]::Sleep(250)
    }
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$TelemetryPort/api/health" -TimeoutSec 2
    }
    catch {
        Write-Warning "Telemetry startup log:"
        Get-Content (Join-Path $LocalState "telemetry-error.log") -ErrorAction SilentlyContinue
        throw "Telemetry dashboard did not become reachable on port $TelemetryPort"
    }
    if ($Health.status -ne "ok") { throw "Telemetry dashboard is not healthy" }
    Write-Host "MuJoCo telemetry: http://localhost:$TelemetryPort"
    if ($LanAddress) {
        try {
            $LanHealth = Invoke-RestMethod -Uri "http://${LanAddress}:$TelemetryPort/api/health" -TimeoutSec 2
            if ($LanHealth.status -ne "ok") { throw "unexpected health response" }
        }
        catch {
            throw "Telemetry is local but not reachable through http://${LanAddress}:$TelemetryPort"
        }
        Write-Host "Network telemetry: http://${LanAddress}:$TelemetryPort"
    }
    else { Write-Warning "No Ethernet IPv4 address was detected; telemetry is only advertised locally." }
}

function Start-TelemetryServer {
    New-Item -ItemType Directory -Force -Path $LocalState | Out-Null
    $PidFile = Join-Path $LocalState "telemetry.pid"
    Stop-ManagedPythonProcess -PidFile $PidFile -CommandMarker "microduck_remote_brain.telemetry_server"
    $Start = @{
        FilePath = "$Project\.venv\Scripts\python.exe"
        ArgumentList = @(
            "-u", "-m", "microduck_remote_brain.telemetry_server",
            "--simulator-host", "127.0.0.1", "--simulator-port", "7801",
            "--listen-host", "0.0.0.0", "--listen-port", "$TelemetryPort"
        )
        RedirectStandardOutput = Join-Path $LocalState "telemetry.log"
        RedirectStandardError = Join-Path $LocalState "telemetry-error.log"
        PassThru = $true
    }
    $Process = Start-Process @Start
    Set-Content -Path $PidFile -Value $Process.Id
}

function Stop-ManagedPythonProcess {
    param(
        [Parameter(Mandatory)][string]$PidFile,
        [Parameter(Mandatory)][string]$CommandMarker
    )
    if (-not (Test-Path $PidFile)) {
        return
    }
    try {
        $ManagedPid = [int](Get-Content $PidFile -ErrorAction Stop)
    }
    catch [System.Management.Automation.ItemNotFoundException] {
        return
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    $Managed = Get-CimInstance Win32_Process -Filter "ProcessId = $ManagedPid" -ErrorAction SilentlyContinue
    if ($null -eq $Managed) {
        return
    }
    $PythonLauncher = (Resolve-Path "$Project\.venv\Scripts\python.exe").Path
    $ExpectedPython = (& $PythonLauncher -c "import sys; print(sys._base_executable)" |
        Select-Object -Last 1).Trim()
    $SameExecutable = $Managed.ExecutablePath -in @($PythonLauncher, $ExpectedPython)
    $SameCommand = $Managed.CommandLine -like "*$CommandMarker*"
    if ($SameExecutable -and $SameCommand) {
        $ManagedPids = @($ManagedPid)
        $Related = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                ($_.ParentProcessId -eq $ManagedPid -or $_.ProcessId -eq $Managed.ParentProcessId) -and
                $_.ExecutablePath -in @($PythonLauncher, $ExpectedPython) -and
                $_.CommandLine -like "*$CommandMarker*"
            }
        $ManagedPids += @($Related | ForEach-Object { [int]$_.ProcessId })
        $ManagedPids = @($ManagedPids | Sort-Object -Unique)
        foreach ($ProcessId in $ManagedPids) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
        Wait-Process -Id $ManagedPids -Timeout 5 -ErrorAction SilentlyContinue
        $Remaining = @($ManagedPids | Where-Object {
            $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue)
        })
        if ($Remaining.Count -ne 0) {
            throw "Managed process $($Remaining -join ', ') for $CommandMarker did not stop"
        }
    }
    else {
        Write-Warning "PID $ManagedPid no longer belongs to $CommandMarker; it was not stopped."
    }
}

function Show-GamepadStatus {
    $PidFile = Join-Path $Project ".local\gamepad.pid"
    $ProcessRunning = $false
    if (Test-Path $PidFile) {
        $ProcessRunning = $null -ne (Get-Process -Id ([int](Get-Content $PidFile)) -ErrorAction SilentlyContinue)
    }
    if (Test-XInputGamepad) {
        Write-Host "Gamepad:           connected through XInput"
    }
    else {
        Write-Warning "Gamepad is paired in Windows but no XInput stream is available. The client is waiting safely. Wake or re-pair it, then verify with joy.cpl."
    }
    Write-Host "Gamepad client:    $(if ($ProcessRunning) { 'running' } else { 'not running' })"
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port)
    try {
        $Client = [System.Net.Sockets.TcpClient]::new()
        $Connect = $Client.ConnectAsync($HostName, $Port)
        if (-not $Connect.Wait(2000)) {
            return $false
        }
        return $Client.Connected
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $Client) {
            $Client.Dispose()
        }
    }
}

function Ensure-Ollama {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
        return
    }
    catch {
        $Ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        if (-not (Test-Path $Ollama)) {
            throw "Ollama is not installed at $Ollama"
        }
        $OllamaProcess = Start-Process -FilePath $Ollama -ArgumentList "serve" -WindowStyle Hidden -PassThru
        for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
            [System.Threading.Thread]::Sleep(500)
            try {
                Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
                $LocalState = Join-Path $Project ".local"
                New-Item -ItemType Directory -Force -Path $LocalState | Out-Null
                Set-Content -Path (Join-Path $LocalState "ollama.pid") -Value $OllamaProcess.Id
                return
            }
            catch {
            }
        }
        throw "Ollama did not become ready"
    }
}

function Assert-OllamaModel {
    $Models = (Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3).models |
        ForEach-Object { $_.name }
    if ($OllamaModel -notin $Models) {
        throw "Ollama model '$OllamaModel' is not installed. Run: ollama pull $OllamaModel"
    }
}

function Stop-ManagedOllama {
    $PidFile = Join-Path $Project ".local\ollama.pid"
    if (-not (Test-Path $PidFile)) {
        return
    }
    try {
        $ManagedPid = [int](Get-Content $PidFile -ErrorAction Stop)
    }
    catch [System.Management.Automation.ItemNotFoundException] {
        return
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    $Managed = Get-CimInstance Win32_Process -Filter "ProcessId = $ManagedPid" -ErrorAction SilentlyContinue
    if ($null -eq $Managed) {
        return
    }
    $ExpectedOllama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if ($Managed.ExecutablePath -eq $ExpectedOllama -and $Managed.CommandLine -like "*serve*") {
        Stop-Process -Id $ManagedPid -ErrorAction SilentlyContinue
    }
    else {
        Write-Warning "PID $ManagedPid no longer belongs to the managed Ollama server; it was not stopped."
    }
}

if ($Action -eq "stop") {
    New-Item -ItemType Directory -Force -Path $LocalState | Out-Null
    Set-Content -Path $StopRequest -Value "stop"
    Stop-ManagedPythonProcess -PidFile (Join-Path $Project ".local\panel.pid") -CommandMarker "microduck_remote_brain.control_panel"
    Stop-ManagedPythonProcess -PidFile (Join-Path $Project ".local\voice.pid") -CommandMarker "microduck_remote_brain.voice_cli"
    Stop-ManagedPythonProcess -PidFile (Join-Path $Project ".local\gamepad.pid") -CommandMarker "microduck_remote_brain.gamepad_cli"
    Stop-ManagedPythonProcess -PidFile (Join-Path $Project ".local\telemetry.pid") -CommandMarker "microduck_remote_brain.telemetry_server"
    Stop-ManagedOllama
    Invoke-WslStack -StackAction stop
    Write-Host "Local MicroDuck stack stopped."
    exit 0
}

if ($Action -eq "status") {
    Invoke-WslStack -StackAction status
    if (-not (Test-TcpPort "127.0.0.1" 8765)) {
        throw "Fake Wi-Fi gateway is not reachable on 127.0.0.1:8765"
    }
    Ensure-Ollama
    Assert-OllamaModel
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$TelemetryPort/api/health" -TimeoutSec 2
    if ($Health.status -ne "ok") { throw "Telemetry dashboard is not healthy" }
    Write-Host "Fake Wi-Fi, telemetry, and Ollama are reachable."
    Show-GamepadStatus
    exit 0
}

Write-Host "Synchronizing the PC-side brain..."
$StackStarted = $false
try {
Remove-Item $StopRequest -Force -ErrorAction SilentlyContinue
& uv sync --project $Project --extra voice --dev
if ($LASTEXITCODE -ne 0) {
    throw "Remote Brain dependency synchronization failed"
}
Ensure-Ollama
Assert-OllamaModel

Write-Host "Starting the visual MicroDuck world, robot runtime, audio, and fake Wi-Fi..."
Invoke-WslStack -StackAction start
$StackStarted = $true

for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    if (Test-TcpPort "127.0.0.1" 8765) {
        break
    }
    [System.Threading.Thread]::Sleep(250)
}
if (-not (Test-TcpPort "127.0.0.1" 8765)) {
    throw "Fake Wi-Fi gateway did not become reachable"
}
Start-TelemetryServer
Show-TelemetryEndpoint

Write-Host "Visual simulator: ready"
Write-Host "Fake Wi-Fi:       127.0.0.1:8765"
Write-Host "Ollama model:     $OllamaModel"

$LocalState = Join-Path $Project ".local"
New-Item -ItemType Directory -Force -Path $LocalState | Out-Null
$PanelPidFile = Join-Path $LocalState "panel.pid"
Stop-ManagedPythonProcess -PidFile $PanelPidFile -CommandMarker "microduck_remote_brain.control_panel"
$PanelStart = @{
    FilePath = "$Project\.venv\Scripts\python.exe"
    ArgumentList = @("-m", "microduck_remote_brain.control_panel")
    PassThru = $true
}
$PanelProcess = Start-Process @PanelStart
Set-Content -Path $PanelPidFile -Value $PanelProcess.Id
$GamepadPidFile = Join-Path $LocalState "gamepad.pid"
Stop-ManagedPythonProcess -PidFile $GamepadPidFile -CommandMarker "microduck_remote_brain.gamepad_cli"
$GamepadStart = @{
    FilePath = "$Project\.venv\Scripts\python.exe"
    ArgumentList = @(
        "-u", "-m", "microduck_remote_brain.gamepad_cli",
        "--robot-host", "127.0.0.1",
        "--robot-port", "8765",
        "--pause-file", (Join-Path $LocalState "brain-active"),
        "--status-file", (Join-Path $LocalState "gamepad-state.json")
    )
    RedirectStandardOutput = Join-Path $LocalState "gamepad.log"
    RedirectStandardError = Join-Path $LocalState "gamepad-error.log"
    PassThru = $true
}
$GamepadProcess = Start-Process @GamepadStart
Set-Content -Path $GamepadPidFile -Value $GamepadProcess.Id
Show-GamepadStatus

if ($NoVoice) {
    Write-Host "Voice loop skipped. Run this script again without -NoVoice when ready."
    exit 0
}

$VoiceArguments = @(
    "-m", "microduck_remote_brain.voice_cli",
    "--ollama-model", $OllamaModel,
    "--robot-host", "127.0.0.1",
    "--robot-port", "8765",
    "--simulator-host", "127.0.0.1",
    "--simulator-port", "7801",
    "--minimum-displacement", "0.02",
    "--gamepad-pause-file", (Join-Path $LocalState "brain-active"),
    "--pid-file", (Join-Path $LocalState "voice.pid")
)

if ($Action -eq "text") {
    if ([string]::IsNullOrWhiteSpace($Text)) {
        throw "-Text is required with -Action text"
    }
    $VoiceArguments += @("--text", $Text)
}
else {
    $ResolvedTrigger = $Trigger
    if ($ResolvedTrigger -eq "auto") {
        $ResolvedTrigger = if (Test-XInputGamepad) { "gamepad" } else { "keyboard" }
    }
    $VoiceArguments += @(
        "--trigger", $ResolvedTrigger,
        "--gamepad-button", "$GamepadButton",
        "--microphone", $Microphone,
        "--whisper-exe", "$AiRoot\whisper.cpp\build_bis\bin\Release\whisper-cli.exe",
        "--whisper-model", "$AiRoot\whisper.cpp\models\ggml-large-v3.bin"
    )
    Write-Host "Push-to-talk trigger: $ResolvedTrigger (gamepad button index $GamepadButton)"
}

& "$Project\.venv\Scripts\python.exe" @VoiceArguments
$VoiceExitCode = $LASTEXITCODE
if (Test-Path $StopRequest) {
    Remove-Item $StopRequest -Force -ErrorAction SilentlyContinue
    exit 0
}
if ($VoiceExitCode -ne 0) {
    throw "Voice pipeline failed with exit code $VoiceExitCode"
}
exit 0
}
catch {
    Stop-ManagedPythonProcess -PidFile (Join-Path $Project ".local\panel.pid") -CommandMarker "microduck_remote_brain.control_panel"
    Stop-ManagedPythonProcess -PidFile (Join-Path $Project ".local\voice.pid") -CommandMarker "microduck_remote_brain.voice_cli"
    Stop-ManagedPythonProcess -PidFile (Join-Path $Project ".local\gamepad.pid") -CommandMarker "microduck_remote_brain.gamepad_cli"
    Stop-ManagedPythonProcess -PidFile (Join-Path $Project ".local\telemetry.pid") -CommandMarker "microduck_remote_brain.telemetry_server"
    Stop-ManagedOllama
    if ($StackStarted) {
        try {
            Invoke-WslStack -StackAction stop
        }
        catch {
            Write-Warning "Stack rollback failed: $_"
        }
    }
    throw
}