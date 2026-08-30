param(
    [ValidateSet("start", "stop", "status", "logs", "backup", "verify-backup")]
    [string]$Action = "start",
    [string]$BackupPath = ""
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
$LegacyConfigFile = Join-Path $RootDir ".env.personal"
$LocalStateRoot = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA "ChunqiuYuanquanGEO"
} else {
    Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "ChunqiuYuanquanGEO"
}
$ConfigFile = Join-Path $LocalStateRoot ".env.personal"
$BackupRoot = Join-Path $LocalStateRoot "backups"
$BackupKeyFile = Join-Path $LocalStateRoot "backup.key"
$ComposeFile = Join-Path $RootDir "infra/docker-compose.personal.yml"
$DataVolume = if ($env:GEO_DATA_VOLUME_NAME) { $env:GEO_DATA_VOLUME_NAME } else { "chunqiu_yuanquan_geo_personal_data" }
$ArtifactVolume = if ($env:GEO_ARTIFACT_VOLUME_NAME) { $env:GEO_ARTIFACT_VOLUME_NAME } else { "chunqiu_yuanquan_geo_personal_artifacts" }

function Stop-WithMessage([string]$Message) {
    Write-Host "`n错误：$Message" -ForegroundColor Red
    exit 1
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose --env-file $ConfigFile -f $ComposeFile @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose 执行失败。" }
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Stop-WithMessage "未检测到 Docker Desktop。请先安装并启动 Docker Desktop。"
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage "需要 Docker Compose v2。请升级 Docker Desktop。" }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "Docker Desktop 尚未运行。请启动并等待显示 Running 后重试。"
    }
}

function Test-VolumeExists([string]$Name) {
    & docker volume inspect $Name *> $null
    return $LASTEXITCODE -eq 0
}

function Test-VolumeDatabase {
    if (-not (Test-VolumeExists $DataVolume)) { return $false }
    & docker run --rm --mount "type=volume,src=$DataVolume,dst=/source,readonly" alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d test -f /source/geo_platform.db *> $null
    return $LASTEXITCODE -eq 0
}

function Initialize-ConfigLocation {
    New-Item -ItemType Directory -Force -Path $LocalStateRoot, $BackupRoot | Out-Null
    if ((-not (Test-Path $ConfigFile)) -and (Test-Path $LegacyConfigFile)) {
        Copy-Item $LegacyConfigFile $ConfigFile
        Write-Host "已将旧版本机配置迁移到稳定用户目录。"
    }
}

