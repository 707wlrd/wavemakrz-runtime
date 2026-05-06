# Release runtime (GitHub)

1. Générer les ZIP dans `dist/`:
   - `wavemakrz-runtime-win-x64.zip`
   - `wavemakrz-runtime-mac-arm64.zip`
   - `wavemakrz-runtime-mac-x64.zip`
2. Générer checksums:
   - `dist/checksums.txt`
3. Créer une release taguée (ex: `v1`) sur le repo `wavemakrz-runtime`.
4. Uploader les 3 ZIP + `checksums.txt` dans les assets de la release.
5. Dans l’app WAVEMAKRZ, pointer:
   - `WAVEMAKRZ_RUNTIME_BASE_URL=https://github.com/<owner>/wavemakrz-runtime/releases/download/v1`
   - `WAVEMAKRZ_RUNTIME_VERSION=v1`

