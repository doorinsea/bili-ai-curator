$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
$logPath = Join-Path $logDir "curator.log"

if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

function Write-CuratorLog([string]$message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$stamp] $message" -Encoding UTF8
}

trap {
    Write-CuratorLog "fatal startup error: $($_.Exception.Message)"
    exit 1
}

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
} catch {}
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment is missing: $python"
}

$biliHomeCandidates = @(Join-Path $root "data\bili-cli")
if ($env:APPDATA) {
    $biliHomeCandidates += Join-Path $env:APPDATA "bili-cli"
}
if ($env:USERPROFILE) {
    $biliHomeCandidates += Join-Path $env:USERPROFILE "AppData\Roaming\bili-cli"
}
$existingBiliHome = $biliHomeCandidates | Where-Object {
    Test-Path -LiteralPath (Join-Path $_ "owner.json")
} | Select-Object -First 1
if ($existingBiliHome) {
    $env:BILI_CLI_HOME = $existingBiliHome
} elseif (-not $env:BILI_CLI_HOME -and $biliHomeCandidates.Count -gt 0) {
    $env:BILI_CLI_HOME = $biliHomeCandidates[0]
}
$runtimeIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$ownerConfigReadable = $false
try {
    $ownerPath = Join-Path $env:BILI_CLI_HOME "owner.json"
    $ownerConfigReadable = Test-Path -LiteralPath $ownerPath -PathType Leaf -ErrorAction Stop
} catch {}

$mutex = [System.Threading.Mutex]::new($false, "Local\BiliAICurator")
$ownsMutex = $false
try {
    $ownsMutex = $mutex.WaitOne(0)
    if (-not $ownsMutex) {
        Write-CuratorLog "launch skipped: another curator process is already running"
        exit 0
    }
} catch {
    $mutex.Dispose()
    throw
}

$envPath = Join-Path $root ".env"
try {
    if (Test-Path -LiteralPath $envPath) {
        Get-Content -LiteralPath $envPath -Encoding UTF8 | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
                $parts = $line.Split("=", 2)
                $key = $parts[0].Trim()
                $value = $parts[1].Trim().Trim('"').Trim("'")
                if ($key -and $value -and -not [Environment]::GetEnvironmentVariable($key, "Process")) {
                    [Environment]::SetEnvironmentVariable($key, $value, "Process")
                }
            }
        }
    }

    $configPath = Join-Path $root "config.json"
    if (-not (Test-Path -LiteralPath $configPath)) {
        Copy-Item -LiteralPath (Join-Path $root "config.example.json") -Destination $configPath
        Write-Host "Created config.json. Set owner_uid and review dry_run before starting." -ForegroundColor Yellow
        exit 1
    }

    Write-CuratorLog (
        "curator service starting as $runtimeIdentity; " +
        "BILI_CLI_HOME=$env:BILI_CLI_HOME; owner_readable=$ownerConfigReadable"
    )
    Push-Location $root
    try {
        & $python -u -m bili_ai_curator run 2>&1 | Tee-Object -FilePath $logPath -Append
        $exitCode = $LASTEXITCODE
        Write-CuratorLog "curator service exited with code $exitCode"
        exit $exitCode
    } finally {
        Pop-Location
    }
} finally {
    if ($ownsMutex) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
