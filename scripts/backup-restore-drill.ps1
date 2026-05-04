param(
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$BackupPath = "",
    [string]$RestoreDatabaseUrl = "",
    [ValidateSet("Auto", "Local", "Docker")]
    [string]$ClientMode = "Auto",
    [string]$DockerImage = "postgis/postgis:16-3.4",
    [switch]$VerifyClient,
    [switch]$ExecuteBackup,
    [switch]$InspectBackup,
    [switch]$ExecuteRestoreToScratch,
    [switch]$ConfirmScratchRestore
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Fail-Drill {
    param([string]$Message)
    [Console]::Error.WriteLine("Backup/restore drill failed: $Message")
    exit 1
}

function Test-CommandAvailable {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        Write-Host "FOUND $Name at $($command.Source)"
        return $true
    }

    Write-Host "MISSING $Name"
    return $false
}

function Test-DockerAvailable {
    $docker = Get-Command "docker" -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Host "MISSING docker"
        return $false
    }

    Write-Host "FOUND docker at $($docker.Source)"
    & docker version --format "{{.Server.Version}}" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker daemon is not reachable."
        return $false
    }

    Write-Host "Docker daemon is reachable."
    return $true
}

function Resolve-ClientMode {
    param([string]$ToolName)

    $local = Get-Command $ToolName -ErrorAction SilentlyContinue
    if ($ClientMode -eq "Local") {
        if (-not $local) {
            Fail-Drill "$ToolName is required when -ClientMode Local is used."
        }

        return "Local"
    }

    if ($ClientMode -eq "Docker") {
        if (-not (Test-DockerAvailable)) {
            Fail-Drill "Docker is required when -ClientMode Docker is used."
        }

        return "Docker"
    }

    if ($local) {
        return "Local"
    }

    if (Test-DockerAvailable) {
        return "Docker"
    }

    Fail-Drill "$ToolName was not found locally and Docker fallback is not available."
}

function Convert-ToDockerBackupPath {
    param([string]$Path)

    $directory = Split-Path -Parent $Path
    if (-not $directory) {
        $directory = "."
    }

    $resolvedDir = Resolve-Path -LiteralPath $directory
    $fileName = Split-Path -Leaf $Path
    return @{
        HostDir = $resolvedDir.Path
        ContainerPath = "/backup/$fileName"
    }
}

function Invoke-PostgresClient {
    param(
        [string]$ToolName,
        [string[]]$Arguments,
        [string]$MountedBackupPath = "",
        [switch]$ReadOnlyMount
    )

    $mode = Resolve-ClientMode -ToolName $ToolName
    Write-Host "Using $mode PostgreSQL client for $ToolName."

    if ($mode -eq "Local") {
        & $ToolName @Arguments | ForEach-Object { Write-Host $_ }
        $exitCode = $LASTEXITCODE
        return $exitCode
    }

    $dockerArgs = @("run", "--rm")
    if ($MountedBackupPath) {
        $mapping = Convert-ToDockerBackupPath -Path $MountedBackupPath
        $mountMode = "rw"
        if ($ReadOnlyMount) {
            $mountMode = "ro"
        }
        $dockerArgs += @("-v", "$($mapping.HostDir):/backup:$mountMode")

        $containerArguments = @()
        foreach ($argument in $Arguments) {
            $containerArguments += $argument.Replace($MountedBackupPath, $mapping.ContainerPath)
        }
    } else {
        $containerArguments = $Arguments
    }

    $dockerArgs += @($DockerImage, $ToolName)
    $dockerArgs += $containerArguments
    & docker @dockerArgs | ForEach-Object { Write-Host $_ }
    $exitCode = $LASTEXITCODE
    return $exitCode
}

function Test-PostgresClient {
    param([string]$ToolName)

    $exitCode = Invoke-PostgresClient -ToolName $ToolName -Arguments @("--version")
    if ($exitCode -ne 0) {
        Fail-Drill "$ToolName --version exited with code $exitCode."
    }
}

function Assert-BackupPath {
    if (-not $BackupPath) {
        Fail-Drill "BackupPath is required for this operation."
    }
}

