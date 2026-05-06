$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist"
$out = Join-Path $dist "checksums.txt"

if (-not (Test-Path $dist)) {
  throw "dist/ not found. Run package-runtime.ps1 first."
}

$zips = Get-ChildItem -Path $dist -Filter "*.zip" -File
if ($zips.Count -eq 0) {
  throw "No zip files found in dist/."
}

$lines = @()
foreach ($f in $zips) {
  $hash = (Get-FileHash -Algorithm SHA256 -Path $f.FullName).Hash.ToLowerInvariant()
  $lines += "$hash  $($f.Name)"
}

$lines | Set-Content -Path $out -Encoding utf8
Write-Host "Created $out"

