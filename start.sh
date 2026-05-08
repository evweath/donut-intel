#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
cd "$SCRIPT_DIR"

PORT=$(python3 -c "import yaml; d=yaml.safe_load(open('config/settings.yaml')); print(d['app']['port'])" 2>/dev/null || echo "8743")
HTTP_PORT=$((PORT - 1))
CERT="$SCRIPT_DIR/certs/cert.pem"
KEY="$SCRIPT_DIR/certs/key.pem"

cleanup() {
    kill "$REDIRECT_PID" 2>/dev/null
    exit
}
trap cleanup INT TERM

if [ -f "$CERT" ] && [ -f "$KEY" ]; then
  echo "Starting Donut Intel Platform on https://localhost:$PORT"
  echo "   HTTP redirect:  http://localhost:$HTTP_PORT -> https://localhost:$PORT"
  echo "   API docs:       https://localhost:$PORT/api/docs"
  echo "   Press Ctrl+C to stop"
  echo ""

  python3 -c "
import http.server
class R(http.server.BaseHTTPRequestHandler):
    def redirect(self):
        self.send_response(302)
        self.send_header('Location', 'https://localhost:${PORT}' + self.path)
        self.end_headers()
    do_GET = do_POST = do_HEAD = redirect
    def log_message(self, *a): pass
http.server.HTTPServer(('0.0.0.0', ${HTTP_PORT}), R).serve_forever()
" &
  REDIRECT_PID=$!

  uvicorn backend.app:app --host 0.0.0.0 --port "$PORT" \
    --ssl-certfile "$CERT" --ssl-keyfile "$KEY" \
    --log-level warning
else
  echo "  [WARN] No TLS cert found — running on HTTP"
  uvicorn backend.app:app --host 0.0.0.0 --port "$PORT" --log-level warning
fi
