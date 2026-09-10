"""Architecture gates for the Mukha ASGI transport boundary."""

from pathlib import Path


_WEB_ROOT = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "mukha" / "web"


def test_obsolete_http_handler_modules_are_absent() -> None:
    assert not (_WEB_ROOT / "http_handler.py").exists()
    assert not (_WEB_ROOT / "static_handler.py").exists()


def test_mukha_has_no_stdlib_handler_transport() -> None:
    forbidden = (
        "from http.server",
        "import http.server",
        "BaseHTTPRequestHandler",
        "ThreadingHTTPServer",
        ".send_response(",
        ".send_header(",
        ".end_headers(",
        ".wfile",
    )
    offenders: list[str] = []
    for path in sorted(_WEB_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(_WEB_ROOT)}: {token}")
    assert not offenders, "obsolete HTTP handler transport remains: " + ", ".join(offenders)
