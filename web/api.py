from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
from typing import Optional, List

def create_app(config: dict, db, emby_client):
    app = FastAPI(title="Lemon Emby Admin API", version="1.0.0")
    secret_key = config.get("server", {}).get("secret_key", "lemon-emby-admin-secret-key-change-me")

    async def verify_auth(x_admin_token: Optional[str] = Header(None)):
        if x_admin_token != secret_key:
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
        card_type: str = "days"
        value: int = 30
        count: int = 5

    @app.post("/api/codes/generate", dependencies=[Depends(verify_auth)])
    async def generate_codes(req: GenCodeRequest):
        count = min(req.count, 100)
        codes = []
        for _ in range(count):
            c = await db.generate_code(req.card_type, req.value, created_by=0)
            codes.append(c)
        return {"codes": codes}

    class StopSessionRequest(BaseModel):
        session_id: str
        message: str = "管理员已手动终止播放"

    @app.post("/api/sessions/kill", dependencies=[Depends(verify_auth)])
    async def kill_session(req: StopSessionRequest):
        res = await emby_client.stop_session(req.session_id, req.message)
        return {"success": res}

    return app
