# Desktop build (Windows .exe)

Slice 7 packages LocalCut as a real Windows installer — the goal from day one:
install it, use it, uninstall it whenever you want. No accounts, no watermarks,
no internet needed after install.

## How it's put together

| Piece | What it is | Built by |
|---|---|---|
| `localcut-backend.exe` | The whole Python backend (FastAPI, faster-whisper, Qwen3-TTS) frozen with PyInstaller | GitHub Actions, Windows runner |
| `ffmpeg.exe` / `ffprobe.exe` | Static builds, bundled so users need nothing installed | Downloaded in CI (gyan.dev) |
| React UI | The same `frontend/` you already know, built with `VITE_API_BASE=http://127.0.0.1:8000` | GitHub Actions |
| `LocalCut_*_x64-setup.exe` | **The installer (NSIS)** — includes an uninstaller, per-machine Start Menu entry | `tauri build` in CI |

The Tauri shell (`src-tauri/`) is tiny on purpose: on launch it starts the
backend sidecar with `--port 8000 --data-dir <app-data> --ffmpeg-dir <bundled>`,
and kills it when the window closes. Projects live in the user's app-data
folder, not next to the .exe, so uninstalling never eats anyone's work.

## Getting the installer

Windows can't be cross-built from Linux, so the .exe is produced in CI:

1. Go to the repo's **Actions** tab → **Build Windows installer** → **Run workflow**
   (or push a `v*` tag, e.g. `git tag v0.1.0 && git push origin v0.1.0`).
2. When it finishes, download the **LocalCut-Windows-installer** artifact.
3. Run the `-setup.exe`. First launch downloads the AI models once
   (~2.4GB: whisper + Qwen3-TTS); after that it's fully offline.

Requirements on the PC: Windows 10 1809+ / 11, ~8GB free disk, 8GB+ RAM.
WebView2 is embedded in the installer, so no Edge dependency surprises.

## Uninstall

Settings → Apps → LocalCut → Uninstall (the NSIS installer registers a
standard uninstaller). Project files stay in `%APPDATA%/com.localcut.app`
until you delete them yourself.

## Notes for developers

- `backend/run.py` is the frozen entry point (`--port`, `--data-dir`, `--ffmpeg-dir`).
- `backend/localcut-backend.spec` is the PyInstaller spec (torch makes it ~2GB — expected).
- `src-tauri/tauri.conf.json` — bundle config; `targets: ["nsis"]`.
- The frontend's API base is build-time (`VITE_API_BASE`); plain browser dev
  still uses relative URLs.
- First-run model downloads reuse the same chunked, resumable downloader as dev.
