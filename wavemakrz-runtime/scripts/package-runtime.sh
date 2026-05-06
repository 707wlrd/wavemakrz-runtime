#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="$ROOT/runtime"
DIST="$ROOT/dist"
mkdir -p "$DIST"

zip_platform() {
  local platform_dir="$1"
  local zip_name="$2"
  local src="$RUNTIME/$platform_dir"
  if [[ ! -d "$src" ]]; then
    echo "Missing runtime folder: $src" >&2
    exit 1
  fi

  local tmp
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/runtime"
  cp -R "$src" "$tmp/runtime/$platform_dir"
  (cd "$tmp" && zip -qr "$DIST/$zip_name" runtime)
  rm -rf "$tmp"
  echo "Created $DIST/$zip_name"
}

# Ensure mac executables are executable
chmod +x "$RUNTIME/darwin-arm64/bin/ffmpeg" "$RUNTIME/darwin-arm64/bin/yt-dlp" "$RUNTIME/darwin-arm64/python/bin/python3" 2>/dev/null || true
chmod +x "$RUNTIME/darwin-x64/bin/ffmpeg" "$RUNTIME/darwin-x64/bin/yt-dlp" "$RUNTIME/darwin-x64/python/bin/python3" 2>/dev/null || true

zip_platform "win32-x64" "wavemakrz-runtime-win-x64.zip"
zip_platform "darwin-arm64" "wavemakrz-runtime-mac-arm64.zip"
zip_platform "darwin-x64" "wavemakrz-runtime-mac-x64.zip"

(
  cd "$DIST"
  shasum -a 256 *.zip > checksums.txt
)
echo "Created $DIST/checksums.txt"
echo "Done."

