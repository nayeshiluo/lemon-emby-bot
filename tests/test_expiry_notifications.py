import asyncio
import datetime
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest
import pytest_asyncio

from bot.telegram_bot import LemonEmbyBot
from core.database import Database
from core.scheduler import BackgroundScheduler
from core import scheduler as scheduler_module


@pytest_asyncio.fixture
async def reminder_account(tmp_path):
    db = Database(str(tmp_path / "reminders.db"))
    await db.init_db()
    await db.create_user_record(9201, "emby_reminder", "reminder_user", days=2)
    emby = SimpleNamespace(
        get_user_by_name=AsyncMock(return_value={"Id": "emby_reminder"}),
        set_user_disabled=AsyncMock(return_value=True),
    )
    bot = object.__new__(LemonEmbyBot)
    bot.db, bot.emby, bot.admin_ids = db, emby, [1]
    return db, emby, bot


async def renew(bot):
    message = SimpleNamespace(reply_text=AsyncMock())
    await bot.cmd_addtime(
        SimpleNamespace(effective_user=SimpleNamespace(id=1), message=message),
        SimpleNamespace(args=["reminder_user", "30"]),
    )
    assert "增加 30 天时长" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True], ids=["warning", "expired"])
async def test_renewal_before_delivery_skips_stale_reminder(reminder_account, expired):
    db, emby, bot = reminder_account
    if expired:
        old_expiry = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        ).isoformat()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("UPDATE users SET expiry_date = ?", (old_expiry,))
            await conn.commit()

    snapshot_ready, resume_delivery = asyncio.Event(), asyncio.Event()
    original_lock = db.account_lock
    pause_first = True

    @asynccontextmanager
    async def pause_after_snapshot(tg_id):
        nonlocal pause_first
        should_pause = pause_first
        pause_first = False
        async with original_lock(tg_id):
            yield
        if should_pause:
            snapshot_ready.set()
            await resume_delivery.wait()

    db.account_lock = pause_after_snapshot
    notify = AsyncMock(return_value=True)
    scheduler = BackgroundScheduler(db, emby, {"rules": {}}, notify)
    task = asyncio.create_task(scheduler.check_expirations())
    try:
        await asyncio.wait_for(snapshot_ready.wait(), 2)
        await asyncio.wait_for(renew(bot), 2)
        resume_delivery.set()
        await asyncio.wait_for(task, 2)
        notify.assert_not_awaited()
        user = await db.get_user_by_tg(9201)
        assert user["is_disabled"] == 0
        assert user["expiry_warning_for"] is None
    finally:
        resume_delivery.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_inflight_reminder_serializes_admin_renewal(reminder_account):
    db, emby, bot = reminder_account
    started, finish = asyncio.Event(), asyncio.Event()
    lookup_done = asyncio.Event()
    old_expiry = (await db.get_user_by_tg(9201))["expiry_date"]

    async def lookup(username):
        lookup_done.set()
        return {"Id": "emby_reminder"}

    emby.get_user_by_name.side_effect = lookup

    async def notify(tg_id, msg):
        started.set()
        await finish.wait()
        return True

    scheduler = BackgroundScheduler(db, emby, {"rules": {}}, notify)
    delivery_task = asyncio.create_task(scheduler.check_expirations())
    renewal_task = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        renewal_task = asyncio.create_task(renew(bot))
        await asyncio.wait_for(lookup_done.wait(), 2)
        # Database lookup happens before cmd_addtime attempts its account lock.
        for _ in range(1000):
            if renewal_task.done() or db._account_lock_users.get(9201, 0) == 2:
                break
            await asyncio.sleep(0.001)
        assert not renewal_task.done()
        assert db._account_lock_users.get(9201) == 2
        assert (await db.get_user_by_tg(9201))["expiry_date"] == old_expiry
        finish.set()
        await asyncio.wait_for(asyncio.gather(delivery_task, renewal_task), 2)
        assert (await db.get_user_by_tg(9201))["expiry_date"] != old_expiry
    finally:
        finish.set()
        tasks = [delivery_task] + ([renewal_task] if renewal_task else [])
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancel"])
async def test_interrupted_warning_releases_lock_and_retries(reminder_account, monkeypatch, cancel):
    db, emby, _ = reminder_account
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def blocked_notify(tg_id, msg):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(scheduler_module, "NOTIFICATION_TIMEOUT_SECONDS", 0.02 if not cancel else 10)
    scheduler = BackgroundScheduler(db, emby, {"rules": {}}, blocked_notify)
    task = asyncio.create_task(scheduler.check_expirations())
    try:
        await asyncio.wait_for(started.wait(), 2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        else:
            await asyncio.wait_for(task, 2)
        assert cancelled.is_set()
        assert (await db.get_user_by_tg(9201))["expiry_warning_for"] is None
        assert not db._account_locks
        scheduler.notify_func = AsyncMock(return_value=True)
        await asyncio.wait_for(scheduler.check_expirations(), 2)
        scheduler.notify_func.assert_awaited_once()
        user = await db.get_user_by_tg(9201)
        assert user["expiry_warning_for"] == user["expiry_date"]
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
