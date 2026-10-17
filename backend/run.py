"""Frozen entry point for the desktop (.exe) build.

`python run.py` also works for plain local runs. The Tauri launcher starts:
    localcut-backend.exe --port 8000 --data-dir <app-data> --ffmpeg-dir <dir>

PyInstaller: `pyinstaller localcut-backend.spec`
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    ap = argparse.ArgumentParser(prog="localcut-backend")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--data-dir", default=None,
                    help="project storage dir (default: backend/data)")
    ap.add_argument("--ffmpeg-dir", default=None,
                    help="dir containing ffmpeg/ffprobe binaries")
    args = ap.parse_args()

    if args.data_dir:
        os.environ["LOCALCUT_DATA_DIR"] = args.data_dir
    if args.ffmpeg_dir:
        # Workers resolve ffmpeg via shutil.which — put the bundled dir first.
        os.environ["PATH"] = args.ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    import uvicorn
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
