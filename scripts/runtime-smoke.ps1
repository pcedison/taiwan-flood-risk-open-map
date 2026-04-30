param(
    [int]$StartupTimeoutSeconds = 180,
    [int]$HttpTimeoutSeconds = 10,
    [string]$ApiBaseUrl = "http://localhost:8000",
    [string]$WebBaseUrl = "http://localhost:3000",
    [switch]$StopOnExit,
    [switch]$SkipExtendedSmoke,
    [switch]$SkipQueueSmoke,
    [switch]$SkipAdapterFixtureSmoke,
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
  - API /health, /ready, and /metrics.
  - POST /v1/risk/assess, including query_heat presence.
  - Web HTTP 200.

Extended checks are enabled by default:
  - Queue live smoke: verify idempotent enqueue/dedupe for the same adapter
    producer, consume one durable worker_runtime_jobs item, and verify final
    failed/dead-letter-equivalent list and requeue/dequeue visibility for an
    exhausted queue job.
  - Official adapter fixture dry run: run --run-official-demo in a one-off
    worker container without external API credentials.
  - Reports smoke: verify /v1/reports is default-disabled over live HTTP, then
    verify the enabled path in a one-off API container with USER_REPORTS_ENABLED=true.
  - MVT smoke: GET seeded query-heat and flood-potential .mvt endpoints.
  - Maintenance scheduler bounded tick smoke: run the Query Heat/tile cadence
    path once with --maintenance --scheduler --max-ticks 1.
  - Query heat / tile cache job readiness: run the worker query heat
    aggregation and retention CLI paths with bounded inputs, refresh
    flood-potential feature rows, upsert/prune/invalidate tile cache rows,
    verify the API can serve the cached tile path, and clean up smoke rows.

Options:
  -StartupTimeoutSeconds <int>  Startup wait budget. Default: 180.
  -HttpTimeoutSeconds <int>     Per-request HTTP timeout. Default: 10.
  -ApiBaseUrl <url>             API base URL. Default: http://localhost:8000.
  -WebBaseUrl <url>             Web base URL. Default: http://localhost:3000.
  -StopOnExit                   Stop runtime services after the smoke.
  -SkipExtendedSmoke            Run only base API/Web smoke.
  -SkipQueueSmoke               Skip only the durable queue live smoke.
  -SkipAdapterFixtureSmoke      Skip only the official adapter fixture dry run.
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
    $queueSmokeCleanupSql = "DELETE FROM worker_runtime_jobs WHERE queue_name = 'runtime-smoke-adapters' OR job_key LIKE 'runtime-smoke.queue.%';"
    $script:RuntimeSmokeCleanupSql += $queueSmokeCleanupSql

    $queueSmokePython = @'
import psycopg

from app.config import load_worker_settings
from app.jobs.queue import PostgresRuntimeQueue
from app.jobs.runtime import produce_enabled_runtime_adapter_jobs, work_runtime_queue_once

SMOKE_QUEUE_NAME = "runtime-smoke-adapters"
DEDUPE_JOB_KEY = "runtime-smoke.queue.dedupe"
FAILED_JOB_KEY = "runtime-smoke.queue.final-failed"
ADAPTER_KEY = "official.wra.water_level"
UNKNOWN_ADAPTER_KEY = "runtime-smoke.unknown_adapter"


class SmokeRuntimeQueue(PostgresRuntimeQueue):
    def enqueue_adapter_job(
        self,
        *,
        adapter_key,
        job_key="runtime.adapter.ingest",
        queue_name="runtime-adapters",
        payload=None,
        priority=0,
        max_attempts=3,
        run_after=None,
        dedupe_key=None,
    ):
        del queue_name
        return super().enqueue_adapter_job(
            adapter_key=adapter_key,
            job_key=job_key,
            queue_name=SMOKE_QUEUE_NAME,
            payload=payload,
            priority=priority,
            max_attempts=max_attempts,
            run_after=run_after,
            dedupe_key=dedupe_key,
        )


def cleanup(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM worker_runtime_jobs
                WHERE queue_name = %s
                    OR job_key IN (%s, %s)
                """,
                (SMOKE_QUEUE_NAME, DEDUPE_JOB_KEY, FAILED_JOB_KEY),
            )


def active_job_count(database_url: str, *, job_key: str, adapter_key: str) -> int:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM worker_runtime_jobs
                WHERE queue_name = %s
                    AND job_key = %s
                    AND adapter_key = %s
                    AND status IN ('queued', 'running')
                """,
                (SMOKE_QUEUE_NAME, job_key, adapter_key),
            )
            return int(cur.fetchone()[0])


def failed_job_visibility(database_url: str, *, job_id: str):
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    status,
                    attempts,
                    max_attempts,
                    last_error,
                    finished_at IS NOT NULL,
                    final_failed_at IS NOT NULL
                FROM worker_runtime_jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            return cur.fetchone()

settings = load_worker_settings()
if not settings.database_url:
    raise SystemExit("queue smoke requires WORKER_DATABASE_URL or DATABASE_URL")

queue = SmokeRuntimeQueue(database_url=settings.database_url)
cleanup(settings.database_url)

try:
    first = produce_enabled_runtime_adapter_jobs(
        settings,
        queue=queue,
        job_key=DEDUPE_JOB_KEY,
        queue_name=SMOKE_QUEUE_NAME,
    )
    if first.status != "succeeded" or not first.job_ids:
        raise SystemExit(
            "expected first runtime producer enqueue to write a durable smoke job, "
            f"got status={first.status} reason={first.reason} job_ids={first.job_ids}"
        )

    second = produce_enabled_runtime_adapter_jobs(
        settings,
        queue=queue,
        job_key=DEDUPE_JOB_KEY,
        queue_name=SMOKE_QUEUE_NAME,
    )
    if second.status not in {"succeeded", "deduped"} and not (
        second.status == "skipped" and second.reason == "no_durable_jobs"
    ):
        raise SystemExit(
            "expected idempotent second producer run, "
            f"got status={second.status} reason={second.reason}"
        )

    active_count = active_job_count(
        settings.database_url,
        job_key=DEDUPE_JOB_KEY,
        adapter_key=ADAPTER_KEY,
    )
    if active_count != 1:
        raise SystemExit(
            "expected exactly one active runtime job after duplicate producer runs, "
            f"got active_count={active_count}"
        )

    result = work_runtime_queue_once(
        settings=settings,
        queue=queue,
        queue_name=SMOKE_QUEUE_NAME,
        worker_id="runtime-smoke-consumer",
    )
    if result.status != "succeeded":
        raise SystemExit(f"runtime queue worker status={result.status} reason={result.reason}")

    remaining_active = active_job_count(
        settings.database_url,
        job_key=DEDUPE_JOB_KEY,
        adapter_key=ADAPTER_KEY,
    )
    if remaining_active != 0:
        raise SystemExit(
            "expected no active runtime jobs after successful consume, "
            f"got active_count={remaining_active}"
        )

    failed_enqueue = queue.enqueue_adapter_job(
        adapter_key=UNKNOWN_ADAPTER_KEY,
        job_key=FAILED_JOB_KEY,
        payload={"adapter_key": UNKNOWN_ADAPTER_KEY},
        max_attempts=1,
        dedupe_key="runtime-smoke.queue.final-failed",
    )
    failed_job_id = failed_enqueue.job_id
    if failed_job_id is None:
        raise SystemExit(f"expected failed-job enqueue to return a job id, got {failed_enqueue!r}")
    failed_result = work_runtime_queue_once(
        settings=settings,
        queue=queue,
        queue_name=SMOKE_QUEUE_NAME,
        worker_id="runtime-smoke-failure-consumer",
        retry_delay_seconds=1,
    )
    if failed_result.status != "failed":
        raise SystemExit(
            "expected exhausted unknown-adapter job to fail, "
            f"got status={failed_result.status} reason={failed_result.reason}"
        )

    failed_row = failed_job_visibility(settings.database_url, job_id=failed_job_id)
    if failed_row is None:
        raise SystemExit("expected exhausted failed job to remain visible in worker_runtime_jobs")
    status, attempts, max_attempts, last_error, finished, final_failed = failed_row
    if status != "failed" or attempts != max_attempts or not finished or not final_failed:
        raise SystemExit(
            "expected final failed/dead-letter-equivalent visibility with exhausted attempts, "
            f"got status={status} attempts={attempts} max_attempts={max_attempts} "
            f"finished={finished} final_failed={final_failed}"
        )
    if not last_error or "unknown runtime adapter_key" not in last_error:
        raise SystemExit(f"expected failed job last_error to explain unknown adapter, got {last_error!r}")

    dead_letters = queue.list_dead_letter_jobs(queue_name=SMOKE_QUEUE_NAME, limit=5)
    if not any(job.id == failed_job_id for job in dead_letters):
        raise SystemExit(
            "expected exhausted failed job to be visible through list_dead_letter_jobs"
        )

    requeue_result = queue.requeue_failed_job(job_id=failed_job_id)
    if not requeue_result.requeued:
        raise SystemExit(
            "expected exhausted failed job to be requeued through PostgresRuntimeQueue"
        )
    if requeue_result.attempts != 0:
        raise SystemExit(
            "expected requeue helper to reset attempts, "
            f"got attempts={requeue_result.attempts}"
        )

    dead_letters_after_requeue = queue.list_dead_letter_jobs(queue_name=SMOKE_QUEUE_NAME, limit=5)
    if any(job.id == failed_job_id for job in dead_letters_after_requeue):
        raise SystemExit("expected requeued job to disappear from list_dead_letter_jobs")

    requeued_job = queue.dequeue_adapter_job(
        queue_name=SMOKE_QUEUE_NAME,
        worker_id="runtime-smoke-requeue-consumer",
        lease_seconds=settings.runtime_job_lease_seconds,
    )
    if requeued_job is None or requeued_job.id != failed_job_id:
        raise SystemExit(
            "expected requeued failed job to be available through live dequeue path, "
            f"got {requeued_job!r}"
        )
    if requeued_job.attempts != 1:
        raise SystemExit(
            "expected requeued job attempts to reset before dequeue, "
            f"got attempts={requeued_job.attempts}"
        )

    print(
        "queue_smoke=ok "
        f"dedupe_active_count={active_count} "
        f"consumed_job_id={result.job_id} "
        f"adapter_key={result.adapter_key} "
        f"failed_job_id={failed_job_id} "
        f"failed_status={status} "
        "dead_letter_visible=true "
        "dead_letter_requeued=true"
    )
finally:
    cleanup(settings.database_url)
'@

    try {
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
    finally {
        Invoke-BestEffortPostgresSql -Sql $queueSmokeCleanupSql
        $script:RuntimeSmokeCleanupSql = @($script:RuntimeSmokeCleanupSql | Where-Object { $_ -ne $queueSmokeCleanupSql })
    }
}

function Invoke-AdapterFixtureDryRunSmoke {
    Invoke-ComposeRun `
        -Description "Running official adapter fixture dry-run smoke" `
        -Service "worker" `
        -ShellScript "pip install -e . >/tmp/worker-install.log && python -m app.main --run-official-demo" `
        -Environment @(
            "WORKER_RUNTIME_FIXTURES_ENABLED=true",
            "WORKER_ENABLED_ADAPTER_KEYS=official.cwa.rainfall,official.wra.water_level,official.flood_potential.geojson",
            "FRESHNESS_MAX_AGE_SECONDS=21600",
            "WORKER_INSTANCE=runtime-smoke-adapter-fixture"
        )
    Write-Host "Official adapter fixture dry-run smoke: --run-official-demo completed without external API credentials."
}

function Invoke-SchedulerBoundedTickSmoke {
    $schedulerSmokeCleanupSql = "DELETE FROM worker_scheduler_leases WHERE lease_key = 'scheduler.maintenance' AND holder_id = 'runtime-smoke-maintenance';"
    $script:RuntimeSmokeCleanupSql += $schedulerSmokeCleanupSql

    try {
        Invoke-ComposeRun `
            -Description "Running maintenance scheduler bounded tick smoke" `
            -Service "worker" `
            -ShellScript "pip install -e . >/tmp/worker-install.log && python -m app.main --maintenance --scheduler --max-ticks 1 --query-heat-periods P1D,P7D --query-heat-retention-days 14 --tile-layer-id flood-potential --tile-feature-limit 1000 --tile-prune-limit 10" `
            -Environment @(
                "WORKER_INSTANCE=runtime-smoke-maintenance",
                "SCHEDULER_INTERVAL_SECONDS=1",
                "SCHEDULER_LEASE_TTL_SECONDS=30"
            )
        Write-Host "Maintenance scheduler bounded tick smoke: --maintenance --scheduler --max-ticks 1 completed."
    }
    finally {
        Invoke-BestEffortPostgresSql -Sql $schedulerSmokeCleanupSql
        $script:RuntimeSmokeCleanupSql = @($script:RuntimeSmokeCleanupSql | Where-Object { $_ -ne $schedulerSmokeCleanupSql })
    }
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
    $tileSmokeCleanupSql = "DELETE FROM tile_cache_entries WHERE metadata ->> 'source' = 'runtime-smoke'; DELETE FROM map_layer_features WHERE feature_key IN ('runtime-smoke-flood-potential', 'runtime-smoke-expired-feature'); DELETE FROM evidence WHERE raw_ref = 'runtime-smoke:tile-cache'; DELETE FROM query_heat_buckets WHERE h3_index = 'runtime-smoke-retention';"
    $script:RuntimeSmokeCleanupSql += $tileSmokeCleanupSql
    $queryHeatWindowStart = (Get-Date).ToUniversalTime().AddDays(-1).ToString("yyyy-MM-ddTHH:mm:ssZ")
    $queryHeatWindowEnd = (Get-Date).ToUniversalTime().AddDays(1).ToString("yyyy-MM-ddTHH:mm:ssZ")

    Invoke-ComposeRun `
        -Description "Running bounded query heat aggregation worker job" `
        -Service "worker" `
        -ShellScript "pip install -e . >/tmp/worker-install.log && python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D --query-heat-created-at-start $queryHeatWindowStart --query-heat-created-at-end $queryHeatWindowEnd"

    Invoke-PostgresSqlSmoke `
        -Description "Checking query heat materialized buckets" `
        -Sql "DO `$`$ BEGIN IF (SELECT count(*) FROM query_heat_buckets WHERE period IN ('P1D','P7D')) = 0 THEN RAISE EXCEPTION 'query heat aggregation produced no buckets'; END IF; END `$`$;"

    Invoke-PostgresSqlSmoke `
        -Description "Seeding query heat retention smoke bucket" `
        -Sql "$tileSmokeCleanupSql INSERT INTO query_heat_buckets (h3_index, period, period_started_at, query_count, unique_approx_count) VALUES ('runtime-smoke-retention', 'P7D', '2000-01-03T00:00:00Z'::timestamptz, 1, 1);"

    Invoke-ComposeRun `
        -Description "Running query heat retention worker job" `
        -Service "worker" `
        -ShellScript "pip install -e . >/tmp/worker-install.log && python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D --query-heat-created-at-start $queryHeatWindowStart --query-heat-created-at-end $queryHeatWindowEnd --query-heat-retention-days 14"

    Invoke-PostgresSqlSmoke `
        -Description "Checking query heat retention cleanup" `
        -Sql "DO `$`$ BEGIN IF EXISTS (SELECT 1 FROM query_heat_buckets WHERE h3_index = 'runtime-smoke-retention') THEN RAISE EXCEPTION 'query heat retention did not prune old smoke bucket'; END IF; END `$`$;"

    Invoke-PostgresSqlSmoke `
        -Description "Seeding flood-potential evidence for tile feature refresh smoke" `
        -Sql "$tileSmokeCleanupSql INSERT INTO evidence (source_id, source_type, event_type, title, summary, geom, confidence, privacy_level, ingestion_status, properties, raw_ref) VALUES ('runtime-smoke-flood-potential', 'derived', 'flood_potential', 'Runtime smoke flood potential', 'Synthetic smoke feature for tile cache validation.', ST_SetSRID(ST_MakePoint(121.5654, 25.033), 4326), 0.5, 'public', 'accepted', '{}'::jsonb, 'runtime-smoke:tile-cache');"

    Invoke-SchedulerBoundedTickSmoke

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
        -Description "Seeding expired tile cache rows for prune smoke" `
        -Sql "DELETE FROM map_layer_features WHERE feature_key = 'runtime-smoke-expired-feature'; DELETE FROM tile_cache_entries WHERE layer_id = 'flood-potential' AND z = 24 AND x = 1 AND y = 1; INSERT INTO map_layer_features (layer_id, feature_key, source_ref, geom, minzoom, maxzoom, properties, generated_at, expires_at, metadata) VALUES ('flood-potential', 'runtime-smoke-expired-feature', 'runtime-smoke-expired', ST_SetSRID(ST_MakePoint(121.5654, 25.033), 4326), 0, 24, '{}'::jsonb, now() - interval '3 days', now() - interval '2 days', '{`"source`":`"runtime-smoke`"}'::jsonb); INSERT INTO tile_cache_entries (layer_id, z, x, y, tile_data, content_hash, generated_at, expires_at, metadata) VALUES ('flood-potential', 24, 1, 1, convert_to('runtime-smoke-expired', 'UTF8'), 'runtime-smoke-expired', now() - interval '3 days', now() - interval '2 days', '{`"source`":`"runtime-smoke`"}'::jsonb);"

    $tileLifecyclePython = @'
from datetime import UTC, datetime

from app.config import load_worker_settings
from app.jobs.tile_cache import PostgresTileCacheWriter

settings = load_worker_settings()
writer = PostgresTileCacheWriter(database_url=settings.database_url)
prune = writer.prune_expired(
    expired_before=datetime.now(UTC),
    layer_id="flood-potential",
    limit=10,
)
if prune.tile_cache_deleted < 1 or prune.features_deleted < 1:
    raise SystemExit(
        "expected prune_expired to delete at least one tile cache row and one feature; "
        f"got tile_cache_deleted={prune.tile_cache_deleted} features_deleted={prune.features_deleted}"
    )

invalidation = writer.invalidate_layer(
    layer_id="flood-potential",
    invalidated_at=datetime.now(UTC),
    reason="runtime-smoke",
)
if invalidation.features_invalidated < 1 or invalidation.tile_cache_deleted < 1:
    raise SystemExit(
        "expected invalidate_layer to mark at least one feature and delete at least one cache row; "
        f"got features_invalidated={invalidation.features_invalidated} "
        f"tile_cache_deleted={invalidation.tile_cache_deleted}"
    )

print(
    "tile_lifecycle_smoke=ok "
    f"pruned_cache={prune.tile_cache_deleted} "
    f"pruned_features={prune.features_deleted} "
    f"invalidated_features={invalidation.features_invalidated} "
    f"deleted_cache={invalidation.tile_cache_deleted}"
)
'@

    Invoke-ComposePythonScript `
        -Description "Running tile cache prune and invalidation smoke" `
        -Service "worker" `
        -PythonSource $tileLifecyclePython

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

    $metrics = Invoke-HttpRequestExpectStatus `
        -Name "Calling API /metrics" `
        -Url "$ApiBaseUrl/metrics" `
        -AcceptStatusCodes @(200)
    if ([string]$metrics.Content -notmatch "flood_risk_api_up 1") {
        Fail-Smoke "API /metrics did not include flood_risk_api_up." "api"
    }
    Write-Host "API metrics smoke: flood_risk_api_up exported"

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

        if ($SkipAdapterFixtureSmoke) {
            Write-Host "Official adapter fixture dry-run smoke skipped by -SkipAdapterFixtureSmoke."
        }
        else {
            Invoke-AdapterFixtureDryRunSmoke
        }

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
