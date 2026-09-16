from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import os
import secrets
import time
import logging
from typing import Optional, Dict

logger = logging.getLogger("lemon-emby.web")

# In-memory failed auth tracking: {ip: [fail_timestamps]}
FAILED_ATTEMPTS: Dict[str, list] = {}
MAX_FAILS = 5
LOCKOUT_SECONDS = 300

def check_ip_rate_limit(client_ip: str):
    now = time.time()
    fails = FAILED_ATTEMPTS.get(client_ip, [])
    # Filter only recent fails within window
    recent_fails = [t for t in fails if now - t < LOCKOUT_SECONDS]
    FAILED_ATTEMPTS[client_ip] = recent_fails
    if len(recent_fails) >= MAX_FAILS:
        raise HTTPException(
            status_code=429,
            detail="Too many failed authentication attempts. Locked out for 5 minutes."
        )

def record_failed_attempt(client_ip: str):
    now = time.time()
    fails = FAILED_ATTEMPTS.get(client_ip, [])
    fails.append(now)
    FAILED_ATTEMPTS[client_ip] = fails

def create_app(config: dict, db, emby_client):
    app = FastAPI(title="Lemon Emby Admin API", version="1.1.0", docs_url=None, redoc_url=None)
    secret_key = config.get("server", {}).get("secret_key", "")
    
    if not secret_key or secret_key == "lemon-emby-admin-secret-key-change-me":
        raise RuntimeError(
            "Refusing to start admin API with an empty/default server.secret_key; "
            "set a strong unique secret in config.yaml"
        )

    async def verify_auth(request: Request, x_admin_token: Optional[str] = Header(None)):
        client_ip = request.client.host if request.client else "unknown"
        check_ip_rate_limit(client_ip)

        if not x_admin_token or not secrets.compare_digest(x_admin_token, secret_key):
            record_failed_attempt(client_ip)
            logger.warning(f"Unauthorized Web API access attempt from {client_ip}")
            raise HTTPException(status_code=401, detail="Unauthorized")

    # Static UI
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/api/stats", dependencies=[Depends(verify_auth)])
    async def get_stats():
        users = await db.get_all_users()
        sessions = await emby_client.get_active_sessions()
        sys_info = await emby_client.get_system_info()
        return {
            "total_users": len(users),
            "active_sessions": len(sessions),
            "server_info": sys_info,
            "sessions": sessions
        }

    @app.get("/api/users", dependencies=[Depends(verify_auth)])
    async def list_users():
        return await db.get_all_users()

    class GenCodeRequest(BaseModel):
        card_type: str = Field(default="days", pattern="^(days|points)$")
        value: int = Field(default=30, ge=1, le=3650)
        count: int = Field(default=5, ge=1, le=100)

    @app.post("/api/codes/generate", dependencies=[Depends(verify_auth)])
    async def generate_codes(req: GenCodeRequest):
        codes = []
        for _ in range(req.count):
            c = await db.generate_code(req.card_type, req.value, created_by=0)
            codes.append(c)
        return {"codes": codes}

    class StopSessionRequest(BaseModel):
        session_id: str = Field(min_length=1, max_length=128)
        message: str = Field(default="管理员已手动终止播放", max_length=200)

    @app.post("/api/sessions/kill", dependencies=[Depends(verify_auth)])
    async def kill_session(req: StopSessionRequest):
        res = await emby_client.stop_session(req.session_id, req.message)
        return {"success": res}

    return app
