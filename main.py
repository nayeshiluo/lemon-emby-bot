import asyncio
import logging
import os
from typing import Any
import yaml
import uvicorn
from core.database import Database
from core.emby import EmbyClient
from core.scheduler import BackgroundScheduler
from bot.telegram_bot import LemonEmbyBot
from web.api import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("lemon-emby.main")

def load_config(config_path: str = "config.yaml") -> dict:
    if not os.path.exists(config_path):
        if os.path.exists("config.example.yaml"):
            logger.warning("config.yaml not found, loading config.example.yaml")
            config_path = "config.example.yaml"
        else:
            raise FileNotFoundError("Config file not found!")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

async def main():
    config = load_config()
    db_path = config.get("server", {}).get("db_path", "lemon_emby.db")
    
    # 1. Init Database
    db = Database(db_path=db_path)
    await db.init_db()

    # 2. Init Emby Client
    emby_cfg = config.get("emby", {})
    emby_client = EmbyClient(
        server_url=emby_cfg.get("server_url", "http://127.0.0.1:8096"),
        api_key=emby_cfg.get("api_key", ""),
        template_user_id=emby_cfg.get("template_user_id")
    )

    # 3. Init Telegram Bot
    tg_token = config.get("telegram", {}).get("bot_token", "")
    bot = None
    if tg_token and not tg_token.startswith("1234567890:"):
        logger.info("Initializing Telegram Bot...")
        bot = LemonEmbyBot(tg_token, config, db, emby_client)
    else:
        logger.warning("Telegram Bot token is not configured or is placeholder. Bot will not run.")

    # 4. Init Background Scheduler
    notify_func = bot.send_notification if bot else None
    scheduler = BackgroundScheduler(db, emby_client, config, notify_func=notify_func)
    await scheduler.start()

    # 5. Init Web API Server
    web_app = create_app(config, db, emby_client)
    server_cfg = config.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = server_cfg.get("port", 8888)

    uvicorn_config = uvicorn.Config(web_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(uvicorn_config)

    logger.info(f"🍋 Lemon Emby Manager is running! Web Panel on http://{host}:{port}")

    # Run tasks concurrently
    tasks: list[asyncio.Task[Any]] = [asyncio.create_task(server.serve())]
    if bot:
        # Start TG Bot polling
        await bot.app.initialize()
        await bot.app.start()
        if bot.app.updater:
            tasks.append(asyncio.create_task(bot.app.updater.start_polling()))

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down Lemon Emby...")
        await scheduler.stop()
        if bot:
            if bot.app.updater:
                await bot.app.updater.stop()
            await bot.app.stop()
            await bot.app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
