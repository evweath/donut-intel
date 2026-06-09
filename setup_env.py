#!/usr/bin/env python3
"""
Cross-platform setup script for prodComp.
Works on macOS and Windows.
Usage: python setup_env.py

For macOS auto-start (LaunchAgent), use setup_macos.sh instead.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
VENV = ROOT / '.venv'
BIN = VENV / ('Scripts' if sys.platform == 'win32' else 'bin')


def run(cmd: list) -> None:
    print(f'  $ {" ".join(str(c) for c in cmd)}')
    subprocess.run(cmd, check=True, cwd=ROOT)


def step(n: int, total: int, label: str) -> None:
    print(f'\n[{n}/{total}] {label}')


def create_dirs() -> None:
    for d in ('data', 'logs', 'exports', 'certs'):
        (ROOT / d).mkdir(exist_ok=True)


def create_venv() -> None:
    if VENV.exists():
        print('  Virtual environment already exists — skipping.')
        return
    run([sys.executable, '-m', 'venv', str(VENV)])


def install_deps() -> None:
    run([str(BIN / 'pip'), 'install', '--upgrade', 'pip'])
    run([str(BIN / 'pip'), 'install', '-r', 'requirements.txt'])


def install_playwright() -> None:
    run([str(BIN / 'python'), '-m', 'playwright', 'install', 'chromium', 'firefox'])


def generate_certs() -> None:
    cert = ROOT / 'certs' / 'cert.pem'
    key = ROOT / 'certs' / 'key.pem'
    if cert.exists() and key.exists():
        print('  Certificates already exist — skipping.')
        return
    run([str(BIN / 'python'), str(ROOT / 'generate_certs.py')])


def main() -> None:
    print('prodComp — Setup')
    print('=' * 40)

    total = 5
    step(1, total, 'Creating project directories')
    create_dirs()

    step(2, total, 'Creating virtual environment')
    create_venv()

    step(3, total, 'Installing Python dependencies')
    install_deps()

    step(4, total, 'Installing Playwright browser engines')
    install_playwright()

    step(5, total, 'Generating TLS certificates')
    generate_certs()

    print('\nSetup complete!')
    print('  Start:  python start.py')
    print('  Stop:   python stop.py')
    if sys.platform != 'win32':
        print('  Or use: ./start.sh / ./stop.sh')


if __name__ == '__main__':
    main()
