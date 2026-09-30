import pytest
import pytest_asyncio
import datetime
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.telegram_bot import LemonEmbyBot
from core.database import Database
from core.emby import EmbyClient
from core.scheduler import BackgroundScheduler
from web.api import create_app, FAILED_ATTEMPTS
from web import api as web_api
from starlette.testclient import TestClient

TEST_DB_PATH = "test_lemon_emby_pytest.db"

@pytest_asyncio.fixture
async def test_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    db = Database(TEST_DB_PATH)
    await db.init_db()
    yield db
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest.mark.asyncio
async def test_user_lifecycle_and_checkin(test_db):
    await test_db.create_user_record(1001, "emby_uid_1", "testuser1", days=30, max_devices=2)
    u = await test_db.get_user_by_tg(1001)
    assert u is not None
    assert u.get("emby_username") == "testuser1"
    assert u.get("points") == 0
    assert u.get("max_devices") == 2

    res1 = await test_db.user_checkin(1001, reward_days=1, points=10)
    assert res1["success"] is True
    assert res1["points"] == 10
    assert res1["total_points"] == 10

    res2 = await test_db.user_checkin(1001, reward_days=1, points=10)
    assert res2["success"] is False

@pytest.mark.asyncio
async def test_concurrent_checkins_are_applied_once(test_db):
    import asyncio
    await test_db.create_user_record(1002, "emby_uid_2", "testuser2", days=30)

    results = await asyncio.gather(*(test_db.user_checkin(1002, 1, 10) for _ in range(5)))

    assert sum(result["success"] for result in results) == 1
    user = await test_db.get_user_by_tg(1002)
    assert user["points"] == 10

@pytest.mark.asyncio
async def test_duplicate_user_record_does_not_replace_existing_data(test_db):
    assert await test_db.create_user_record(1003, "emby_uid_3", "testuser3", days=30) is True
    await test_db.add_user_points(1003, 75)

    inserted = await test_db.create_user_record(1003, "emby_uid_replaced", "replacement", days=30)

    assert inserted is False
    user = await test_db.get_user_by_tg(1003)
    assert user["emby_user_id"] == "emby_uid_3"
    assert user["emby_username"] == "testuser3"
    assert user["points"] == 75

@pytest.mark.asyncio
async def test_unbound_user_cannot_consume_redeem_code(test_db):
    code = await test_db.generate_code("days", 30)

    rejected = await test_db.redeem_code(9999, code)
    assert rejected["success"] is False

    await test_db.create_user_record(9999, "emby_uid_9999", "testuser9999", days=10)
    redeemed = await test_db.redeem_code(9999, code)
    assert redeemed["success"] is True

@pytest.mark.asyncio
async def test_concurrent_expiry_extensions_are_not_lost(test_db):
    import asyncio
    await test_db.create_user_record(1004, "emby_uid_4", "testuser4", days=30)
    await test_db.update_user_status(1004, True)
    original = (await test_db.get_user_by_tg(1004))["expiry_date"]

    await asyncio.gather(*(test_db.extend_user_expiry(1004, 5) for _ in range(4)))

    expiry = test_db.as_utc((await test_db.get_user_by_tg(1004))["expiry_date"])
    assert expiry == test_db.as_utc(original) + datetime.timedelta(days=20)
    assert (await test_db.get_user_by_tg(1004))["is_disabled"] == 1

