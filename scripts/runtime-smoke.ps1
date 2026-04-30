param(
    [int]$StartupTimeoutSeconds = 180,
    [int]$HttpTimeoutSeconds = 10,
    [string]$ApiBaseUrl = "http://localhost:8000",
    [string]$WebBaseUrl = "http://localhost:3000",
    [switch]$StopOnExit
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Fail-Smoke {
    param(
        [string]$Message,
        [string]$ServiceForLogs = ""
    )

    [Console]::Error.WriteLine("Runtime smoke failed: $Message")
    if ($ServiceForLogs) {
        Write-Host ""
        Write-Host "Recent $ServiceForLogs logs:"
        docker compose logs --tail=80 $ServiceForLogs
    }
    exit 1
}

function Invoke-CheckedCommand {
    param(
        [string]$Description,
        [string[]]$Command
    )

    Write-Step $Description
    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        Fail-Smoke "$Description exited with code $LASTEXITCODE"
    }
}

function Wait-HttpJson {
    param(
        [string]$Name,
        [string]$Url,
        [int[]]$AcceptStatusCodes = @(200),
        [int]$TimeoutSeconds = $StartupTimeoutSeconds,
        [string]$ServiceForLogs = "api"
    )

    Write-Step "Waiting for $Name at $Url"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null

    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $HttpTimeoutSeconds
            if ($AcceptStatusCodes -contains [int]$response.StatusCode) {
                if ($response.Content) {
                    return $response.Content | ConvertFrom-Json
                }
                return $response
            }
            $lastError = "HTTP $($response.StatusCode)"
        }
        catch {
            $lastError = $_.Exception.Message
        }

        Start-Sleep -Seconds 3
    }

    Fail-Smoke "$Name did not become ready within ${TimeoutSeconds}s. Last error: $lastError" $ServiceForLogs
}

function Wait-HttpOk {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = $StartupTimeoutSeconds,
        [string]$ServiceForLogs = ""
    )

    Write-Step "Waiting for $Name at $Url"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null

    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $HttpTimeoutSeconds
            if ([int]$response.StatusCode -eq 200) {
                return $response
            }
            $lastError = "HTTP $($response.StatusCode)"
        }
        catch {
            $lastError = $_.Exception.Message
        }

        Start-Sleep -Seconds 3
    }

    Fail-Smoke "$Name did not return HTTP 200 within ${TimeoutSeconds}s. Last error: $lastError" $ServiceForLogs
}

function Invoke-JsonPost {
    param(
        [string]$Name,
        [string]$Url,
        [string]$JsonBody
    )

    Write-Step $Name
    try {
        return Invoke-RestMethod `
            -Method Post `
            -Uri $Url `
            -ContentType "application/json" `
            -Body $JsonBody `
            -TimeoutSec $HttpTimeoutSeconds
    }
    catch {
        Fail-Smoke "$Name failed: $($_.Exception.Message)" "api"
    }
}

try {
    Invoke-CheckedCommand "Validating docker compose config" @("docker", "compose", "config", "--quiet")

    Invoke-CheckedCommand "Checking Docker daemon" @("docker", "info")

    Invoke-CheckedCommand "Starting runtime services" @(
        "docker",
        "compose",
        "up",
        "-d",
        "postgres",
        "redis",
        "minio",
        "api",
        "web"
    )

    Invoke-CheckedCommand "Running database migrations" @(
        "docker",
        "compose",
        "--profile",
        "tools",
        "run",
        "--rm",
        "migrate"
    )

    $health = Wait-HttpJson -Name "API /health" -Url "$ApiBaseUrl/health"
    if ($health.status -ne "ok") {
        Fail-Smoke "Expected /health status ok, got '$($health.status)'." "api"
    }
    Write-Host "API health: status=$($health.status), service=$($health.service), version=$($health.version)"

    $ready = Wait-HttpJson -Name "API /ready" -Url "$ApiBaseUrl/ready"
    if ($ready.status -ne "ok") {
        $dependencySummary = ($ready.dependencies.PSObject.Properties | ForEach-Object {
            "$($_.Name)=$($_.Value.status)"
        }) -join ", "
        Fail-Smoke "Expected /ready status ok, got '$($ready.status)' ($dependencySummary)." "api"
    }
    Write-Host "API ready: database=$($ready.dependencies.database.status), redis=$($ready.dependencies.redis.status)"

    $riskPayload = @'
{
  "point": {
    "lat": 25.033,
    "lng": 121.5654
  },
  "radius_m": 500,
  "time_context": "now",
  "location_text": "Taipei 101"
}
'@

    $risk = Invoke-JsonPost `
        -Name "Calling API /v1/risk/assess" `
        -Url "$ApiBaseUrl/v1/risk/assess" `
        -JsonBody $riskPayload

    if (-not $risk.assessment_id) {
        Fail-Smoke "Risk assessment response did not include assessment_id." "api"
    }
    if (-not $risk.realtime -or -not $risk.historical -or -not $risk.confidence) {
        Fail-Smoke "Risk assessment response did not include expected risk blocks." "api"
    }

    Write-Host "Risk smoke: assessment_id=$($risk.assessment_id), realtime=$($risk.realtime.level), historical=$($risk.historical.level), confidence=$($risk.confidence.level)"

    $webResponse = Wait-HttpOk -Name "web runtime" -Url $WebBaseUrl -ServiceForLogs "web"
    Write-Host "Web smoke: HTTP $($webResponse.StatusCode) from $WebBaseUrl"

    Write-Host ""
    Write-Host "Runtime smoke passed."
}
finally {
    if ($StopOnExit) {
        Write-Step "Stopping runtime services without deleting volumes"
        docker compose stop web api postgres redis minio
    }
}
