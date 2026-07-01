#!/usr/bin/env python3
"""
Cross-platform server stop script.
Works on macOS and Windows. Uses psutil to find and terminate server processes.
Usage: python stop.py
"""
import os
import subprocess
import sys
from pathlib import Path


def _ensure_venv() -> None:
    """Re-run under the project's .venv interpreter so psutil is available even
    when launched with the system Python (as the Windows guide instructs)."""
    root = Path(__file__).resolve().parent
    bin_dir = 'Scripts' if os.name == 'nt' else 'bin'
    exe = 'python.exe' if os.name == 'nt' else 'python'
    vpy = root / '.venv' / bin_dir / exe
    if not vpy.exists():
        return
    try:
        if Path(sys.executable).resolve() == vpy.resolve():
            return
    except OSError:
        return
    sys.exit(subprocess.run([str(vpy), *sys.argv]).returncode)


_ensure_venv()

try:
    import psutil
except ImportError:
    print('psutil not installed. Run: python setup_env.py')
    sys.exit(1)

_PATTERNS = [
    'uvicorn backend.app:app',
    'chrome-headless-shell',
    # Playwright node driver (path separator differs by platform)
    'playwright/driver/node',
    'playwright\\driver\\node',
]


def main() -> None:
    killed = 0
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.cmdline())
            if any(p in cmdline for p in _PATTERNS):
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if killed:
        print(f'Stopped {killed} process(es).')
    else:
        print('No running instance found.')


if __name__ == '__main__':
    main()
