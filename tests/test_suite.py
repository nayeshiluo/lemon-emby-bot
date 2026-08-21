import asyncio
import os
import sys

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.database import Database
from core.emby import EmbyClient
from web.api import create_app

TEST_DB_PATH = "test_lemon_emby.db"

class AsyncLemonTestSuite:
    def __init__(self):
        self.db = Database(TEST_DB_PATH)

    async def setup(self):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        await self.db.init_db()

    async def teardown(self):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

    async def test_user_lifecycle_and_checkin(self):
        print("  [1/6] 测试用户生命周期与签到体系...")
        # 1. Create user
        await self.db.create_user_record(1001, "emby_uid_1", "testuser1", days=30, max_devices=2)
        u = await self.db.get_user_by_tg(1001)
        assert u is not None, "用户记录创建失败"
        assert u.get("emby_username") == "testuser1"
        assert u.get("points") == 0
        assert u.get("max_devices") == 2

        # 2. Check-in
        res1 = await self.db.user_checkin(1001, reward_days=1, points=10)
        assert res1["success"] is True
        assert res1["points"] == 10
        assert res1["total_points"] == 10

        # Duplicate check-in same day
        res2 = await self.db.user_checkin(1001, reward_days=1, points=10)
        assert res2["success"] is False
        print("      ✓ 用户建档、签到加分与重复签到拦截正常")

    async def test_atomic_double_spend_prevention(self):
        print("  [2/6] 测试并发双花与竞态条件防御 (Anti-Double-Spend)...")
        # Give user 50 points
        await self.db.add_user_points(1001, 40) # Now user has 50 points
        u = await self.db.get_user_by_tg(1001)
        assert u is not None and u.get("points") == 50

        # Run 5 concurrent purchases that each cost 50 points
        # Exactly 1 must succeed, 4 must fail
        tasks = [self.db.exchange_item(1001, "days_7") for _ in range(5)]
        results = await asyncio.gather(*tasks)
        successes = [r for r in results if r["success"]]
        failures = [r for r in results if not r["success"]]

        assert len(successes) == 1, f"并发购买预期只有1次成功，实际成功: {len(successes)}"
        assert len(failures) == 4, f"并发购买预期有4次失败，实际失败: {len(failures)}"

        u_after = await self.db.get_user_by_tg(1001)
        assert u_after is not None and u_after.get("points") == 0, f"用户剩余积分异常"
        print("      ✓ 5个并发扣费请求中仅 1 个成功扣减，完美杜绝并发双花漏洞！")

    async def test_atomic_card_redemption(self):
        print("  [3/6] 测试卡密生成与并发抢兑 (Anti-Card-Snatching)...")
        code = await self.db.generate_code("days", 30, created_by=999)
        assert code.startswith("LEMON-")

        # Simulate 5 users trying to redeem the EXACT same card code at once
        for uid in range(2001, 2006):
            await self.db.create_user_record(uid, f"emby_{uid}", f"user_{uid}", days=10)

        tasks = [self.db.redeem_code(uid, code) for uid in range(2001, 2006)]
        results = await asyncio.gather(*tasks)
        successes = [r for r in results if r["success"]]
        failures = [r for r in results if not r["success"]]

        assert len(successes) == 1, f"卡密并发兑换预期仅1次成功，实际: {len(successes)}"
        assert len(failures) == 4, f"卡密并发兑换预期4次失败，实际: {len(failures)}"
        print("      ✓ 同一张卡密 5 人并发兑换，严格保证 1 成功 4 拦截！")

    async def test_mini_games(self):
        print("  [4/6] 测试游戏系统 (PvE骰子 / PvP决斗 / 打劫风控)...")
        # Give points
        await self.db.add_user_points(2001, 100)
        await self.db.add_user_points(2002, 100)

        # 1. PvE Dice
        dice_res = await self.db.game_dice_bot(2001, bet=20)
        assert dice_res["success"] is True
        assert dice_res["outcome"] in ("win", "lose", "tie")

        # 2. PvP Duel
        pvp_res = await self.db.game_pvp_dice_resolve(2001, 2002, bet=20)
        assert pvp_res["success"] is True
        assert pvp_res["outcome"] in ("u1_win", "u2_win", "tie")

        # 3. Rob
        rob_res = await self.db.game_rob(2001, 2002)
        assert rob_res["success"] is True
        assert rob_res["status"] in ("win", "lose")

        # 4. Lottery
        lot_res = await self.db.lottery_draw(2001, cost=20)
        assert lot_res["success"] is True
        print("      ✓ 掷骰、PvP 决斗、打劫攻防与抽奖逻辑运算正常")

    async def test_points_transfer_and_leaderboard(self):
        print("  [5/6] 测试积分转账与排行榜...")
        await self.db.add_user_points(2001, 100)
        trans_res = await self.db.transfer_points(2001, 2002, amount=30)
        assert trans_res["success"] is True
        assert trans_res["amount"] == 30

        # Insufficient transfer test
        trans_fail = await self.db.transfer_points(2001, 2002, amount=99999)
        assert trans_fail["success"] is False

        # Leaderboard
        board = await self.db.get_leaderboard(limit=5)
        assert len(board) > 0
        assert (board[0]["points"] or 0) >= (board[-1]["points"] or 0)
        print("      ✓ 积分安全转账与富豪榜排序校验通过")

    async def test_web_api_security(self):
        print("  [6/6] 测试 Web 管理 API 鉴权与防暴力破解...")
        from starlette.testclient import TestClient
        cfg = {
            "server": {"secret_key": "test-super-secret-key-12345"},
            "emby": {"server_url": "http://127.0.0.1:8096", "api_key": "dummy"}
        }
        emby = EmbyClient(cfg["emby"]["server_url"], cfg["emby"]["api_key"])
        app = create_app(cfg, self.db, emby)
        client = TestClient(app)

        # 1. Unauthorized request
        r1 = client.get("/api/users")
        assert r1.status_code == 401, f"未授权访问应返回 401，实际: {r1.status_code}"

        # 2. Test Brute Force Rate Limiting (5 failures -> 429)
        for _ in range(5):
            client.get("/api/users", headers={"x-admin-token": "wrong_key"})
        
        r_locked = client.get("/api/users", headers={"x-admin-token": "wrong_key"})
        assert r_locked.status_code == 429, f"连续错误鉴权应触发 429 防爆破封禁，实际: {r_locked.status_code}"

        # 3. Valid request
        from web.api import FAILED_ATTEMPTS
        FAILED_ATTEMPTS.clear()

        r_valid = client.get("/api/users", headers={"x-admin-token": "test-super-secret-key-12345"})
        assert r_valid.status_code == 200
        assert isinstance(r_valid.json(), list)

        # 4. Generate code via API with validation
        r_gen = client.post(
            "/api/codes/generate",
            headers={"x-admin-token": "test-super-secret-key-12345"},
            json={"card_type": "days", "value": 30, "count": 3}
        )
        assert r_gen.status_code == 200
        assert len(r_gen.json()["codes"]) == 3
        print("      ✓ Web API 鉴权拒绝(401)、防爆破封禁(429)与卡密生成(200)全部达标！")

async def main():
    print("\n========================================================")
    print("🍋 正在启动 Lemon Emby Bot 全功能与安全专项测试套件...")
    print("========================================================")
    suite = AsyncLemonTestSuite()
    await suite.setup()
    try:
        await suite.test_user_lifecycle_and_checkin()
        await suite.test_atomic_double_spend_prevention()
        await suite.test_atomic_card_redemption()
        await suite.test_mini_games()
        await suite.test_points_transfer_and_leaderboard()
        await suite.test_web_api_security()
        print("\n🎉 全部 6 大核心模块与安全测试用例【100% 通过】！")
    finally:
        await suite.teardown()

if __name__ == "__main__":
    asyncio.run(main())
