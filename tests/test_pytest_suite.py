import pytest
import pytest_asyncio
import os
import sys

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.database import Database
from core.emby import EmbyClient
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
