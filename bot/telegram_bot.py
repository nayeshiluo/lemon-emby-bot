import logging
import datetime
import secrets
import string
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

logger = logging.getLogger("lemon-emby.bot")

class LemonEmbyBot:
    """Telegram Bot with Rich Inline Keyboards and Admin Controls"""
    def __init__(self, token: str, config: dict, db, emby_client):
        self.token = token
        self.config = config
        self.db = db
        self.emby = emby_client
        self.admin_ids = config.get("telegram", {}).get("admin_ids", [])
        self.app = Application.builder().token(token).build()
        self._register_handlers()

    def _is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("my", self.cmd_my))
        self.app.add_handler(CommandHandler("checkin", self.cmd_checkin))
        self.app.add_handler(CommandHandler("bind", self.cmd_bind))
        self.app.add_handler(CommandHandler("redeem", self.cmd_redeem))
        self.app.add_handler(CommandHandler("resetpw", self.cmd_resetpw))
        
        # User & Admin Query Commands (Supports Reply & Explicit args)
        self.app.add_handler(CommandHandler(["info", "check", "whois", "user"], self.cmd_info))
        
        # Admin Commands (Supports Reply & Explicit args)
        self.app.add_handler(CommandHandler(["create", "open", "adduser"], self.cmd_create))
        self.app.add_handler(CommandHandler(["deluser", "rmuser", "delete"], self.cmd_deluser))
        self.app.add_handler(CommandHandler("gen", self.cmd_gen))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("users", self.cmd_users))
        self.app.add_handler(CommandHandler("ban", self.cmd_ban))
        self.app.add_handler(CommandHandler("unban", self.cmd_unban))
        self.app.add_handler(CommandHandler("addtime", self.cmd_addtime))

        # Callback queries (Inline buttons)
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))

    async def send_notification(self, tg_id: int, message: str):
        """Send message directly to user"""
        try:
            await self.app.bot.send_message(chat_id=tg_id, text=message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send TG message to {tg_id}: {e}")

    def _get_main_keyboard(self, is_admin: bool = False) -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton("👤 个人中心", callback_data="cb_my"),
                InlineKeyboardButton("🎁 每日签到", callback_data="cb_checkin")
            ],
            [
                InlineKeyboardButton("🎟️ 兑换卡密", callback_data="cb_redeem_info"),
                InlineKeyboardButton("🌐 线路节点", callback_data="cb_lines")
            ],
            [
                InlineKeyboardButton("📱 客户端推荐", callback_data="cb_clients"),
                InlineKeyboardButton("🔄 刷新状态", callback_data="cb_refresh")
            ]
        ]
        if is_admin:
            buttons.append([InlineKeyboardButton("⚙️ 管理员控制台", callback_data="cb_admin_panel")])
        return InlineKeyboardMarkup(buttons)

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        is_admin = self._is_admin(user.id)
        
        text = (
            f"🍋 <b>欢迎来到 Lemon Emby 智能中控！</b>\n\n"
            f"你好，<b>{user.first_name}</b>！这里是 Emby 媒体服务器专属服务助手。\n\n"
            f"📌 <b>常用操作：</b>\n"
            f"• 点击下方 <b>【👤 个人中心】</b> 查看账号与剩余天数\n"
            f"• 每日点击 <b>【🎁 每日签到】</b> 免费领取时长与积分\n"
            f"• 发送 <code>/bind 账号 密码</code> 自助开通或绑定账号\n"
            f"• 发送 <code>/redeem 卡密</code> 快速兑换时长\n\n"
            f"🎬 <i>祝你观影愉快！</i>"
        )
        await update.message.reply_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        is_admin = self._is_admin(update.effective_user.id)
        user_help = (
            "📖 <b>Lemon Emby 用户指令大全：</b>\n\n"
            "• <code>/start</code> - 打开主控制面板\n"
            "• <code>/my</code> - 查看个人账号信息与到期时间\n"
            "• <code>/checkin</code> - 每日签到领时长\n"
            "• <code>/bind &lt;账号&gt; &lt;密码&gt;</code> - 开通或绑定 Emby 账号\n"
            "• <code>/redeem &lt;卡密&gt;</code> - 使用兑换码续费\n"
            "• <code>/resetpw &lt;新密码&gt;</code> - 自助修改 Emby 密码\n"
            "• <code>/info</code> - 查看账号状态（支持回复他人消息查号）\n"
        )
        admin_help = (
            "\n👑 <b>管理员特权快捷指令：</b>\n"
            "• <b>一键开号：</b> 回复某人消息发送 <code>/create [天数] [初始密码]</code>，或 <code>/create &lt;用户名&gt; [密码] [天数]</code>\n"
            "• <b>一键查号：</b> 回复某人消息发送 <code>/info</code>，或 <code>/info &lt;用户名/TG_ID&gt;</code>\n"
            "• <b>一键销号：</b> 回复某人消息发送 <code>/deluser</code>，或 <code>/deluser &lt;用户名/TG_ID&gt;</code>\n"
            "• <code>/gen &lt;天数&gt; [张数]</code> - 批量生成天数卡密\n"
            "• <code>/status</code> - 查看 Emby 服务器状态与当前播放\n"
            "• <code>/users</code> - 列出最近注册用户\n"
            "• <code>/addtime &lt;用户名&gt; &lt;天数&gt;</code> - 手动给用户加时长\n"
            "• <code>/ban &lt;用户名&gt;</code> - 封禁/禁用用户\n"
            "• <code>/unban &lt;用户名&gt;</code> - 解封用户\n"
        ) if is_admin else ""
        
        await update.message.reply_text(user_help + admin_help, parse_mode="HTML")

    async def cmd_my(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        u = await self.db.get_user_by_tg(user_id)
        
        if not u:
            await update.message.reply_text(
                "❌ <b>尚未绑定 Emby 账号！</b>\n\n"
                "请使用 <code>/bind 用户名 密码</code> 快速注册/绑定你的专属账号。",
                parse_mode="HTML"
            )
            return

        expiry = datetime.datetime.fromisoformat(u["expiry_date"])
        now = datetime.datetime.now(datetime.timezone.utc)
        delta_days = (expiry - now).days
        status_tag = "🔴 已过期/冻结" if (delta_days < 0 or u.get("is_disabled")) else f"🟢 正常 (剩余 {delta_days} 天)"

        text = (
            f"👤 <b>我的 Emby 账号档案</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ <b>用户名：</b> <code>{u['emby_username']}</code>\n"
            f"📶 <b>账号状态：</b> {status_tag}\n"
            f"⏳ <b>到期时间：</b> <code>{expiry.strftime('%Y-%m-%d %H:%M')}</code>\n"
            f"💎 <b>账户积分：</b> <code>{u.get('points', 0)}</code> PTS\n"
            f"📱 <b>最大设备限制：</b> <code>{u.get('max_devices', 2)}</code> 台\n"
            f"🌐 <b>服务器地址：</b> <code>{self.config.get('emby', {}).get('public_url')}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>提示：发送 <code>/resetpw 新密码</code> 可自助修改密码。</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Query user details by replying to a message or providing identifier"""
        sender_id = update.effective_user.id
        is_admin = self._is_admin(sender_id)
        args = context.args
        reply_msg = update.message.reply_to_message

        u_db = None
        target_tg_id = None
        target_name = None

        if reply_msg and reply_msg.from_user:
            # Mode A: Reply to a user's message
            target_user = reply_msg.from_user
            target_tg_id = target_user.id
            target_name = target_user.first_name or target_user.username
            u_db = await self.db.get_user_by_tg(target_tg_id)
        elif args:
            # Mode B: Explicit argument
            identifier = args[0].strip()
            u_db = await self.db.get_user_by_identifier(identifier)
            if not u_db:
                # Also check directly on Emby
                emby_u = await self.emby.get_user_by_name(identifier)
                if emby_u:
                    u_db = await self.db.get_user_by_emby_id(emby_u["Id"])
        else:
            # Mode C: Self query
            target_tg_id = sender_id
            u_db = await self.db.get_user_by_tg(sender_id)

        if not u_db:
            who = f"用户 <code>{target_name or (args[0] if args else '您')}</code>"
            await update.message.reply_text(f"❌ 未查询到 {who} 的 Emby 绑定信息！", parse_mode="HTML")
            return

        # Check permission: non-admin can only check their own
        if not is_admin and u_db.get("tg_id") != sender_id:
            await update.message.reply_text("🔒 仅管理员可查询其他用户的详细档案！", parse_mode="HTML")
            return

        expiry = datetime.datetime.fromisoformat(u_db["expiry_date"])
        now = datetime.datetime.now(datetime.timezone.utc)
        delta_days = (expiry - now).days
        status_tag = "🔴 已过期/冻结" if (delta_days < 0 or u_db.get("is_disabled")) else f"🟢 正常 (剩余 {delta_days} 天)"

        # Check live playback
        playing_info = "💤 当前空闲"
        sessions = await self.emby.get_active_sessions()
        user_sessions = [s for s in sessions if s.get("UserId") == u_db.get("emby_user_id")]
        if user_sessions:
            items = []
            for s in user_sessions:
                dev = s.get("DeviceName", "未知设备")
                media = s.get("NowPlayingItem", {}).get("Name", "媒体")
                items.append(f"• <b>{dev}</b>: <i>{media}</i>")
            playing_info = f"🔥 <b>正在播放中 ({len(user_sessions)} 台设备)：</b>\n" + "\n".join(items)

        text = (
            f"🔍 <b>Emby 用户状态档案</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Emby 账号：</b> <code>{u_db['emby_username']}</code>\n"
            f"🆔 <b>Telegram ID：</b> <code>{u_db['tg_id']}</code>\n"
            f"📶 <b>账号状态：</b> {status_tag}\n"
            f"⏳ <b>到期时间：</b> <code>{expiry.strftime('%Y-%m-%d %H:%M')}</code>\n"
            f"💎 <b>账户积分：</b> <code>{u_db.get('points', 0)}</code> PTS\n"
            f"📱 <b>最大设备限制：</b> <code>{u_db.get('max_devices', 2)}</code> 台\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎬 <b>播放状态：</b>\n{playing_info}"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # --- ADMIN: ONE-CLICK CREATE USER (REPLY OR EXPLICIT) ---
    async def cmd_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command to create/open account by replying to a user message or specifying arguments"""
        if not self._is_admin(update.effective_user.id):
            return

        reply_msg = update.message.reply_to_message
        args = context.args

        target_tg_id = None
        username = None
        password = None
        days = 30

        if reply_msg and reply_msg.from_user:
            # Mode 1: Reply to someone's message in group/DM
            # Usage: /create [天数] [密码] [指定用户名]
            target_user = reply_msg.from_user
            target_tg_id = target_user.id
            
            # Default username from TG username or first_name or ID
            if target_user.username:
                username = target_user.username
            else:
                username = f"u_{target_user.id}"

            # Parse optional arguments: e.g. /create 60 pass123 or /create 60
            if args:
                if args[0].isdigit():
                    days = int(args[0])
                    if len(args) > 1:
                        password = args[1]
                    if len(args) > 2:
                        username = args[2]
                else:
                    username = args[0]
                    if len(args) > 1:
                        password = args[1]
                    if len(args) > 2 and args[2].isdigit():
                        days = int(args[2])

            if not password:
                # Random 8-character password
                password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        else:
            # Mode 2: Explicit command: /create <用户名> [密码] [天数] [tg_id]
            if not args:
                await update.message.reply_text(
                    "💡 <b>一键开号指令说明：</b>\n\n"
                    "1️⃣ <b>回复开号：</b> 选中群友消息直接回复 <code>/create [天数] [密码]</code>\n"
                    "2️⃣ <b>直接开号：</b> <code>/create &lt;用户名&gt; [密码] [天数] [TG_ID]</code>",
                    parse_mode="HTML"
                )
                return

            username = args[0].strip()
            password = args[1].strip() if len(args) > 1 else "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
            days = int(args[2]) if len(args) > 2 and args[2].isdigit() else 30
            target_tg_id = int(args[3]) if len(args) > 3 and args[3].isdigit() else 0

        # Check existing user
        if target_tg_id:
            existing = await self.db.get_user_by_tg(target_tg_id)
            if existing:
                await update.message.reply_text(
                    f"⚠️ 该用户 (TG: <code>{target_tg_id}</code>) 已绑定 Emby 账号：<code>{existing['emby_username']}</code>！\n"
                    f"如需延期请使用 <code>/addtime {existing['emby_username']} {days}</code>。",
                    parse_mode="HTML"
                )
                return

        # Check existing on Emby
        emby_u = await self.emby.get_user_by_name(username)
        if emby_u:
            emby_user_id = emby_u["Id"]
            await self.emby.update_user_password(emby_user_id, password)
            await self.emby.set_user_disabled(emby_user_id, False)
        else:
            new_u = await self.emby.create_user(username, password)
            if not new_u:
                await update.message.reply_text("❌ Emby 服务器开号失败，请检查服务器连接或 API Key！")
                return
            emby_user_id = new_u["Id"]

        # Record into Database
        tg_id_to_save = target_tg_id or int(f"99{secrets.randbelow(1000000)}")
        await self.db.create_user_record(tg_id_to_save, emby_user_id, username, days=days)
        await self.db.log_action(update.effective_user.id, "ADMIN_CREATE", f"Created {username} for TG:{target_tg_id} days:{days}")

        public_url = self.config.get("emby", {}).get("public_url", "https://emby.example.com")
        
        reply_card = (
            f"🎉 <b>Emby 账号一键开通成功！</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>用户名：</b> <code>{username}</code>\n"
            f"🔑 <b>初始密码：</b> <code>{password}</code>\n"
            f"⏳ <b>有效时长：</b> <b>{days}</b> 天\n"
            f"🆔 <b>绑定 TG：</b> <code>{target_tg_id or '未绑定'}</code>\n"
            f"🌐 <b>服务器地址：</b> <code>{public_url}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>建议登录后使用 <code>/resetpw</code> 或在客户端修改个人密码。</i>"
        )
        await update.message.reply_text(reply_card, parse_mode="HTML")

        # Try to send a private DM to the target user
        if target_tg_id and target_tg_id > 0:
            dm_text = (
                f"🎉 <b>你好！管理员已为你开通 Emby 观影账号！</b>\n\n"
                f"👤 <b>登录账号：</b> <code>{username}</code>\n"
                f"🔑 <b>登录密码：</b> <code>{password}</code>\n"
                f"⏳ <b>有效期：</b> <b>{days}</b> 天\n"
                f"🌐 <b>服务器地址：</b> <code>{public_url}</code>\n\n"
                f"📱 <b>快速开始：</b>\n"
                f"1. 下载 Infuse / Fileball / VidHub 或 Emby 官方客户端\n"
                f"2. 输入上方服务器地址、账号和密码即可畅快观影！\n"
                f"3. 每日在 Bot 发送 <code>/checkin</code> 即可免费领时长~"
            )
            await self.send_notification(target_tg_id, dm_text)

    # --- ADMIN: DELETE USER (REPLY OR EXPLICIT) ---
    async def cmd_deluser(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command to delete account by replying or specifying identifier"""
        if not self._is_admin(update.effective_user.id):
            return

        reply_msg = update.message.reply_to_message
        args = context.args
        u_db = None

        if reply_msg and reply_msg.from_user:
            target_tg_id = reply_msg.from_user.id
            u_db = await self.db.get_user_by_tg(target_tg_id)
        elif args:
            u_db = await self.db.get_user_by_identifier(args[0].strip())
        else:
            await update.message.reply_text("💡 格式：回复用户消息发送 <code>/deluser</code>，或 <code>/deluser &lt;用户名/TG_ID&gt;</code>", parse_mode="HTML")
            return

        if not u_db:
            await update.message.reply_text("❌ 未找到该用户的档案信息！")
            return

        emby_uid = u_db.get("emby_user_id")
        username = u_db.get("emby_username")
        tg_id = u_db.get("tg_id")

        if emby_uid:
            await self.emby.delete_user(emby_uid)
        await self.db.delete_user_record(tg_id)
        await self.db.log_action(update.effective_user.id, "ADMIN_DELETE", f"Deleted {username} (TG: {tg_id})")

        await update.message.reply_text(f"🗑️ 已成功删除用户 <code>{username}</code> (TG: <code>{tg_id}</code>) 的 Emby 账号及全部数据！", parse_mode="HTML")

    async def cmd_checkin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        reward_days = self.config.get("telegram", {}).get("checkin_reward_days", 1)
        points = self.config.get("telegram", {}).get("checkin_points", 10)
        
        res = await self.db.user_checkin(user_id, reward_days, points)
        if not res.get("success"):
            await update.message.reply_text(f"⚠️ {res.get('msg')}")
            return

        text = (
            f"🎉 <b>签到成功！</b>\n\n"
            f"🎁 获得时长：<b>+{res['reward_days']}</b> 天\n"
            f"💎 获得积分：<b>+{res['points']}</b> PTS (当前总积分: {res['total_points']})\n"
            f"⏳ 最新到期时间：<code>{res['new_expiry']}</code>\n\n"
            f"<i>感谢陪伴，记得明天再来哦~</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_bind(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        args = context.args
        if not args or len(args) < 2:
            await update.message.reply_text("💡 使用格式：<code>/bind &lt;用户名&gt; &lt;密码&gt;</code>", parse_mode="HTML")
            return

        username = args[0].strip()
        password = args[1].strip()

        # Check existing TG record
        existing = await self.db.get_user_by_tg(user_id)
        if existing:
            await update.message.reply_text(f"⚠️ 你已经绑定了账号：<code>{existing['emby_username']}</code>，无法重复开号！", parse_mode="HTML")
            return

        # Check existing on Emby
        emby_u = await self.emby.get_user_by_name(username)
        if emby_u:
            # User exists on Emby, update password and link
            emby_user_id = emby_u["Id"]
            await self.emby.update_user_password(emby_user_id, password)
            await self.emby.set_user_disabled(emby_user_id, False)
        else:
            # Create fresh user on Emby
            new_u = await self.emby.create_user(username, password)
            if not new_u:
                await update.message.reply_text("❌ Emby 服务器创建账号失败，请联系管理员！")
                return
            emby_user_id = new_u["Id"]

        # Save to DB (Default 30 days initial)
        await self.db.create_user_record(user_id, emby_user_id, username, days=30)
        await self.db.log_action(user_id, "BIND_USER", f"Username: {username}")

        text = (
            f"🎉 <b>Emby 账号开通/绑定成功！</b>\n\n"
            f"👤 用户名：<code>{username}</code>\n"
            f"🔑 密码：<code>{password}</code>\n"
            f"🎁 初始赠送：<b>30</b> 天有效期\n"
            f"🌐 服务器公网地址：<code>{self.config.get('emby', {}).get('public_url')}</code>\n\n"
            f"<i>请在客户端（Infuse/Fileball/Emby等）输入以上信息登录。</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_redeem(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        args = context.args
        if not args:
            await update.message.reply_text("💡 使用格式：<code>/redeem &lt;卡密兑换码&gt;</code>", parse_mode="HTML")
            return

        code = args[0].strip()
        res = await self.db.redeem_code(user_id, code)
        if not res.get("success"):
            await update.message.reply_text(f"❌ {res.get('msg')}")
            return

        if res.get("type") == "days":
            msg = f"🎉 <b>兑换成功！</b>\n\n延长时长：<b>+{res['value']}</b> 天\n新到期时间：<code>{res['new_expiry']}</code>"
        elif res.get("type") == "points":
            msg = f"🎉 <b>兑换成功！</b>\n\n增加积分：<b>+{res['value']}</b> PTS\n当前积分：<code>{res['total_points']}</code>"
        else:
            msg = "🎉 兑换成功！"
        
        await update.message.reply_text(msg, parse_mode="HTML")

    async def cmd_resetpw(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        args = context.args
        if not args:
            await update.message.reply_text("💡 使用格式：<code>/resetpw &lt;新密码&gt;</code>", parse_mode="HTML")
            return
        
        new_pw = args[0].strip()
        u = await self.db.get_user_by_tg(user_id)
        if not u or not u.get("emby_user_id"):
            await update.message.reply_text("❌ 你尚未绑定 Emby 账号！")
            return
        
        success = await self.emby.update_user_password(u["emby_user_id"], new_pw)
        if success:
            await update.message.reply_text(f"✅ 密码修改成功！新密码已生效：<code>{new_pw}</code>", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ 密码同步到 Emby 失败，请稍后重试。")

    # --- ADMIN COMMANDS ---
    async def cmd_gen(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return
        args = context.args
        if not args:
            await update.message.reply_text("💡 管理员格式：<code>/gen &lt;天数&gt; [张数]</code>", parse_mode="HTML")
            return
        
        days = int(args[0])
        count = int(args[1]) if len(args) > 1 else 1
        count = min(count, 50) # Cap at 50

        codes = []
        for _ in range(count):
            c = await self.db.generate_code("days", days, update.effective_user.id)
            codes.append(c)

        codes_text = "\n".join([f"<code>{c}</code>" for c in codes])
        await update.message.reply_text(
            f"🎟️ <b>成功生成 {count} 张 【{days}天时长卡】：</b>\n\n{codes_text}",
            parse_mode="HTML"
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return
        
        sys_info = await self.emby.get_system_info()
        sessions = await self.emby.get_active_sessions()
        users = await self.db.get_all_users()

        server_name = sys_info.get("ServerName", "Emby Server") if sys_info else "连接失败"
        ver = sys_info.get("Version", "未知") if sys_info else "N/A"

        active_str = ""
        if sessions:
            for s in sessions[:5]:
                user_name = s.get("UserName", "Unknown")
                dev = s.get("DeviceName", "Unknown")
                item = s.get("NowPlayingItem", {}).get("Name", "媒体")
                active_str += f"\n• <b>{user_name}</b> | {dev} 播放中: <i>{item}</i>"
        else:
            active_str = "\n• 暂无活跃播放会话"

        text = (
            f"📊 <b>Emby 服务器实时监控</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🖥️ <b>服务器名：</b> {server_name} (v{ver})\n"
            f"👥 <b>系统注册总用户：</b> {len(users)} 人\n"
            f"🎬 <b>当前活跃播放数：</b> {len(sessions)} 个\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 <b>活跃会话列表：</b>{active_str}"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return
        users = await self.db.get_all_users()
        lines = []
        for u in users[:15]:
            status = "🔴" if u.get("is_disabled") else "🟢"
            exp = u.get("expiry_date", "")[:10]
            lines.append(f"{status} <code>{u['emby_username']}</code> (TG: {u['tg_id']}) - 到期: {exp}")
        
        text = f"👥 <b>用户列表（前 15 名）：</b>\n\n" + ("\n".join(lines) if lines else "暂无用户")
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_ban(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return
        args = context.args
        if not args:
            await update.message.reply_text("💡 格式：<code>/ban &lt;用户名&gt;</code>", parse_mode="HTML")
            return
        username = args[0]
        emby_u = await self.emby.get_user_by_name(username)
        if emby_u:
            await self.emby.set_user_disabled(emby_u["Id"], True)
            u_db = await self.db.get_user_by_emby_id(emby_u["Id"])
            if u_db:
                await self.db.update_user_status(u_db["tg_id"], True)
            await update.message.reply_text(f"🛑 用户 <code>{username}</code> 已封禁/禁用！", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ 未找到用户 {username}")

    async def cmd_unban(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return
        args = context.args
        if not args:
            await update.message.reply_text("💡 格式：<code>/unban &lt;用户名&gt;</code>", parse_mode="HTML")
            return
        username = args[0]
        emby_u = await self.emby.get_user_by_name(username)
        if emby_u:
            await self.emby.set_user_disabled(emby_u["Id"], False)
            u_db = await self.db.get_user_by_emby_id(emby_u["Id"])
            if u_db:
                await self.db.update_user_status(u_db["tg_id"], False)
            await update.message.reply_text(f"✅ 用户 <code>{username}</code> 已解封！", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ 未找到用户 {username}")

    async def cmd_addtime(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("💡 格式：<code>/addtime &lt;用户名&gt; &lt;天数&gt;</code>", parse_mode="HTML")
            return
        username = args[0]
        days = int(args[1])
        
        emby_u = await self.emby.get_user_by_name(username)
        if not emby_u:
            await update.message.reply_text(f"❌ 未找到用户 {username}")
            return
        
        u_db = await self.db.get_user_by_emby_id(emby_u["Id"])
        if not u_db:
            await update.message.reply_text("❌ 该用户未在系统数据库中登记")
            return
        
        new_exp = await self.db.extend_user_expiry(u_db["tg_id"], days)
        await self.emby.set_user_disabled(emby_u["Id"], False)
        await update.message.reply_text(f"✅ 已为 <code>{username}</code> 增加 {days} 天时长！\n新到期时间：<code>{new_exp.strftime('%Y-%m-%d %H:%M')}</code>", parse_mode="HTML")

    # --- CALLBACK HANDLER ---
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = query.from_user.id
        is_admin = self._is_admin(user_id)

        if data == "cb_my":
            u = await self.db.get_user_by_tg(user_id)
            if not u:
                await query.edit_message_text("❌ 尚未绑定 Emby 账号！请使用 /bind 账号 密码 绑定。", reply_markup=self._get_main_keyboard(is_admin))
                return
            expiry = datetime.datetime.fromisoformat(u["expiry_date"])
            now = datetime.datetime.now(datetime.timezone.utc)
            delta_days = (expiry - now).days
            status_tag = "🔴 已过期" if delta_days < 0 else f"🟢 正常 (余 {delta_days} 天)"
            text = (
                f"👤 <b>我的 Emby 账号档案</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏷️ <b>用户名：</b> <code>{u['emby_username']}</code>\n"
                f"📶 <b>状态：</b> {status_tag}\n"
                f"⏳ <b>到期时间：</b> <code>{expiry.strftime('%Y-%m-%d %H:%M')}</code>\n"
                f"💎 <b>积分：</b> <code>{u.get('points', 0)}</code> PTS\n"
                f"📱 <b>最大设备限制：</b> <code>{u.get('max_devices', 2)}</code> 台\n"
                f"🌐 <b>服务器地址：</b> <code>{self.config.get('emby', {}).get('public_url')}</code>"
            )
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

        elif data == "cb_checkin":
            reward_days = self.config.get("telegram", {}).get("checkin_reward_days", 1)
            points = self.config.get("telegram", {}).get("checkin_points", 10)
            res = await self.db.user_checkin(user_id, reward_days, points)
            if res.get("success"):
                text = f"🎉 <b>签到成功！</b>\n\n获得时长: +{res['reward_days']} 天\n获得积分: +{res['points']} PTS\n新到期: <code>{res['new_expiry']}</code>"
            else:
                text = f"⚠️ {res.get('msg')}"
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

        elif data == "cb_redeem_info":
            text = (
                "🎟️ <b>卡密兑换指引</b>\n\n"
                "请直接在聊天框回复指令：\n"
                "<code>/redeem LEMON-XXXX-XXXX</code>\n\n"
                "💡 <i>卡密可通过活动、服主赠送或积分商城兑换获得。</i>"
            )
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

        elif data == "cb_lines":
            pub_url = self.config.get("emby", {}).get("public_url", "https://emby.example.com")
            text = (
                f"🌐 <b>Emby 推荐线路与节点信息</b>\n\n"
                f"🚀 <b>主线路（直连/CDN加速）：</b>\n<code>{pub_url}</code>\n\n"
                f"💡 <i>如遇卡顿或连接异常，可在群内联系服主或更换客户端重试。</i>"
            )
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

        elif data == "cb_clients":
            text = (
                "📱 <b>推荐 Emby 客户端：</b>\n\n"
                "• <b>iOS / Apple TV:</b> Infuse, Fileball, VidHub, SenPlayer, Emby 官方\n"
                "• <b>Android / Android TV:</b> Emby 官方客户端, yamby, Afast\n"
                "• <b>Windows / Mac:</b> Emby Theater, 网页端, PotPlayer / IINA (配合脚本)\n"
            )
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

        elif data == "cb_refresh":
            await query.edit_message_text("🔄 状态已刷新！", reply_markup=self._get_main_keyboard(is_admin))

        elif data == "cb_admin_panel" and is_admin:
            sys_info = await self.emby.get_system_info()
            sessions = await self.emby.get_active_sessions()
            users = await self.db.get_all_users()
            text = (
                f"⚙️ <b>管理员极速中控</b>\n\n"
                f"👥 <b>总用户：</b> {len(users)} 人\n"
                f"🎬 <b>在线播放数：</b> {len(sessions)} 个\n"
                f"💡 快捷指令：\n"
                f"• 回复某人消息发送 <code>/create 30</code> 一键开号\n"
                f"• 回复某人消息发送 <code>/info</code> 一键查号\n"
                f"• 回复某人消息发送 <code>/deluser</code> 一键销号\n"
                f"• <code>/gen 30 5</code> 生成 5 张 30 天卡密\n"
                f"• <code>/status</code> 查看详细播放会话"
            )
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")
