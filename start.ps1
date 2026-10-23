$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
} catch {}
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment is missing: $python"
}

$envPath = Join-Path $root ".env"
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

Push-Location $root
try {
    & $python -m bili_ai_curator run
} finally {
    Pop-Location
}
