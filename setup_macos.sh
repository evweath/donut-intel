#!/usr/bin/env bash
# ==============================================================================
# Donut Intel Platform — macOS Setup Script (F48/F51)
# Run once: bash setup_macos.sh
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_NAME="com.donutintel.app"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
CERT_DIR="$SCRIPT_DIR/certs"
LOG_DIR="$SCRIPT_DIR/logs"
DATA_DIR="$SCRIPT_DIR/data"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
success() { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo ""
echo "  🍩  Donut Intel Platform — macOS Setup"
echo "  ======================================="
echo ""

# 1. Check Python 3.11+
info "Checking Python version..."
PYTHON=$(command -v python3 || command -v python || error "Python 3 not found. Install from https://www.python.org/downloads/")
PY_VER=$($PYTHON -c 'import sys; print(sys.version_info[:2])' 2>/dev/null)
info "Found Python: $PYTHON ($PY_VER)"
if $PYTHON -c 'import sys; exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
  success "Python 3.11+ confirmed"
else
  warn "Python 3.11+ recommended. Current version may work but is not tested."
fi

# 2. Create virtual environment
info "Setting up virtual environment..."
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
  $PYTHON -m venv "$SCRIPT_DIR/.venv"
  success "Virtual environment created at .venv"
else
  success "Virtual environment already exists"
fi
source "$SCRIPT_DIR/.venv/bin/activate"

# 3. Install Python dependencies
info "Installing Python dependencies..."
pip install --upgrade pip -q
# Use --upgrade so pip selects versions with pre-built wheels for this Python version
pip install --upgrade -r "$SCRIPT_DIR/requirements.txt" || {
  echo ""
  error "Dependency install failed. Try: pip install --upgrade -r requirements.txt"
}
success "Python dependencies installed"

# 4. Install Playwright browsers
info "Installing Playwright Chromium browser..."
python -m playwright install chromium
python -m playwright install-deps chromium 2>/dev/null || warn "install-deps failed (normal on macOS — continuing)"
success "Playwright Chromium installed"

# 5. Create required directories
info "Creating required directories..."
mkdir -p "$CERT_DIR" "$LOG_DIR" "$DATA_DIR" "$SCRIPT_DIR/exports"
success "Directories ready"

# 6. Generate self-signed certificate (F31 — HTTPS dashboard)
info "Generating self-signed TLS certificate..."
if [ ! -f "$CERT_DIR/cert.pem" ] || [ ! -f "$CERT_DIR/key.pem" ]; then
  openssl req -x509 -newkey rsa:4096 -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" \
    -days 3650 -nodes -subj "/CN=localhost/O=DonutIntel/C=US" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null
  success "TLS certificate generated (valid 10 years)"
else
  success "TLS certificate already exists"
fi

# 7. Prompt for Google Drive DB path
echo ""
echo -e "${YELLOW}  DATABASE CONFIGURATION${NC}"
echo "  By default, the database is stored at: $DATA_DIR/donut_intel.db"
echo "  For shared Google Drive access, use a path like:"
echo "  /Users/$(whoami)/Library/CloudStorage/GoogleDrive-YOUR@gmail.com/My\\ Drive/donut-intel/donut_intel.db"
echo ""
read -p "  Enter custom DB path (or press Enter to use default): " DB_PATH_INPUT
if [ -n "$DB_PATH_INPUT" ]; then
  # Update settings.yaml
  python3 - <<EOF
import yaml, sys
from pathlib import Path
config_path = Path("$SCRIPT_DIR/config/settings.yaml")
if config_path.exists():
    with open(config_path) as f:
        settings = yaml.safe_load(f) or {}
    settings.setdefault('database', {})['path'] = "$DB_PATH_INPUT"
    with open(config_path, 'w') as f:
        yaml.dump(settings, f, default_flow_style=False)
    print("  Database path updated.")
EOF
  # Create parent directory if it doesn't exist
  mkdir -p "$(dirname "$DB_PATH_INPUT")" 2>/dev/null || true
  success "Database path set to: $DB_PATH_INPUT"
else
  success "Using default database path: $DATA_DIR/donut_intel.db"
fi

# 8. Generate start.sh
info "Generating start.sh..."
cat > "$SCRIPT_DIR/start.sh" << 'STARTSCRIPT'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
cd "$SCRIPT_DIR"

PORT=$(python3 -c "import yaml; d=yaml.safe_load(open('config/settings.yaml')); print(d['app']['port'])" 2>/dev/null || echo "8743")
CERT="$SCRIPT_DIR/certs/cert.pem"
KEY="$SCRIPT_DIR/certs/key.pem"

echo "🍩 Starting Donut Intel Platform on https://localhost:$PORT"
echo "   API docs: https://localhost:$PORT/api/docs"
echo "   Press Ctrl+C to stop"
echo ""

if [ -f "$CERT" ] && [ -f "$KEY" ]; then
  uvicorn backend.app:app --host 0.0.0.0 --port "$PORT" \
    --ssl-certfile "$CERT" --ssl-keyfile "$KEY" \
    --log-level warning
else
  echo "  [WARN] No TLS cert found — running on HTTP"
  uvicorn backend.app:app --host 0.0.0.0 --port "$PORT" --log-level warning
fi
STARTSCRIPT
chmod +x "$SCRIPT_DIR/start.sh"
success "start.sh created"

# 9. Generate stop.sh
cat > "$SCRIPT_DIR/stop.sh" << 'STOPSCRIPT'
#!/usr/bin/env bash
echo "Stopping Donut Intel Platform..."
pkill -f "uvicorn backend.app:app" 2>/dev/null && echo "Stopped." || echo "No running instance found."
STOPSCRIPT
chmod +x "$SCRIPT_DIR/stop.sh"
success "stop.sh created"

# 10. Generate launchd plist for auto-start (F48)
info "Creating launchd plist for auto-start at login..."
SCRIPT_DIR_ESC="${SCRIPT_DIR//&/&amp;}"
cat > "$PLIST_SRC" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_NAME}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${SCRIPT_DIR}/.venv/bin/python</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>backend.app:app</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8743</string>
    <string>--ssl-certfile</string>
    <string>${SCRIPT_DIR}/certs/cert.pem</string>
    <string>--ssl-keyfile</string>
    <string>${SCRIPT_DIR}/certs/key.pem</string>
    <string>--log-level</string>
    <string>warning</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>
  <key>RunAtLoad</key>
  <false/>
  <key>KeepAlive</key>
  <false/>
  <key>StandardOutPath</key>
  <string>${SCRIPT_DIR}/logs/launchd_stdout.log</string>
  <key>StandardErrorPath</key>
  <string>${SCRIPT_DIR}/logs/launchd_stderr.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST
