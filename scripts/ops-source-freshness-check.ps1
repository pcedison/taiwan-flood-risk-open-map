param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$AdminToken = $env:ADMIN_BEARER_TOKEN,
    [int]$MaxAgeMinutes = 60,
    [string]$FixturePath = "",
    [string]$MetricsPath = "",
    [switch]$DryRun,
    [switch]$WarnOnly
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host $Message
}

function Fail-Check {
    param([string]$Message)
    [Console]::Error.WriteLine("Source freshness check failed: $Message")
    if ($WarnOnly) {
        exit 0
    }
    exit 1
}

function Get-SourceTimestamp {
    param([object]$Source)

    foreach ($propertyName in @("source_timestamp_max", "last_success_at")) {
        if ($Source.PSObject.Properties.Name -contains $propertyName) {
            $value = $Source.$propertyName
            if ($value) {
                return [DateTimeOffset]::Parse($value).ToUniversalTime()
            }
        }
    }

    return $null
}

function ConvertTo-PrometheusLabelValue {
    param([string]$Value)

    return $Value.Replace("\", "\\").Replace("`n", "\n").Replace('"', '\"')
}

function New-SourceMetricLine {
    param(
        [string]$MetricName,
        [hashtable]$Labels,
        [double]$Value
    )

    $labelPairs = foreach ($key in ($Labels.Keys | Sort-Object)) {
        $escapedValue = ConvertTo-PrometheusLabelValue -Value ([string]$Labels[$key])
        "$key=`"$escapedValue`""
    }

    return "$MetricName{$($labelPairs -join ",")} $Value"
}

function Write-FreshnessMetrics {
    param(
        [string]$Path,
        [object]$Result,
        [int]$ThresholdMinutes
    )

    if (-not $Path) {
        return
    }

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# HELP flood_risk_source_freshness_check_success Whether the last source freshness check passed.")
    $lines.Add("# TYPE flood_risk_source_freshness_check_success gauge")
    $lines.Add("flood_risk_source_freshness_check_success $([int]$Result.Passed)")
    $lines.Add("# HELP flood_risk_source_freshness_threshold_seconds Freshness threshold used by the ops check.")
    $lines.Add("# TYPE flood_risk_source_freshness_threshold_seconds gauge")
    $lines.Add("flood_risk_source_freshness_threshold_seconds $($ThresholdMinutes * 60)")
    $lines.Add("# HELP flood_risk_source_freshness_age_seconds Age of the newest source timestamp used by the ops check.")
    $lines.Add("# TYPE flood_risk_source_freshness_age_seconds gauge")
    $lines.Add("# HELP flood_risk_source_freshness_stale Whether the source exceeded the freshness threshold.")
    $lines.Add("# TYPE flood_risk_source_freshness_stale gauge")
    $lines.Add("# HELP flood_risk_source_freshness_status Source health status as a labeled gauge where the active status is 1.")
    $lines.Add("# TYPE flood_risk_source_freshness_status gauge")

    foreach ($source in $Result.Sources) {
        $labels = @{
            source_id = $source.SourceId
            health_status = $source.HealthStatus
        }
        $lines.Add((New-SourceMetricLine -MetricName "flood_risk_source_freshness_age_seconds" -Labels $labels -Value $source.AgeSeconds))
        $lines.Add((New-SourceMetricLine -MetricName "flood_risk_source_freshness_stale" -Labels $labels -Value ([int]$source.IsStale)))

        foreach ($status in @("healthy", "degraded", "failed", "unknown", "disabled")) {
            $statusLabels = @{
                source_id = $source.SourceId
                status = $status
            }
            $lines.Add((New-SourceMetricLine -MetricName "flood_risk_source_freshness_status" -Labels $statusLabels -Value ([int]($source.HealthStatus -eq $status))))
        }
    }

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    $resolvedPath = if ([System.IO.Path]::IsPathRooted($Path)) {
        $Path
    } else {
        Join-Path (Get-Location) $Path
    }
    [System.IO.File]::WriteAllLines($resolvedPath, [string[]]$lines, $utf8NoBom)
    Write-Info "Wrote Prometheus metrics to $Path"
}

