"""Tests verifying strict zero-network isolation for OCR and OpenVINO runtime."""

from __future__ import annotations

import socket

import pytest

from sarathi.shakti.ocr.engine import check_ocr_readiness


def test_openvino_and_ocr_zero_network_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that checking OCR readiness and importing OpenVINO makes zero outbound socket connections."""
    def denied_connect(self, *args, **kwargs):
        raise RuntimeError("NETWORK_ACCESS_DENIED: Socket connection forbidden by Kavacha/local policy.")

    monkeypatch.setattr(socket.socket, "connect", denied_connect)

    # Calling check_ocr_readiness must never attempt socket connections
    is_ready, reason = check_ocr_readiness()
    # If openvino is installed, import it and verify Core() does not connect to internet
    try:
        import openvino as ov

        core = ov.Core()
        _ = core.available_devices
    except ImportError:
        pass
