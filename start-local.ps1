[CmdletBinding()]
param([switch]$RestartBackend)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backendDir = Join-Path $root 'backend'
$dashboardDir = Join-Path $root 'dashboard'
$python = Join-Path $backendDir '.venv\Scripts\python.exe'
$logs = Join-Path $root 'personal\local-weather\logs'
$api = 'http://127.0.0.1:8000'
$dashboard = 'http://127.0.0.1:5500'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Backend Python venv missing. Follow backend/README.md.'
}
New-Item -ItemType Directory -Path $logs -Force | Out-Null

function Wait-LocalService($Name, $TimeoutSeconds, [scriptblock]$Check) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            if (& $Check) {
                Write-Host "[OK] $Name"
                return
            }
        } catch {
            # Services can refuse connections while starting up.
        }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "$Name did not become ready. Check $logs"
}

function Get-LocalProcess([int]$Port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    }
}

function Test-ProjectPython($Process) {
    $command = [string]$Process.CommandLine
    $command.StartsWith('"' + $python + '" ', [StringComparison]::OrdinalIgnoreCase) -or
        $command.StartsWith($python + ' ', [StringComparison]::OrdinalIgnoreCase)
}

function Start-LocalPython($Name, $Directory, $Arguments) {
    $processOptions = @{
        FilePath = $python
        WorkingDirectory = $Directory
        ArgumentList = $Arguments
        WindowStyle = 'Hidden'
        RedirectStandardOutput = (Join-Path $logs "$Name.stdout.log")
        RedirectStandardError = (Join-Path $logs "$Name.stderr.log")
    }
    Start-Process @processOptions
}

function Test-DockerEngine {
    try {
        docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

Get-Command docker | Out-Null
if (-not (Test-DockerEngine)) {
    $dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path -LiteralPath $dockerDesktop -PathType Leaf) {
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    }
    Wait-LocalService 'Docker Desktop' 90 { Test-DockerEngine }
}
docker compose --project-directory $root up -d --no-recreate mqtt-broker postgres-db
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose could not start MQTT and PostgreSQL.' }
Wait-LocalService 'PostgreSQL' 35 {
    docker compose --project-directory $root exec -T postgres-db pg_isready | Out-Null
    $LASTEXITCODE -eq 0
}

$runningBackend = Get-LocalProcess 8000
$backendCommand = ' -m uvicorn app\.main:app --host 127\.0\.0\.1 --port 8000$'
if ($runningBackend) {
    if (-not ((Test-ProjectPython $runningBackend) -and $runningBackend.CommandLine -match $backendCommand)) {
        throw 'Port 8000 is already in use by a different command. Free the port before retrying.'
    }
    if ($RestartBackend) {
        Stop-Process -Id $runningBackend.ProcessId
        Wait-LocalService 'Port 8000 released' 10 { -not (Get-LocalProcess 8000) }
    }
}
if (-not $runningBackend -or $RestartBackend) {
    Start-LocalPython 'backend' $backendDir '-m uvicorn app.main:app --host 127.0.0.1 --port 8000'
}
Wait-LocalService 'Backend and MQTT' 45 {
    $health = Invoke-RestMethod -Uri "$api/api/health" -TimeoutSec 3
    $health.service -eq 'IoT Weather Backend' -and $health.database_connected -and $health.mqtt_connected
}

if (-not (Get-LocalProcess 5500)) {
    Start-LocalPython 'dashboard' $dashboardDir '-m http.server 5500 --bind 127.0.0.1'
}
Wait-LocalService 'Dashboard' 12 {
    $page = Invoke-WebRequest -Uri $dashboard -TimeoutSec 3 -UseBasicParsing
    $page.Content -match 'id="forecast-evaluation"'
}

$crawlCommand = ' -m openweather_benchmark\.crawler --loop-recent-15min( |$)'
$crawler = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    (Test-ProjectPython $_) -and $_.CommandLine -match $crawlCommand
} | Select-Object -First 1
if (-not $crawler) {
    $crawlerArguments = '-m openweather_benchmark.crawler --loop-recent-15min --interval 900'
    Start-LocalPython 'open-meteo' (Join-Path $root 'ai_engine') $crawlerArguments
}
try {
    Wait-LocalService 'Open-Meteo reference data' 45 {
        $reference = Invoke-RestMethod -Uri "$api/api/weather/benchmark?source=open-meteo-15min&hours=1" -TimeoutSec 5
        @($reference.reference).Count -gt 0
    }
} catch {
    Write-Warning "Open-Meteo data is not available yet. The crawler retries every 15 minutes. Check $logs"
}
Write-Host "Dashboard: $dashboard/?device=station01&view=forecast"
Write-Host "Backend:   $api/docs"
