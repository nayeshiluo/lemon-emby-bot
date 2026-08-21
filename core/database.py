import aiosqlite
import datetime
import secrets
import random
import string
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger("lemon-emby.database")

class Database:
    """Async SQLite Database for Lemon Emby Manager with Full Economy & Mini-Games"""
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

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE LOWER(emby_username) = LOWER(?)", (username,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Look up by TG ID (if integer) or username"""
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

    async def add_user_points(self, tg_id: int, delta: int) -> int:
        """Add or subtract user points, returns new total"""
        user = await self.get_user_by_tg(tg_id)
        current = user.get("points", 0) if user else 0
        new_pts = max(0, current + delta)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (new_pts, tg_id))
            await db.commit()
        return new_pts

    async def update_user_status(self, tg_id: int, is_disabled: bool):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET is_disabled = ? WHERE tg_id = ?", (1 if is_disabled else 0, tg_id))
            await db.commit()

    async def delete_user_record(self, tg_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM users WHERE tg_id = ?", (tg_id,))
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

    async def exchange_item(self, tg_id: int, item_key: str) -> Dict[str, Any]:
        """Points Shop Exchange items"""
        shop_items = {
            "days_7": {"name": "7天观影时长", "cost": 50, "type": "days", "val": 7},
            "days_30": {"name": "30天观影时长", "cost": 180, "type": "days", "val": 30},
            "days_90": {"name": "90天观影时长", "cost": 500, "type": "days", "val": 90},
            "dev_plus1": {"name": "并发设备限制 +1 台", "cost": 300, "type": "dev", "val": 1}
        }
        item = shop_items.get(item_key)
        if not item:
            return {"success": False, "msg": "无效的商品"}

        user = await self.get_user_by_tg(tg_id)
        if not user:
            return {"success": False, "msg": "未绑定 Emby 账号"}

        points = user.get("points", 0)
        cost = item["cost"]
        if points < cost:
            return {"success": False, "msg": f"积分不足！需要 {cost} 积分，您当前仅有 {points} 积分。"}

        new_points = points - cost
        async with aiosqlite.connect(self.db_path) as db:
            if item["type"] == "days":
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (new_points, tg_id))
                await db.commit()
                new_exp = await self.extend_user_expiry(tg_id, item["val"])
                return {
                    "success": True,
                    "item_name": item["name"],
                    "cost": cost,
                    "remaining_points": new_points,
                    "details": f"到期时间已延长至: {new_exp.strftime('%Y-%m-%d %H:%M')}"
                }
            elif item["type"] == "dev":
                new_devs = user.get("max_devices", 2) + item["val"]
                await db.execute("UPDATE users SET points = ?, max_devices = ? WHERE tg_id = ?", (new_points, new_devs, tg_id))
                await db.commit()
                return {
                    "success": True,
                    "item_name": item["name"],
                    "cost": cost,
                    "remaining_points": new_points,
                    "details": f"允许最大并发设备数已提升至: {new_devs} 台"
                }

        return {"success": False, "msg": "未知兑换类型"}

    async def lottery_draw(self, tg_id: int, cost: int = 20) -> Dict[str, Any]:
        """Lottery / Lucky Draw using points"""
        user = await self.get_user_by_tg(tg_id)
        if not user:
            return {"success": False, "msg": "未绑定 Emby 账号"}
        
        points = user.get("points", 0)
        if points < cost:
            return {"success": False, "msg": f"抽奖需要 {cost} 积分，您当前仅有 {points} 积分！"}

        cur_pts = points - cost
        roll = random.random() * 100
        prize = {}
        
        if roll < 5:
            new_devs = user.get("max_devices", 2) + 1
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET points = ?, max_devices = ? WHERE tg_id = ?", (cur_pts, new_devs, tg_id))
                await db.commit()
            prize = {"type": "grand", "msg": f"🎉 欧皇降临！抽中【并发设备 +1 台】（当前上限: {new_devs} 台）"}
        elif roll < 20:
            new_exp = await self.extend_user_expiry(tg_id, 7)
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (cur_pts, tg_id))
                await db.commit()
            prize = {"type": "days", "msg": f"🎁 大吉！抽中【7天观影时长】（新到期: {new_exp.strftime('%Y-%m-%d')}）"}
        elif roll < 45:
            new_exp = await self.extend_user_expiry(tg_id, 3)
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (cur_pts, tg_id))
                await db.commit()
            prize = {"type": "days", "msg": f"✨ 中奖！抽中【3天观影时长】（新到期: {new_exp.strftime('%Y-%m-%d')}）"}
        elif roll < 75:
            cur_pts += 35
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (cur_pts, tg_id))
                await db.commit()
            prize = {"type": "points", "msg": f"💰 积分红包！抽中【35 积分】（净赚 15 积分）"}
        else:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (cur_pts, tg_id))
                await db.commit()
            prize = {"type": "none", "msg": "☕ 差点就中了！获得了【赛博安慰奖：功德 +1】"}

        prize["remaining_points"] = cur_pts
        prize["success"] = True
        return prize

    # --- MINI GAMES SYSTEM ---
    async def game_dice_bot(self, tg_id: int, bet: int) -> Dict[str, Any]:
        """PvE Dice roll against Lemon Bot"""
        user = await self.get_user_by_tg(tg_id)
        if not user:
            return {"success": False, "msg": "未绑定 Emby 账号"}
        if bet <= 0:
            return {"success": False, "msg": "押注积分必须大于 0"}
        points = user.get("points", 0)
        if points < bet:
            return {"success": False, "msg": f"积分不足！您当前仅有 {points} 积分"}

        user_roll = random.randint(1, 6)
        bot_roll = random.randint(1, 6)

        if user_roll > bot_roll:
            # Win 1x bet
            new_pts = points + bet
            res_str = f"🎉 <b>您赢了！</b> 赢得 <b>+{bet}</b> 积分！"
            outcome = "win"
        elif user_roll < bot_roll:
            # Lose bet
            new_pts = points - bet
            res_str = f"💥 <b>您输了！</b> 损失 <b>-{bet}</b> 积分！"
            outcome = "lose"
        else:
            # Tie
            new_pts = points
            res_str = "🤝 <b>平局！</b> 积分已全额退回。"
            outcome = "tie"

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (new_pts, tg_id))
            await db.commit()

        return {
            "success": True,
            "user_roll": user_roll,
            "bot_roll": bot_roll,
            "outcome": outcome,
            "result_str": res_str,
            "remaining_points": new_pts
        }

    async def game_rob(self, from_tg: int, to_tg: int) -> Dict[str, Any]:
        """Rob points from another user with risk"""
        if from_tg == to_tg:
            return {"success": False, "msg": "你不能抢劫你自己！"}

        u_from = await self.get_user_by_tg(from_tg)
        if not u_from:
            return {"success": False, "msg": "打劫者未绑定 Emby 账号"}

        u_to = await self.get_user_by_tg(to_tg)
        if not u_to:
            return {"success": False, "msg": "目标群友未绑定 Emby 账号，身无分文！"}

        from_pts = u_from.get("points", 0)
        to_pts = u_to.get("points", 0)

        if from_pts < 15:
            return {"success": False, "msg": "打劫需要至少 15 积分作为行动经费（以防打劫失败被反杀赔偿）！"}

        if to_pts < 30:
            return {"success": False, "msg": f"目标用户 <code>{u_to['emby_username']}</code> 太穷了（积分低于 30），触发新手贫困保护！"}

        # 45% success rate
        is_success = random.random() < 0.45

        if is_success:
            # Rob 10% to 25% of target points (max 80 pts)
            percent = random.randint(10, 25) / 100.0
            robbed_amount = min(80, max(5, int(to_pts * percent)))
            
            new_from_pts = from_pts + robbed_amount
            new_to_pts = to_pts - robbed_amount

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (new_from_pts, from_tg))
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (new_to_pts, to_tg))
                await db.commit()

            await self.log_action(from_tg, "ROB_SUCCESS", f"Robbed {robbed_amount} pts from TG:{to_tg}")
            return {
                "success": True,
                "status": "win",
                "robbed_amount": robbed_amount,
                "victim_name": u_to.get("emby_username"),
                "from_pts": new_from_pts,
                "to_pts": new_to_pts
            }
        else:
            # Failed and got countered! Pay 15 pts penalty to victim
            penalty = 15
            new_from_pts = from_pts - penalty
            new_to_pts = to_pts + penalty

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (new_from_pts, from_tg))
                await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (new_to_pts, to_tg))
                await db.commit()

            await self.log_action(from_tg, "ROB_FAIL", f"Failed robbing TG:{to_tg}, lost {penalty} pts")
            return {
                "success": True,
                "status": "lose",
                "penalty": penalty,
                "victim_name": u_to.get("emby_username"),
                "from_pts": new_from_pts,
                "to_pts": new_to_pts
            }

    async def game_pvp_dice_resolve(self, u1_tg: int, u2_tg: int, bet: int) -> Dict[str, Any]:
        """Resolve PvP dice between two users"""
        u1 = await self.get_user_by_tg(u1_tg)
        u2 = await self.get_user_by_tg(u2_tg)
        if not u1 or not u2:
            return {"success": False, "msg": "双方需均已绑定 Emby 账号"}
        
        if u1.get("points", 0) < bet or u2.get("points", 0) < bet:
            return {"success": False, "msg": "其中一方积分不足以支付赌注！"}

        u1_roll = random.randint(1, 6)
        u2_roll = random.randint(1, 6)

        if u1_roll > u2_roll:
            winner_tg = u1_tg
            loser_tg = u2_tg
            winner_name = u1.get("emby_username")
            loser_name = u2.get("emby_username")
            outcome = "u1_win"
            await self.add_user_points(u1_tg, bet)
            await self.add_user_points(u2_tg, -bet)
        elif u2_roll > u1_roll:
            winner_tg = u2_tg
            loser_tg = u1_tg
            winner_name = u2.get("emby_username")
            loser_name = u1.get("emby_username")
            outcome = "u2_win"
            await self.add_user_points(u2_tg, bet)
            await self.add_user_points(u1_tg, -bet)
        else:
            outcome = "tie"
            winner_name = None
            loser_name = None

        return {
            "success": True,
            "outcome": outcome,
            "u1_roll": u1_roll,
            "u2_roll": u2_roll,
            "u1_name": u1.get("emby_username"),
            "u2_name": u2.get("emby_username"),
            "winner_name": winner_name,
            "loser_name": loser_name,
            "bet": bet
        }

    async def transfer_points(self, from_tg: int, to_tg: int, amount: int) -> Dict[str, Any]:
        """Transfer points from one user to another"""
        if amount <= 0:
            return {"success": False, "msg": "转账积分必须大于 0"}
        if from_tg == to_tg:
            return {"success": False, "msg": "不能给自己转账"}

        u_from = await self.get_user_by_tg(from_tg)
        if not u_from:
            return {"success": False, "msg": "转账方未绑定 Emby 账号"}
        
        u_to = await self.get_user_by_tg(to_tg)
        if not u_to:
            return {"success": False, "msg": "收款方未绑定 Emby 账号"}

        from_pts = u_from.get("points", 0)
        if from_pts < amount:
            return {"success": False, "msg": f"您的积分不足！当前仅有 {from_pts} 积分"}

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET points = points - ? WHERE tg_id = ?", (amount, from_tg))
            await db.execute("UPDATE users SET points = points + ? WHERE tg_id = ?", (amount, to_tg))
            await db.commit()

        await self.log_action(from_tg, "TRANSFER_POINTS", f"Sent {amount} pts to TG:{to_tg}")
        return {
            "success": True,
            "amount": amount,
            "from_remaining": from_pts - amount,
            "to_username": u_to.get("emby_username")
        }

    async def get_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get points & days ranking"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY points DESC LIMIT ?", (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

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
            new_pts = await self.add_user_points(tg_id, val)
            return {"success": True, "type": "points", "value": val, "total_points": new_pts}
        
        return {"success": True, "type": card_type, "value": val}

    async def log_action(self, tg_id: int, action: str, details: str = ""):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO logs (tg_id, action, details, created_at) VALUES (?, ?, ?, ?)", (tg_id, action, details, now))
            await db.commit()
