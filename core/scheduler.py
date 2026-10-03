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
        """Disable expired users and retry expiry-only reactivations."""
        users = await self.db.get_all_users()
        rules = self.config.get("rules", {})
        warn_days = rules.get("warn_days_before_expiry", 3)
        auto_disable = rules.get("auto_disable_expired", True)

        for listed_user in users:
            tg_id = listed_user.get("tg_id")
            if tg_id is None:
                continue

            notification = None
            async with self.db.account_lock(tg_id):
                # The list may be stale by the time we reach this account. Reload
                # after acquiring the same lock used by renewal and admin actions.
                user = await self.db.get_user_by_tg(tg_id)
                if not user:
                    continue

                expiry_str = user.get("expiry_date")
                expiry = self.db.as_utc(expiry_str)
                if not expiry:
                    continue

                now = datetime.datetime.now(datetime.timezone.utc)
                emby_user_id = user.get("emby_user_id")
                is_disabled = bool(user.get("is_disabled", 0))

                if expiry < now:
                    if is_disabled or not auto_disable:
                        continue

                    logger.warning(
                        "User %s (TG: %s) expired. Disabling on Emby...",
                        user.get("emby_username"),
                        tg_id,
                    )
                    try:
                        disabled = bool(emby_user_id) and await self.emby.set_user_disabled(
                            emby_user_id, True
                        )
                    except Exception:
                        logger.exception(
                            "Failed to disable expired Emby user %s (TG: %s)",
                            emby_user_id,
                            tg_id,
                        )
                        disabled = False

                    if not disabled:
                        logger.error(
                            "Failed to disable expired Emby user %s (TG: %s); retaining retryable local state",
                            emby_user_id,
                            tg_id,
                        )
                        await self.db.log_action(
                            tg_id, "AUTO_EXPIRE_FAILED", "Emby disable request failed"
                        )
                        continue

                    await self.db.update_user_status(tg_id, True, reason="expired")
                    await self.db.log_action(
                        tg_id, "AUTO_EXPIRE", f"Account disabled at {expiry_str}"
                    )
                    notification = ("expired", user.get("emby_username", ""), expiry, expiry_str)
                else:
                    # A previous renewal may have extended the account while Emby
                    # was unavailable. Retry only expiry-caused disables; never
                    # clear an admin or unknown disable automatically.
                    if (
                        is_disabled
                        and user.get("disabled_reason") == "expired"
                        and emby_user_id
                    ):
                        try:
                            enabled = await self.emby.set_user_disabled(
                                emby_user_id, False
                            )
                        except Exception:
                            logger.exception(
                                "Failed to retry Emby reactivation for user %s (TG: %s)",
                                emby_user_id,
                                tg_id,
                            )
                            enabled = False

                        if enabled:
                            await self.db.update_user_status(tg_id, False)
                            await self.db.log_action(
                                tg_id, "AUTO_REACTIVATE", "Renewed account re-enabled"
                            )
                        else:
                            logger.error(
                                "Failed to retry Emby reactivation for user %s (TG: %s)",
                                emby_user_id,
                                tg_id,
                            )
                            await self.db.log_action(
                                tg_id,
                                "AUTO_REACTIVATE_FAILED",
                                "Emby enable request failed; will retry",
                            )

                    delta = expiry - now
                    if (
                        self.notify_func
                        and warn_days > 0
                        and 0 < delta.total_seconds() <= warn_days * 86400
                        and await self.db.claim_expiry_warning(tg_id, expiry_str)
                    ):
                        notification = (
                            "warning",
                            user.get("emby_username", ""),
                            expiry,
                            expiry_str,
                        )

            if notification and self.notify_func:
                kind, username, expiry, expiry_str = notification
                if kind == "expired":
                    msg = (
                        f"🚨 <b>Emby 账号已到期提醒</b>\n\n"
                        f"尊敬的 <b>{username}</b>：\n"
                        f"您的 Emby 账号已于 <code>{expiry.strftime('%Y-%m-%d %H:%M')}</code> 到期并被自动冻结。\n"
                        f"💡 <i>您可以签到或使用兑换码自助续费激活！</i>"
                    )
                else:
                    msg = (
                        f"⏰ <b>Emby 账号即将到期</b>\n\n"
                        f"尊敬的 <b>{username}</b>：\n"
                        f"您的账号预计于 <code>{expiry.strftime('%Y-%m-%d %H:%M')}</code> 到期。\n"
                        f"💡 <i>您可以签到或使用兑换码自助续费。</i>"
                    )
                try:
                    delivered = await self.notify_func(tg_id, msg)
                    if kind == "warning" and delivered is False:
                        await self.db.release_expiry_warning(tg_id, expiry_str)
                except Exception:
                    logger.exception("Failed to send expiry notification for TG: %s", tg_id)
                    if kind == "warning":
                        await self.db.release_expiry_warning(tg_id, expiry_str)

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
                    stopped = await self.emby.stop_session(sid, f"超过最大同时播放限制（限制 {max_devs} 台）")
                    if not stopped:
                        logger.error("Failed to stop excess session %s for Emby user %s", sid, emby_user_id)
                        continue
                    
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