function Test-PortBusy([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait(250) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function New-RandomHex([int]$ByteCount) {
    $bytes = New-Object byte[] $ByteCount
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

function Initialize-BackupKey {
    if (-not (Test-Path $BackupKeyFile)) {
        [System.IO.File]::WriteAllText($BackupKeyFile, (New-RandomHex 32), (New-Object System.Text.UTF8Encoding($false)))
    }
    $keyText = [System.IO.File]::ReadAllText($BackupKeyFile).Trim()
    if ($keyText -notmatch "^[0-9a-fA-F]{64}$") {
        Stop-WithMessage "备份密钥无效。请从安全副本恢复 $BackupKeyFile。"
    }
}

function Invoke-SecureBackup([string]$Mode, [string]$InputPath, [string]$OutputPath = "") {
    $directory = Split-Path -Parent $InputPath
    $inputName = Split-Path -Leaf $InputPath
    $arguments = @(
        "compose", "--env-file", $ConfigFile, "-f", $ComposeFile,
        "run", "--rm", "--no-deps", "-T",
        "-v", "${BackupKeyFile}:/run/secrets/geo-backup-key:ro",
        "-v", "${directory}:/secure-backup",
        "api", "uv", "run", "--no-sync", "python", "scripts/secure_backup_bundle.py", $Mode,
        "--key-file", "/run/secrets/geo-backup-key", "--input", "/secure-backup/$inputName"
    )
    if ($OutputPath) {
        $arguments += @("--output", "/secure-backup/$(Split-Path -Leaf $OutputPath)")
    }
    & docker @arguments
    if ($LASTEXITCODE -ne 0) { throw "加密备份处理失败。" }
}

function Test-EncryptedBackup([string]$Path) {
    if (-not $Path -or -not (Test-Path $Path -PathType Leaf)) {
        Stop-WithMessage "请提供存在的 .gcm 备份文件。"
    }
    Initialize-BackupKey
    Invoke-SecureBackup "verify" (Resolve-Path $Path).Path
    Write-Host "OK  备份已通过 AES-256-GCM 完整性和解密验证。" -ForegroundColor Green
}

function New-PersonalConfig {
    if (Test-Path $ConfigFile) { return $false }
    if ((Test-VolumeExists $DataVolume) -or (Test-VolumeExists $ArtifactVolume)) {
        Stop-WithMessage "检测到已有 GEO 数据卷，但本机密钥不存在。为避免旧 Provider 凭据无法解密，启动已停止。请恢复原 .env.personal。"
    }
    $port = $null
    foreach ($candidate in 3000..3010) {
        if (-not (Test-PortBusy $candidate)) { $port = $candidate; break }
    }
    if ($null -eq $port) { Stop-WithMessage "3000-3010 端口均已被占用，本程序不会结束其他应用。" }

    $secret = New-RandomHex 48
    $proxySecret = New-RandomHex 48
    $workerInstanceId = New-RandomHex 16
    $content = "GEO_AUTH_SECRET=$secret`nGEO_INTERNAL_PROXY_SECRET=$proxySecret`nGEO_HTTP_PORT=$port`nGEO_WORKER_CONCURRENCY=8`nGEO_WORKER_INSTANCE_ID=$workerInstanceId`n"
    [System.IO.File]::WriteAllText($ConfigFile, $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "已创建本机私密配置（端口 $port，Worker 并发 8）。"
    return $true
}

function Add-MissingConfigKeys {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $text = [System.IO.File]::ReadAllText($ConfigFile)
    if ($text -notmatch "(?m)^GEO_INTERNAL_PROXY_SECRET=") {
        [System.IO.File]::AppendAllText($ConfigFile, "GEO_INTERNAL_PROXY_SECRET=$(New-RandomHex 48)`n", $encoding)
    }
    if ($text -notmatch "(?m)^GEO_WORKER_CONCURRENCY=") {
        [System.IO.File]::AppendAllText($ConfigFile, "GEO_WORKER_CONCURRENCY=8`n", $encoding)
    }
    if ($text -notmatch "(?m)^GEO_WORKER_INSTANCE_ID=") {
        [System.IO.File]::AppendAllText($ConfigFile, "GEO_WORKER_INSTANCE_ID=$(New-RandomHex 16)`n", $encoding)
    }
}

function Get-Setting([string]$Key) {
    $line = Get-Content $ConfigFile | Where-Object { $_.StartsWith("$Key=") } | Select-Object -Last 1
    if (-not $line) { Stop-WithMessage ".env.personal 缺少 $Key。" }
    return $line.Substring($Key.Length + 1)
}

function Get-AppUrl {
    $portText = Get-Setting "GEO_HTTP_PORT"
    $port = 0
    if (-not [int]::TryParse($portText, [ref]$port)) { Stop-WithMessage "GEO_HTTP_PORT 无效。" }
    return "http://127.0.0.1:$port"
}

function Test-Url([string]$Url) {
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch { return $false }
}

function Test-Worker {
    $workerInstanceId = Get-Setting "GEO_WORKER_INSTANCE_ID"
    & docker compose --env-file $ConfigFile -f $ComposeFile exec -T worker uv run python scripts/check_worker_heartbeat.py --worker-id "personal:$workerInstanceId" --quiet *> $null
    return $LASTEXITCODE -eq 0
}

function Wait-Ready([string]$Url) {
    $deadline = (Get-Date).AddMinutes(10)
    Write-Host -NoNewline "正在等待 Web、API 和 Worker 就绪"
    while ((Get-Date) -lt $deadline) {
        if ((Test-Url "$Url/api/health/ready") -and (Test-Url "$Url/register") -and (Test-Worker)) {
            Write-Host " 完成"
            return
        }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 3
    }
    Write-Host
    & docker compose --env-file $ConfigFile -f $ComposeFile ps
    & docker compose --env-file $ConfigFile -f $ComposeFile logs --tail 80 api web worker gateway
    Stop-WithMessage "10 分钟内未全部就绪。现有数据卷不会被删除。日志可能包含内部请求路径，请勿整段转发。"
}

function Show-Status {
    if (-not (Test-Path $ConfigFile)) { Stop-WithMessage "尚未安装。请先运行启动入口。" }
    $url = Get-AppUrl
    & docker compose --env-file $ConfigFile -f $ComposeFile ps
    $failed = $false
    if (Test-Url "$url/api/health/ready") { Write-Host "OK  API 与数据库" -ForegroundColor Green } else { Write-Host "ERR API 或数据库" -ForegroundColor Red; $failed = $true }
    if (Test-Url "$url/register") { Write-Host "OK  Web 界面" -ForegroundColor Green } else { Write-Host "ERR Web 界面" -ForegroundColor Red; $failed = $true }
    if (Test-Worker) { Write-Host "OK  采集 Worker 心跳" -ForegroundColor Green } else { Write-Host "ERR 采集 Worker 心跳" -ForegroundColor Red; $failed = $true }
    Write-Host "访问地址：$url"
    if ($failed) { exit 1 }
}

function Restore-Services([string[]]$Services) {
    if ($Services.Count -eq 0) { return }
    & docker compose --env-file $ConfigFile -f $ComposeFile start @Services *> $null
}

function Backup-Data([bool]$RestoreOnSuccess = $true) {
    if (-not (Test-Path $ConfigFile)) { Stop-WithMessage "尚未安装，无需备份。" }
    if (-not (Test-VolumeExists $DataVolume)) { Stop-WithMessage "未找到个人数据卷，备份已停止。" }
    if (-not (Test-VolumeExists $ArtifactVolume)) { Stop-WithMessage "未找到证据卷，备份已停止。" }

    Initialize-BackupKey
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupDir = Join-Path $BackupRoot $stamp
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $runningServices = @(& docker compose --env-file $ConfigFile -f $ComposeFile ps --status running --services)
    $allCoreServicesWereRunning = (@("api", "web", "worker", "gateway") | Where-Object { $runningServices -notcontains $_ }).Count -eq 0
    $completed = $false
    try {
        & docker compose --env-file $ConfigFile -f $ComposeFile stop *> $null
        if ($LASTEXITCODE -ne 0) { throw "无法暂停全部写入服务。" }
        Copy-Item $ConfigFile (Join-Path $backupDir "env.personal")

        & docker run --rm --mount "type=volume,src=$DataVolume,dst=/source,readonly" --mount "type=bind,src=$backupDir,dst=/backup" alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d sh -c "test -f /source/geo_platform.db && cd /source && tar -czf /backup/data.tar.gz ."
        if ($LASTEXITCODE -ne 0) { throw "数据库备份失败。" }
        & docker run --rm --mount "type=volume,src=$ArtifactVolume,dst=/source,readonly" --mount "type=bind,src=$backupDir,dst=/backup" alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d sh -c "cd /source && tar -czf /backup/artifacts.tar.gz ."
        if ($LASTEXITCODE -ne 0) { throw "证据备份失败。" }
        & docker run --rm --mount "type=bind,src=$backupDir,dst=/backup,readonly" alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d sh -c "tar -tzf /backup/data.tar.gz >/dev/null && tar -tzf /backup/artifacts.tar.gz >/dev/null"
        if ($LASTEXITCODE -ne 0) { throw "备份完整性校验失败。" }

        $hashLines = @(
            "{0}  data.tar.gz" -f (Get-FileHash (Join-Path $backupDir "data.tar.gz") -Algorithm SHA256).Hash.ToLowerInvariant()
            "{0}  artifacts.tar.gz" -f (Get-FileHash (Join-Path $backupDir "artifacts.tar.gz") -Algorithm SHA256).Hash.ToLowerInvariant()
            "{0}  env.personal" -f (Get-FileHash (Join-Path $backupDir "env.personal") -Algorithm SHA256).Hash.ToLowerInvariant()
        )
        [System.IO.File]::WriteAllLines((Join-Path $backupDir "SHA256SUMS"), $hashLines, (New-Object System.Text.UTF8Encoding($false)))
        [System.IO.File]::WriteAllText((Join-Path $backupDir "BACKUP_COMPLETE"), "complete`n", (New-Object System.Text.UTF8Encoding($false)))
        $bundle = Join-Path $backupDir "geo-backup.tar.gz"
        $encrypted = Join-Path $backupDir "geo-backup-$stamp.gcm"
        & docker run --rm --mount "type=bind,src=$backupDir,dst=/backup" alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d sh -c "cd /backup && tar -czf geo-backup.tar.gz data.tar.gz artifacts.tar.gz env.personal SHA256SUMS BACKUP_COMPLETE"
        if ($LASTEXITCODE -ne 0) { throw "无法创建备份归档。" }
        Invoke-SecureBackup "encrypt" $bundle $encrypted
        Invoke-SecureBackup "verify" $encrypted
        Remove-Item -Force @(
            (Join-Path $backupDir "data.tar.gz"),
            (Join-Path $backupDir "artifacts.tar.gz"),
            (Join-Path $backupDir "env.personal"),
            (Join-Path $backupDir "SHA256SUMS"),
            (Join-Path $backupDir "BACKUP_COMPLETE"),
            $bundle
        )
        $completed = $true
    } catch {
        Restore-Services $runningServices
        Stop-WithMessage "$($_.Exception.Message) 原服务状态已尝试恢复。"
    }
    if ($completed -and $RestoreOnSuccess) {
        Restore-Services $runningServices
        if ($allCoreServicesWereRunning) { Wait-Ready (Get-AppUrl) }
    }
    Write-Host "加密备份已保存到：$encrypted"
    Write-Host "请另行安全保存备份密钥 $BackupKeyFile；丢失后无法恢复。"
}

Set-Location $RootDir
Assert-Docker
Initialize-ConfigLocation

switch ($Action) {
    "start" {
        $firstInstall = New-PersonalConfig
        Add-MissingConfigKeys
        $url = Get-AppUrl
        if (Test-VolumeDatabase) {
            Write-Host "检测到已有数据，启动前先创建一致性备份。"
            Invoke-Compose build api
            Backup-Data $false
        }
        Write-Host "正在构建并启动春秋元泉 GEO。首次启动需要下载镜像，可能需要数分钟。"
        Invoke-Compose up -d --build
        Wait-Ready $url
        Show-Status
        if ($env:GEO_NO_BROWSER -ne "true") {
            if ($firstInstall) { Start-Process "$url/register" } else { Start-Process $url }
        }
    }
    "stop" {
        if (-not (Test-Path $ConfigFile)) { Stop-WithMessage "尚未安装。" }
        Invoke-Compose stop
        Write-Host "已停止服务。账号、数据库和证据卷已保留。"
    }
    "status" { Show-Status }
    "logs" {
        if (-not (Test-Path $ConfigFile)) { Stop-WithMessage "尚未安装。" }
        Write-Host "以下日志仅供本机排查，不要整段转发。"
        Invoke-Compose logs --tail 150 api web worker gateway
    }
    "backup" { Backup-Data $true }
    "verify-backup" { Test-EncryptedBackup $BackupPath }
}