function Test-ScratchUrl {
    param([string]$Url)
    if (-not $Url) {
        return $false
    }

    try {
        $uri = [Uri]$Url
        $databaseName = $uri.AbsolutePath.TrimStart("/")
    } catch {
        return $false
    }

    if (-not $databaseName) {
        return $false
    }

    return $databaseName -match "(scratch|restore|drill)"
}

$willExecute = $ExecuteBackup -or $InspectBackup -or $ExecuteRestoreToScratch

if (-not $willExecute) {
    Write-Step "Dry-run checklist"
    Write-Host "No backup or restore command will be executed."
    Write-Host "Planned drill:"
    Write-Host "1. Confirm source DATABASE_URL points to the intended environment."
    Write-Host "2. Run pg_dump with --format=custom to create a backup archive."
    Write-Host "3. Run pg_restore --list against the archive."
    Write-Host "4. Restore only to a scratch/drill database."
    Write-Host "5. Run health, readiness, runtime smoke, and source freshness checks."

    Write-Step "Tool availability"
    [void](Test-CommandAvailable "pg_dump")
    [void](Test-CommandAvailable "pg_restore")
    if ($ClientMode -eq "Docker" -or $ClientMode -eq "Auto") {
        [void](Test-DockerAvailable)
    }

    if ($VerifyClient) {
        Write-Step "Client version check"
        Test-PostgresClient "pg_dump"
        Test-PostgresClient "pg_restore"
    } else {
        Write-Host "Use -VerifyClient to run pg_dump --version and pg_restore --version through the selected client path."
    }
    exit 0
}

if ($ExecuteBackup) {
    if (-not $DatabaseUrl) {
        Fail-Drill "DatabaseUrl is required for -ExecuteBackup."
    }
    Assert-BackupPath

    $backupDir = Split-Path -Parent $BackupPath
    if ($backupDir -and -not (Test-Path -LiteralPath $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir | Out-Null
    }

    Write-Step "Creating custom-format backup"
    $exitCode = Invoke-PostgresClient `
        -ToolName "pg_dump" `
        -Arguments @("--format=custom", "--no-owner", "--no-privileges", "--file", "$BackupPath", "$DatabaseUrl") `
        -MountedBackupPath "$BackupPath"
    if ($exitCode -ne 0) {
        Fail-Drill "pg_dump exited with code $exitCode."
    }

    $backupItem = Get-Item -LiteralPath $BackupPath
    Write-Host "Backup created: $($backupItem.FullName) ($($backupItem.Length) bytes)"
}

if ($InspectBackup) {
    Assert-BackupPath
    if (-not (Test-Path -LiteralPath $BackupPath)) {
        Fail-Drill "Backup file not found: $BackupPath"
    }

    Write-Step "Inspecting backup archive"
    $exitCode = Invoke-PostgresClient `
        -ToolName "pg_restore" `
        -Arguments @("--list", "$BackupPath") `
        -MountedBackupPath "$BackupPath" `
        -ReadOnlyMount
    if ($exitCode -ne 0) {
        Fail-Drill "pg_restore --list exited with code $exitCode."
    }
}

if ($ExecuteRestoreToScratch) {
    Assert-BackupPath
    if (-not (Test-Path -LiteralPath $BackupPath)) {
        Fail-Drill "Backup file not found: $BackupPath"
    }
    if (-not $ConfirmScratchRestore) {
        Fail-Drill "-ConfirmScratchRestore is required for restore execution."
    }
    if (-not (Test-ScratchUrl -Url $RestoreDatabaseUrl)) {
        Fail-Drill "RestoreDatabaseUrl database name must clearly include scratch, restore, or drill."
    }
    if ($DatabaseUrl -and $RestoreDatabaseUrl -eq $DatabaseUrl) {
        Fail-Drill "RestoreDatabaseUrl must not equal DatabaseUrl."
    }

    Write-Step "Restoring backup to scratch database"
    $exitCode = Invoke-PostgresClient `
        -ToolName "pg_restore" `
        -Arguments @("--single-transaction", "--exit-on-error", "--no-owner", "--no-privileges", "--dbname", "$RestoreDatabaseUrl", "$BackupPath") `
        -MountedBackupPath "$BackupPath" `
        -ReadOnlyMount
    if ($exitCode -ne 0) {
        Fail-Drill "pg_restore exited with code $exitCode."
    }

    Write-Host "Scratch restore completed."
}
