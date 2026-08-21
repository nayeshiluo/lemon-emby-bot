import aiosqlite
import datetime
import secrets
import string
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger("lemon-emby.database")

class Database:
    """Async SQLite Database for Lemon Emby Manager"""
    def __init__(self, db_path: str = "lemon_emby.db"):
        self.db_path = db_path

    async def init_db(self):
        """Initialize database schema"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                emby_user_id TEXT,
                emby_username TEXT UNIQUE,
                expiry_date TEXT,
                points INTEGER DEFAULT 0,
                max_devices INTEGER DEFAULT 2,
                is_disabled INTEGER DEFAULT 0,
                last_checkin TEXT,
                created_at TEXT
            );
            """)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS codes (
                code TEXT PRIMARY KEY,
                card_type TEXT,
                value INTEGER,
                created_by INTEGER,
                used_by INTEGER,
                used_at TEXT,
                created_at TEXT
            );
            """)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                action TEXT,
                details TEXT,
                created_at TEXT
            );
            """)
            await db.commit()
            logger.info("Database initialized successfully.")

    async def get_user_by_tg(self, tg_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_by_emby_id(self, emby_user_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE emby_user_id = ?", (emby_user_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_all_users(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def create_user_record(self, tg_id: int, emby_user_id: str, emby_username: str, days: int = 30, max_devices: int = 2):
        now = datetime.datetime.now(datetime.timezone.utc)
        expiry = now + datetime.timedelta(days=days)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
            INSERT OR REPLACE INTO users (tg_id, emby_user_id, emby_username, expiry_date, points, max_devices, is_disabled, created_at)
            VALUES (?, ?, ?, ?, 0, ?, 0, ?)
            """, (tg_id, emby_user_id, emby_username, expiry.isoformat(), max_devices, now.isoformat()))
            await db.commit()

    async def extend_user_expiry(self, tg_id: int, days: int) -> Optional[datetime.datetime]:
        user = await self.get_user_by_tg(tg_id)
        if not user:
            return None
        
        now = datetime.datetime.now(datetime.timezone.utc)
        current_expiry = datetime.datetime.fromisoformat(user["expiry_date"]) if user.get("expiry_date") else now
        if current_expiry < now:
            current_expiry = now
        
        new_expiry = current_expiry + datetime.timedelta(days=days)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET expiry_date = ?, is_disabled = 0 WHERE tg_id = ?", (new_expiry.isoformat(), tg_id))
            await db.commit()
        return new_expiry

    async def update_user_status(self, tg_id: int, is_disabled: bool):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET is_disabled = ? WHERE tg_id = ?", (1 if is_disabled else 0, tg_id))
            await db.commit()

    async def user_checkin(self, tg_id: int, reward_days: int = 1, points: int = 10) -> Dict[str, Any]:
        """Process daily checkin"""
        user = await self.get_user_by_tg(tg_id)
        if not user:
            return {"success": False, "msg": "未绑定 Emby 账号"}
        
        now = datetime.datetime.now(datetime.timezone.utc)
        last_checkin = user.get("last_checkin")
        if last_checkin:
            last_date = datetime.datetime.fromisoformat(last_checkin).date()
            if last_date == now.date():
                return {"success": False, "msg": "今天已经签过到啦，明天再来吧！"}
        
        # Add days if reward_days > 0
        new_expiry = await self.extend_user_expiry(tg_id, reward_days) if reward_days > 0 else datetime.datetime.fromisoformat(user["expiry_date"])
        new_points = user.get("points", 0) + points
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET last_checkin = ?, points = ? WHERE tg_id = ?", (now.isoformat(), new_points, tg_id))
            await db.commit()
        
        return {
            "success": True,
            "reward_days": reward_days,
            "points": points,
            "total_points": new_points,
            "new_expiry": new_expiry.strftime("%Y-%m-%d %H:%M")
        }

    async def generate_code(self, card_type: str, value: int, created_by: int = 0) -> str:
        """Generate a random unique card key"""
        chars = string.ascii_uppercase + string.digits
        code = "LEMON-" + "".join(secrets.choice(chars) for _ in range(12))
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
            INSERT INTO codes (code, card_type, value, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            """, (code, card_type, value, created_by, now))
            await db.commit()
        return code

    async def redeem_code(self, tg_id: int, code: str) -> Dict[str, Any]:
        """Redeem a card key for a user"""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM codes WHERE code = ?", (code,)) as cursor:
                card = await cursor.fetchone()
                if not card:
                    return {"success": False, "msg": "无效的兑换码"}
                card = dict(card)
                if card.get("used_by"):
                    return {"success": False, "msg": "该兑换码已被使用"}
                
                # Mark as used
                await db.execute("UPDATE codes SET used_by = ?, used_at = ? WHERE code = ?", (tg_id, now, code))
                await db.commit()

        card_type = card.get("card_type")
        val = card.get("value", 0)
        
        if card_type == "days":
            new_exp = await self.extend_user_expiry(tg_id, val)
            return {"success": True, "type": "days", "value": val, "new_expiry": new_exp.strftime("%Y-%m-%d %H:%M") if new_exp else ""}
        elif card_type == "points":
            user = await self.get_user_by_tg(tg_id)
            new_pts = (user.get("points", 0) if user else 0) + val
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (new_pts, tg_id))
                await db.commit()
            return {"success": True, "type": "points", "value": val, "total_points": new_pts}
        
        return {"success": True, "type": card_type, "value": val}

    async def log_action(self, tg_id: int, action: str, details: str = ""):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO logs (tg_id, action, details, created_at) VALUES (?, ?, ?, ?)", (tg_id, action, details, now))
            await db.commit()
