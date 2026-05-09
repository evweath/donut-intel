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
