import logging
from contextlib import asynccontextmanager
import aiohttp
from aiohttp import web
import pytest
from core.emby import EmbyClient

TOKEN = "fixture-secret-not-a-live-key"

@asynccontextmanager
async def server(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()

@pytest.mark.asyncio
async def test_token_only_in_header_and_success_responses():
    requests = []
    async def handler(request):
        requests.append((dict(request.query), request.headers.get("X-Emby-Token")))
        return web.json_response({"Version": "fixture"}) if request.method == "GET" else web.Response(status=204)
    app = web.Application()
    app.router.add_route("*", "/System/Info", handler)
    async with server(app) as url:
        client = EmbyClient(url, TOKEN)
        assert await client.get_system_info() == {"Version": "fixture"}
        assert await client._request("POST", "/System/Info") == ""
    assert len(requests) == 2
    assert all(q == {} and header == TOKEN for q, header in requests)

@pytest.mark.asyncio
async def test_http_error_body_never_logged(caplog):
    async def handler(request):
        return web.Response(status=403, text="upstream reflected " + TOKEN)
    app = web.Application(); app.router.add_get("/System/Info", handler)
    async with server(app) as url:
        with caplog.at_level(logging.ERROR):
            assert await EmbyClient(url, TOKEN).get_system_info() is None
    assert TOKEN not in caplog.text
    assert "403" in caplog.text

@pytest.mark.asyncio
async def test_redirect_never_forwards_token(caplog):
    reached = []
    async def target(request):
        reached.append(request.headers.get("X-Emby-Token"))
        return web.json_response({"Version": "unexpected"})
    target_app = web.Application(); target_app.router.add_get("/target", target)
    async with server(target_app) as target_url:
        async def redirect(request):
            raise web.HTTPFound(target_url + "/target")
        app = web.Application(); app.router.add_get("/System/Info", redirect)
        async with server(app) as url:
            assert await EmbyClient(url, TOKEN).get_system_info() is None
    assert not reached
    assert TOKEN not in caplog.text

@pytest.mark.asyncio
async def test_connection_exception_never_logged_with_secret(monkeypatch, caplog):
    class BrokenRequest:
        async def __aenter__(self):
            raise aiohttp.ClientConnectionError("URL?api_key=" + TOKEN)
        async def __aexit__(self, *args):
            pass
    class Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def request(self, *args, **kwargs):
            return BrokenRequest()
    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    with caplog.at_level(logging.ERROR):
        assert await EmbyClient("http://127.0.0.1", TOKEN).get_system_info() is None
    assert TOKEN not in caplog.text
    assert "ClientConnectionError" in caplog.text
