"""Iter35s — Regression test: _sms_send_generic must exist as a top-level
async function and properly route to the webhook bridge when
auth_type='webhook'.

Context: the previous agent's search_replace accidentally deleted the
`async def _sms_send_generic(...)` signature line, turning its body into
unreachable dead code inside _sms_send_via_webhook. The function symbol
was missing → NameError at runtime when sending SMS via Orange/Moov/Telecel.
"""
import asyncio
import inspect
import sys

sys.path.insert(0, "/app/backend")


class TestSmsSendGenericExists:
    def test_function_is_defined_and_async(self):
        from server import _sms_send_generic
        assert inspect.iscoroutinefunction(_sms_send_generic), (
            "_sms_send_generic must be an async function"
        )

    def test_webhook_auth_type_routes_to_webhook_bridge(self):
        """When auth_type='webhook' is configured, _sms_send_generic must
        delegate to _sms_send_via_webhook (no /outbound suffix added)."""
        from server import _sms_send_generic
        cfg = {
            "name": "orange",
            "kind": "generic",
            "auth_type": "webhook",
            "url": "https://httpbin.org/post",
        }
        r = asyncio.run(_sms_send_generic(cfg, "22607332313", "test iter35s", None))
        # httpbin echoes back: HTTP 200, no error → success
        assert r.get("http_status") == 200, r
        assert r.get("ok") is True, r
        # Ensure the URL was NOT mangled with a suffix
        echoed = r.get("raw_response", {})
        if isinstance(echoed, dict):
            url = echoed.get("url", "")
            # httpbin echoes the request URL
            assert "/outbound" not in url, f"URL was mangled: {url}"

    def test_empty_url_returns_failed_cleanly(self):
        from server import _sms_send_generic
        cfg = {"name": "orange", "kind": "generic", "auth_type": "none", "url": ""}
        r = asyncio.run(_sms_send_generic(cfg, "22607332313", "hi", None))
        assert r["ok"] is False
        assert "non configur" in (r.get("api_message") or "").lower()
