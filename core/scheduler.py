import asyncio
import datetime
import logging
from typing import Optional, Callable

logger = logging.getLogger("lemon-emby.scheduler")

class BackgroundScheduler:
    """Periodic task scheduler for Emby expiration and concurrency control"""
    def __init__(self, db, emby_client, config: dict, notify_func: Optional[Callable] = None):
        self.db = db
        self.emby = emby_client
        self.config = config
        self.notify_func = notify_func
        self.running = False
        self._task = None

    async def start(self):
        self.running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Background scheduler started.")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while self.running:
            try:
                await self.check_expirations()
                if self.config.get("rules", {}).get("max_concurrency_kill", True):
                    await self.check_concurrency()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
            
            interval = self.config.get("rules", {}).get("check_interval_minutes", 5) * 60
            await asyncio.sleep(interval)

    async def check_expirations(self):
        """Check expired accounts and impending expiry warnings"""
        users = await self.db.get_all_users()
        now = datetime.datetime.now(datetime.timezone.utc)
        warn_days = self.config.get("rules", {}).get("warn_days_before_expiry", 3)
        auto_disable = self.config.get("rules", {}).get("auto_disable_expired", True)

        for u in users:
            expiry_str = u.get("expiry_date")
            if not expiry_str:
                continue
            
            expiry = datetime.datetime.fromisoformat(expiry_str)
            tg_id = u["tg_id"]
            emby_user_id = u["emby_user_id"]
            is_disabled = u.get("is_disabled", 0)

            # Check if expired
            if expiry < now:
                if not is_disabled and auto_disable:
                    logger.warning(f"User {u['emby_username']} (TG: {tg_id}) expired. Disabling on Emby...")
                    if emby_user_id:
                        await self.emby.set_user_disabled(emby_user_id, True)
                    await self.db.update_user_status(tg_id, True)
                    await self.db.log_action(tg_id, "AUTO_EXPIRE", f"Account disabled at {expiry_str}")
                    
                    if self.notify_func:
                        msg = (
                            f"🚨 <b>Emby 账号已到期提醒</b>\n\n"
                            f"尊敬的 <b>{u['emby_username']}</b>：\n"
                            f"您的 Emby 账号已于 <code>{expiry.strftime('%Y-%m-%d %H:%M')}</code> 到期并被自动冻结。\n"
                            f"💡 <i>您可以签到或使用兑换码自助续费激活！</i>"
                        )
                        await self.notify_func(tg_id, msg)
            else:
                # Check impending expiry warning (e.g., between 0 and warn_days)
                delta = expiry - now
                if 0 < delta.total_seconds() <= warn_days * 86400:
                    # Notify only once or check flag (simple notice)
                    pass

    async def check_concurrency(self):
        """Check active playback sessions and enforce device limits"""
        sessions = await self.emby.get_active_sessions()
        if not sessions:
            return

        # Group by UserId
        user_sessions = {}
        for s in sessions:
            uid = s.get("UserId")
            if uid:
                user_sessions.setdefault(uid, []).append(s)

        for emby_user_id, s_list in user_sessions.items():
            user_db = await self.db.get_user_by_emby_id(emby_user_id)
            max_devs = user_db.get("max_devices", 2) if user_db else self.config.get("emby", {}).get("default_max_devices", 2)
            
            if len(s_list) > max_devs:
                logger.warning(f"User {emby_user_id} exceeded concurrency limit ({len(s_list)}/{max_devs})")
                # Sort by playback position / creation, kill the newest excess sessions
                excess = s_list[max_devs:]
                for ex_s in excess:
                    sid = ex_s.get("Id")
                    client_name = ex_s.get("Client", "未知客户端")
                    device_name = ex_s.get("DeviceName", "未知设备")
                    item_name = ex_s.get("NowPlayingItem", {}).get("Name", "媒体文件")
                    
                    logger.info(f"Killing excess session {sid} for {device_name} ({client_name})")
                    await self.emby.stop_session(sid, f"超过最大同时播放限制（限制 {max_devs} 台）")
                    
                    if user_db and self.notify_func:
                        msg = (
                            f"⚠️ <b>播放并发超限拦截通知</b>\n\n"
                            f"账号：<code>{user_db['emby_username']}</code>\n"
                            f"限制设备数：<b>{max_devs}</b> 台\n"
                            f"当前正在播放设备数：<b>{len(s_list)}</b> 台\n"
                            f"🛑 已阻断会话：<b>{device_name}</b> ({client_name})\n"
                            f"🎬 媒体：<i>{item_name}</i>\n\n"
                            f"<i>请勿将账号转借他人，防止封禁。</i>"
                        )
                        await self.notify_func(user_db["tg_id"], msg)
