# NOBA Agent — Windows Installer (PowerShell)
# Usage: .\install-agent.ps1 -Server "http://noba:8080" -Key "YOUR_KEY"
#        .\install-agent.ps1  (interactive prompts)

param(
    [string]$Server = "",
    [string]$Key = "",
    [int]$Interval = 30
)

$ErrorActionPreference = "Stop"
$InstallDir = "$env:ProgramData\noba-agent"
$Config = "$InstallDir\noba-agent.yaml"
$TaskName = "NOBA Agent"

Write-Host ""
Write-Host "  NOBA Agent — Windows Installer" -ForegroundColor Cyan
Write-Host "  ───────────────────────────────" -ForegroundColor DarkCyan
Write-Host ""

# Prompt if not provided
if (-not $Server) { $Server = Read-Host "  NOBA Server URL" }
if (-not $Key)    { $Key    = Read-Host "  Agent API Key" }

if (-not $Server -or -not $Key) {
    Write-Host "[x] Server URL and API key are required" -ForegroundColor Red
    exit 1
}

# Check Python
$Python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $Python) {
    Write-Host "[x] Python 3 not found. Install from python.org" -ForegroundColor Red
    exit 1
}
Write-Host "[ok] Python: $($Python.Source)" -ForegroundColor Green

# Install psutil
try {
    & $Python.Source -c "import psutil" 2>$null
    Write-Host "[ok] psutil available" -ForegroundColor Green
} catch {
    Write-Host "[!] Installing psutil..." -ForegroundColor Yellow
    & $Python.Source -m pip install psutil 2>$null
}

# Deploy
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

# Download agent from server
Write-Host "  Downloading agent..."
try {
    $headers = @{ "X-Agent-Key" = $Key }
    Invoke-WebRequest -Uri "$Server/api/agent/update" -Headers $headers -OutFile "$InstallDir\agent.pyz" -UseBasicParsing
    Write-Host "[ok] Agent downloaded" -ForegroundColor Green
} catch {
    Write-Host "[!] Download failed, copying local agent..." -ForegroundColor Yellow
    Copy-Item "$PSScriptRoot\agent.pyz" "$InstallDir\agent.pyz" -Force
}

# Write config
@"
server: $Server
api_key: $Key
interval: $Interval
hostname: $env:COMPUTERNAME
tags: windows
"@ | Set-Content $Config -Encoding UTF8
Write-Host "[ok] Config: $Config" -ForegroundColor Green

# Test
Write-Host ""
Write-Host "  Testing connection..."
& $Python.Source "$InstallDir\agent.pyz" --config $Config --once
if ($LASTEXITCODE -eq 0) {
    Write-Host "[ok] Test report successful!" -ForegroundColor Green
} else {
    Write-Host "[!] Test failed — agent will retry with backoff" -ForegroundColor Yellow
}

# Create scheduled task (runs at startup + every 30s via loop)
$Action = New-ScheduledTaskAction -Execute $Python.Source -Argument "$InstallDir\agent.pyz --config $Config"
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[ok] Scheduled task '$TaskName' created and started" -ForegroundColor Green
} catch {
    Write-Host "[!] Could not create scheduled task: $_" -ForegroundColor Yellow
    Write-Host "    Run manually: python $InstallDir\agent.pyz --config $Config" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[ok] NOBA Agent installation complete!" -ForegroundColor Green
Write-Host ""
