param(
  [switch]$SkipE2E
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$WebRoot = Join-Path $RepoRoot "apps\web"

function Invoke-GateStep {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$Command,
    [string[]]$Arguments = @()
  )

  Write-Host ""
  Write-Host "==> $Name"
  Push-Location $WorkingDirectory
  try {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
      throw "$Name failed with exit code $LASTEXITCODE"
    }
  } finally {
    Pop-Location
  }
}

function Get-FreeTcpPort {
  $Listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Parse("127.0.0.1"),
    0
  )
  try {
    $Listener.Start()
    return $Listener.LocalEndpoint.Port
  } finally {
    $Listener.Stop()
  }
}

$Steps = @(
  @{
    Name = "API tests"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("-m", "pytest", "apps\api\tests", "-q")
  },
  @{
    Name = "Worker tests"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("-m", "pytest", "apps\workers\tests", "-q")
  },
  @{
    Name = "Repository tests"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("-m", "pytest", "tests", "-q")
  },
  @{
    Name = "Unknown address smoke"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("scripts\unknown_address_smoke.py")
  },
  @{
    Name = "Web unit tests"
    WorkingDirectory = $WebRoot
    Command = "npm"
    Arguments = @("test")
  },
  @{
    Name = "Web typecheck"
    WorkingDirectory = $WebRoot
    Command = "npm"
    Arguments = @("run", "typecheck")
  },
  @{
    Name = "Web lint"
    WorkingDirectory = $WebRoot
    Command = "npm"
    Arguments = @("run", "lint")
  }
)

foreach ($Step in $Steps) {
  Invoke-GateStep `
    -Name $Step.Name `
    -WorkingDirectory $Step.WorkingDirectory `
    -Command $Step.Command `
    -Arguments $Step.Arguments
}

if (-not $SkipE2E) {
  $PreviousCi = $env:CI
  $PreviousE2eApiPort = $env:E2E_API_PORT
  $PreviousE2eWebPort = $env:E2E_WEB_PORT
  $PreviousPublicApiBaseUrl = $env:NEXT_PUBLIC_API_BASE_URL
  try {
    $env:CI = "1"
    $env:E2E_API_PORT = [string](Get-FreeTcpPort)
    $env:E2E_WEB_PORT = [string](Get-FreeTcpPort)
    Remove-Item Env:\NEXT_PUBLIC_API_BASE_URL -ErrorAction SilentlyContinue

    Invoke-GateStep `
      -Name "Web E2E" `
      -WorkingDirectory $WebRoot `
      -Command "npm" `
      -Arguments @("run", "e2e")
  } finally {
    if ($null -eq $PreviousCi) {
      Remove-Item Env:\CI -ErrorAction SilentlyContinue
    } else {
      $env:CI = $PreviousCi
    }
    if ($null -eq $PreviousE2eApiPort) {
      Remove-Item Env:\E2E_API_PORT -ErrorAction SilentlyContinue
    } else {
      $env:E2E_API_PORT = $PreviousE2eApiPort
    }
    if ($null -eq $PreviousE2eWebPort) {
      Remove-Item Env:\E2E_WEB_PORT -ErrorAction SilentlyContinue
    } else {
      $env:E2E_WEB_PORT = $PreviousE2eWebPort
    }
    if ($null -eq $PreviousPublicApiBaseUrl) {
      Remove-Item Env:\NEXT_PUBLIC_API_BASE_URL -ErrorAction SilentlyContinue
    } else {
      $env:NEXT_PUBLIC_API_BASE_URL = $PreviousPublicApiBaseUrl
    }
  }
}

Write-Host ""
Write-Host "PUBLIC_BETA_LOCAL_GATE passed"
Write-Host "Hosted public beta still requires production evidence; see docs\runbooks\public-beta-readiness-2026-05-04.md"
