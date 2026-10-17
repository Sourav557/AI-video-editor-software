# PyInstaller spec for the LocalCut backend (Windows .exe sidecar).
# Build:  cd backend && pyinstaller localcut-backend.spec --noconfirm
# Output: dist/localcut-backend.exe  -> staged as the Tauri sidecar.
# NOTE: torch makes this bundle large (~2GB). That is expected and fine —
# the installer is downloaded once; everything then runs offline.

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # web stack
        'uvicorn', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
        'fastapi', 'starlette', 'pydantic', 'multipart',
        # transcription
        'faster_whisper', 'ctranslate2', 'onnxruntime', 'tokenizers',
        # TTS
        'qwen_tts', 'torch', 'soundfile', 'numpy',
        # misc
        'requests', 'PIL',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='localcut-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX on torch binaries causes more trouble than it saves
    console=True,  # keep a console so backend logs are visible/debuggable
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
