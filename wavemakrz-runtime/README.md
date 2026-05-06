# wavemakrz-runtime

Repo des dépendances runtime lourdes de WAVEMAKRZ (hors repo app).

## Structure attendue

```txt
wavemakrz-runtime/
├─ runtime/
│  ├─ win32-x64/
│  │  ├─ bin/
│  │  │  ├─ ffmpeg.exe
│  │  │  └─ yt-dlp.exe
│  │  ├─ python/
│  │  │  └─ Scripts/python.exe
│  │  ├─ python-scripts/
│  │  │  ├─ demucs_runner.py
│  │  │  ├─ analyze.py
│  │  │  └─ loop_finder.py
│  │  └─ models/
│  ├─ darwin-arm64/
│  │  ├─ bin/ffmpeg
│  │  ├─ bin/yt-dlp
│  │  ├─ python/bin/python3
│  │  ├─ python-scripts/...
│  │  └─ models/
│  └─ darwin-x64/
│     ├─ ...
├─ dist/
├─ scripts/
│  ├─ package-runtime.ps1
│  ├─ package-runtime.sh
│  └─ checksums.ps1
└─ RELEASE.md
```

## Noms de ZIP obligatoires

- `wavemakrz-runtime-win-x64.zip`
- `wavemakrz-runtime-mac-arm64.zip`
- `wavemakrz-runtime-mac-x64.zip`

## Important macOS

Avant packaging, rendre exécutables:

```bash
chmod +x runtime/darwin-arm64/bin/ffmpeg runtime/darwin-arm64/bin/yt-dlp runtime/darwin-arm64/python/bin/python3
chmod +x runtime/darwin-x64/bin/ffmpeg runtime/darwin-x64/bin/yt-dlp runtime/darwin-x64/python/bin/python3
```

## Packaging

Windows PowerShell:

```powershell
pwsh ./scripts/package-runtime.ps1
pwsh ./scripts/checksums.ps1
```

macOS/Linux:

```bash
bash ./scripts/package-runtime.sh
```

