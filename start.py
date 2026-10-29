#!/usr/bin/env python3
"""
Cross-platform server start script.
Works on macOS and Windows. Reads port and cert paths from config/settings.yaml.
Usage: python start.py
"""
import os
import subprocess
import sys
from pathlib import Path


def _ensure_venv() -> None:
    """Re-run this script under the project's .venv interpreter so the app's
    dependencies (uvicorn, etc.) are always found — even when the user runs
    `python start.py` with the system Python, as the Windows guide instructs."""
    root = Path(__file__).resolve().parent
    bin_dir = 'Scripts' if os.name == 'nt' else 'bin'
    exe = 'python.exe' if os.name == 'nt' else 'python'
    vpy = root / '.venv' / bin_dir / exe
    if not vpy.exists():
        return  # setup not run yet — let the import error below guide the user
    try:
        if Path(sys.executable).resolve() == vpy.resolve():
            return  # already inside the venv
    except OSError:
        return
    sys.exit(subprocess.run([str(vpy), *sys.argv]).returncode)


_ensure_venv()

try:
    import yaml
except ImportError:
    print('pyyaml not installed. Run: python setup_env.py')
    sys.exit(1)

ROOT = Path(__file__).parent


def _read_port() -> int:
    config_path = ROOT / 'config' / 'settings.yaml'
    if config_path.exists():
        cfg = yaml.safe_load(config_path.read_text(encoding='utf-8')) or {}
        return int(cfg.get('app', {}).get('port', 8743))
    return 8743


def main() -> None:
    port = _read_port()
    cert = ROOT / 'certs' / 'cert.pem'
    key = ROOT / 'certs' / 'key.pem'
    use_tls = cert.exists() and key.exists()

    protocol = 'https' if use_tls else 'http'
    print(f'Starting domainComp v3 on {protocol}://localhost:{port}')
    if not use_tls:
        print('  [WARN] No TLS certs found — running on HTTP. Run: python generate_certs.py')
    print(f'  API docs: {protocol}://localhost:{port}/api/docs')
    print('  Press Ctrl+C to stop')
    print()

    cmd = [
        sys.executable, '-m', 'uvicorn',
        'backend.app:app',
        '--host', '127.0.0.1',
        '--port', str(port),
        '--log-level', 'warning',
    ]
    if use_tls:
        cmd += ['--ssl-certfile', str(cert), '--ssl-keyfile', str(key)]

    subprocess.run(cmd, cwd=ROOT)


if __name__ == '__main__':
    main()
