param(
  [switch]$SkipE2E,
  [switch]$SkipEventSmoke,
  [switch]$SkipDockerConfig
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ApiRoot = Join-Path $RepoRoot "apps\api"
$WebRoot = Join-Path $RepoRoot "apps\web"
$TestResultsRoot = Join-Path $RepoRoot "test-results"
New-Item -ItemType Directory -Path $TestResultsRoot -Force | Out-Null

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
    Name = "Docker compose config"
    WorkingDirectory = $RepoRoot
    Command = "docker"
    Arguments = @("compose", "config", "--quiet")
    Skip = $SkipDockerConfig
  },
  @{
    Name = "API tests"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("-m", "pytest", "apps\api\tests", "-q")
  },
  @{
    Name = "API mypy"
    WorkingDirectory = $ApiRoot
    Command = "python"
    Arguments = @("-m", "mypy", "app", "--no-incremental")
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
    Name = "Source allowlist validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_source_allowlist.py")
  },
  @{
    Name = "OpenAPI validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_openapi.py")
  },
  @{
    Name = "Contract fixtures validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_contract_fixtures.py")
  },
  @{
    Name = "Migration validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_migrations.py")
  },
  @{
    Name = "Monitoring assets validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_monitoring_assets.py")
  },
  @{
    Name = "Production readiness evidence validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_production_readiness_evidence.py")
  },
  @{
    Name = "Basemap CDN evidence validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_basemap_cdn_evidence.py")
  },
  @{
    Name = "Public reports launch evidence validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_public_reports_launch_evidence.py")
  },
  @{
    Name = "Risk calibration manifest validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_risk_calibration_manifest.py")
  },
  @{
    Name = "Flood-potential import manifest validator"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("infra\scripts\validate_flood_potential_import.py")
  },
  @{
    Name = "Unknown address smoke"
    WorkingDirectory = $RepoRoot
    Command = "python"
    Arguments = @("scripts\unknown_address_smoke.py")
  },
  @{
    Name = "Web audit"
    WorkingDirectory = $WebRoot
    Command = "npm"
    Arguments = @("audit")
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
  },
  @{
    Name = "Web build"
    WorkingDirectory = $WebRoot
    Command = "npm"
    Arguments = @("run", "build")
  }
)

if (-not $SkipEventSmoke) {
  $Steps += @(
    @{
      Name = "Event public-value smoke no-network"
      WorkingDirectory = $RepoRoot
      Command = "python"
      Arguments = @(
        "scripts\event_public_value_smoke.py",
        "--sample-size",
        "100",
        "--mode",
        "no-network",
        "--json-output",
        (Join-Path $TestResultsRoot "public-beta-local-gate-event-no-network.json"),
        "--markdown-output",
        (Join-Path $TestResultsRoot "public-beta-local-gate-event-no-network.md")
      )
    },
    @{
      Name = "Event public-value smoke simulated-heavy-rain"
      WorkingDirectory = $RepoRoot
      Command = "python"
      Arguments = @(
        "scripts\event_public_value_smoke.py",
        "--sample-size",
        "100",
        "--mode",
        "simulated-heavy-rain",
        "--json-output",
        (Join-Path $TestResultsRoot "public-beta-local-gate-event-simulated-heavy-rain.json"),
        "--markdown-output",
        (Join-Path $TestResultsRoot "public-beta-local-gate-event-simulated-heavy-rain.md")
      )
    }
  )
}

foreach ($Step in $Steps) {
  if ($Step.Skip) {
    Write-Host ""
    Write-Host "==> $($Step.Name)"
    Write-Host "Skipped by flag."
    continue
  }

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
Write-Host "Hosted public beta still requires private production evidence; see docs\runbooks\private-production-evidence-handoff.md"
