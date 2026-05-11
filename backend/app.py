"""
Donut Intel Platform — Main FastAPI application.
HTTPS via self-signed cert (F31), session auth (F38), static frontend serving.
Scheduler (F43), Webhooks (F72) wired at startup.
"""
import json
import logging
import logging.handlers
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from backend.config import config
from backend.database.db import init_db
from backend.api.routes import router

# ---------------------------------------------------------------------------
# Logging (F59)
# ---------------------------------------------------------------------------

def setup_logging():
    level_str = config.get("logging", "level", default="INFO")
    level = getattr(logging, level_str.upper(), logging.INFO)
    log_path = config.get("logging", "log_path", default="./logs/donut_intel.log")
    log_path_obj = Path(log_path).expanduser()
    if not log_path_obj.is_absolute():
        log_path_obj = (Path(__file__).parent.parent / log_path).resolve()
    log_path_obj.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(level)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    if config.get("logging", "log_to_file", default=True):
        max_mb = config.get("logging", "max_file_size_mb", default=10)
        backup_count = config.get("logging", "backup_count", default=5)
        fh = logging.handlers.RotatingFileHandler(
            log_path_obj, maxBytes=max_mb * 1024 * 1024,
            backupCount=backup_count, encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(formatter)
        root.addHandler(fh)

    for noisy in ["playwright", "urllib3", "httpx", "asyncio", "apscheduler", "ddgs"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)

ERROR_LOG = Path(__file__).parent.parent / "logs" / "errors.jsonl"

def capture_error(exc: BaseException, context: str = "") -> None:
    """Append a structured error record to logs/errors.jsonl."""
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.utcnow().isoformat(),
            "context": context,
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

app = FastAPI(
    title="Donut Intel Platform",
    description="Product intelligence and competitor pricing for donut/bakery supply market",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    capture_error(exc, context=f"{request.method} {request.url.path}")
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if config.get("app", "debug", default=False) else [
        "http://localhost:8743", "https://localhost:8743"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth middleware (F38)
# ---------------------------------------------------------------------------

AUTH_ENABLED = config.get("auth", "enabled", default=True)
_AUTH_USERNAME = config.get("auth", "username", default="admin")
_AUTH_PASSWORD = config.get("auth", "password", default="changeme")

PUBLIC_PATHS = {"/api/auth/login", "/api/auth/logout", "/api/auth/status"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not AUTH_ENABLED:
        return await call_next(request)
    path = request.url.path
    if (
        path in PUBLIC_PATHS
        or path.startswith("/static/")
        or path in ("/", "/favicon.ico")
        or path.endswith(".html")
        or path.endswith(".js")
        or path.endswith(".css")
    ):
        return await call_next(request)
    if not request.session.get("authenticated"):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=config.get("app", "secret_key", default="CHANGE_ME_PLEASE"),
    max_age=config.get("auth", "session_timeout_minutes", default=60) * 60,
)


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    if req.username == _AUTH_USERNAME and req.password == _AUTH_PASSWORD:
        request.session["authenticated"] = True
        request.session["username"] = req.username
        return {"status": "ok", "username": req.username}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/api/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"status": "logged_out"}


@app.get("/api/auth/status")
async def auth_status(request: Request):
    return {
        "authenticated": bool(request.session.get("authenticated")),
        "username": request.session.get("username"),
        "auth_enabled": AUTH_ENABLED,
    }


# ---------------------------------------------------------------------------
# Webhook dispatcher (F72)
# ---------------------------------------------------------------------------

async def _dispatch_webhook(event: str, payload: dict):
    """Fire-and-forget webhook call."""
    webhook_url = config.get("webhook", "url", default="")
    enabled_events = config.get("webhook", "events", default=[])
    if not webhook_url or event not in enabled_events:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json={"event": event, "timestamp": __import__("datetime").datetime.utcnow().isoformat(), **payload})
        logger.info(f"Webhook fired: {event} → {webhook_url}")
    except Exception as exc:
        logger.warning(f"Webhook failed ({event}): {exc}")


# ---------------------------------------------------------------------------
# Include API router
# ---------------------------------------------------------------------------

app.include_router(router)

# ---------------------------------------------------------------------------
# Static files and SPA (F31)
# ---------------------------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount("/static/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
    app.mount("/static/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")


@app.get("/", response_class=HTMLResponse)
@app.get("/{path:path}", response_class=HTMLResponse)
async def serve_spa(request: Request, path: str = ""):
    if path.startswith("api/") or path.startswith("ws/"):
        raise HTTPException(status_code=404)
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse("<h1>Frontend not found. Check frontend/index.html</h1>", status_code=500)


# ---------------------------------------------------------------------------
# Startup / Shutdown (F43, F45)
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup():
    logger.info("Donut Intel Platform v2.0 starting up...")
    init_db()
    logger.info(f"Database ready at: {config.db_path()}")

    # Start APScheduler
    try:
        from backend.scheduler.scheduler import start_scheduler
        start_scheduler(app=app)
        logger.info("Scheduler started")
    except Exception as exc:
        logger.warning(f"Scheduler failed to start: {exc}")

    port = config.get("app", "port", default=8743)
    logger.info(f"Dashboard: https://localhost:{port}")
    logger.info(f"API docs:  https://localhost:{port}/api/docs")


@app.on_event("shutdown")
async def on_shutdown():
    try:
        from backend.scheduler.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    logger.info("Donut Intel Platform shut down.")
