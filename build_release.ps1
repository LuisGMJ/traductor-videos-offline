param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not $Version) {
    $Version = (Get-Content (Join-Path $projectRoot "VERSION") -Raw).Trim()
}

if (-not $Version) {
    throw "No se encontro una version valida."
}

if (Test-Path ".venv\Scripts\python.exe") {
    $pythonCommand = (Resolve-Path ".venv\Scripts\python.exe").Path
    $pythonArgs = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonArgs = @("-3")
} elseif (Test-Path "C:\Users\lgmj9\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe") {
    $pythonCommand = "C:\Users\lgmj9\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    $pythonArgs = @()
} else {
    $pythonCommand = "python"
    $pythonArgs = @()
}

$distRoot = Join-Path $projectRoot "dist\releases\v$Version"
$bundleDir = Join-Path $distRoot "TraductorVideos"
$releaseRoot = Join-Path $projectRoot "releases\v$Version"
$zipPath = Join-Path $releaseRoot "TraductorVideos-windows-v$Version.zip"
$checksumPath = Join-Path $releaseRoot "TraductorVideos-windows-v$Version-sha256.txt"

if (Test-Path $distRoot) {
    Remove-Item -LiteralPath $distRoot -Recurse -Force
}
if (Test-Path $releaseRoot) {
    Remove-Item -LiteralPath $releaseRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $releaseRoot | Out-Null

& $pythonCommand @pythonArgs -m PyInstaller --noconfirm --distpath $distRoot traducir_videos.spec

if (-not (Test-Path $bundleDir)) {
    throw "No se encontro el bundle esperado en $bundleDir"
}

Compress-Archive -Path "$bundleDir\*" -DestinationPath $zipPath -Force

$hash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash
"$hash  $(Split-Path $zipPath -Leaf)" | Set-Content -Path $checksumPath -Encoding utf8

Write-Host ""
Write-Host "Release lista:"
Write-Host "ZIP: $zipPath"
Write-Host "SHA256: $checksumPath"
