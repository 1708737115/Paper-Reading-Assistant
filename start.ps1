$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Port {
  param([int]$Port)
  $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  return [bool]$connection
}

function Stop-ProjectServices {
  $escapedRoot = [regex]::Escape($root)
  Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "python.exe" -and $_.CommandLine -like "*uvicorn*api.app.main*") -or
    ($_.Name -eq "node.exe" -and $_.CommandLine -match $escapedRoot -and $_.CommandLine -like "*next*") -or
    ($_.Name -eq "node.exe" -and $_.CommandLine -like "*npm-cli.js*--prefix web run*")
  } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Seconds 2
}

if (-not (Test-Command "python")) {
  throw "Python was not found on PATH. Install Python 3.11+ first."
}

if (-not (Test-Command "npm")) {
  throw "npm was not found on PATH. Install Node.js 20+ first."
}

New-Item -ItemType Directory -Force -Path "data" | Out-Null

Write-Step "Preparing Python environment"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  python -m venv .venv
}
.\.venv\Scripts\python -m pip install -r api\requirements.txt

Write-Step "Preparing Node dependencies"
if (-not (Test-Path "node_modules")) {
  npm install --cache .npm-cache
}
if (-not (Test-Path "web\node_modules")) {
  npm --prefix web install --cache ..\.npm-cache
}

Write-Step "Stopping existing project services"
Stop-ProjectServices

Write-Step "Cleaning web build cache"
$nextDir = Join-Path $root "web\.next"
if (Test-Path $nextDir) {
  $resolvedNext = (Resolve-Path $nextDir).Path
  if (-not $resolvedNext.StartsWith($root)) {
    throw "Refusing to remove outside project: $resolvedNext"
  }
  Remove-Item -LiteralPath $resolvedNext -Recurse -Force
}

Write-Step "Building web app"
npm --prefix web run build

if (Test-Port 8000) {
  throw "Port 8000 is already in use. Close the existing API server and run this script again."
}

if (Test-Port 3000) {
  throw "Port 3000 is already in use. Close the existing web server and run this script again."
}

Write-Step "Starting local services"
$apiOut = Join-Path $root "data\api.out.log"
$apiErr = Join-Path $root "data\api.err.log"
$webOut = Join-Path $root "data\web.out.log"
$webErr = Join-Path $root "data\web.err.log"

$api = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
  -ArgumentList @("-m", "uvicorn", "api.app.main:app", "--host", "127.0.0.1", "--port", "8000") `
  -WorkingDirectory $root `
  -WindowStyle Hidden `
  -RedirectStandardOutput $apiOut `
  -RedirectStandardError $apiErr `
  -PassThru

$web = Start-Process -FilePath "npm.cmd" `
  -ArgumentList @("--prefix", "web", "run", "start") `
  -WorkingDirectory $root `
  -WindowStyle Hidden `
  -RedirectStandardOutput $webOut `
  -RedirectStandardError $webErr `
  -PassThru

Start-Sleep -Seconds 5

try {
  Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/health" -TimeoutSec 10 | Out-Null
  Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:3000" -TimeoutSec 10 | Out-Null
} catch {
  Write-Host ""
  Write-Host "Startup check failed. Recent logs:" -ForegroundColor Yellow
  Get-Content $apiErr -ErrorAction SilentlyContinue -Tail 30
  Get-Content $webErr -ErrorAction SilentlyContinue -Tail 30
  throw
}

Write-Host ""
Write-Host "Bilingual Paper Reader is running:" -ForegroundColor Green
Write-Host "  Web: http://127.0.0.1:3000"
Write-Host "  API: http://127.0.0.1:8000"
Write-Host "  API PID: $($api.Id)"
Write-Host "  Web PID: $($web.Id)"
Write-Host ""
Write-Host "Logs:"
Write-Host "  data\api.err.log"
Write-Host "  data\web.err.log"

Start-Process "http://127.0.0.1:3000"