function Test-SourceFreshness {
    param(
        [object]$Payload,
        [int]$ThresholdMinutes
    )

    if (-not $Payload.sources) {
        Fail-Check "Expected payload to include a sources array."
    }

    $now = [DateTimeOffset]::UtcNow
    $problems = New-Object System.Collections.Generic.List[string]
    $sourceResults = New-Object System.Collections.Generic.List[object]

    foreach ($source in $Payload.sources) {
        $sourceId = if ($source.id) { $source.id } else { "<unknown>" }
        $status = if ($source.health_status) { $source.health_status } else { "unknown" }
        $ageSeconds = -1
        $isStale = $false

        if ($status -eq "disabled") {
            Write-Info "SKIP $sourceId status=disabled"
            $sourceResults.Add([pscustomobject]@{
                SourceId = $sourceId
                HealthStatus = $status
                AgeSeconds = $ageSeconds
                IsStale = $false
            })
            continue
        }

        if (@("failed", "degraded", "unknown") -contains $status) {
            $problems.Add("$sourceId status=$status")
        }

        $timestamp = Get-SourceTimestamp -Source $source
        if (-not $timestamp) {
            $problems.Add("$sourceId has no source_timestamp_max or last_success_at")
            $sourceResults.Add([pscustomobject]@{
                SourceId = $sourceId
                HealthStatus = $status
                AgeSeconds = $ageSeconds
                IsStale = $true
            })
            continue
        }

        $ageSeconds = [Math]::Max([double]0, [Math]::Round(($now - $timestamp).TotalSeconds, 1))
        $ageMinutes = $ageSeconds / 60
        $ageRounded = [Math]::Round($ageMinutes, 1)
        Write-Info "CHECK $sourceId status=$status age_minutes=$ageRounded"

        if ($ageMinutes -gt $ThresholdMinutes) {
            $isStale = $true
            $problems.Add("$sourceId stale for $ageRounded minutes; threshold=$ThresholdMinutes")
        }

        $sourceResults.Add([pscustomobject]@{
            SourceId = $sourceId
            HealthStatus = $status
            AgeSeconds = $ageSeconds
            IsStale = $isStale
        })
    }

    return [pscustomobject]@{
        Passed = ($problems.Count -eq 0)
        Problems = $problems
        Sources = $sourceResults
    }
}

function Complete-SourceFreshnessCheck {
    param(
        [object]$Payload,
        [int]$ThresholdMinutes,
        [string]$OutputMetricsPath
    )

    $result = Test-SourceFreshness -Payload $Payload -ThresholdMinutes $ThresholdMinutes
    Write-FreshnessMetrics -Path $OutputMetricsPath -Result $result -ThresholdMinutes $ThresholdMinutes

    if (-not $result.Passed) {
        Fail-Check ($result.Problems -join "; ")
    }

    Write-Info "Source freshness check passed."
}

if ($DryRun) {
    Write-Info "Dry run: no API request will be sent."
    Write-Info "Would check GET $BaseUrl/admin/v1/sources with MaxAgeMinutes=$MaxAgeMinutes."
    Write-Info "Alert states: failed, degraded, unknown, or stale enabled sources."
    if ($MetricsPath) {
        $dryRunResult = [pscustomobject]@{
            Passed = $true
            Problems = @()
            Sources = @()
        }
        Write-FreshnessMetrics -Path $MetricsPath -Result $dryRunResult -ThresholdMinutes $MaxAgeMinutes
    }
    exit 0
}

if ($FixturePath) {
    if (-not (Test-Path -LiteralPath $FixturePath)) {
        Fail-Check "Fixture not found: $FixturePath"
    }

    $payload = Get-Content -LiteralPath $FixturePath -Raw | ConvertFrom-Json
    Complete-SourceFreshnessCheck -Payload $payload -ThresholdMinutes $MaxAgeMinutes -OutputMetricsPath $MetricsPath
    exit 0
}

if (-not $AdminToken) {
    Fail-Check "AdminToken is required unless -DryRun or -FixturePath is used."
}

$uri = ($BaseUrl.TrimEnd("/")) + "/admin/v1/sources"
$headers = @{ Authorization = "Bearer $AdminToken" }

try {
    $payload = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 20
}
catch {
    Fail-Check "Could not fetch $uri`: $($_.Exception.Message)"
}

Complete-SourceFreshnessCheck -Payload $payload -ThresholdMinutes $MaxAgeMinutes -OutputMetricsPath $MetricsPath