@pytest.mark.asyncio
async def test_disabled_reason_migration_and_persistence(tmp_path):
    import aiosqlite

    db_path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            CREATE TABLE users (
                tg_id INTEGER PRIMARY KEY, emby_user_id TEXT, emby_username TEXT UNIQUE,
                expiry_date TEXT, points INTEGER DEFAULT 0, max_devices INTEGER DEFAULT 2,
                is_disabled INTEGER DEFAULT 0, last_checkin TEXT, created_at TEXT
            )
        """)
        await conn.commit()

    db = Database(db_path)
    await db.init_db()
    await db.create_user_record(1006, "emby_uid_1006", "testuser1006")
    await db.update_user_status(1006, True, reason="admin")
    assert (await db.get_user_by_tg(1006))["disabled_reason"] == "admin"
    await db.update_user_status(1006, False)
    assert (await db.get_user_by_tg(1006))["disabled_reason"] is None

@pytest.mark.asyncio
async def test_reactivation_updates_local_status_only_after_emby_success():
    class FakeDb:
        def __init__(self):
            self.user = {"tg_id": 1005, "emby_user_id": "emby_uid_5", "is_disabled": 1, "disabled_reason": "expired"}
            self.status_updates = []

        async def get_user_by_tg(self, tg_id):
            return self.user

        async def update_user_status(self, tg_id, disabled, reason=None):
            self.status_updates.append((tg_id, disabled))
            self.user["is_disabled"] = int(disabled)
            self.user["disabled_reason"] = reason if disabled else None

    class FakeEmby:
        def __init__(self, succeeds):
            self.succeeds = succeeds
            self.calls = []

        async def set_user_disabled(self, emby_user_id, disabled):
            self.calls.append((emby_user_id, disabled))
            return self.succeeds

    bot = object.__new__(LemonEmbyBot)
    bot.db = FakeDb()
    bot.emby = FakeEmby(False)

    assert await bot._reactivate_if_disabled(1005) is False
    assert bot.db.user["is_disabled"] == 1
    assert bot.db.status_updates == []

    bot.emby.succeeds = True
    assert await bot._reactivate_if_disabled(1005) is True
    assert bot.db.user["is_disabled"] == 0
    assert bot.db.status_updates == [(1005, False)]

@pytest.mark.asyncio
async def test_renewal_does_not_override_admin_or_legacy_disabled_status():
    class FakeDb:
        def __init__(self, reason):
            self.user = {"tg_id": 1007, "emby_user_id": "emby_uid_7", "is_disabled": 1, "disabled_reason": reason}
            self.status_updates = []

        async def get_user_by_tg(self, tg_id):
            return self.user

        async def update_user_status(self, tg_id, disabled, reason=None):
            self.status_updates.append((tg_id, disabled, reason))

    class FakeEmby:
        def __init__(self):
            self.calls = []

        async def set_user_disabled(self, emby_user_id, disabled):
            self.calls.append((emby_user_id, disabled))
            return True

    for reason in ("admin", None):
        db = FakeDb(reason)
        emby = FakeEmby()
        bot = object.__new__(LemonEmbyBot)
        bot.db, bot.emby = db, emby

        assert await bot._reactivate_if_disabled(1007) is False
        assert db.user["is_disabled"] == 1
        assert db.status_updates == []
        assert emby.calls == []

@pytest.mark.asyncio
async def test_stop_session_reports_emby_failure():
    client = EmbyClient("http://127.0.0.1:8096", "dummy")
    endpoints = []

    async def failed_request(method, endpoint, **kwargs):
        endpoints.append(endpoint)
        return None

    client._request = failed_request
    assert await client.stop_session("session-1") is False
    assert endpoints[-1].endswith("/Playing/Stop")

    async def successful_stop(method, endpoint, **kwargs):
        return "" if endpoint.endswith("/Playing/Stop") else None

    client._request = successful_stop
    assert await client.stop_session("session-1") is True

@pytest.mark.asyncio
async def test_scheduler_does_not_claim_failed_session_was_stopped():
    class FakeDb:
        async def get_user_by_emby_id(self, emby_user_id):
            return {"tg_id": 3001, "emby_username": "viewer", "max_devices": 1}

    class FakeEmby:
        async def get_active_sessions(self):
            return [
                {"UserId": "emby-1", "Id": "session-1", "NowPlayingItem": {"Name": "movie"}},
                {"UserId": "emby-1", "Id": "session-2", "NowPlayingItem": {"Name": "movie"}},
            ]

        async def stop_session(self, session_id, message):
            return False

    notifications = []

    async def notify(tg_id, message):
        notifications.append((tg_id, message))

    scheduler = BackgroundScheduler(
        FakeDb(), FakeEmby(), {"emby": {"default_max_devices": 1}}, notify_func=notify
    )
    await scheduler.check_concurrency()

    assert notifications == []


@pytest.mark.asyncio
async def test_scheduler_handles_legacy_naive_expiry_timestamp(test_db):
    import aiosqlite

    await test_db.create_user_record(
        9010, "emby_legacy_expiry", "legacy_expiry_user", days=30
    )
    legacy_expiry = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).replace(tzinfo=None).isoformat()
    async with aiosqlite.connect(test_db.db_path) as conn:
        await conn.execute(
            "UPDATE users SET expiry_date = ? WHERE tg_id = ?",
            (legacy_expiry, 9010),
        )
        await conn.commit()

    class FakeEmby:
        def __init__(self):
            self.calls = []

        async def set_user_disabled(self, emby_user_id, disabled):
            self.calls.append((emby_user_id, disabled))
            return True

    emby = FakeEmby()
    scheduler = BackgroundScheduler(
        test_db, emby, {"rules": {"auto_disable_expired": True}}
    )

    await scheduler.check_expirations()

    user = await test_db.get_user_by_tg(9010)
    assert user["is_disabled"] == 1
    assert user["disabled_reason"] == "expired"
    assert emby.calls == [("emby_legacy_expiry", True)]


@pytest.mark.asyncio
async def test_password_commands_are_restricted_to_private_chats():
    class FakeMessage:
        reply_to_message = None

        def __init__(self):
            self.replies = []
            self.delete_calls = 0

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

        async def delete(self):
            self.delete_calls += 1

    bot = object.__new__(LemonEmbyBot)
    bot.admin_ids = [101]
    bot.db = object()
    bot.emby = object()
    msg = FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=101),
        effective_chat=SimpleNamespace(type="group"),
        message=msg,
    )

    await bot.cmd_resetpw(update, SimpleNamespace(args=["sensitive-password"]))
    await bot.cmd_create(update, SimpleNamespace(args=["newuser", "sensitive-password"]))

    assert len(msg.replies) == 2
    assert all("私聊" in reply for reply in msg.replies)
    assert msg.delete_calls == 2

@pytest.mark.asyncio
async def test_group_gen_does_not_generate_or_disclose_codes():
    class FakeMessage:
        def __init__(self):
            self.deleted = False
            self.replies = []

        async def delete(self):
            self.deleted = True

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    bot = object.__new__(LemonEmbyBot)
    bot.admin_ids = [101]
    bot.db = SimpleNamespace(generate_code=AsyncMock())
    msg = FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=101),
        effective_chat=SimpleNamespace(type="group"),
        message=msg,
    )

    await bot.cmd_gen(update, SimpleNamespace(args=["30", "3"]))

    assert msg.deleted is True
    assert len(msg.replies) == 1
    assert "私聊" in msg.replies[0]
    bot.db.generate_code.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_transfer_command_replies_without_renewal_state():
    class FakeMessage:
        reply_to_message = None

        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    bot = object.__new__(LemonEmbyBot)
    bot.db = SimpleNamespace(
        get_user_by_username=AsyncMock(),
        transfer_points=AsyncMock(return_value={
            "success": True, "amount": 10, "from_remaining": 20, "to_username": "recipient"
        }),
    )
    msg = FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=201),
        message=msg,
    )

    await bot.cmd_transfer(update, SimpleNamespace(args=["202", "10"]))

    assert bot.db.transfer_points.await_count == 1
    assert "积分转账成功" in msg.replies[0]

@pytest.mark.asyncio
async def test_group_redeem_deletes_command_and_does_not_consume_code():
    class FakeMessage:
        async def delete(self):
            self.deleted = True

        async def reply_text(self, text, **kwargs):
            self.reply = text

    bot = object.__new__(LemonEmbyBot)
    bot.db = SimpleNamespace(redeem_code=AsyncMock())
    msg = FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=301),
        effective_chat=SimpleNamespace(type="group"),
        message=msg,
    )

    await bot.cmd_redeem(update, SimpleNamespace(args=["LEMON-SECRET-CODE"]))

    assert msg.deleted is True
    assert "私聊" in msg.reply
    bot.db.redeem_code.assert_not_awaited()

@pytest.mark.asyncio
async def test_failed_emby_delete_keeps_local_account_record():
    class FakeMessage:
        reply_to_message = None

        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    bot = object.__new__(LemonEmbyBot)
    bot.admin_ids = [1]
    bot.db = SimpleNamespace(
        get_user_by_identifier=AsyncMock(return_value={
            "tg_id": 401, "emby_user_id": "emby401", "emby_username": "viewer"
        }),
        delete_user_record=AsyncMock(),
        log_action=AsyncMock(),
    )
    bot.emby = SimpleNamespace(delete_user=AsyncMock(return_value=False))
    msg = FakeMessage()

    await bot.cmd_deluser(
        SimpleNamespace(effective_user=SimpleNamespace(id=1), message=msg),
        SimpleNamespace(args=["401"]),
    )

    bot.db.delete_user_record.assert_not_awaited()
    assert "Emby 删除失败" in msg.replies[0]

@pytest.mark.asyncio
async def test_create_user_cleans_up_when_password_or_template_application_fails():
    client = EmbyClient("http://127.0.0.1:8096", "dummy")
    client._request = AsyncMock(side_effect=[{"Id": "new-user"}, ""])
    client.update_user_password = AsyncMock(return_value=False)

    assert await client.create_user("name", "password") is None
    assert client._request.await_args_list[-1].args[:2] == ("DELETE", "/Users/new-user")

    client = EmbyClient("http://127.0.0.1:8096", "dummy", template_user_id="template")
    client._request = AsyncMock(side_effect=[{"Id": "new-user"}, ""])
    client.update_user_password = AsyncMock(return_value=True)
    client.get_user = AsyncMock(return_value=None)

    assert await client.create_user("name", "password") is None
    assert client._request.await_args_list[-1].args[:2] == ("DELETE", "/Users/new-user")

    client = EmbyClient("http://127.0.0.1:8096", "dummy", template_user_id="template")
    client._request = AsyncMock(side_effect=[{"Id": "new-user"}, None, ""])
    client.update_user_password = AsyncMock(return_value=True)
    client.get_user = AsyncMock(return_value={"Policy": {"IsAdministrator": True}})

    assert await client.create_user("name", "password") is None
    assert client._request.await_args_list[1].kwargs["json"]["IsAdministrator"] is False
    assert client._request.await_args_list[-1].args[:2] == ("DELETE", "/Users/new-user")

@pytest.mark.asyncio
async def test_admin_create_stops_if_existing_emby_password_update_fails():
    class FakeMessage:
        reply_to_message = None

        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    bot = object.__new__(LemonEmbyBot)
    bot.admin_ids = [1]
    bot.config = {}
    bot.db = SimpleNamespace(
        get_user_by_username=AsyncMock(return_value=None),
        get_user_by_emby_id=AsyncMock(return_value=None),
        create_user_record=AsyncMock(return_value=True),
        log_action=AsyncMock(),
    )
    bot.emby = SimpleNamespace(
        get_user_by_name=AsyncMock(return_value={"Id": "existing-user"}),
        update_user_password=AsyncMock(return_value=False),
        set_user_disabled=AsyncMock(return_value=True),
    )
    msg = FakeMessage()

    await bot.cmd_create(
        SimpleNamespace(
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(type="private"),
            message=msg,
        ),
        SimpleNamespace(args=["existing", "password"]),
    )

    bot.db.create_user_record.assert_not_awaited()
    assert "设置密码" in msg.replies[0]

@pytest.mark.asyncio
async def test_ban_commands_do_not_update_local_state_when_emby_fails():
    class FakeMessage:
        reply_to_message = None

        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    bot = object.__new__(LemonEmbyBot)
    bot.admin_ids = [1]
    bot.db = SimpleNamespace(
        get_user_by_emby_id=AsyncMock(return_value={"tg_id": 501}),
        update_user_status=AsyncMock(),
    )
    bot.emby = SimpleNamespace(
        get_user_by_name=AsyncMock(return_value={"Id": "emby501"}),
        set_user_disabled=AsyncMock(return_value=False),
    )
    msg = FakeMessage()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=1), message=msg)

    await bot.cmd_ban(update, SimpleNamespace(args=["viewer"]))
    await bot.cmd_unban(update, SimpleNamespace(args=["viewer"]))

    bot.db.update_user_status.assert_not_awaited()
    assert all("失败" in reply for reply in msg.replies)

@pytest.mark.asyncio
async def test_atomic_double_spend_prevention(test_db):
    import asyncio
    await test_db.create_user_record(1001, "emby_uid_1", "testuser1", days=30)
    await test_db.add_user_points(1001, 50)
    u = await test_db.get_user_by_tg(1001)
    assert u is not None and u.get("points") == 50

    tasks = [test_db.exchange_item(1001, "days_7") for _ in range(5)]
    results = await asyncio.gather(*tasks)
    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1
    assert len(failures) == 4
    u_after = await test_db.get_user_by_tg(1001)
    assert u_after is not None and u_after.get("points") == 0

@pytest.mark.asyncio
async def test_concurrent_lottery_draws_charge_and_apply_prizes_atomically(test_db, monkeypatch):
    import asyncio
    await test_db.create_user_record(1006, "emby_uid_6", "testuser6", days=30)
    await test_db.add_user_points(1006, 40)
    monkeypatch.setattr("core.database.random.random", lambda: 0.99)

    results = await asyncio.gather(*(test_db.lottery_draw(1006, cost=20) for _ in range(5)))

    assert sum(result["success"] for result in results) == 2
    assert (await test_db.get_user_by_tg(1006))["points"] == 0

@pytest.mark.asyncio
async def test_atomic_card_redemption(test_db):
    import asyncio
    code = await test_db.generate_code("days", 30, created_by=999)
    assert code.startswith("LEMON-")

    for uid in range(2001, 2006):
        await test_db.create_user_record(uid, f"emby_{uid}", f"user_{uid}", days=10)

    tasks = [test_db.redeem_code(uid, code) for uid in range(2001, 2006)]
    results = await asyncio.gather(*tasks)
    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1
    assert len(failures) == 4

@pytest.mark.asyncio
async def test_mini_games(test_db):
    await test_db.create_user_record(2001, "emby_2001", "user_2001", days=10)
    await test_db.create_user_record(2002, "emby_2002", "user_2002", days=10)
    await test_db.add_user_points(2001, 100)
    await test_db.add_user_points(2002, 100)

    dice_res = await test_db.game_dice_bot(2001, bet=20)
    assert dice_res["success"] is True
    assert dice_res["outcome"] in ("win", "lose", "tie")

    pvp_res = await test_db.game_pvp_dice_resolve(2001, 2002, bet=20)
    assert pvp_res["success"] is True

@pytest.mark.asyncio
async def test_game_settlement_failures_roll_back_all_balances(test_db):
    import aiosqlite
    from unittest.mock import patch

    for tg_id in range(8001, 8007):
        await test_db.create_user_record(tg_id, f"emby_{tg_id}", f"user_{tg_id}", days=30)
        await test_db.add_user_points(tg_id, 100)

    async with aiosqlite.connect(test_db.db_path) as conn:
        await conn.execute("""
            CREATE TRIGGER reject_game_payout
            BEFORE UPDATE OF points ON users
            WHEN NEW.tg_id IN (8001, 8003, 8005) AND NEW.points > OLD.points
            BEGIN SELECT RAISE(ABORT, 'injected payout failure'); END
        """)
        await conn.commit()

    with patch("core.database.random.randint", side_effect=[6, 1]):
        with pytest.raises(aiosqlite.IntegrityError):
            await test_db.game_dice_bot(8001, bet=20)
    assert (await test_db.get_user_by_tg(8001))["points"] == 100

    with patch("core.database.random.randint", side_effect=[1, 6]):
        with pytest.raises(aiosqlite.IntegrityError):
            await test_db.game_pvp_dice_resolve(8002, 8003, bet=20)
    assert (await test_db.get_user_by_tg(8002))["points"] == 100
    assert (await test_db.get_user_by_tg(8003))["points"] == 100

    with patch("core.database.random.random", return_value=0.0), \
         patch("core.database.random.randint", return_value=25):
        with pytest.raises(aiosqlite.IntegrityError):
            await test_db.game_rob(8005, 8006)
    assert (await test_db.get_user_by_tg(8005))["points"] == 100
    assert (await test_db.get_user_by_tg(8006))["points"] == 100

@pytest.mark.asyncio
async def test_points_transfer_and_leaderboard(test_db):
    await test_db.create_user_record(3001, "emby_3001", "rich_user", days=10)
    await test_db.create_user_record(3002, "emby_3002", "poor_user", days=10)
    await test_db.add_user_points(3001, 200)

    trans_res = await test_db.transfer_points(3001, 3002, 80)
    assert trans_res["success"] is True
    assert trans_res["amount"] == 80
    assert trans_res["from_remaining"] == 120

    poor = await test_db.get_user_by_tg(3002)
    assert poor.get("points") == 80

    lb = await test_db.get_leaderboard(limit=5)
    assert len(lb) >= 2
    assert lb[0]["tg_id"] == 3001

@pytest.mark.asyncio
async def test_concurrent_transfers_are_atomic(test_db):
    import asyncio
    await test_db.create_user_record(4001, "emby_4001", "sender", days=10)
    await test_db.create_user_record(4002, "emby_4002", "recipient", days=10)
    await test_db.add_user_points(4001, 100)

    results = await asyncio.gather(*(test_db.transfer_points(4001, 4002, 60) for _ in range(5)))

    assert sum(result["success"] for result in results) == 1
    assert (await test_db.get_user_by_tg(4001))["points"] == 40
    assert (await test_db.get_user_by_tg(4002))["points"] == 60

def test_web_auth_failure_tracking_is_bounded_lru_and_expires(monkeypatch):
    FAILED_ATTEMPTS.clear()
    now = [100.0]
    monkeypatch.setattr(web_api, "MAX_TRACKED_IPS", 2)
    monkeypatch.setattr(web_api.time, "monotonic", lambda: now[0])

    try:
        for _ in range(web_api.MAX_FAILS):
            web_api.record_failed_attempt("client-a")
        web_api.record_failed_attempt("client-b")

        with pytest.raises(web_api.HTTPException):
            web_api.check_ip_rate_limit("client-a")
        web_api.record_failed_attempt("client-c")

        assert list(FAILED_ATTEMPTS) == ["client-a", "client-c"]
        with pytest.raises(web_api.HTTPException):
            web_api.check_ip_rate_limit("client-a")

        now[0] += web_api.LOCKOUT_SECONDS + 1
        web_api.check_ip_rate_limit("client-a")
        assert "client-a" not in FAILED_ATTEMPTS
    finally:
        FAILED_ATTEMPTS.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["accept", "reject"])
async def test_bystander_cannot_accept_or_reject_duel(action):
    bot = object.__new__(LemonEmbyBot)
    bot.admin_ids = []
    bot.pending_duels = {
        "duel1234": {"u1_tg": 1001, "u2_tg": 1002, "bet": 10}
    }
    query = SimpleNamespace(
        data=f"cb_{action}_duel_duel1234",
        from_user=SimpleNamespace(id=1003),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )

    await bot.handle_callback(SimpleNamespace(callback_query=query), SimpleNamespace())

    assert "duel1234" in bot.pending_duels
    query.answer.assert_awaited_once_with("这不是发给你的决斗挑战哦！", show_alert=True)
    query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_duel_target_can_accept_pending_duel_once():
    bot = object.__new__(LemonEmbyBot)
    bot.admin_ids = []
    bot.pending_duels = {
        "duel5678": {
            "u1_tg": 1001, "u2_tg": 1002, "u1_name": "Alice",
            "u2_name": "Bob", "bet": 10
        }
    }
    bot.db = SimpleNamespace(game_pvp_dice_resolve=AsyncMock(return_value={
        "success": True, "outcome": "tie", "u1_roll": 3, "u2_roll": 3,
        "u1_name": "Alice", "u2_name": "Bob", "bet": 10
    }))
    query = SimpleNamespace(
        data="cb_accept_duel_duel5678",
        from_user=SimpleNamespace(id=1002),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )

    await bot.handle_callback(SimpleNamespace(callback_query=query), SimpleNamespace())

    assert "duel5678" not in bot.pending_duels
    bot.db.game_pvp_dice_resolve.assert_awaited_once_with(1001, 1002, 10)
    query.answer.assert_awaited_once_with()
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_help_marks_sensitive_commands_private():
    bot = object.__new__(LemonEmbyBot)
    bot.admin_ids = [1001]
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1001),
        message=message,
    )

    await bot.cmd_help(update, SimpleNamespace())

    help_text = message.reply_text.await_args.args[0]
    for command in ("/bind", "/redeem", "/resetpw"):
        line = next(line for line in help_text.splitlines() if command in line)
        assert "仅限私聊" in line
    assert "随机密码私聊发送" in help_text
    assert "指定密码请在私聊操作" in help_text


@pytest.mark.asyncio
async def test_group_create_requires_reply_target_to_avoid_orphan_accounts():
    bot = object.__new__(LemonEmbyBot)
    bot.admin_ids = [1001]
    bot.db = SimpleNamespace(get_user_by_username=AsyncMock())
    message = SimpleNamespace(
        reply_to_message=None,
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1001),
        effective_chat=SimpleNamespace(type="group"),
        message=message,
    )

    await bot.cmd_create(update, SimpleNamespace(args=["orphan-account"]))

    bot.db.get_user_by_username.assert_not_awaited()
    guidance = message.reply_text.await_args.args[0]
    assert "回复目标群友的消息" in guidance
    assert "私聊" in guidance


def test_web_api_security():
    FAILED_ATTEMPTS.clear()
    import asyncio
    db = Database(TEST_DB_PATH)
    asyncio.run(db.init_db())

    cfg = {
        "server": {"secret_key": "test-super-secret-key-12345"},
        "emby": {"server_url": "http://127.0.0.1:8096", "api_key": "dummy"}
    }
    emby = EmbyClient(cfg["emby"]["server_url"], cfg["emby"]["api_key"])
    app = create_app(cfg, db, emby)
    client = TestClient(app)

    try:
        index = client.get("/")
        assert index.status_code == 200
        policy = index.headers["content-security-policy"]
        assert "script-src 'self';" in policy
        assert "unsafe-eval" not in policy
        assert "frame-ancestors 'none'" in policy
        assert index.headers["x-content-type-options"] == "nosniff"
        assert "https://" not in index.text
        assert "/static/app.css" in index.text
        assert "/static/app.js" in index.text
        assert "/static/app-template.js" in index.text
        assert "/static/vendor/vue.runtime.global.prod.js" in index.text
        for asset in (
            "/static/app.css",
            "/static/app.js",
            "/static/app-template.js",
            "/static/vendor/vue.runtime.global.prod.js",
            "/static/vendor/fontawesome/css/all.min.css",
            "/static/vendor/fontawesome/webfonts/fa-solid-900.woff2",
        ):
            assert client.get(asset).status_code == 200

        template_js = client.get("/static/app-template.js")
        assert "LemonAdminRender" in template_js.text
        assert "new Function" not in template_js.text

        r1 = client.get("/api/users")
        assert r1.status_code == 401

        for _ in range(5):
            client.get("/api/users", headers={"x-admin-token": "wrong_key"})

        r_locked = client.get("/api/users", headers={"x-admin-token": "wrong_key"})
        assert r_locked.status_code == 429

        FAILED_ATTEMPTS.clear()
        r_valid = client.get("/api/users", headers={"x-admin-token": "test-super-secret-key-12345"})
        assert r_valid.status_code == 200

        r_gen = client.post(
            "/api/codes/generate",
            headers={"x-admin-token": "test-super-secret-key-12345"},
            json={"card_type": "days", "value": 30, "count": 3}
        )
        assert r_gen.status_code == 200
        assert len(r_gen.json()["codes"]) == 3
    finally:
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
