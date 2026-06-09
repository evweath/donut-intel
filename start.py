#!/usr/bin/env python3
"""
Cross-platform server start script.
Works on macOS and Windows. Reads port and cert paths from config/settings.yaml.
Usage: python start.py
"""
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print('pyyaml not installed. Run: pip install -r requirements.txt')
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
    print(f'Starting prodComp on {protocol}://localhost:{port}')
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
