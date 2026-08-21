import aiohttp
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger("lemon-emby.emby_client")

class EmbyClient:
    """Async client for Emby Server REST API"""
    def __init__(self, server_url: str, api_key: str, template_user_id: Optional[str] = None):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.template_user_id = template_user_id
        self.headers = {
            "X-Emby-Token": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"{self.server_url}{endpoint}"
        params = kwargs.pop("params", {}) or {}
        params["api_key"] = self.api_key
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.request(method, url, params=params, headers=self.headers, timeout=10, **kwargs) as resp:
                    if resp.status in (200, 204):
                        if resp.content_type == "application/json" and resp.status == 200:
                            return await resp.json()
                        return await resp.text()
                    else:
                        error_text = await resp.text()
                        logger.error(f"Emby API Error [{resp.status}] on {method} {endpoint}: {error_text}")
                        return None
            except Exception as e:
                logger.error(f"Emby connection error: {e}")
                return None

    async def get_system_info(self) -> Optional[Dict[str, Any]]:
        """Fetch Emby system info / ping status"""
        return await self._request("GET", "/System/Info")

    async def get_users(self) -> List[Dict[str, Any]]:
        """List all users on the Emby server"""
        res = await self._request("GET", "/Users")
        return res if isinstance(res, list) else []

    async def get_user_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find a user by username"""
        users = await self.get_users()
        for u in users:
            if u.get("Name", "").lower() == name.lower():
                return u
        return None

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user details by ID"""
        return await self._request("GET", f"/Users/{user_id}")

    async def create_user(self, name: str, password: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a new user and optionally clone policy from template user"""
        res = await self._request("POST", "/Users/New", json={"Name": name})
        if not res or not isinstance(res, dict):
            return None
        
        user_id = res.get("Id")
        if not user_id:
            return None
        
        # Set password if provided
        if password:
            await self.update_user_password(user_id, password)

        # Clone policy and access from template user if configured
        if self.template_user_id:
            template_user = await self.get_user(self.template_user_id)
            if template_user and "Policy" in template_user:
                policy = template_user["Policy"]
                # Ensure new user is not admin even if template is
                policy["IsAdministrator"] = False
                await self._request("POST", f"/Users/{user_id}/Policy", json=policy)

        return res

    async def update_user_password(self, user_id: str, new_password: str) -> bool:
        """Update password for given user"""
        res = await self._request("POST", f"/Users/{user_id}/Password", json={
            "Id": user_id,
            "NewPw": new_password,
            "ResetPassword": False
        })
        return res is not None

    async def set_user_disabled(self, user_id: str, disabled: bool = True) -> bool:
        """Enable or disable user access"""
        user = await self.get_user(user_id)
        if not user:
            return False
        policy = user.get("Policy", {})
        policy["IsDisabled"] = disabled
        res = await self._request("POST", f"/Users/{user_id}/Policy", json=policy)
        return res is not None

    async def delete_user(self, user_id: str) -> bool:
        """Permanently delete user from Emby"""
        res = await self._request("DELETE", f"/Users/{user_id}")
        return res is not None

    async def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get currently active playback sessions"""
        res = await self._request("GET", "/Sessions")
        if not isinstance(res, list):
            return []
        # Filter for sessions that are actually playing media
        return [s for s in res if s.get("NowPlayingItem") is not None]

    async def stop_session(self, session_id: str, message: str = "已达到最大并发设备限制") -> bool:
        """Stop / kill a playback session"""
        res = await self._request("POST", f"/Sessions/{session_id}/Message", json={
            "Text": message,
            "TimeoutMs": 3000
        })
        # Command to stop playback
        await self._request("POST", f"/Sessions/{session_id}/Playing/Stop")
        return True
