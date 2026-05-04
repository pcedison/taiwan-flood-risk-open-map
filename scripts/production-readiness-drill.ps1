param(
    [string]$TargetEnv = "production-beta",
    [string]$Operator = $env:USERNAME,
    [string]$CommitSha = "",
    [string]$OutputPath = "",
    [string[]]$AlertRouteRef = @(),
    [string]$RuntimeSmokeRef = "replace-with-private-runtime-smoke-ref",
    [string]$PlaywrightRef = "replace-with-private-playwright-evidence-ref",
    [string]$AlertTestRef = "replace-with-private-alert-test-ref",
    [string]$RollbackTarget = "replace-with-known-good-zeabur-deployment-or-commit",
    [string]$RollbackRef = "replace-with-private-rollback-drill-ref",
    [string]$BackupRestoreRef = "replace-with-private-backup-restore-ref",
    [string[]]$SecretManagerRef = @()
)

$ErrorActionPreference = "Stop"

$AlertFamilies = @(
    "API readiness",
    "Source freshness",
    "Worker heartbeat/last run",
    "Scheduler heartbeat",
    "Runtime queue rows",
    "Backup/restore drill"
)

$SecretNames = @(
    "ABUSE_HASH_SALT",
    "ADMIN_BEARER_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "CWA_API_AUTHORIZATION",
    "WRA_API_TOKEN",
    "GRAFANA_ADMIN_PASSWORD",
    "USER_REPORTS_CHALLENGE_SECRET_KEY",
    "USER_REPORTS_CHALLENGE_STATIC_TOKEN"
)

$SecretManagerRefPrefixes = @(
    "1password://",
    "aws-secretsmanager://",
    "azure-keyvault://",
    "bitwarden://",
    "doppler://",
    "gcp-secret-manager://",
    "op://",
    "private-ops://",
    "secret-manager://",
    "vault://",
    "zeabur://"
)

$SecretValuePrefixes = @(
    "http://",
    "https://",
    "postgres://",
    "postgresql://",
    "redis://"
)

function Fail-Drill {
    param([string]$Message)
    [Console]::Error.WriteLine("Production readiness drill failed: $Message")
    exit 1
}

function Get-IsoTimestamp {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Get-CurrentCommitSha {
    if ($CommitSha) {
        return $CommitSha
    }

    $sha = ""
    try {
        $sha = (& git rev-parse HEAD 2>$null).Trim()
    }
    catch {
        $sha = ""
    }

    if ($LASTEXITCODE -ne 0 -or -not $sha) {
        return "replace-with-reviewed-deployment-sha"
    }

    return $sha
}

function Test-SecretManagerReference {
    param([string]$Ref)

    if (-not $Ref) {
        return $false
    }

    $lower = $Ref.Trim().ToLowerInvariant()
    foreach ($prefix in $SecretValuePrefixes) {
        if ($lower.StartsWith($prefix)) {
            return $false
        }
    }

    foreach ($prefix in $SecretManagerRefPrefixes) {
        if ($lower.StartsWith($prefix)) {
            return $true
        }
    }

    return $false
}

function Split-NameRef {
    param(
        [string]$Item,
        [string]$FieldName
    )

    $parts = $Item -split "=", 2
    if ($parts.Count -ne 2 -or -not $parts[0].Trim() -or -not $parts[1].Trim()) {
        Fail-Drill "$FieldName must use NAME=ref format."
    }

    return [pscustomobject]@{
        Name = $parts[0].Trim()
        Ref = $parts[1].Trim()
    }
}

function Set-AlertRouteRefs {
    param([string[]]$Items)

    $refs = [ordered]@{}
    foreach ($family in $AlertFamilies) {
        $refs[$family] = "replace-with-private-alert-route-ref"
    }

    foreach ($item in $Items) {
        $entry = Split-NameRef -Item $item -FieldName "AlertRouteRef"
        if (-not ($AlertFamilies -contains $entry.Name)) {
            Fail-Drill "Unknown alert family '$($entry.Name)'. Expected one of: $($AlertFamilies -join ', ')."
        }
        $refs[$entry.Name] = $entry.Ref
    }

    return $refs
}

function Set-SecretManagerRefs {
    param([string[]]$Items)

    $refs = [ordered]@{}
    foreach ($name in $SecretNames) {
        $refs[$name] = "replace-with-secret-manager-ref"
    }

    foreach ($item in $Items) {
        $entry = Split-NameRef -Item $item -FieldName "SecretManagerRef"
        if (-not ($SecretNames -contains $entry.Name)) {
            Fail-Drill "Unknown secret name '$($entry.Name)'. Expected one of: $($SecretNames -join ', ')."
        }
        if (-not (Test-SecretManagerReference -Ref $entry.Ref)) {
            Fail-Drill "SecretManagerRef for '$($entry.Name)' must be a secret manager ref such as zeabur://, vault://, op://, or private-ops://. Do not pass secret values."
        }
        $refs[$entry.Name] = $entry.Ref
    }

    $entries = @()
    foreach ($name in $SecretNames) {
        $entries += [ordered]@{
            name = $name
            ref = $refs[$name]
        }
    }

    return $entries
}

$now = Get-IsoTimestamp
$commit = Get-CurrentCommitSha

$evidence = [ordered]@{
    schema_version = "production-readiness-drill-preflight/v1"
    generated_at = $now
    target_env = $TargetEnv
    commit_sha = $commit
    operator = $Operator
    alert_route_refs = Set-AlertRouteRefs -Items $AlertRouteRef
    drill_timestamps = [ordered]@{
        "on-call drill" = $now
        "rollback drill" = $now
        "backup restore drill" = $now
    }
    runtime_smoke_ref = $RuntimeSmokeRef
    playwright_ref = $PlaywrightRef
    alert_test_ref = $AlertTestRef
    rollback = [ordered]@{
        target = $RollbackTarget
        evidence_ref = $RollbackRef
    }
    backup_restore_ref = $BackupRestoreRef
    secret_manager_refs = Set-SecretManagerRefs -Items $SecretManagerRef
    merge_hint = "Place this object under drill_preflight in the private production readiness evidence file. It contains only refs, never secret values."
}

$json = $evidence | ConvertTo-Json -Depth 8

if ($OutputPath) {
    $directory = Split-Path -Parent $OutputPath
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }
    Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8
    Write-Host "Production readiness drill evidence skeleton written to $OutputPath"
}
else {
    Write-Output $json
}
