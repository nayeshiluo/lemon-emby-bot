import pytest
import pytest_asyncio
import datetime
import os
import sys
from types import SimpleNamespace

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.telegram_bot import LemonEmbyBot
from core.database import Database
from core.emby import EmbyClient
from core.scheduler import BackgroundScheduler
from web.api import create_app, FAILED_ATTEMPTS
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

    expiry = test_db._as_utc((await test_db.get_user_by_tg(1004))["expiry_date"])
    assert expiry == test_db._as_utc(original) + datetime.timedelta(days=20)
    assert (await test_db.get_user_by_tg(1004))["is_disabled"] == 1

@pytest.mark.asyncio
async def test_reactivation_updates_local_status_only_after_emby_success():
    class FakeDb:
        def __init__(self):
            self.user = {"tg_id": 1005, "emby_user_id": "emby_uid_5", "is_disabled": 1}
            self.status_updates = []

        async def get_user_by_tg(self, tg_id):
            return self.user

        async def update_user_status(self, tg_id, disabled):
            self.status_updates.append((tg_id, disabled))
            self.user["is_disabled"] = int(disabled)

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
async def test_password_commands_are_restricted_to_private_chats():
    class FakeMessage:
        reply_to_message = None

        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

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
