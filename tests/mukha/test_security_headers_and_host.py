"""Regression tests for Mukha Web Server Host validation and Security Headers.

Verifies:
- H.1: Structural Host and Origin parsing (rejecting malicious prefixes, suffixes, invalid ports).
- H.2: Centralized security headers (CSP, Referrer-Policy, X-Content-Type-Options, Cache-Control).
"""

from __future__ import annotations

import http.client
from pathlib import Path

import pytest

from sarathi.mukha.web.security import (
    _is_authorized_loopback_host,
    _is_authorized_loopback_origin,
)
from sarathi.mukha.web.server import MukhaWebServer


class TestStructuralHostValidation:
    @pytest.mark.parametrize(
        "valid_host",
        [
            "localhost",
            "localhost:8000",
            "127.0.0.1",
            "127.0.0.1:8080",
            "[::1]",
            "[::1]:9000",
            "localhost:65535",
        ],
    )
    def test_authorized_loopback_hosts(self, valid_host: str) -> None:
        assert _is_authorized_loopback_host(valid_host) is True

    @pytest.mark.parametrize(
        "invalid_host",
        [
            "localhost.attacker.example",
            "127.0.0.1.attacker.example",
            "localhostevil",
            "127.0.0.1evil",
            "[::1]evil",
            "localhost:0",
            "localhost:70000",
            "localhost:-1",
            "localhost:abc",
            "evil.com",
            "192.168.1.1",
            "",
            "   ",
            "[malformed_ipv6",
        ],
    )
    def test_rejected_hosts(self, invalid_host: str) -> None:
        assert _is_authorized_loopback_host(invalid_host) is False

    @pytest.mark.parametrize(
        "valid_origin",
        [
            "http://localhost",
            "http://localhost:8000",
            "http://127.0.0.1:8080",
            "https://[::1]:9000",
        ],
    )
    def test_authorized_loopback_origins(self, valid_origin: str) -> None:
        assert _is_authorized_loopback_origin(valid_origin) is True

    @pytest.mark.parametrize(
        "invalid_origin",
        [
            "http://localhost.attacker.example",
            "http://127.0.0.1.attacker.example",
            "http://evil.com",
            "ftp://localhost:8000",
            "http://localhost:0",
            "http://localhost:70000",
            "",
        ],
    )
    def test_rejected_origins(self, invalid_origin: str) -> None:
        assert _is_authorized_loopback_origin(invalid_origin) is False


class TestMukhaWebServerSecurityHeaders:
    @staticmethod
    def _headers(response: http.client.HTTPResponse) -> dict[str, str]:
        """Normalize HTTP header names because field names are case-insensitive."""
        return {name.lower(): value for name, value in response.getheaders()}

    def test_live_server_rejects_malicious_host_header(self, web_server: MukhaWebServer) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", web_server.resolved_port)
        conn.putrequest("GET", "/api/state", skip_host=True)
        conn.putheader("Host", "localhost.attacker.example")
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 403
        data = response.read().decode("utf-8")
        assert "Forbidden Host header" in data
        conn.close()

    def test_live_server_security_headers_on_api_state(self, web_server: MukhaWebServer) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", web_server.resolved_port)
        conn.putrequest("GET", "/api/state", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{web_server.resolved_port}")
        conn.putheader("Cookie", f"sarathi_session={web_server.auth_token}")
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 200

        headers = self._headers(response)
        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert headers.get("x-frame-options") == "DENY"
        assert "default-src 'self'" in headers.get("content-security-policy", "")
        assert headers.get("cache-control") == "no-store"
        conn.close()

    def test_live_server_security_headers_on_static_resource(self, web_server: MukhaWebServer) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", web_server.resolved_port)
        conn.putrequest("GET", "/", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{web_server.resolved_port}")
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 200

        headers = self._headers(response)
        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert headers.get("x-frame-options") == "DENY"
        assert "default-src 'self'" in headers.get("content-security-policy", "")
        assert headers.get("cache-control") == "no-cache"
        conn.close()


def test_bug_S1_web_security_and_auth(tmp_path: Path) -> None:
    """S1: Verify session token authentication on /api/** and allowlist-root path containment on /api/preview*."""
    from starlette.testclient import TestClient

    from sarathi.agni import Agni
    from sarathi.mukha.web import MukhaWebServer

    input_dir = tmp_path / "Input"
    input_dir.mkdir()
    output_dir = tmp_path / "Output"
    output_dir.mkdir()
    runtime_dir = tmp_path / "Runtime"
    runtime_dir.mkdir()
    outside_dir = tmp_path / "Outside"
    outside_dir.mkdir()

    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("classified data", encoding="utf-8")

    allowed_file = input_dir / "sample.txt"
    allowed_file.write_text("public input data", encoding="utf-8")

    # Symlink inside allowed root pointing outside
    symlink_file = input_dir / "symlink_secret.txt"
    try:
        symlink_file.symlink_to(outside_file)
        has_symlink = True
    except OSError:
        has_symlink = False

    with Agni(runtime_root=runtime_dir, output_root=output_dir, input_root=input_dir) as agni:
        server = MukhaWebServer(agni=agni, host="127.0.0.1", port=0)
        client = TestClient(server._asgi_app, base_url="http://127.0.0.1")

        # 1. Every /api/** route returns 401/403 without the token cookie
        for route in ("/api/state", "/api/history", "/api/review"):
            resp = client.get(route)
            assert resp.status_code in (401, 403), (
                f"Route {route} was accessible without auth (got {resp.status_code})"
            )

        # 2. Wrong token is rejected on GET /?t=...
        resp_wrong = client.get("/?t=wrong_token_12345", follow_redirects=False)
        assert resp_wrong.status_code in (401, 403)

        # 3. Valid token sets HttpOnly; SameSite=Strict cookie and redirects to /
        token = getattr(server, "auth_token", "test_token")
        resp_valid = client.get(f"/?t={token}", follow_redirects=False)
        assert resp_valid.status_code in (302, 303)
        assert resp_valid.headers.get("location") == "/"
        cookie_header = resp_valid.headers.get("set-cookie", "")
        assert "sarathi_session=" in cookie_header
        assert "httponly" in cookie_header.lower()
        assert "samesite=strict" in cookie_header.lower()

        # 4. With the session cookie, API calls work
        client.cookies.set("sarathi_session", token)
        resp_auth = client.get("/api/state")
        assert resp_auth.status_code == 200
        assert resp_auth.json().get("ok") is True

        # 5. File outside allowed roots is refused by all three /api/preview* routes
        for p_route in ("/api/preview", "/api/preview/raw", "/api/preview/pdf_page"):
            resp_outside = client.get(f"{p_route}?path={outside_file}")
            assert resp_outside.status_code in (400, 403), (
                f"{p_route} allowed outside path (got {resp_outside.status_code})"
            )

            if has_symlink:
                resp_symlink = client.get(f"{p_route}?path={symlink_file}")
                assert resp_symlink.status_code in (400, 403), (
                    f"{p_route} followed escaping symlink (got {resp_symlink.status_code})"
                )

        # 6. File inside allowed root is served
        resp_inside = client.get(f"/api/preview?path={allowed_file}")
        assert resp_inside.status_code == 200
        resp_inside_raw = client.get(f"/api/preview/raw?path={allowed_file}")
        assert resp_inside_raw.status_code == 200
