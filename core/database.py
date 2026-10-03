import aiosqlite
import asyncio
import datetime
from contextlib import asynccontextmanager
import secrets
import random
import string
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger("lemon-emby.database")

class Database:
    """Async SQLite Database for Lemon Emby Manager with Atomic Transactions & Hardened Security"""
    def __init__(self, db_path: str = "lemon_emby.db"):
        self.db_path = db_path
        self._account_locks: Dict[int, asyncio.Lock] = {}
        self._account_lock_users: Dict[int, int] = {}

    @asynccontextmanager
    async def account_lock(self, tg_id: int):
        """Serialize per-account Emby and database changes in this process."""
        key = int(tg_id)
        lock = self._account_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._account_locks[key] = lock
        self._account_lock_users[key] = self._account_lock_users.get(key, 0) + 1
        try:
            async with lock:
                yield
        finally:
            users = self._account_lock_users.get(key, 1) - 1
            if users <= 0:
                self._account_lock_users.pop(key, None)
                if self._account_locks.get(key) is lock:
                    self._account_locks.pop(key, None)
            else:
                self._account_lock_users[key] = users

    @staticmethod
    def as_utc(value: Optional[str]) -> Optional[datetime.datetime]:
        """Parse stored timestamps consistently, including legacy naive values."""
        if not value:
            return None
        parsed = datetime.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)

    async def init_db(self):
        """Initialize database schema with WAL mode for concurrency"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                emby_user_id TEXT,
                emby_username TEXT UNIQUE,
                expiry_date TEXT,
                points INTEGER DEFAULT 0,
                max_devices INTEGER DEFAULT 2,
                is_disabled INTEGER DEFAULT 0,
                disabled_reason TEXT,
                last_checkin TEXT,
                created_at TEXT
            );
            """)
            async with db.execute("PRAGMA table_info(users)") as cursor:
                user_columns = {row[1] for row in await cursor.fetchall()}
            if "disabled_reason" not in user_columns:
                # Existing disabled users remain unknown until an admin reviews them;
                # never infer that a prior manual ban was only an expiry suspension.
                await db.execute("ALTER TABLE users ADD COLUMN disabled_reason TEXT")
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
            logger.info("Database initialized successfully with WAL mode.")

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

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE LOWER(emby_username) = LOWER(?)", (username,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]:
        if identifier.isdigit() or (identifier.startswith("-") and identifier[1:].isdigit()):
            u = await self.get_user_by_tg(int(identifier))
            if u:
                return u
        return await self.get_user_by_username(identifier)

    async def get_all_users(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def create_user_record(self, tg_id: int, emby_user_id: str, emby_username: str, days: int = 30, max_devices: int = 2) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        expiry = now + datetime.timedelta(days=days)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
            INSERT INTO users (tg_id, emby_user_id, emby_username, expiry_date, points, max_devices, is_disabled, created_at)
            VALUES (?, ?, ?, ?, 0, ?, 0, ?)
            ON CONFLICT DO NOTHING
            """, (tg_id, emby_user_id, emby_username, expiry.isoformat(), max_devices, now.isoformat()))
            await db.commit()
            return cursor.rowcount == 1

    async def extend_user_expiry(self, tg_id: int, days: int) -> Optional[datetime.datetime]:
        now = datetime.datetime.now(datetime.timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT expiry_date FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                user = await cursor.fetchone()
            if not user:
                await db.rollback()
                return None

            current_expiry = self.as_utc(user["expiry_date"]) or now
            new_expiry = max(current_expiry, now) + datetime.timedelta(days=days)
            await db.execute(
                "UPDATE users SET expiry_date = ? WHERE tg_id = ?",
                (new_expiry.isoformat(), tg_id),
            )
            await db.commit()
        return new_expiry

    async def add_user_points(self, tg_id: int, delta: int) -> int:
        """Atomic addition of user points"""
        async with aiosqlite.connect(self.db_path) as db:
            if delta < 0:
                await db.execute("UPDATE users SET points = MAX(0, points + ?) WHERE tg_id = ?", (delta, tg_id))
            else:
                await db.execute("UPDATE users SET points = points + ? WHERE tg_id = ?", (delta, tg_id))
            await db.commit()
        user = await self.get_user_by_tg(tg_id)
        return user.get("points", 0) if user else 0

    async def deduct_user_points_atomic(self, tg_id: int, amount: int) -> bool:
        """Deduct points with atomic balance check (Prevents Race Condition / Double-Spend)"""
        if amount <= 0:
            return False
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("UPDATE users SET points = points - ? WHERE tg_id = ? AND points >= ?", (amount, tg_id, amount))
            await db.commit()
            return cursor.rowcount > 0

    async def update_user_status(self, tg_id: int, is_disabled: bool, reason: Optional[str] = None):
        async with aiosqlite.connect(self.db_path) as db:
            if is_disabled:
                await db.execute(
                    "UPDATE users SET is_disabled = 1, disabled_reason = ? WHERE tg_id = ?",
                    (reason or "unknown", tg_id),
                )
            else:
                await db.execute(
                    "UPDATE users SET is_disabled = 0, disabled_reason = NULL WHERE tg_id = ?",
                    (tg_id,),
                )
            await db.commit()

    async def delete_user_record(self, tg_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM users WHERE tg_id = ?", (tg_id,))
            await db.commit()

    async def user_checkin(self, tg_id: int, reward_days: int = 1, points: int = 10) -> Dict[str, Any]:
        now = datetime.datetime.now(datetime.timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                user = await cursor.fetchone()
            if not user:
                await db.rollback()
                return {"success": False, "msg": "未绑定 Emby 账号"}

            last_checkin = self.as_utc(user["last_checkin"])
            if last_checkin and last_checkin.date() == now.date():
                await db.rollback()
                return {"success": False, "msg": "今天已经签过到啦，明天再来吧！"}

            current_expiry = self.as_utc(user["expiry_date"]) or now
            new_expiry = max(current_expiry, now) + datetime.timedelta(days=reward_days) if reward_days > 0 else current_expiry
            await db.execute(
                "UPDATE users SET last_checkin = ?, points = points + ?, expiry_date = ? WHERE tg_id = ?",
                (now.isoformat(), points, new_expiry.isoformat(), tg_id),
            )
            new_points = user["points"] + points
            await db.commit()

        return {
            "success": True,
            "reward_days": reward_days,
            "points": points,
            "total_points": new_points,
            "new_expiry": new_expiry.strftime("%Y-%m-%d %H:%M")
        }

    async def exchange_item(self, tg_id: int, item_key: str) -> Dict[str, Any]:
        """Exchange points and deliver the item in one transaction."""
        shop_items = {
            "days_7": {"name": "7天观影时长", "cost": 50, "type": "days", "val": 7},
            "days_30": {"name": "30天观影时长", "cost": 180, "type": "days", "val": 30},
            "days_90": {"name": "90天观影时长", "cost": 500, "type": "days", "val": 90},
            "dev_plus1": {"name": "并发设备限制 +1 台", "cost": 300, "type": "dev", "val": 1}
        }
        item = shop_items.get(item_key)
        if not item:
            return {"success": False, "msg": "无效的商品"}

        cost = item["cost"]
        now = datetime.datetime.now(datetime.timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                user = await cursor.fetchone()
            if not user:
                await db.rollback()
                return {"success": False, "msg": "未绑定 Emby 账号"}

            if user["points"] < cost:
                await db.rollback()
                return {"success": False, "msg": f"积分不足！需要 {cost} 积分，您当前仅有 {user['points']} 积分。"}

            await db.execute("UPDATE users SET points = points - ? WHERE tg_id = ?", (cost, tg_id))
            if item["type"] == "days":
                current_expiry = self.as_utc(user["expiry_date"]) or now
                new_expiry = max(current_expiry, now) + datetime.timedelta(days=item["val"])
                await db.execute(
                    "UPDATE users SET expiry_date = ? WHERE tg_id = ?",
                    (new_expiry.isoformat(), tg_id),
                )
                details = f"到期时间已延长至: {new_expiry.strftime('%Y-%m-%d %H:%M')}"
            else:
                await db.execute("UPDATE users SET max_devices = max_devices + ? WHERE tg_id = ?", (item["val"], tg_id))
                async with db.execute("SELECT max_devices FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                    updated = await cursor.fetchone()
                details = f"允许最大并发设备数已提升至: {updated['max_devices']} 台"

            async with db.execute("SELECT points FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                updated_points = await cursor.fetchone()
            await db.commit()

        return {
            "success": True,
            "item_name": item["name"],
            "cost": cost,
            "remaining_points": updated_points["points"],
            "details": details,
        }

    async def lottery_draw(self, tg_id: int, cost: int = 20) -> Dict[str, Any]:
        """Charge the draw and apply its prize as one transaction."""
        if cost <= 0:
            return {"success": False, "msg": "抽奖积分必须大于 0"}

        now = datetime.datetime.now(datetime.timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                user = await cursor.fetchone()
            if not user:
                await db.rollback()
                return {"success": False, "msg": "未绑定 Emby 账号"}
            if user["points"] < cost:
                await db.rollback()
                return {"success": False, "msg": f"抽奖需要 {cost} 积分，您当前积分不足！"}

            await db.execute("UPDATE users SET points = points - ? WHERE tg_id = ?", (cost, tg_id))
            roll = random.random() * 100
            if roll < 5:
                await db.execute("UPDATE users SET max_devices = max_devices + 1 WHERE tg_id = ?", (tg_id,))
                async with db.execute("SELECT max_devices FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                    new_devs = (await cursor.fetchone())["max_devices"]
                prize = {"type": "grand", "msg": f"🎉 欧皇降临！抽中【并发设备 +1 台】（当前上限: {new_devs} 台）"}
            elif roll < 45:
                reward_days = 7 if roll < 20 else 3
                current_expiry = self.as_utc(user["expiry_date"]) or now
                new_exp = max(current_expiry, now) + datetime.timedelta(days=reward_days)
                await db.execute("UPDATE users SET expiry_date = ? WHERE tg_id = ?", (new_exp.isoformat(), tg_id))
                if reward_days == 7:
                    prize = {"type": "days", "msg": f"🎁 大吉！抽中【7天观影时长】（新到期: {new_exp.strftime('%Y-%m-%d')}）"}
                else:
                    prize = {"type": "days", "msg": f"✨ 中奖！抽中【3天观影时长】（新到期: {new_exp.strftime('%Y-%m-%d')}）"}
            elif roll < 75:
                await db.execute("UPDATE users SET points = points + 35 WHERE tg_id = ?", (tg_id,))
                prize = {"type": "points", "msg": "💰 积分红包！抽中【35 积分】（净赚 15 积分）"}
            else:
                prize = {"type": "none", "msg": "☕ 差点就中了！获得了【赛博安慰奖：功德 +1】"}

            async with db.execute("SELECT points FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                prize["remaining_points"] = (await cursor.fetchone())["points"]
            await db.commit()

        prize["success"] = True
        return prize

    async def game_dice_bot(self, tg_id: int, bet: int) -> Dict[str, Any]:
        """Resolve a PvE dice bet and its payout in one transaction."""
        if bet <= 0:
            return {"success": False, "msg": "押注积分必须大于 0"}

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT points FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                user = await cursor.fetchone()
            if not user:
                await db.rollback()
                return {"success": False, "msg": "未绑定 Emby 账号"}
            if user["points"] < bet:
                await db.rollback()
                return {"success": False, "msg": f"积分不足！您当前仅有 {user['points']} 积分"}

            user_roll = random.randint(1, 6)
            bot_roll = random.randint(1, 6)
            if user_roll > bot_roll:
                outcome = "win"
                res_str = f"🎉 <b>您赢了！</b> 赢得 <b>+{bet}</b> 积分！"
                payout = bet * 2
            elif user_roll < bot_roll:
                outcome = "lose"
                res_str = f"💥 <b>您输了！</b> 损失 <b>-{bet}</b> 积分！"
                payout = 0
            else:
                outcome = "tie"
                res_str = "🤝 <b>平局！</b> 积分已全额退回。"
                payout = bet

            await db.execute("UPDATE users SET points = points - ? WHERE tg_id = ?", (bet, tg_id))
            if payout:
                await db.execute("UPDATE users SET points = points + ? WHERE tg_id = ?", (payout, tg_id))
            async with db.execute("SELECT points FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                remaining_points = (await cursor.fetchone())["points"]
            await db.commit()

        return {
            "success": True,
            "user_roll": user_roll,
            "bot_roll": bot_roll,
            "outcome": outcome,
            "result_str": res_str,
            "remaining_points": remaining_points,
        }

    async def game_rob(self, from_tg: int, to_tg: int) -> Dict[str, Any]:
        """Resolve a robbery, both balance changes, and its audit log atomically."""
        if from_tg == to_tg:
            return {"success": False, "msg": "你不能打劫你自己！"}

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT points FROM users WHERE tg_id = ?", (from_tg,)) as cursor:
                u_from = await cursor.fetchone()
            async with db.execute("SELECT points, emby_username FROM users WHERE tg_id = ?", (to_tg,)) as cursor:
                u_to = await cursor.fetchone()
            if not u_from:
                await db.rollback()
                return {"success": False, "msg": "打劫者未绑定 Emby 账号"}
            if not u_to:
                await db.rollback()
                return {"success": False, "msg": "目标群友未绑定 Emby 账号，身无分文！"}

            from_pts, to_pts = u_from["points"], u_to["points"]
            if from_pts < 15:
                await db.rollback()
                return {"success": False, "msg": "打劫需要至少 15 积分作为行动保证金！"}
            if to_pts < 30:
                await db.rollback()
                return {"success": False, "msg": f"目标群友 <code>{u_to['emby_username']}</code> 积分过低（<30），触发新手保护机制！"}

            if random.random() < 0.45:
                percent = random.randint(10, 25) / 100.0
                robbed_amount = min(80, max(5, int(to_pts * percent)))
                await db.execute("UPDATE users SET points = points - ? WHERE tg_id = ?", (robbed_amount, to_tg))
                await db.execute("UPDATE users SET points = points + ? WHERE tg_id = ?", (robbed_amount, from_tg))
                await db.execute(
                    "INSERT INTO logs (tg_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                    (from_tg, "ROB_SUCCESS", f"Robbed {robbed_amount} pts from TG:{to_tg}", now),
                )
                result = {"success": True, "status": "win", "robbed_amount": robbed_amount, "victim_name": u_to["emby_username"]}
            else:
                penalty = 15
                await db.execute("UPDATE users SET points = points - ? WHERE tg_id = ?", (penalty, from_tg))
                await db.execute("UPDATE users SET points = points + ? WHERE tg_id = ?", (penalty, to_tg))
                await db.execute(
                    "INSERT INTO logs (tg_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                    (from_tg, "ROB_FAIL", f"Failed robbing TG:{to_tg}, paid {penalty} pts penalty", now),
                )
                result = {"success": True, "status": "lose", "penalty": penalty, "victim_name": u_to["emby_username"]}
            await db.commit()
            return result

    async def game_pvp_dice_resolve(self, u1_tg: int, u2_tg: int, bet: int) -> Dict[str, Any]:
        """Lock both stakes, roll, and settle a PvP game atomically."""
        if bet <= 0:
            return {"success": False, "msg": "押注积分必须大于 0"}
        if u1_tg == u2_tg:
            return {"success": False, "msg": "不能与自己进行决斗"}

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT points, emby_username FROM users WHERE tg_id = ?", (u1_tg,)) as cursor:
                u1 = await cursor.fetchone()
            async with db.execute("SELECT points, emby_username FROM users WHERE tg_id = ?", (u2_tg,)) as cursor:
                u2 = await cursor.fetchone()
            if not u1 or not u2:
                await db.rollback()
                return {"success": False, "msg": "双方均需绑定 Emby 账号"}
            if u1["points"] < bet:
                await db.rollback()
                return {"success": False, "msg": f"发起者 <code>{u1['emby_username']}</code> 积分不足！"}
            if u2["points"] < bet:
                await db.rollback()
                return {"success": False, "msg": f"应战者 <code>{u2['emby_username']}</code> 积分不足！"}

            await db.execute("UPDATE users SET points = points - ? WHERE tg_id IN (?, ?)", (bet, u1_tg, u2_tg))
            u1_roll = random.randint(1, 6)
            u2_roll = random.randint(1, 6)
            if u1_roll > u2_roll:
                await db.execute("UPDATE users SET points = points + ? WHERE tg_id = ?", (bet * 2, u1_tg))
                outcome, winner_name = "u1_win", u1["emby_username"]
            elif u2_roll > u1_roll:
                await db.execute("UPDATE users SET points = points + ? WHERE tg_id = ?", (bet * 2, u2_tg))
                outcome, winner_name = "u2_win", u2["emby_username"]
            else:
                await db.execute("UPDATE users SET points = points + ? WHERE tg_id IN (?, ?)", (bet, u1_tg, u2_tg))
                outcome, winner_name = "tie", None
            await db.commit()

        return {
            "success": True,
            "outcome": outcome,
            "u1_roll": u1_roll,
            "u2_roll": u2_roll,
            "u1_name": u1["emby_username"],
            "u2_name": u2["emby_username"],
            "winner_name": winner_name,
            "bet": bet,
        }

    async def transfer_points(self, from_tg: int, to_tg: int, amount: int) -> Dict[str, Any]:
        """Transfer points and write its audit log in one transaction."""
        if amount <= 0:
            return {"success": False, "msg": "转账积分必须大于 0"}
        if from_tg == to_tg:
            return {"success": False, "msg": "不能给自己转账"}

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT points FROM users WHERE tg_id = ?", (from_tg,)) as cursor:
                u_from = await cursor.fetchone()
            if not u_from:
                await db.rollback()
                return {"success": False, "msg": "转账方未绑定 Emby 账号"}
            async with db.execute("SELECT emby_username FROM users WHERE tg_id = ?", (to_tg,)) as cursor:
                u_to = await cursor.fetchone()
            if not u_to:
                await db.rollback()
                return {"success": False, "msg": "收款方未绑定 Emby 账号"}
            if u_from["points"] < amount:
                await db.rollback()
                return {"success": False, "msg": f"您的积分不足！当前仅有 {u_from['points']} 积分"}

            await db.execute("UPDATE users SET points = points - ? WHERE tg_id = ?", (amount, from_tg))
            await db.execute("UPDATE users SET points = points + ? WHERE tg_id = ?", (amount, to_tg))
            await db.execute(
                "INSERT INTO logs (tg_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                (from_tg, "TRANSFER_POINTS", f"Sent {amount} pts to TG:{to_tg}", now),
            )
            async with db.execute("SELECT points FROM users WHERE tg_id = ?", (from_tg,)) as cursor:
                from_remaining = (await cursor.fetchone())["points"]
            await db.commit()

        return {
            "success": True,
            "amount": amount,
            "from_remaining": from_remaining,
            "to_username": u_to["emby_username"]
        }

    async def get_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY points DESC LIMIT ?", (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def generate_code(self, card_type: str, value: int, created_by: int = 0) -> str:
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
        """Validate the account, consume the code, and grant its value atomically."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                user = await cursor.fetchone()
            if not user:
                await db.rollback()
                return {"success": False, "msg": "请先绑定 Emby 账号后再兑换"}

            async with db.execute("SELECT * FROM codes WHERE code = ?", (code,)) as cursor:
                card = await cursor.fetchone()
                if not card:
                    await db.rollback()
                    return {"success": False, "msg": "无效的兑换码"}
                card = dict(card)
                if card.get("used_by") is not None:
                    await db.rollback()
                    return {"success": False, "msg": "该兑换码已被使用"}

            card_type = card.get("card_type")
            val = card.get("value", 0)
            if card_type not in ("days", "points") or not isinstance(val, int) or val <= 0:
                await db.rollback()
                return {"success": False, "msg": "兑换码数据无效，请联系管理员"}

            cursor = await db.execute("UPDATE codes SET used_by = ?, used_at = ? WHERE code = ? AND used_by IS NULL", (tg_id, now, code))
            if cursor.rowcount == 0:
                await db.rollback()
                return {"success": False, "msg": "该兑换码刚已被其他请求使用！"}

            result = {"success": True, "type": card_type, "value": val}
            if card_type == "days":
                current_expiry = self.as_utc(user["expiry_date"]) or datetime.datetime.now(datetime.timezone.utc)
                new_expiry = max(current_expiry, datetime.datetime.now(datetime.timezone.utc)) + datetime.timedelta(days=val)
                await db.execute(
                    "UPDATE users SET expiry_date = ? WHERE tg_id = ?",
                    (new_expiry.isoformat(), tg_id),
                )
                result["new_expiry"] = new_expiry.strftime("%Y-%m-%d %H:%M")
            else:
                await db.execute("UPDATE users SET points = points + ? WHERE tg_id = ?", (val, tg_id))
                async with db.execute("SELECT points FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                    updated = await cursor.fetchone()
                result["total_points"] = updated["points"]

            await db.commit()
            return result

    async def log_action(self, tg_id: int, action: str, details: str = ""):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO logs (tg_id, action, details, created_at) VALUES (?, ?, ?, ?)", (tg_id, action, details, now))
            await db.commit()
