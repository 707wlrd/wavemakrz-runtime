$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root "runtime"
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null

function Zip-Platform {
  param(
    [string]$platformDir,
    [string]$zipName
  )
  $src = Join-Path $runtime $platformDir
  if (-not (Test-Path $src)) {
    throw "Missing runtime folder: $src"
  }
  $tmp = Join-Path $env:TEMP ("wavemakrz-runtime-" + [guid]::NewGuid().ToString())
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  New-Item -ItemType Directory -Force -Path (Join-Path $tmp "runtime") | Out-Null
  Copy-Item -Recurse -Force $src (Join-Path $tmp "runtime\$platformDir")
  $zipPath = Join-Path $dist $zipName
  if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
  Compress-Archive -Path (Join-Path $tmp "runtime") -DestinationPath $zipPath -Force
  Remove-Item -Recurse -Force $tmp
  Write-Host "Created $zipPath"
}

Zip-Platform "win32-x64" "wavemakrz-runtime-win-x64.zip"
Zip-Platform "darwin-arm64" "wavemakrz-runtime-mac-arm64.zip"
Zip-Platform "darwin-x64" "wavemakrz-runtime-mac-x64.zip"

Write-Host "Done."

