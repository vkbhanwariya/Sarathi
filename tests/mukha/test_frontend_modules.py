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


def test_root_serves_preact_shell(web_server: MukhaWebServer) -> None:
    """Root GET request must serve the Preact application index."""
    status, data, headers = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/")
    assert status == 200
    html = data.decode("utf-8")
    assert 'id="app"' in html
    assert '<script type="module" crossorigin src="/ui/app.js"></script>' in html
    assert headers["content-type"].startswith("text/html")


def test_ui_app_js_bundle_served(web_server: MukhaWebServer) -> None:
    """Preact app.js bundle must be served with javascript MIME type."""
    status, data, headers = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/app.js")
    assert status == 200
    js = data.decode("utf-8")
    assert headers["content-type"].startswith("application/javascript")
    assert "Sarathi" in js
    assert len(data) > 1000


def test_ui_app_css_served(web_server: MukhaWebServer) -> None:
    """Preact app.css stylesheet must be served with text/css MIME type."""
    status, data, headers = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/app.css")
    assert status == 200
    css = data.decode("utf-8")
    assert headers["content-type"].startswith("text/css")
    assert ":root" in css
    assert ".palette-dialog" in css
    assert ".preview-modal-dialog" in css


def test_ui_endpoint_rejects_traversal(web_server: MukhaWebServer) -> None:
    """Attempting invalid asset names or traversal in /ui/ endpoint must return 404."""
    status, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/..%2F..%2Fsecret.py")
    assert status == 404

    status_missing, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/nonexistent.js")
    assert status_missing == 404


def test_preview_dialog_and_close_button_contract(web_server: MukhaWebServer) -> None:
    """Verify document preview dialog structure and close contract exist in compiled Preact UI bundle."""
    status_app, data_app, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/app.js")
    assert status_app == 200
    app_js = data_app.decode("utf-8")
    assert "doc-preview-dialog" in app_js
    assert "btn-close-preview" in app_js
    assert "btn-pdf-prev" in app_js
    assert "btn-pdf-next" in app_js


def test_command_palette_contract_in_bundle(web_server: MukhaWebServer) -> None:
    """Verify command palette dialog and keyboard navigation elements exist in compiled Preact UI bundle."""
    status_app, data_app, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/app.js")
    assert status_app == 200
    app_js = data_app.decode("utf-8")
    assert "command-palette-dialog" in app_js
    assert "palette-search-input" in app_js
    assert "palette-command-list" in app_js
