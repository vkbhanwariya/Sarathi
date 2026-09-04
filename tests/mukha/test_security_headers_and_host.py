"""Regression tests for Mukha Web Server Host validation and Security Headers.

Verifies:
- H.1: Structural Host and Origin parsing (rejecting malicious prefixes, suffixes, invalid ports).
- H.2: Centralized security headers (CSP, Referrer-Policy, X-Content-Type-Options, Cache-Control).
"""

from __future__ import annotations

import http.client
import urllib.request
import pytest

from sarathi.mukha.web.server import (
    MukhaWebServer,
    _is_authorized_loopback_host,
    _is_authorized_loopback_origin,
)


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
        conn.putrequest("GET", "/api/state")
        conn.putheader("Host", f"127.0.0.1:{web_server.resolved_port}")
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 200

        headers = dict(response.getheaders())
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in headers.get("Content-Security-Policy", "")
        assert headers.get("Cache-Control") == "no-store"
        conn.close()

    def test_live_server_security_headers_on_static_resource(self, web_server: MukhaWebServer) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", web_server.resolved_port)
        conn.putrequest("GET", "/")
        conn.putheader("Host", f"127.0.0.1:{web_server.resolved_port}")
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 200

        headers = dict(response.getheaders())
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in headers.get("Content-Security-Policy", "")
        assert headers.get("Cache-Control") == "no-cache"
        conn.close()
