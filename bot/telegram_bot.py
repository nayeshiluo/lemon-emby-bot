import logging
import datetime
import html
import secrets
import string
import random
import time
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
    """Telegram Bot with Rich Inline Keyboards, Security Hardening, Economy & Mini-Games"""
    def __init__(self, token: str, config: dict, db, emby_client):
        self.token = token
        self.config = config
        self.db = db
        self.emby = emby_client
        raw_admin_ids = config.get("telegram", {}).get("admin_ids", [])
        self.admin_ids = [int(i) for i in raw_admin_ids if str(i).isdigit() or (str(i).startswith("-") and str(i)[1:].isdigit())]
        self.app = Application.builder().token(token).build()
        self.pending_duels: Dict[str, dict] = {}
        self.user_cooldowns: Dict[int, float] = {}  # {tg_id: last_command_time}
        self.rob_counts: Dict[str, int] = {}       # {"YYYY-MM-DD:tg_id": count}
        self._register_handlers()

    def _is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def _check_cooldown(self, user_id: int, cooldown_seconds: float = 2.0) -> bool:
        """Returns True if user is within cooldown (throttled)"""
        now = time.time()
        last = self.user_cooldowns.get(user_id, 0)
        if now - last < cooldown_seconds:
            return True
        self.user_cooldowns[user_id] = now
        return False

    @staticmethod
    def _is_private_chat(update: Update) -> bool:
        return bool(update.effective_chat and update.effective_chat.type == "private")

    def _clean_expired_duels(self):
        """Clean up pending duels older than 120 seconds"""
        now = datetime.datetime.now()
        expired_keys = [k for k, v in self.pending_duels.items() if (now - v["time"]).total_seconds() > 120]
        for k in expired_keys:
            self.pending_duels.pop(k, None)

    def _register_handlers(self):
        # General & Account
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("my", self.cmd_my))
        self.app.add_handler(CommandHandler("bind", self.cmd_bind))
        self.app.add_handler(CommandHandler("redeem", self.cmd_redeem))
        self.app.add_handler(CommandHandler("resetpw", self.cmd_resetpw))
        
        # Points & Economy
        self.app.add_handler(CommandHandler("checkin", self.cmd_checkin))
        self.app.add_handler(CommandHandler(["shop", "store"], self.cmd_shop))
        self.app.add_handler(CommandHandler(["lottery", "draw", "chou"], self.cmd_lottery))
        self.app.add_handler(CommandHandler(["transfer", "pay", "sendpts"], self.cmd_transfer))
        self.app.add_handler(CommandHandler(["rank", "top", "leaderboard"], self.cmd_rank))

        # Gaming Modes (PK / Dice / Rob)
        self.app.add_handler(CommandHandler(["dice", "touzi"], self.cmd_dice))
        self.app.add_handler(CommandHandler(["rob", "steal", "qiang"], self.cmd_rob))
        self.app.add_handler(CommandHandler(["duel", "pk"], self.cmd_duel))

        # Query & Lookup
        self.app.add_handler(CommandHandler(["info", "check", "whois", "user"], self.cmd_info))
        
        # Admin Commands
        self.app.add_handler(CommandHandler(["create", "open", "adduser"], self.cmd_create))
        self.app.add_handler(CommandHandler(["deluser", "rmuser", "delete"], self.cmd_deluser))
        self.app.add_handler(CommandHandler("gen", self.cmd_gen))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("users", self.cmd_users))
        self.app.add_handler(CommandHandler("ban", self.cmd_ban))
        self.app.add_handler(CommandHandler("unban", self.cmd_unban))
        self.app.add_handler(CommandHandler("addtime", self.cmd_addtime))
        self.app.add_handler(CommandHandler(["addpts", "addpoints"], self.cmd_addpts))
        self.app.add_handler(CommandHandler(["delpts", "delpoints"], self.cmd_delpts))

        # Callback queries (Inline buttons)
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))

    async def send_notification(self, tg_id: int, message: str):
        """Send message directly to user with error handling"""
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
                InlineKeyboardButton("🛒 积分商城", callback_data="cb_shop"),
                InlineKeyboardButton("🎰 幸运抽奖", callback_data="cb_lottery")
            ],
            [
                InlineKeyboardButton("🎲 掷骰对决", callback_data="cb_game_dice_menu"),
                InlineKeyboardButton("🏆 积分富豪榜", callback_data="cb_rank")
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

    def _get_shop_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📦 7天时长 (50分)", callback_data="cb_buy_days_7"),
                InlineKeyboardButton("📦 30天时长 (180分)", callback_data="cb_buy_days_30")
            ],
            [
                InlineKeyboardButton("📦 90天季卡 (500分)", callback_data="cb_buy_days_90"),
                InlineKeyboardButton("🚀 并发设备+1 (300分)", callback_data="cb_buy_dev_plus1")
            ],
            [
                InlineKeyboardButton("🔙 返回主菜单", callback_data="cb_main_menu")
            ]
        ])

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or not update.message: return
        is_admin = self._is_admin(user.id)
        name = html.escape(user.first_name or "朋友")
        
        text = (
            f"🍋 <b>欢迎来到 Lemon Emby 智能中控！</b>\n\n"
            f"你好，<b>{name}</b>！这里是 Emby 媒体服务器专属服务助手。\n\n"
            f"📌 <b>常用操作：</b>\n"
            f"• 点击 <b>【👤 个人中心】</b> 查看账号与剩余天数\n"
            f"• 每日 <b>【🎁 每日签到】</b> 免费领取时长与积分\n"
            f"• 逛逛 <b>【🛒 积分商城】</b> 兑换观影时长与并发设备\n"
            f"• 参与 <b>【🎲 游戏娱乐】</b> 体验掷骰对决、群友PK与打劫\n\n"
            f"🎬 <i>祝你观影愉快！</i>"
        )
        await update.message.reply_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
        is_admin = self._is_admin(update.effective_user.id)
        user_help = (
            "📖 <b>Lemon Emby 用户指令大全：</b>\n\n"
            "• <code>/start</code> - 打开主控制面板\n"
            "• <code>/my</code> - 查看个人账号信息与到期时间\n"
            "• <code>/checkin</code> - 每日签到领时长与积分\n"
            "• <code>/shop</code> - 积分商城（换时长/并发设备）\n"
            "• <code>/lottery</code> - 积分幸运抽奖（20分/次）\n"
            "• <code>/dice [押注]</code> - 掷骰子比大小（回复群友发起PK，或单人挑战Bot）\n"
            "• <code>/rob</code> - 打劫群友积分（回复某人发送，有反杀风险）\n"
            "• <code>/transfer &lt;用户&gt; &lt;积分&gt;</code> - 积分转账给群友\n"
            "• <code>/rank</code> - 查看群内积分富豪榜\n"
            "• <code>/bind &lt;账号&gt; &lt;密码&gt;</code> - 开通或绑定 Emby 账号\n"
            "• <code>/redeem &lt;卡密&gt;</code> - 使用兑换码续费\n"
            "• <code>/resetpw &lt;新密码&gt;</code> - 自助修改 Emby 密码\n"
            "• <code>/info</code> - 查看账号状态（支持回复他人消息查号）\n"
        )
        admin_help = (
            "\n👑 <b>管理员特权快捷指令：</b>\n"
            "• <b>一键开号：</b> 回复群友发送 <code>/create [天数] [密码]</code>\n"
            "• <b>一键查号：</b> 回复群友发送 <code>/info</code>\n"
            "• <b>一键销号：</b> 回复群友发送 <code>/deluser</code>\n"
            "• <code>/addpts &lt;用户名/TG_ID&gt; &lt;点数&gt;</code> - 给用户发放积分\n"
            "• <code>/delpts &lt;用户名/TG_ID&gt; &lt;点数&gt;</code> - 扣除用户积分\n"
            "• <code>/gen &lt;天数&gt; [张数]</code> - 批量生成天数卡密\n"
            "• <code>/status</code> - 查看 Emby 服务器状态与当前播放\n"
            "• <code>/addtime &lt;用户名&gt; &lt;天数&gt;</code> - 手动加时长\n"
            "• <code>/ban &lt;用户名&gt;</code> / <code>/unban &lt;用户名&gt;</code> - 封禁/解封\n"
        ) if is_admin else ""
        
        await update.message.reply_text(user_help + admin_help, parse_mode="HTML")

    async def cmd_my(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
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
        username_safe = html.escape(u.get("emby_username", ""))

        text = (
            f"👤 <b>我的 Emby 账号档案</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ <b>用户名：</b> <code>{username_safe}</code>\n"
            f"📶 <b>账号状态：</b> {status_tag}\n"
            f"⏳ <b>到期时间：</b> <code>{expiry.strftime('%Y-%m-%d %H:%M')}</code>\n"
            f"💎 <b>账户积分：</b> <code>{u.get('points', 0)}</code> PTS\n"
            f"📱 <b>最大设备限制：</b> <code>{u.get('max_devices', 2)}</code> 台\n"
            f"🌐 <b>服务器地址：</b> <code>{html.escape(self.config.get('emby', {}).get('public_url', ''))}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>提示：发送 <code>/resetpw 新密码</code> 可自助修改密码。</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # --- GAMING MODES: DICE, ROB, PK DUEL ---
    async def cmd_dice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
        sender_id = update.effective_user.id
        if self._check_cooldown(sender_id, cooldown_seconds=1.5):
            return

        args = context.args
        reply_msg = update.message.reply_to_message

        bet = 10
        if args:
            try:
                bet = max(1, min(1000, int(args[0])))
            except ValueError:
                bet = 10

        if reply_msg and reply_msg.from_user and reply_msg.from_user.id != sender_id:
            target_user = reply_msg.from_user
            duel_id = secrets.token_hex(4)
            self._clean_expired_duels()

            self.pending_duels[duel_id] = {
                "u1_tg": sender_id,
                "u2_tg": target_user.id,
                "u1_name": update.effective_user.first_name or "群友",
                "u2_name": target_user.first_name or "群友",
                "bet": bet,
                "time": datetime.datetime.now()
            }

            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⚔️ 接受对决！", callback_data=f"cb_accept_duel_{duel_id}"),
                    InlineKeyboardButton("🏳️ 认怂拒绝", callback_data=f"cb_reject_duel_{duel_id}")
                ]
            ])
            text = (
                f"⚔️ <b>掷骰 PK 决斗挑战发起！</b>\n\n"
                f"👤 <b>发起者：</b> {html.escape(update.effective_user.first_name or '群友')}\n"
                f"🎯 <b>应战方：</b> {html.escape(target_user.first_name or '群友')}\n"
                f"💰 <b>押注积分：</b> <b>{bet}</b> PTS\n\n"
                f"<i>请应战方点击下方按钮应战（60秒内有效）！</i>"
            )
            await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
            return

        res = await self.db.game_dice_bot(sender_id, bet)
        if not res.get("success"):
            await update.message.reply_text(f"⚠️ {res.get('msg')}")
            return

        dice_emojis = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
        u_dice = dice_emojis[res['user_roll'] - 1]
        b_dice = dice_emojis[res['bot_roll'] - 1]

        text = (
            f"🎲 <b>人机掷骰对决结果</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 您掷出了：{u_dice} <b>({res['user_roll']} 点)</b>\n"
            f"🍋 柠檬掷出：{b_dice} <b>({res['bot_roll']} 点)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{res['result_str']}\n"
            f"💎 剩余总积分：<code>{res['remaining_points']}</code> PTS"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_duel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.cmd_dice(update, context)

    async def cmd_rob(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
        from_id = update.effective_user.id
        reply_msg = update.message.reply_to_message
        args = context.args

        # Anti-flood check
        today_key = f"{datetime.date.today().isoformat()}:{from_id}"
        robbed_today = self.rob_counts.get(today_key, 0)
        if robbed_today >= 5:
            await update.message.reply_text("🛑 今日打劫次数已达上限（每日限 5 次），做个遵纪守法的好群友吧！")
            return

        to_id = None
        if reply_msg and reply_msg.from_user:
            to_id = reply_msg.from_user.id
        elif args:
            target_str = args[0].strip()
            if target_str.isdigit():
                to_id = int(target_str)
            else:
                target_u = await self.db.get_user_by_username(target_str.lstrip("@"))
                if target_u:
                    to_id = target_u["tg_id"]

        if not to_id:
            await update.message.reply_text("💡 <b>打劫玩法：</b>\n长按/回复你想打劫的群友消息，发送 <code>/rob</code>", parse_mode="HTML")
            return

        res = await self.db.game_rob(from_id, to_id)
        if not res.get("success"):
            await update.message.reply_text(f"⚠️ {res.get('msg')}", parse_mode="HTML")
            return

        self.rob_counts[today_key] = robbed_today + 1
        robber_name = html.escape(update.effective_user.first_name or "神秘人")
        victim_name = html.escape(res.get("victim_name", "受害者"))

        if res["status"] == "win":
            text = (
                f"🥷 <b>打劫大成功！劫富济贫！</b>\n\n"
                f"👤 劫匪：<b>{robber_name}</b>\n"
                f"🎯 受害者：<code>{victim_name}</code>\n"
                f"💰 成功掠夺：<b>+{res['robbed_amount']}</b> 积分！\n\n"
                f"<i>受害者已被洗劫，劫匪潇洒离去~ (今日剩余次数: {4 - robbed_today})</i>"
            )
        else:
            text = (
                f"💥 <b>打劫翻车！被当场反杀！</b>\n\n"
                f"👤 劫匪：<b>{robber_name}</b>\n"
                f"🛡️ 勇士：<code>{victim_name}</code>\n"
                f"💸 赔偿罚金：<b>-{res['penalty']}</b> 积分（已直接转入受害者账户）\n\n"
                f"<i>偷鸡不成蚀把米，受害者笑嘻嘻收下赔款！(今日剩余次数: {4 - robbed_today})</i>"
            )
        await update.message.reply_text(text, parse_mode="HTML")

    # --- POINTS & ECONOMY HANDLERS ---
    async def cmd_shop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
        user_id = update.effective_user.id
        u = await self.db.get_user_by_tg(user_id)
        pts = u.get("points", 0) if u else 0

        text = (
            f"🛒 <b>Lemon Emby 积分商城</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 <b>您的当前积分：</b> <code>{pts}</code> PTS\n\n"
            f"🎁 <b>热销商品列表：</b>\n"
            f"• <b>7天时长卡：</b> <code>50</code> 积分\n"
            f"• <b>30天月卡：</b> <code>180</code> 积分\n"
            f"• <b>90天季卡：</b> <code>500</code> 积分\n"
            f"• <b>并发播放设备限制 +1 台：</b> <code>300</code> 积分\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👇 <i>点击下方按钮即可一键兑换：</i>"
        )
        await update.message.reply_text(text, reply_markup=self._get_shop_keyboard(), parse_mode="HTML")

    async def cmd_lottery(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
        user_id = update.effective_user.id
        if self._check_cooldown(user_id, cooldown_seconds=1.5): return

        res = await self.db.lottery_draw(user_id, cost=20)
        if not res.get("success"):
            await update.message.reply_text(f"⚠️ {res.get('msg')}")
            return
        
        text = (
            f"🎰 <b>Lemon 积分幸运大转盘</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>抽奖结果：</b>\n"
            f"{res['msg']}\n\n"
            f"💎 <b>剩余积分：</b> <code>{res['remaining_points']}</code> PTS\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>单次抽奖消耗 20 积分，祝您下次欧气满满！</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
        from_id = update.effective_user.id
        args = context.args
        reply_msg = update.message.reply_to_message

        to_id = None
        amount = 0

        try:
            if reply_msg and reply_msg.from_user:
                to_id = reply_msg.from_user.id
                if args: amount = int(args[0])
            elif args and len(args) >= 2:
                target_str = args[0].strip()
                if target_str.isdigit():
                    to_id = int(target_str)
                else:
                    target_u = await self.db.get_user_by_username(target_str.lstrip("@"))
                    if target_u: to_id = target_u["tg_id"]
                amount = int(args[1])
        except (ValueError, IndexError):
            amount = 0

        if not to_id or amount <= 0:
            await update.message.reply_text(
                "💡 <b>积分转账格式：</b>\n"
                "1. 回复群友消息发送：<code>/transfer 50</code>\n"
                "2. 指定用户名/TG发送：<code>/transfer 用户名 50</code>",
                parse_mode="HTML"
            )
            return

        res = await self.db.transfer_points(from_id, to_id, amount)
        if not res.get("success"):
            await update.message.reply_text(f"❌ {res.get('msg')}")
            return

        target_name_safe = html.escape(res.get("to_username", "群友"))
        text = (
            f"💸 <b>积分转账成功！</b>\n\n"
            f"📤 转出积分：<b>{res['amount']}</b> PTS\n"
            f"📥 收款方：<code>{target_name_safe}</code> (TG: {to_id})\n"
            f"💎 您的剩余积分：<code>{res['from_remaining']}</code> PTS"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_rank(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message: return
        top_users = await self.db.get_leaderboard(limit=10)
        if not top_users:
            await update.message.reply_text("暂无排行榜数据")
            return
        
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        lines = []
        for i, u in enumerate(top_users):
            m = medals[i] if i < len(medals) else f"{i+1}."
            name_safe = html.escape(u.get("emby_username", "匿名"))
            lines.append(f"{m} <b>{name_safe}</b> — <code>{u.get('points', 0)}</code> 积分 (设备: {u.get('max_devices', 2)}台)")

        text = (
            f"🏆 <b>Lemon Emby 积分富豪榜 TOP 10</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n" +
            "\n".join(lines) +
            "\n━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>每日签到或参与群聊互动积攒积分，可兑换丰富观影权益！</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # --- ADMIN POINTS MANAGEMENT ---
    async def cmd_addpts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
            return
        args = context.args
        reply_msg = update.message.reply_to_message

        target_u = None
        pts = 0

        try:
            if reply_msg and reply_msg.from_user:
                target_u = await self.db.get_user_by_tg(reply_msg.from_user.id)
                if args: pts = int(args[0])
            elif args and len(args) >= 2:
                target_u = await self.db.get_user_by_identifier(args[0])
                pts = int(args[1])
        except (ValueError, IndexError):
            pts = 0

        if not target_u or pts <= 0:
            await update.message.reply_text("💡 格式：回复用户 <code>/addpts 100</code> 或 <code>/addpts 用户名 100</code>", parse_mode="HTML")
            return

        new_total = await self.db.add_user_points(target_u["tg_id"], pts)
        name_safe = html.escape(target_u.get("emby_username", ""))
        await update.message.reply_text(f"✅ 已为 <code>{name_safe}</code> 增加 <b>{pts}</b> 积分！当前总积分：<code>{new_total}</code>", parse_mode="HTML")

    async def cmd_delpts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
            return
        args = context.args
        reply_msg = update.message.reply_to_message

        target_u = None
        pts = 0

        try:
            if reply_msg and reply_msg.from_user:
                target_u = await self.db.get_user_by_tg(reply_msg.from_user.id)
                if args: pts = int(args[0])
            elif args and len(args) >= 2:
                target_u = await self.db.get_user_by_identifier(args[0])
                pts = int(args[1])
        except (ValueError, IndexError):
            pts = 0

        if not target_u or pts <= 0:
            await update.message.reply_text("💡 格式：回复用户 <code>/delpts 100</code> 或 <code>/delpts 用户名 100</code>", parse_mode="HTML")
            return

        new_total = await self.db.add_user_points(target_u["tg_id"], -pts)
        name_safe = html.escape(target_u.get("emby_username", ""))
        await update.message.reply_text(f"🛑 已扣除 <code>{name_safe}</code> <b>{pts}</b> 积分！当前剩余积分：<code>{new_total}</code>", parse_mode="HTML")

    # --- LOOKUP / INFO ---
    async def cmd_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
        sender_id = update.effective_user.id
        is_admin = self._is_admin(sender_id)
        args = context.args
        reply_msg = update.message.reply_to_message

        u_db = None
        target_name = None

        if reply_msg and reply_msg.from_user:
            target_user = reply_msg.from_user
            target_name = target_user.first_name or target_user.username or "群友"
            u_db = await self.db.get_user_by_tg(target_user.id)
        elif args:
            identifier = args[0].strip()
            u_db = await self.db.get_user_by_identifier(identifier)
            if not u_db:
                emby_u = await self.emby.get_user_by_name(identifier)
                if emby_u:
                    u_db = await self.db.get_user_by_emby_id(emby_u["Id"])
        else:
            u_db = await self.db.get_user_by_tg(sender_id)

        if not u_db:
            who = f"用户 <code>{html.escape(target_name or (args[0] if args else '您'))}</code>"
            await update.message.reply_text(f"❌ 未查询到 {who} 的 Emby 绑定信息！", parse_mode="HTML")
            return

        if not is_admin and u_db.get("tg_id") != sender_id:
            await update.message.reply_text("🔒 仅管理员可查询其他用户的详细档案！", parse_mode="HTML")
            return

        expiry = datetime.datetime.fromisoformat(u_db["expiry_date"])
        now = datetime.datetime.now(datetime.timezone.utc)
        delta_days = (expiry - now).days
        status_tag = "🔴 已过期/冻结" if (delta_days < 0 or u_db.get("is_disabled")) else f"🟢 正常 (剩余 {delta_days} 天)"

        playing_info = "💤 当前空闲"
        sessions = await self.emby.get_active_sessions()
        user_sessions = [s for s in sessions if s.get("UserId") == u_db.get("emby_user_id")]
        if user_sessions:
            items = []
            for s in user_sessions:
                dev = html.escape(s.get("DeviceName", "未知设备"))
                media = html.escape(s.get("NowPlayingItem", {}).get("Name", "媒体"))
                items.append(f"• <b>{dev}</b>: <i>{media}</i>")
            playing_info = f"🔥 <b>正在播放中 ({len(user_sessions)} 台设备)：</b>\n" + "\n".join(items)

        emby_name_safe = html.escape(u_db.get("emby_username", ""))
        text = (
            f"🔍 <b>Emby 用户状态档案</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Emby 账号：</b> <code>{emby_name_safe}</code>\n"
            f"🆔 <b>Telegram ID：</b> <code>{u_db['tg_id']}</code>\n"
            f"📶 <b>账号状态：</b> {status_tag}\n"
            f"⏳ <b>到期时间：</b> <code>{expiry.strftime('%Y-%m-%d %H:%M')}</code>\n"
            f"💎 <b>账户积分：</b> <code>{u_db.get('points', 0)}</code> PTS\n"
            f"📱 <b>最大设备限制：</b> <code>{u_db.get('max_devices', 2)}</code> 台\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎬 <b>播放状态：</b>\n{playing_info}"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # --- ADMIN: ONE-CLICK CREATE USER ---
    async def cmd_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
            return

        reply_msg = update.message.reply_to_message
        args = context.args
        target_tg_id = None
        username = None
        password = None
        days = 30

        if reply_msg and reply_msg.from_user:
            target_user = reply_msg.from_user
            target_tg_id = target_user.id
            username = target_user.username or f"u_{target_user.id}"

            if args:
                if args[0].isdigit():
                    days = max(1, min(3650, int(args[0])))
                    if len(args) > 1: password = args[1]
                    if len(args) > 2: username = args[2]
                else:
                    username = args[0]
                    if len(args) > 1: password = args[1]
                    if len(args) > 2 and args[2].isdigit():
                        days = max(1, min(3650, int(args[2])))

            if not password:
                password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        else:
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
            days = max(1, min(3650, int(args[2]))) if len(args) > 2 and args[2].isdigit() else 30
            target_tg_id = int(args[3]) if len(args) > 3 and args[3].isdigit() else 0

        # Sanitize username (alphanumeric, underscore, dash)
        username = "".join(c for c in username if c.isalnum() or c in "_-")
        if not username:
            username = f"user_{secrets.randbelow(100000)}"

        if target_tg_id:
            existing = await self.db.get_user_by_tg(target_tg_id)
            if existing:
                await update.message.reply_text(
                    f"⚠️ 该用户 (TG: <code>{target_tg_id}</code>) 已绑定 Emby 账号：<code>{html.escape(existing['emby_username'])}</code>！\n"
                    f"如需延期请使用 <code>/addtime {html.escape(existing['emby_username'])} {days}</code>。",
                    parse_mode="HTML"
                )
                return

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

        tg_id_to_save = target_tg_id or int(f"99{secrets.randbelow(1000000)}")
        await self.db.create_user_record(tg_id_to_save, emby_user_id, username, days=days)
        await self.db.log_action(update.effective_user.id, "ADMIN_CREATE", f"Created {username} for TG:{target_tg_id} days:{days}")

        public_url = html.escape(self.config.get("emby", {}).get("public_url", "https://emby.example.com"))
        name_safe = html.escape(username)
        pass_safe = html.escape(password)
        
        reply_card = (
            f"🎉 <b>Emby 账号一键开通成功！</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>用户名：</b> <code>{name_safe}</code>\n"
            f"🔑 <b>初始密码：</b> <code>{pass_safe}</code>\n"
            f"⏳ <b>有效时长：</b> <b>{days}</b> 天\n"
            f"🆔 <b>绑定 TG：</b> <code>{target_tg_id or '未绑定'}</code>\n"
            f"🌐 <b>服务器地址：</b> <code>{public_url}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>建议登录后使用 <code>/resetpw</code> 自助修改个人密码。</i>"
        )
        if self._is_private_chat(update):
            await update.message.reply_text(reply_card, parse_mode="HTML")
        else:
            await update.message.reply_text(
                "✅ Emby 账号已开通。登录凭据已通过私聊发送，请勿在群内索取或发布密码。",
                parse_mode="HTML",
            )

        if target_tg_id and target_tg_id > 0:
            dm_text = (
                f"🎉 <b>你好！管理员已为你开通 Emby 观影账号！</b>\n\n"
                f"👤 <b>登录账号：</b> <code>{name_safe}</code>\n"
                f"🔑 <b>登录密码：</b> <code>{pass_safe}</code>\n"
                f"⏳ <b>有效期：</b> <b>{days}</b> 天\n"
                f"🌐 <b>服务器地址：</b> <code>{public_url}</code>\n\n"
                f"📱 <b>快速开始：</b>\n"
                f"1. 下载 Infuse / Fileball / VidHub 或 Emby 官方客户端\n"
                f"2. 输入上方服务器地址、账号和密码即可畅快观影！\n"
                f"3. 每日在 Bot 发送 <code>/checkin</code> 即可免费领时长与积分~"
            )
            await self.send_notification(target_tg_id, dm_text)

    # --- ADMIN: DELETE USER ---
    async def cmd_deluser(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
            return

        reply_msg = update.message.reply_to_message
        args = context.args
        u_db = None

        if reply_msg and reply_msg.from_user:
            u_db = await self.db.get_user_by_tg(reply_msg.from_user.id)
        elif args:
            u_db = await self.db.get_user_by_identifier(args[0].strip())
        else:
            await update.message.reply_text("💡 格式：回复用户 <code>/deluser</code> 或 <code>/deluser &lt;用户名/TG_ID&gt;</code>", parse_mode="HTML")
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
        await update.message.reply_text(f"🗑️ 已成功删除用户 <code>{html.escape(username)}</code> (TG: <code>{tg_id}</code>) 的 Emby 账号及全部数据！", parse_mode="HTML")

    async def cmd_checkin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
        user_id = update.effective_user.id
        if self._check_cooldown(user_id, cooldown_seconds=1.0): return

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
        if not update.effective_user or not update.message: return
        user_id = update.effective_user.id
        if not self._is_private_chat(update):
            await update.message.reply_text("🔒 为保护账号安全，请在与 Bot 的私聊中使用 /bind；群聊不会处理账号凭据。")
            return
        args = context.args
        if not args or len(args) < 2:
            await update.message.reply_text("💡 使用格式：<code>/bind &lt;用户名&gt; &lt;密码&gt;</code>", parse_mode="HTML")
            return

        username = "".join(c for c in args[0].strip() if c.isalnum() or c in "_-")
        password = args[1].strip()

        existing = await self.db.get_user_by_tg(user_id)
        if existing:
            await update.message.reply_text(f"⚠️ 你已经绑定了账号：<code>{html.escape(existing['emby_username'])}</code>，无法重复开号！", parse_mode="HTML")
            return

        emby_u = await self.emby.get_user_by_name(username)
        if emby_u:
            emby_user_id = emby_u["Id"]
            linked = await self.db.get_user_by_emby_id(emby_user_id)
            if not linked:
                logger.warning("Refusing bind for existing unlinked Emby user %s", emby_user_id)
                await update.message.reply_text("❌ 该 Emby 账号已存在，但无法验证归属；请联系管理员处理。")
                return
            if linked["tg_id"] != user_id:
                logger.warning("Refusing bind for Emby user %s linked to another Telegram user", emby_user_id)
                await update.message.reply_text("❌ 该 Emby 账号已与其他用户绑定，无法认领。")
                return
            await update.message.reply_text(
                f"✅ 你已绑定账号：<code>{html.escape(linked['emby_username'])}</code>。未重置密码。",
                parse_mode="HTML",
            )
            return
        else:
            new_u = await self.emby.create_user(username, password)
            if not new_u:
                await update.message.reply_text("❌ Emby 服务器创建账号失败，请联系管理员！")
                return
            emby_user_id = new_u["Id"]

        await self.db.create_user_record(user_id, emby_user_id, username, days=30)
        await self.db.log_action(user_id, "BIND_USER", f"Username: {username}")

        text = (
            f"🎉 <b>Emby 账号开通/绑定成功！</b>\n\n"
            f"👤 用户名：<code>{html.escape(username)}</code>\n"
            f"🔑 密码：<code>{html.escape(password)}</code>\n"
            f"🎁 初始赠送：<b>30</b> 天有效期\n"
            f"🌐 服务器公网地址：<code>{html.escape(self.config.get('emby', {}).get('public_url', ''))}</code>\n\n"
            f"<i>请在客户端（Infuse/Fileball/Emby等）输入以上信息登录。</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_redeem(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message: return
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
        if not update.effective_user or not update.message: return
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
            await update.message.reply_text("✅ 密码修改成功！新密码已生效。")
        else:
            await update.message.reply_text("❌ 密码同步到 Emby 失败，请稍后重试。")

    # --- ADMIN MISC COMMANDS ---
    async def cmd_gen(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
            return
        args = context.args
        if not args:
            await update.message.reply_text("💡 管理员格式：<code>/gen &lt;天数&gt; [张数]</code>", parse_mode="HTML")
            return
        
        try:
            days = max(1, min(3650, int(args[0])))
            count = max(1, min(50, int(args[1]) if len(args) > 1 else 1))
        except ValueError:
            await update.message.reply_text("❌ 参数必须为正整数！")
            return

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
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
            return
        
        sys_info = await self.emby.get_system_info()
        sessions = await self.emby.get_active_sessions()
        users = await self.db.get_all_users()

        server_name = html.escape(sys_info.get("ServerName", "Emby Server") if sys_info else "连接失败")
        ver = html.escape(sys_info.get("Version", "未知") if sys_info else "N/A")

        active_str = ""
        if sessions:
            for s in sessions[:5]:
                user_name = html.escape(s.get("UserName", "Unknown"))
                dev = html.escape(s.get("DeviceName", "Unknown"))
                item = html.escape(s.get("NowPlayingItem", {}).get("Name", "媒体"))
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
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
            return
        users = await self.db.get_all_users()
        lines = []
        for u in users[:15]:
            status = "🔴" if u.get("is_disabled") else "🟢"
            exp = u.get("expiry_date", "")[:10]
            name_safe = html.escape(u.get("emby_username", ""))
            lines.append(f"{status} <code>{name_safe}</code> (TG: {u['tg_id']}) - 到期: {exp} - {u.get('points', 0)}分")
        
        text = f"👥 <b>用户列表（前 15 名）：</b>\n\n" + ("\n".join(lines) if lines else "暂无用户")
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_ban(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
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
            await update.message.reply_text(f"🛑 用户 <code>{html.escape(username)}</code> 已封禁/禁用！", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ 未找到用户 {html.escape(username)}")

    async def cmd_unban(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
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
            await update.message.reply_text(f"✅ 用户 <code>{html.escape(username)}</code> 已解封！", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ 未找到用户 {html.escape(username)}")

    async def cmd_addtime(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.message or not self._is_admin(update.effective_user.id):
            return
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("💡 格式：<code>/addtime &lt;用户名&gt; &lt;天数&gt;</code>", parse_mode="HTML")
            return
        username = args[0]
        try:
            days = max(1, min(3650, int(args[1])))
        except ValueError:
            await update.message.reply_text("❌ 天数必须为有效正整数")
            return
        
        emby_u = await self.emby.get_user_by_name(username)
        if not emby_u:
            await update.message.reply_text(f"❌ 未找到用户 {html.escape(username)}")
            return
        
        u_db = await self.db.get_user_by_emby_id(emby_u["Id"])
        if not u_db:
            await update.message.reply_text("❌ 该用户未在系统数据库中登记")
            return
        
        new_exp = await self.db.extend_user_expiry(u_db["tg_id"], days)
        await self.emby.set_user_disabled(emby_u["Id"], False)
        name_safe = html.escape(username)
        await update.message.reply_text(f"✅ 已为 <code>{name_safe}</code> 增加 {days} 天时长！\n新到期时间：<code>{new_exp.strftime('%Y-%m-%d %H:%M')}</code>", parse_mode="HTML")

    # --- CALLBACK HANDLER ---
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query: return
        await query.answer()
        data = query.data or ""
        user_id = query.from_user.id
        is_admin = self._is_admin(user_id)

        if data == "cb_main_menu":
            await query.edit_message_text("🍋 <b>主控制面板</b>", reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

        elif data == "cb_game_dice_menu":
            text = (
                "🎲 <b>游戏娱乐大厅</b>\n\n"
                "1️⃣ <b>单人挑战柠檬：</b> 发送 <code>/dice 20</code> 与机器人比大小\n"
                "2️⃣ <b>群友掷骰 PK：</b> 引用群友消息发送 <code>/dice 50</code> 发起决斗\n"
                "3️⃣ <b>积分打劫：</b> 引用群友消息发送 <code>/rob</code> 劫富济贫\n"
                "4️⃣ <b>幸运抽奖：</b> 发送 <code>/lottery</code> 或点击下方按钮"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎰 幸运大转盘", callback_data="cb_lottery")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="cb_main_menu")]
            ])
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

        elif data.startswith("cb_accept_duel_"):
            duel_id = data.replace("cb_accept_duel_", "")
            duel = self.pending_duels.pop(duel_id, None)
            if not duel:
                await query.edit_message_text("⚠️ 决斗已失效或已超时！")
                return
            
            if user_id != duel["u2_tg"]:
                await query.answer("这不是发给你的决斗挑战哦！", show_alert=True)
                return

            res = await self.db.game_pvp_dice_resolve(duel["u1_tg"], duel["u2_tg"], duel["bet"])
            if not res.get("success"):
                await query.edit_message_text(f"⚠️ 对决失败：{res.get('msg')}")
                return

            dice_emojis = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
            d1 = dice_emojis[res['u1_roll'] - 1]
            d2 = dice_emojis[res['u2_roll'] - 1]

            if res["outcome"] == "tie":
                res_text = "🤝 <b>势均力敌！双方平局！</b> 积分已全额保留。"
            else:
                res_text = f"👑 <b>恭喜胜者：<code>{html.escape(res.get('winner_name', ''))}</code>！</b>\n💰 赢取赌注：<b>+{res['bet']}</b> 积分！"

            text = (
                f"⚔️ <b>掷骰 PK 决斗结果揭晓！</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>{html.escape(res['u1_name'])}：</b> {d1} <b>({res['u1_roll']} 点)</b>\n"
                f"👤 <b>{html.escape(res['u2_name'])}：</b> {d2} <b>({res['u2_roll']} 点)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{res_text}"
            )
            await query.edit_message_text(text, parse_mode="HTML")

        elif data.startswith("cb_reject_duel_"):
            duel_id = data.replace("cb_reject_duel_", "")
            duel = self.pending_duels.pop(duel_id, None)
            if duel:
                await query.edit_message_text(f"🏳️ 应战方已认怂拒绝了决斗！")
            else:
                await query.edit_message_text("决斗已关闭")

        elif data == "cb_my":
            u = await self.db.get_user_by_tg(user_id)
            if not u:
                await query.edit_message_text("❌ 尚未绑定 Emby 账号！请使用 /bind 账号 密码 绑定。", reply_markup=self._get_main_keyboard(is_admin))
                return
            expiry = datetime.datetime.fromisoformat(u["expiry_date"])
            now = datetime.datetime.now(datetime.timezone.utc)
            delta_days = (expiry - now).days
            status_tag = "🔴 已过期" if delta_days < 0 else f"🟢 正常 (余 {delta_days} 天)"
            name_safe = html.escape(u.get("emby_username", ""))
            pub_url = html.escape(self.config.get("emby", {}).get("public_url", ""))
            text = (
                f"👤 <b>我的 Emby 账号档案</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏷️ <b>用户名：</b> <code>{name_safe}</code>\n"
                f"📶 <b>状态：</b> {status_tag}\n"
                f"⏳ <b>到期时间：</b> <code>{expiry.strftime('%Y-%m-%d %H:%M')}</code>\n"
                f"💎 <b>积分：</b> <code>{u.get('points', 0)}</code> PTS\n"
                f"📱 <b>最大设备限制：</b> <code>{u.get('max_devices', 2)}</code> 台\n"
                f"🌐 <b>服务器地址：</b> <code>{pub_url}</code>"
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

        elif data == "cb_shop":
            u = await self.db.get_user_by_tg(user_id)
            pts = u.get("points", 0) if u else 0
            text = (
                f"🛒 <b>Lemon Emby 积分商城</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💎 <b>当前积分：</b> <code>{pts}</code> PTS\n\n"
                f"• 7天卡：50 积分\n"
                f"• 30天卡：180 积分\n"
                f"• 90天卡：500 积分\n"
                f"• 并发设备+1：300 积分\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            await query.edit_message_text(text, reply_markup=self._get_shop_keyboard(), parse_mode="HTML")

        elif data.startswith("cb_buy_"):
            item_key = data.replace("cb_buy_", "")
            res = await self.db.exchange_item(user_id, item_key)
            if res.get("success"):
                text = (
                    f"🎉 <b>兑换成功！</b>\n\n"
                    f"📦 商品：<b>{html.escape(res['item_name'])}</b>\n"
                    f"💸 消耗积分：<b>{res['cost']}</b> PTS\n"
                    f"💎 剩余积分：<code>{res['remaining_points']}</code> PTS\n"
                    f"✨ {res['details']}"
                )
            else:
                text = f"⚠️ 兑换失败：{res.get('msg')}"
            await query.edit_message_text(text, reply_markup=self._get_shop_keyboard(), parse_mode="HTML")

        elif data == "cb_lottery":
            res = await self.db.lottery_draw(user_id, cost=20)
            if res.get("success"):
                text = (
                    f"🎰 <b>幸运大转盘抽奖结果</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{res['msg']}\n\n"
                    f"💎 剩余积分：<code>{res['remaining_points']}</code> PTS\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                text = f"⚠️ {res.get('msg')}"
            
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎰 再抽一次 (20分)", callback_data="cb_lottery")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="cb_main_menu")]
            ])
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

        elif data == "cb_rank":
            top_users = await self.db.get_leaderboard(limit=10)
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            lines = []
            for i, u in enumerate(top_users):
                m = medals[i] if i < len(medals) else f"{i+1}."
                lines.append(f"{m} <b>{html.escape(u.get('emby_username', ''))}</b> — <code>{u.get('points', 0)}</code> 积分")

            text = (
                f"🏆 <b>Lemon Emby 积分富豪榜 TOP 10</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n" +
                ("\n".join(lines) if lines else "暂无数据") +
                "\n━━━━━━━━━━━━━━━━━━━━"
            )
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

        elif data == "cb_redeem_info":
            text = "🎟️ <b>卡密兑换指引</b>\n\n请直接回复：<code>/redeem LEMON-XXXX-XXXX</code>"
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

        elif data == "cb_lines":
            pub_url = html.escape(self.config.get("emby", {}).get("public_url", "https://emby.example.com"))
            text = f"🌐 <b>推荐线路</b>\n\n<code>{pub_url}</code>"
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")

        elif data == "cb_clients":
            text = (
                "📱 <b>推荐 Emby 客户端：</b>\n\n"
                "• <b>iOS / Apple TV:</b> Infuse, Fileball, VidHub\n"
                "• <b>Android / TV:</b> Emby 官方, yamby\n"
                "• <b>PC / Mac:</b> Emby Theater, 网页端\n"
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
                f"• <code>/create 30</code> 回复一键开号\n"
                f"• <code>/info</code> 回复一键查号\n"
                f"• <code>/addpts 用户 100</code> 加积分\n"
                f"• <code>/gen 30 5</code> 批量制卡"
            )
            await query.edit_message_text(text, reply_markup=self._get_main_keyboard(is_admin), parse_mode="HTML")
