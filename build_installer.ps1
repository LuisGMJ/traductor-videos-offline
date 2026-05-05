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

$releaseZip = Join-Path $projectRoot "releases\v$Version\TraductorVideos-windows-v$Version.zip"
$outputExe = Join-Path $projectRoot "releases\v$Version\TraductorVideos-Setup-v$Version.exe"
$checksumPath = Join-Path $projectRoot "releases\v$Version\TraductorVideos-Setup-v$Version-sha256.txt"
$buildRoot = Join-Path $projectRoot "build\installer\v$Version"
$distRoot = Join-Path $buildRoot "dist"
$workRoot = Join-Path $buildRoot "work"
$stubName = "TraductorVideos-Setup-bootstrap"
$stubExe = Join-Path $distRoot "$stubName.exe"
$python = "C:\Users\lgmj9\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $releaseZip)) {
    throw "No se encontro la release ZIP en $releaseZip. Ejecuta primero build_release.bat."
}

if (Test-Path $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name $stubName `
    --distpath $distRoot `
    --workpath $workRoot `
    --specpath $buildRoot `
    --add-data "$projectRoot\VERSION;." `
    (Join-Path $projectRoot "installer\installer_stub.py")

if (-not (Test-Path $stubExe)) {
    throw "No se genero el bootstrap del instalador."
}

Copy-Item -Path $stubExe -Destination $outputExe -Force

$payloadBytes = [System.IO.File]::ReadAllBytes($releaseZip)
$payloadSize = [System.BitConverter]::GetBytes([UInt64]$payloadBytes.Length)
$marker = [System.Text.Encoding]::ASCII.GetBytes("TVI_PAYLOAD_V1")
$stream = [System.IO.File]::Open($outputExe, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
try {
    $stream.Write($payloadBytes, 0, $payloadBytes.Length)
    $stream.Write($payloadSize, 0, $payloadSize.Length)
    $stream.Write($marker, 0, $marker.Length)
} finally {
    $stream.Dispose()
}

if (-not (Test-Path $outputExe)) {
    throw "No se genero el instalador esperado en $outputExe."
}

$hash = (Get-FileHash -Path $outputExe -Algorithm SHA256).Hash
"$hash  $(Split-Path $outputExe -Leaf)" | Set-Content -Path $checksumPath -Encoding utf8

Write-Host ""
Write-Host "Instalador listo:"
Write-Host $outputExe
