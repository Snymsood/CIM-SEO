"""The PageSpeed fetch should recover from transient rate limits."""

import asyncio

import site_speed_monitoring as speed


class _Response:
    def __init__(self, status, payload=None):
        self.status = status
        self.ok = status == 200
        self.headers = {}
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def json(self):
        return self.payload

    async def text(self):
        return "rate limited"

    def raise_for_status(self):
        raise RuntimeError(f"HTTP {self.status}")


class _Session:
    def __init__(self):
        self.responses = [_Response(429), _Response(200, {"ok": True})]
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return self.responses.pop(0)


def test_pagespeed_retries_rate_limit(monkeypatch):
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(speed.asyncio, "sleep", fake_sleep)
    session = _Session()
    result = asyncio.run(speed.fetch_pagespeed_async(session, "https://www.cim.org/"))
    assert result == {"ok": True}
    assert session.calls == 2
    assert waits == [2]
