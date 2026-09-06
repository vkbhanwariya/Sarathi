"""OpenVINO environment configuration, device patching, and safe model resolution."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import DeviceType, ExecutionBinding
from sarathi.shakti.ocr.engine.common import SAFE_FILENAME_PATTERN


def is_safe_filename(name: Any) -> bool:
    """Validate that filename is a safe, non-empty basename without path traversal or separators."""
    if not isinstance(name, str):
        return False
    clean = name.strip()
    if not clean or clean in (".", ".."):
        return False
    if "/" in clean or "\\" in clean or ":" in clean:
        return False
    if not SAFE_FILENAME_PATTERN.match(clean):
        return False
    return True


_is_safe_filename = is_safe_filename


def disable_openvino_telemetry() -> None:
    """Enforce strict local zero-network policy for OpenVINO and openvino-telemetry."""
    os.environ["OPENVINO_TELEMETRY_OPTOUT"] = "1"
    os.environ["TELEMETRY_OPTOUT"] = "1"

    try:
        import platform
        from pathlib import Path

        base_dir: str | None = None
        if platform.system() == "Windows":
            base_dir = os.environ.get("LOCALAPPDATA")
        else:
            base_dir = str(Path.home())
        if base_dir and os.path.isdir(base_dir):
            consent_dir = Path(base_dir) / "openvino_telemetry"
            consent_dir.mkdir(parents=True, exist_ok=True)
            consent_file = consent_dir / "openvino_telemetry"
            if not consent_file.exists() or consent_file.read_text(encoding="ascii", errors="ignore").strip() != "0":
                consent_file.write_text("0", encoding="ascii")
    except Exception:
        pass

    try:
        import openvino_telemetry

        if hasattr(openvino_telemetry, "Telemetry"):
            openvino_telemetry.Telemetry.send = lambda *args, **kwargs: None
            openvino_telemetry.Telemetry.send_opt_in_event = lambda *args, **kwargs: None
        try:
            from openvino_telemetry.utils.sender import TelemetrySender

            TelemetrySender.send = lambda *args, **kwargs: None
        except Exception:
            pass
    except Exception:
        pass


_disable_openvino_telemetry = disable_openvino_telemetry

# Enforce telemetry suppression on module load
_disable_openvino_telemetry()


_SHARED_OPENVINO_CORE: Any = None
_SHARED_CORE_LOCK = threading.Lock()


def get_shared_openvino_core(cache_dir: Path | None = None) -> Any:
    """Return a thread-safe shared OpenVINO Core instance configured with persistent model caching.

    Caches compiled model binaries on disk (in Runtime/Cache/openvino_model_cache), eliminating
    the 30-45s OpenCL GPU kernel JIT compilation lag on subsequent worker initializations.
    """
    global _SHARED_OPENVINO_CORE
    if _SHARED_OPENVINO_CORE is not None:
        return _SHARED_OPENVINO_CORE

    with _SHARED_CORE_LOCK:
        if _SHARED_OPENVINO_CORE is None:
            try:
                from openvino import Core
            except ImportError:
                from openvino.runtime import Core

            core = Core()
            effective_cache_dir = (cache_dir or Path("Runtime/Cache/openvino_model_cache")).resolve()
            try:
                effective_cache_dir.mkdir(parents=True, exist_ok=True)
                core.set_property({"CACHE_DIR": str(effective_cache_dir)})
            except Exception:
                pass
            _SHARED_OPENVINO_CORE = core
    return _SHARED_OPENVINO_CORE


def patch_rapidocr_openvino_device(cache_dir: Path | None = None) -> None:
    """Ensure RapidOCR OpenVINOInferSession respects the device configured in the inference params."""
    _disable_openvino_telemetry()
    try:
        import rapidocr.inference_engine.openvino.main as ov_main

        if getattr(ov_main.OpenVINOInferSession, "_sarathi_device_patched", False):
            return

        def _custom_init(self: Any, cfg: Any) -> None:
            from pathlib import Path

            device_name = str(cfg.get("device", "CPU")).upper()
            core = get_shared_openvino_core(cache_dir)
            model_path = Path(cfg.get("model_path"))
            self._verify_model(model_path)

            if device_name == "CPU":
                try:
                    from rapidocr.inference_engine.openvino.device_config import CPUConfig

                    cpu_config = CPUConfig(cfg.get("engine_cfg", {}))
                    core.set_property("CPU", cpu_config.get_config())
                except Exception:
                    pass

            self.model = core.read_model(model_path)
            compile_model = core.compile_model(model=self.model, device_name=device_name)
            self.session = compile_model.create_infer_request()

        ov_main.OpenVINOInferSession.__init__ = _custom_init
        ov_main.OpenVINOInferSession._sarathi_device_patched = True
    except Exception:
        pass


_patch_rapidocr_openvino_device = patch_rapidocr_openvino_device



def resolve_target_device(execution_binding: ExecutionBinding | None) -> str:
    """Resolve factual OpenVINO target device string from execution binding."""
    if execution_binding is None or execution_binding.device_type == DeviceType.CPU:
        return "CPU"
    if execution_binding.device_type == DeviceType.GPU:
        return execution_binding.backend_device_id or "GPU"
    if execution_binding.device_type == DeviceType.NPU:
        return execution_binding.backend_device_id or "NPU"
    raise DoshError(
        code=FailureCode.UNSUPPORTED,
        message=f"Unsupported execution device type '{execution_binding.device_type.value}' for OCR.",
    )


_resolve_target_device = resolve_target_device
