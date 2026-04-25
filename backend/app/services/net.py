"""
Network helpers — primarily resolving the real client IP when the app sits
behind a reverse proxy (Cloudflare today, nginx tomorrow, both possible).

Header preference order:
  1. CF-Connecting-IP   — set by Cloudflare with the original client IP
  2. X-Forwarded-For    — set by nginx / generic load balancers; first hop wins
  3. request.client.host — direct connection (local dev, or no proxy)

If/when we want to harden against header spoofing, we should restrict trust
to Cloudflare's published IP ranges. For now we accept any inbound CF header
because the VPS firewall can be locked down to Cloudflare IPs separately.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request


def client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    headers = request.headers

    cf = headers.get("CF-Connecting-IP", "").strip()
    if cf:
        return cf[:64]

    xff = headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if xff:
        return xff[:64]

    if request.client and request.client.host:
        return request.client.host[:64]

    return None
