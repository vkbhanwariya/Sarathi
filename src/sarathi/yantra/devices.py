"""Device inventory contracts for Yantra Resource Manager in Sarathi V2.

Defines:
- DeviceInfo: Immutable record of an available device and its slot capacity.
- DeviceInventory: Immutable collection of available devices.

Contains pure hardware capacity declarations only; performs no hardware probing,
OS queries, or dynamic detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sarathi.sankalpa import DeviceType


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Immutable record of an available hardware execution device."""

    device_id: str
    device_type: DeviceType
    capacity: int
    supported_backends: tuple[str, ...] | None = None
    memory_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.device_id or not isinstance(self.device_id, str) or not self.device_id.strip():
            raise ValueError("device_id must be a non-empty string.")

        if not isinstance(self.device_type, DeviceType):
            raise TypeError(f"device_type must be a DeviceType, got {type(self.device_type).__name__}.")

        if not isinstance(self.capacity, int) or isinstance(self.capacity, bool):
            raise TypeError(f"capacity must be an integer, got {type(self.capacity).__name__}.")

        if self.capacity <= 0:
            raise ValueError(f"capacity must be a positive integer (> 0), got {self.capacity}.")

        if self.supported_backends is None:
            if self.device_type == DeviceType.GPU:
                default_backends = ("openvino", "cuda")
            elif self.device_type == DeviceType.NPU:
                default_backends = ("openvino",)
            else:
                default_backends = ("cpu", "openvino")
            object.__setattr__(self, "supported_backends", default_backends)
        else:
            if isinstance(self.supported_backends, set):
                raise TypeError("supported_backends must be an ordered sequence (list or tuple), not a set.")
            if not isinstance(self.supported_backends, (list, tuple)):
                raise TypeError(f"supported_backends must be a sequence of strings, got {type(self.supported_backends)}.")
            cleaned_backends = tuple(str(b).strip().lower() for b in self.supported_backends if str(b).strip())
            object.__setattr__(self, "supported_backends", cleaned_backends)

        if self.memory_bytes is not None:
            if not isinstance(self.memory_bytes, int) or isinstance(self.memory_bytes, bool) or self.memory_bytes < 0:
                raise ValueError("memory_bytes must be a non-negative integer or None.")


@dataclass(frozen=True, slots=True)
class DeviceInventory:
    """Immutable collection of available execution devices."""

    devices: tuple[DeviceInfo, ...]

    def __init__(self, devices: Sequence[DeviceInfo]) -> None:
        if isinstance(devices, set):
            raise TypeError("devices must be an ordered sequence (list or tuple), not a set.")
        if not isinstance(devices, (list, tuple)):
            raise TypeError(f"devices must be an ordered sequence of DeviceInfo, got {type(devices).__name__}.")

        cleaned: list[DeviceInfo] = []
        seen_ids: set[str] = set()
        for i, dev in enumerate(devices):
            if not isinstance(dev, DeviceInfo):
                raise TypeError(f"devices[{i}] must be a DeviceInfo instance, got {type(dev).__name__}.")
            if dev.device_id in seen_ids:
                raise ValueError(f"Duplicate device_id in inventory: {dev.device_id!r}")
            seen_ids.add(dev.device_id)
            cleaned.append(dev)

        object.__setattr__(self, "devices", tuple(cleaned))

    def get_device(self, device_id: str) -> DeviceInfo | None:
        """Return device by device_id or None if not found."""
        for dev in self.devices:
            if dev.device_id == device_id:
                return dev
        return None

    def __len__(self) -> int:
        return len(self.devices)

    def __iter__(self):
        return iter(self.devices)

    @classmethod
    def default_inventory(cls, detect_accelerators: bool = False) -> DeviceInventory:
        """Create a factual default inventory using system CPU capacity, optionally including hardware accelerators.

        When detect_accelerators is True, factual hardware discovery queries runtime backends
        (OpenVINO and CUDA) for physically accessible accelerators. Accelerator capacity is defined
        as a bounded scheduler concurrency limit (default 2 concurrent streams per physical accelerator),
        not fabricated physical compute cores.
        """
        import os

        count_fn = getattr(os, "process_cpu_count", None)
        cpu_count = count_fn() if callable(count_fn) else os.cpu_count()
        actual_capacity = max(1, cpu_count or 1)

        devices: list[DeviceInfo] = [
            DeviceInfo(
                device_id="cpu-0",
                device_type=DeviceType.CPU,
                capacity=actual_capacity,
                supported_backends=("cpu", "openvino"),
            ),
        ]

        if detect_accelerators:
            # Safely probe OpenVINO accelerators
            ov_gpus: list[str] = []
            ov_npus: list[str] = []
            try:
                import openvino as ov

                core = ov.Core()
                available = [str(d).strip() for d in core.available_devices]
                ov_gpus = [d for d in available if "GPU" in d.upper()]
                ov_npus = [d for d in available if "NPU" in d.upper()]
            except Exception:
                pass

            # Safely probe CUDA accelerators
            cuda_count = 0
            try:
                import ctranslate2

                if hasattr(ctranslate2, "get_cuda_device_count"):
                    cuda_count = ctranslate2.get_cuda_device_count()
            except Exception:
                pass

            # Add OpenVINO GPUs (and note if also CUDA-accessible)
            for idx, _ in enumerate(ov_gpus):
                dev_id = f"gpu-{idx}"
                backends = ["openvino"]
                if idx < cuda_count:
                    backends.append("cuda")
                devices.append(
                    DeviceInfo(
                        device_id=dev_id,
                        device_type=DeviceType.GPU,
                        capacity=2,
                        supported_backends=tuple(backends),
                    )
                )

            # Add remaining CUDA-only GPUs if any
            if cuda_count > len(ov_gpus):
                for idx in range(len(ov_gpus), cuda_count):
                    dev_id = f"gpu-cuda-{idx}"
                    devices.append(
                        DeviceInfo(
                            device_id=dev_id,
                            device_type=DeviceType.GPU,
                            capacity=2,
                            supported_backends=("cuda",),
                        )
                    )

            # Add OpenVINO NPUs
            for idx, _ in enumerate(ov_npus):
                dev_id = f"npu-{idx}"
                devices.append(
                    DeviceInfo(
                        device_id=dev_id,
                        device_type=DeviceType.NPU,
                        capacity=2,
                        supported_backends=("openvino",),
                    )
                )

        return cls(devices)
