"""Tests for Mukha native ES modules serving and static integrity (Phase 4)."""

from __future__ import annotations

import urllib.request

from sarathi.mukha.web.server import MukhaWebServer


def _http_get(url: str) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers={"Host": "127.0.0.1"})
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            status = resp.status
            data = resp.read()
            headers = {k.lower(): v for k, v in resp.getheaders()}
            return status, data, headers
    except urllib.error.HTTPError as err:
        return err.code, err.read(), {k.lower(): v for k, v in err.headers.items()}


def test_app_html_loads_modular_script(web_server: MukhaWebServer) -> None:
    """app.html must reference app.js as a native ES module."""
    status, data, headers = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/")
    assert status == 200
    html = data.decode("utf-8")
    assert '<script type="module" src="/app.js"></script>' in html
    assert headers["content-type"].startswith("text/html")


def test_app_js_composition_root_served(web_server: MukhaWebServer) -> None:
    """app.js composition root must be served with javascript MIME type and valid imports."""
    status, data, headers = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/app.js")
    assert status == 200
    js = data.decode("utf-8")
    assert headers["content-type"].startswith("application/javascript")
    assert 'import { initDom, elements, hideError } from "./js/dom.js";' in js or 'from "./js/dom.js"' in js
    assert 'import { state, switchScreen, registerScreenCallback } from "./js/state.js";' in js or 'from "./js/state.js"' in js


def test_native_es_modules_served_cleanly(web_server: MukhaWebServer) -> None:
    """All native ES modules in /js/ must be served with correct content-type."""
    modules = [
        "/js/formatters.js",
        "/js/dom.js",
        "/js/state.js",
        "/js/api.js",
        "/js/preview.js",
        "/js/screens/home.js",
        "/js/screens/monitor.js",
        "/js/screens/review.js",
        "/js/screens/summary.js",
        "/js/screens/inspector.js",
    ]

    for mod in modules:
        status, data, headers = _http_get(f"http://127.0.0.1:{web_server.resolved_port}{mod}")
        assert status == 200, f"Module {mod} returned status {status}"
        assert headers["content-type"].startswith("application/javascript")
        assert len(data) > 50, f"Module {mod} was empty or truncated"


def test_js_endpoint_rejects_traversal(web_server: MukhaWebServer) -> None:
    """Attempting path traversal in /js/ endpoint must be blocked with HTTP 400."""
    status, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/js/..%2F..%2Fsecret.py")
    assert status == 400


def test_inspector_tabs_and_containers_integrity(web_server: MukhaWebServer) -> None:
    """Every inspector tab button in app.html must have a corresponding container in app.html and match inspector.js."""
    import re

    # Fetch app.html
    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/")
    assert status == 200
    html = data.decode("utf-8")

    # Find all data-tab values in inspector sub-nav
    tabs = re.findall(r'class="inspector-tab[^"]*"\s+data-tab="([^"]+)"', html)
    assert set(tabs) == {"activity", "performance", "quality", "system"}

    # Verify each tab has a matching container id="tab-inspector-<tab>"
    for tab in tabs:
        expected_id = f'id="tab-inspector-{tab}"'
        assert expected_id in html, f"Missing container {expected_id} in app.html"

    # Verify inspector.js matches tab-inspector- IDs and toggles hidden class
    status_js, data_js, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/js/screens/inspector.js")
    assert status_js == 200
    js = data_js.decode("utf-8")
    assert "tab-inspector-${state.activeInspectorTab}" in js
    assert 'c.classList.toggle("hidden"' in js
