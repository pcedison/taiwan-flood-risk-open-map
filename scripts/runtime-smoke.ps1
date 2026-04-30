param(
    [int]$StartupTimeoutSeconds = 180,
    [int]$HttpTimeoutSeconds = 10,
    [string]$ApiBaseUrl = "http://localhost:8000",
    [string]$WebBaseUrl = "http://localhost:3000",
    [switch]$StopOnExit,
    [switch]$SkipExtendedSmoke,
    [switch]$SkipQueueSmoke,
    [switch]$SkipReportsEnabledSmoke,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$script:RuntimeSmokeCleanupSql = @()

function Show-SmokeHelp {
    Write-Host @"
Runtime smoke for the Flood Risk local Docker Compose stack.

Usage:
  .\scripts\runtime-smoke.ps1 [options]

Base checks:
  - docker compose config and Docker daemon availability.
  - postgres, redis, minio, api, and web startup.
  - database migrations.
  - API /health and /ready.
  - POST /v1/risk/assess, including query_heat presence.
  - Web HTTP 200.

Extended checks are enabled by default:
  - Queue live smoke: enqueue and consume one durable worker_runtime_jobs item
    through a one-off worker container with fixture runtime adapters enabled.
  - Reports smoke: verify /v1/reports is default-disabled over live HTTP, then
    verify the enabled path in a one-off API container with USER_REPORTS_ENABLED=true.
  - MVT smoke: GET seeded query-heat and flood-potential .mvt endpoints.
  - Query heat / tile cache job readiness: run the worker query heat
    aggregation CLI, refresh flood-potential feature rows, upsert a tile cache
    smoke row, verify the API can serve the cached tile path, and clean up smoke
    rows.

Options:
  -StartupTimeoutSeconds <int>  Startup wait budget. Default: 180.
  -HttpTimeoutSeconds <int>     Per-request HTTP timeout. Default: 10.
  -ApiBaseUrl <url>             API base URL. Default: http://localhost:8000.
  -WebBaseUrl <url>             Web base URL. Default: http://localhost:3000.
  -StopOnExit                   Stop runtime services after the smoke.
  -SkipExtendedSmoke            Run only base API/Web smoke.
  -SkipQueueSmoke               Skip only the durable queue live smoke.
  -SkipReportsEnabledSmoke      Skip only the reports enabled-path smoke.
  -Help                         Print this help and exit without touching Docker.
"@
}

if ($Help) {
    Show-SmokeHelp
    exit 0
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Invoke-BestEffortPostgresSql {
    param([string]$Sql)

    $tempDir = Join-Path (Get-Location).Path ".runtime-smoke"
    $fileName = "cleanup-postgres-$([Guid]::NewGuid().ToString('N')).sql"
    $hostPath = Join-Path $tempDir $fileName
    $containerPath = "/workspace/.runtime-smoke/$fileName"

    try {
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
        Set-Content -LiteralPath $hostPath -Value $Sql -Encoding UTF8
        & docker compose --profile tools run --rm migrate sh -c "psql `"`$DATABASE_URL`" -v ON_ERROR_STOP=1 -f $containerPath" | Out-Null
    }
    catch {
        Write-Warning "Best-effort runtime smoke cleanup failed: $($_.Exception.Message)"
    }
    finally {
        Remove-Item -LiteralPath $hostPath -Force -ErrorAction SilentlyContinue
        $remainingTempFiles = @(Get-ChildItem -LiteralPath $tempDir -Force -ErrorAction SilentlyContinue)
        if ($remainingTempFiles.Count -eq 0) {
            Remove-Item -LiteralPath $tempDir -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-RegisteredSmokeCleanup {
    if ($script:RuntimeSmokeCleanupSql.Count -eq 0) {
        return
    }

    Write-Host ""
    Write-Host "==> Running best-effort runtime smoke cleanup"
    foreach ($cleanupSql in $script:RuntimeSmokeCleanupSql) {
        Invoke-BestEffortPostgresSql -Sql $cleanupSql
    }
    $script:RuntimeSmokeCleanupSql = @()
}

function Fail-Smoke {
    param(
        [string]$Message,
        [string]$ServiceForLogs = ""
    )

    Invoke-RegisteredSmokeCleanup
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

function Invoke-ComposeRun {
    param(
        [string]$Description,
        [string]$Service,
        [string]$ShellScript,
        [string[]]$Environment = @()
    )

    $command = @("docker", "compose", "run", "--rm")
    foreach ($item in $Environment) {
        $command += @("-e", $item)
    }
    $command += @($Service, "sh", "-c", $ShellScript)
    Invoke-CheckedCommand $Description $command
}

function Invoke-ComposePythonScript {
    param(
        [string]$Description,
        [string]$Service,
        [string]$PythonSource,
        [string[]]$Environment = @()
    )

    $tempDir = Join-Path (Get-Location).Path ".runtime-smoke"
    $fileName = "smoke-$Service-$([Guid]::NewGuid().ToString('N')).py"
    $hostPath = Join-Path $tempDir $fileName
    $containerPath = "/workspace/.runtime-smoke/$fileName"

    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    Set-Content -LiteralPath $hostPath -Value $PythonSource -Encoding UTF8

    $command = @("docker", "compose", "run", "--rm")
    foreach ($item in $Environment) {
        $command += @("-e", $item)
    }
    $command += @($Service, "sh", "-c", "pip install -e . >/tmp/$Service-install.log && python $containerPath")

    Write-Step $Description
    & $command[0] $command[1..($command.Length - 1)]
    $exitCode = $LASTEXITCODE

    Remove-Item -LiteralPath $hostPath -Force -ErrorAction SilentlyContinue
    $remainingTempFiles = @(Get-ChildItem -LiteralPath $tempDir -Force -ErrorAction SilentlyContinue)
    if ($remainingTempFiles.Count -eq 0) {
        Remove-Item -LiteralPath $tempDir -Force -ErrorAction SilentlyContinue
    }

    if ($exitCode -ne 0) {
        Fail-Smoke "$Description exited with code $exitCode"
    }
}

function Get-ErrorHttpResponse {
    param([object]$ErrorRecord)

    $response = $ErrorRecord.Exception.Response
    if (-not $response) {
        return $null
    }

    $statusCode = $null
    if ($null -ne $response.StatusCode) {
        $statusCode = [int]$response.StatusCode
    }

    $content = ""
    try {
        if ($response.Content -and $response.Content.PSObject.Methods["ReadAsStringAsync"]) {
            $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        }
        elseif ($response.PSObject.Methods["GetResponseStream"]) {
            $stream = $response.GetResponseStream()
            if ($stream) {
                $reader = New-Object System.IO.StreamReader($stream)
                try {
                    $content = $reader.ReadToEnd()
                }
                finally {
                    $reader.Dispose()
                }
            }
        }
    }
    catch {
        $content = ""
    }

    if (-not $content -and $ErrorRecord.ErrorDetails -and $ErrorRecord.ErrorDetails.Message) {
        $content = [string]$ErrorRecord.ErrorDetails.Message
    }

    return [pscustomobject]@{
        StatusCode = $statusCode
        Content = $content
        Headers = $response.Headers
    }
}

function Invoke-HttpRequestExpectStatus {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method = "Get",
        [AllowNull()][string]$JsonBody = $null,
        [int[]]$AcceptStatusCodes = @(200),
        [string]$ServiceForLogs = "api"
    )

    Write-Step $Name

    $statusCode = $null
    $content = ""
    $headers = $null
    $rawContentLength = $null

    try {
        $request = @{
            Method = $Method
            Uri = $Url
            UseBasicParsing = $true
            TimeoutSec = $HttpTimeoutSeconds
        }
        if (-not [string]::IsNullOrEmpty($JsonBody)) {
            $request.ContentType = "application/json"
            $request.Body = $JsonBody
        }

        $response = Invoke-WebRequest @request
        $statusCode = [int]$response.StatusCode
        $content = $response.Content
        $headers = $response.Headers
        $rawContentLength = $response.RawContentLength
    }
    catch {
        $errorResponse = Get-ErrorHttpResponse $_
        if (-not $errorResponse -or $null -eq $errorResponse.StatusCode) {
            Fail-Smoke "$Name failed: $($_.Exception.Message)" $ServiceForLogs
        }

        $statusCode = $errorResponse.StatusCode
        $content = $errorResponse.Content
        $headers = $errorResponse.Headers
    }

    if (-not ($AcceptStatusCodes -contains [int]$statusCode)) {
        $bodySummary = ""
        if ($content) {
            $bodySummary = " Body: $content"
        }
        Fail-Smoke "$Name returned HTTP $statusCode; expected $($AcceptStatusCodes -join ',').$bodySummary" $ServiceForLogs
    }

    return [pscustomobject]@{
        StatusCode = [int]$statusCode
        Content = $content
        Headers = $headers
        RawContentLength = $rawContentLength
    }
}

function Invoke-HttpJsonExpectStatus {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method = "Get",
        [AllowNull()][string]$JsonBody = $null,
        [int[]]$AcceptStatusCodes = @(200),
        [string]$ServiceForLogs = "api"
    )

    $response = Invoke-HttpRequestExpectStatus `
        -Name $Name `
        -Url $Url `
        -Method $Method `
        -JsonBody $JsonBody `
        -AcceptStatusCodes $AcceptStatusCodes `
        -ServiceForLogs $ServiceForLogs

    if (-not $response.Content) {
        return $null
    }

    try {
        return $response.Content | ConvertFrom-Json
    }
    catch {
        Fail-Smoke "$Name returned non-JSON content: $($_.Exception.Message)" $ServiceForLogs
    }
}

function Get-ErrorPayloadCode {
    param([AllowNull()][object]$Payload)

    if ($null -eq $Payload) {
        return $null
    }

    if ($Payload.PSObject.Properties["code"]) {
        return [string]$Payload.code
    }

    if ($Payload.PSObject.Properties["error"]) {
        $errorObject = $Payload.error
        if ($null -ne $errorObject -and $errorObject.PSObject.Properties["code"]) {
            return [string]$errorObject.code
        }
    }

    if ($Payload.PSObject.Properties["detail"]) {
        $detailObject = $Payload.detail
        if ($detailObject -is [string]) {
            return [string]$detailObject
        }
        if ($null -ne $detailObject -and $detailObject.PSObject.Properties["code"]) {
            return [string]$detailObject.code
        }
        if ($null -ne $detailObject -and $detailObject.PSObject.Properties["error"]) {
            $nestedError = $detailObject.error
            if ($null -ne $nestedError -and $nestedError.PSObject.Properties["code"]) {
                return [string]$nestedError.code
            }
        }
    }

    return $null
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

    return Invoke-HttpJsonExpectStatus `
        -Name $Name `
        -Url $Url `
        -Method "Post" `
        -JsonBody $JsonBody `
        -AcceptStatusCodes @(200)
}

function Invoke-ReportsDisabledSmoke {
    param([string]$ApiBaseUrl)

    $reportPayload = @'
{
  "point": {
    "lat": 25.033,
    "lng": 121.5654
  },
  "summary": "Runtime smoke disabled report path."
}
'@

    $disabledReport = Invoke-HttpJsonExpectStatus `
        -Name "Calling API /v1/reports with default-disabled reports" `
        -Url "$ApiBaseUrl/v1/reports" `
        -Method "Post" `
        -JsonBody $reportPayload `
        -AcceptStatusCodes @(404)

    $disabledReportCode = Get-ErrorPayloadCode $disabledReport
    if ($disabledReportCode -ne "feature_disabled") {
        Fail-Smoke "Expected /v1/reports default-disabled code feature_disabled, got '$disabledReportCode'." "api"
    }

    Write-Host "Reports default-disabled smoke: HTTP 404 feature_disabled"
}

function Invoke-ReportsEnabledSmoke {
    $reportsEnabledPython = @'
import asyncio

from app.api.routes.reports import create_user_report
from app.api.schemas import LatLng, UserReportCreateRequest
from app.core.config import get_settings

get_settings.cache_clear()

async def main() -> None:
    report_id = None
    response = await create_user_report(
        UserReportCreateRequest(
            point=LatLng(lat=25.033, lng=121.5654),
            summary="Runtime smoke enabled report path.",
        )
    )
    if response.status != "pending" or not response.report_id:
        raise SystemExit("expected a pending report_id from enabled reports path")
    report_id = response.report_id
    settings = get_settings()
    import psycopg

    try:
        with psycopg.connect(settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, privacy_level, media_ref FROM user_reports WHERE id = %s",
                    (report_id,),
                )
                row = cur.fetchone()
                if row != ("pending", "redacted", None):
                    raise SystemExit(f"unexpected user_reports row: {row!r}")
                cur.execute(
                    "SELECT count(*) FROM audit_logs WHERE subject_type = 'user_report' AND subject_id = %s",
                    (report_id,),
                )
                audit_count = cur.fetchone()[0]
                if audit_count != 1:
                    raise SystemExit(f"expected one audit row, got {audit_count}")
    finally:
        if report_id is not None:
            with psycopg.connect(settings.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM audit_logs WHERE subject_type = 'user_report' AND subject_id = %s",
                        (report_id,),
                    )
                    cur.execute("DELETE FROM user_reports WHERE id = %s", (report_id,))
    print(f"reports_enabled_smoke=ok report_id={response.report_id} status={response.status}")

asyncio.run(main())
'@

    Invoke-ComposePythonScript `
        -Description "Running reports enabled-path smoke in one-off API container" `
        -Service "api" `
        -PythonSource $reportsEnabledPython `
        -Environment @("USER_REPORTS_ENABLED=true")
}

function Invoke-QueueLiveSmoke {
    $queueSmokePython = @'
from app.config import load_worker_settings
from app.jobs.runtime import enqueue_enabled_runtime_adapter_jobs, work_runtime_queue_once

settings = load_worker_settings()
job_ids = enqueue_enabled_runtime_adapter_jobs(settings)
if not job_ids:
    raise SystemExit("expected at least one durable runtime queue job")

result = None
try:
    result = work_runtime_queue_once(settings=settings)
    if result.status != "succeeded":
        raise SystemExit(f"runtime queue worker status={result.status} reason={result.reason}")
finally:
    import psycopg

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM worker_runtime_jobs WHERE id = ANY(%s::uuid[])",
                ([*job_ids],),
            )

print(f"queue_smoke=ok job_id={result.job_id} adapter_key={result.adapter_key}")
'@

    Invoke-ComposePythonScript `
        -Description "Running worker durable queue live smoke" `
        -Service "worker" `
        -PythonSource $queueSmokePython `
        -Environment @(
            "WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level",
            "WORKER_RUNTIME_FIXTURES_ENABLED=true",
            "WORKER_INSTANCE=runtime-smoke"
        )
}

function Invoke-MvtSmoke {
    param([string]$ApiBaseUrl)

    $tiles = @(
        @{ Layer = "query-heat"; Url = "$ApiBaseUrl/v1/tiles/query-heat/8/215/107.mvt" },
        @{ Layer = "flood-potential"; Url = "$ApiBaseUrl/v1/tiles/flood-potential/8/215/107.mvt" }
    )

    foreach ($tile in $tiles) {
        $response = Invoke-HttpRequestExpectStatus `
            -Name "Calling API MVT tile $($tile.Layer)" `
            -Url $tile.Url `
            -AcceptStatusCodes @(200)

        $contentType = [string]$response.Headers["Content-Type"]
        if ($contentType -notlike "*application/vnd.mapbox-vector-tile*") {
            Fail-Smoke "Expected MVT content type for layer $($tile.Layer), got '$contentType'." "api"
        }

        Write-Host "MVT smoke: layer=$($tile.Layer), HTTP $($response.StatusCode), content-type=$contentType"
    }
}

function Invoke-PostgresSqlSmoke {
    param(
        [string]$Description,
        [string]$Sql
    )

    $tempDir = Join-Path (Get-Location).Path ".runtime-smoke"
    $fileName = "smoke-postgres-$([Guid]::NewGuid().ToString('N')).sql"
    $hostPath = Join-Path $tempDir $fileName
    $containerPath = "/workspace/.runtime-smoke/$fileName"

    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    Set-Content -LiteralPath $hostPath -Value $Sql -Encoding UTF8

    $command = @(
        "docker",
        "compose",
        "--profile",
        "tools",
        "run",
        "--rm",
        "migrate",
        "sh",
        "-c",
        "psql `"`$DATABASE_URL`" -v ON_ERROR_STOP=1 -f $containerPath"
    )

    Write-Step $Description
    & $command[0] $command[1..($command.Length - 1)]
    $exitCode = $LASTEXITCODE

    Remove-Item -LiteralPath $hostPath -Force -ErrorAction SilentlyContinue
    $remainingTempFiles = @(Get-ChildItem -LiteralPath $tempDir -Force -ErrorAction SilentlyContinue)
    if ($remainingTempFiles.Count -eq 0) {
        Remove-Item -LiteralPath $tempDir -Force -ErrorAction SilentlyContinue
    }

    if ($exitCode -ne 0) {
        Fail-Smoke "$Description exited with code $exitCode"
    }
}

function Invoke-QueryHeatAndTileCacheJobSmoke {
    $tileSmokeCleanupSql = "DELETE FROM tile_cache_entries WHERE metadata ->> 'source' = 'runtime-smoke'; DELETE FROM map_layer_features WHERE feature_key = 'runtime-smoke-flood-potential'; DELETE FROM evidence WHERE raw_ref = 'runtime-smoke:tile-cache';"
    $script:RuntimeSmokeCleanupSql += $tileSmokeCleanupSql

    Invoke-ComposeRun `
        -Description "Running query heat aggregation worker job" `
        -Service "worker" `
        -ShellScript "pip install -e . >/tmp/worker-install.log && python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D"

    Invoke-PostgresSqlSmoke `
        -Description "Checking query heat materialized buckets" `
        -Sql "DO `$`$ BEGIN IF (SELECT count(*) FROM query_heat_buckets WHERE period IN ('P1D','P7D')) = 0 THEN RAISE EXCEPTION 'query heat aggregation produced no buckets'; END IF; END `$`$;"

    Invoke-PostgresSqlSmoke `
        -Description "Seeding flood-potential evidence for tile feature refresh smoke" `
        -Sql "$tileSmokeCleanupSql INSERT INTO evidence (source_id, source_type, event_type, title, summary, geom, confidence, privacy_level, ingestion_status, properties, raw_ref) VALUES ('runtime-smoke-flood-potential', 'derived', 'flood_potential', 'Runtime smoke flood potential', 'Synthetic smoke feature for tile cache validation.', ST_SetSRID(ST_MakePoint(121.5654, 25.033), 4326), 0.5, 'public', 'accepted', '{}'::jsonb, 'runtime-smoke:tile-cache');"

    Invoke-ComposeRun `
        -Description "Running tile feature refresh worker job" `
        -Service "worker" `
        -ShellScript "pip install -e . >/tmp/worker-install.log && python -m app.main --refresh-tile-features --tile-layer-id flood-potential --tile-feature-limit 25"

    Invoke-PostgresSqlSmoke `
        -Description "Checking refreshed flood-potential layer features" `
        -Sql "DO `$`$ BEGIN IF NOT EXISTS (SELECT 1 FROM map_layer_features WHERE layer_id = 'flood-potential' AND feature_key = 'runtime-smoke-flood-potential') THEN RAISE EXCEPTION 'tile feature refresh did not write runtime smoke feature'; END IF; END `$`$;"

    $tileCachePython = @'
from app.jobs.tile_cache import PostgresTileCacheWriter
from app.config import load_worker_settings

settings = load_worker_settings()
writer = PostgresTileCacheWriter(database_url=settings.database_url)
result = writer.upsert_tile_cache_entry(
    layer_id="flood-potential",
    z=8,
    x=215,
    y=107,
    tile_data=b"runtime-smoke-cache",
    metadata={"source": "runtime-smoke"},
)
if result.layer_id != "flood-potential":
    raise SystemExit("unexpected tile cache layer")
print(f"tile_cache_smoke=ok hash={result.content_hash}")
'@

    Invoke-ComposePythonScript `
        -Description "Writing tile cache smoke row" `
        -Service "worker" `
        -PythonSource $tileCachePython

    $cachedTile = Invoke-HttpRequestExpectStatus `
        -Name "Calling API cached flood-potential MVT tile" `
        -Url "$ApiBaseUrl/v1/tiles/flood-potential/8/215/107.mvt" `
        -AcceptStatusCodes @(200)

    $cachedTileContent = $cachedTile.Content
    if ($cachedTileContent -is [byte[]]) {
        $cachedTileContent = [System.Text.Encoding]::UTF8.GetString($cachedTileContent)
    }
    if ([string]$cachedTileContent -ne "runtime-smoke-cache") {
        Fail-Smoke "Expected cached flood-potential tile response to match smoke cache bytes." "api"
    }

    Invoke-PostgresSqlSmoke `
        -Description "Cleaning query heat/tile cache smoke rows" `
        -Sql $tileSmokeCleanupSql

    $script:RuntimeSmokeCleanupSql = @($script:RuntimeSmokeCleanupSql | Where-Object { $_ -ne $tileSmokeCleanupSql })

    Write-Host "Query heat/tile cache job smoke: aggregation, feature refresh, cache write, API cache read, and cleanup passed."
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

    if (-not $risk.query_heat) {
        Fail-Smoke "Risk assessment response did not include query_heat." "api"
    }
    if ($risk.query_heat.query_count_bucket -eq "limited-db-unavailable") {
        Fail-Smoke "Query heat fell back to limited-db-unavailable despite ready database." "api"
    }
    Write-Host "Query heat smoke: period=$($risk.query_heat.period), query_count_bucket=$($risk.query_heat.query_count_bucket), unique_approx_count_bucket=$($risk.query_heat.unique_approx_count_bucket)"

    if (-not $SkipExtendedSmoke) {
        Invoke-ReportsDisabledSmoke -ApiBaseUrl $ApiBaseUrl
        Invoke-MvtSmoke -ApiBaseUrl $ApiBaseUrl

        if ($SkipQueueSmoke) {
            Write-Host "Queue live smoke skipped by -SkipQueueSmoke."
        }
        else {
            Invoke-QueueLiveSmoke
        }

        if ($SkipReportsEnabledSmoke) {
            Write-Host "Reports enabled-path smoke skipped by -SkipReportsEnabledSmoke."
        }
        else {
            Invoke-ReportsEnabledSmoke
        }

        Invoke-QueryHeatAndTileCacheJobSmoke
    }
    else {
        Write-Host "Extended runtime smokes skipped by -SkipExtendedSmoke."
    }

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
