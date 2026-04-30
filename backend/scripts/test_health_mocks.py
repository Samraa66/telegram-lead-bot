"""
Shared HTTP and Telethon mocks for health-check unit tests.
Imported by every test_health_<check>.py script.
"""
from typing import Optional


class MockResponse:
    """Stand-in for an httpx.Response. Only the methods we use."""
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


class MockHttpClient:
    """
    Minimal httpx.AsyncClient stand-in. Pass a routes dict mapping URL prefix
    (or exact URL) -> (status_code, body). On each .get(), the first matching
    route wins. Calls are recorded in `.calls` for assertion.

    Special routes:
      - body == "TIMEOUT": raise httpx.TimeoutException on the call.
      - body == "NETWORK_ERROR": raise httpx.NetworkError on the call.
    """
    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    async def get(self, url: str, **kwargs):
        import httpx
        self.calls.append(url)
        for prefix, payload in self.routes.items():
            if url.startswith(prefix) or url == prefix:
                status, body = payload
                if body == "TIMEOUT":
                    raise httpx.TimeoutException("mocked timeout", request=None)
                if body == "NETWORK_ERROR":
                    raise httpx.NetworkError("mocked network error", request=None)
                return MockResponse(status, body)
        raise httpx.NetworkError(f"unmocked URL: {url}", request=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None


class MockTelethonClient:
    """
    Stand-in for a Telethon TelegramClient. Configure each return value in
    the constructor.
    """
    def __init__(
        self,
        connected: bool = True,
        authorized: bool = True,
        authorize_raises: Optional[Exception] = None,
        authorize_delay_s: float = 0.0,
    ):
        self._connected = connected
        self._authorized = authorized
        self._authorize_raises = authorize_raises
        self._authorize_delay_s = authorize_delay_s

    def is_connected(self) -> bool:
        return self._connected

    async def is_user_authorized(self) -> bool:
        if self._authorize_delay_s:
            import asyncio
            await asyncio.sleep(self._authorize_delay_s)
        if self._authorize_raises:
            raise self._authorize_raises
        return self._authorized