success "launchd plist created at $PLIST_SRC"

# 11. Offer to enable auto-start
echo ""
read -p "  Enable auto-start at login (launchd)? [y/N]: " AUTOSTART
if [[ "$AUTOSTART" =~ ^[Yy]$ ]]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cp "$PLIST_SRC" "$PLIST_DST"
  launchctl load "$PLIST_DST" 2>/dev/null || warn "launchctl load failed — you can run manually with start.sh"
  success "Auto-start enabled"
else
  info "Auto-start skipped. To enable later: launchctl load $PLIST_DST"
fi

# 12. Initialize database
info "Initializing database..."
python3 - << 'PYINIT'
import sys, os
sys.path.insert(0, '.')
os.chdir(os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else '.')
from backend.database.db import init_db
init_db()
print("  Database initialized successfully.")
PYINIT
success "Database ready"

# Done
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║  ✅  Setup complete!                     ║"
echo "  ╠══════════════════════════════════════════╣"
echo "  ║  Start:   ./start.sh                     ║"
echo "  ║  Stop:    ./stop.sh                      ║"
echo "  ║  CLI:     python cli.py --help           ║"
echo "  ║  Browser: https://localhost:8743          ║"
echo "  ║  Login:   admin / changeme               ║"
echo "  ║  (change password in Settings)           ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  ⚠️  Your browser will show a security warning for the self-signed cert."
echo "  Click 'Advanced' → 'Proceed to localhost' to continue."
echo ""
