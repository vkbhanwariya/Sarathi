"""Device inventory contracts for Yantra Resource Manager in Sarathi.

Defines:
- DeviceInfo: Immutable record of an available device and its slot capacity.
- DeviceInventory: Immutable collection of available devices.

Contains pure hardware capacity declarations only; performs no hardware probing,
OS queries, or dynamic detection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from sarathi.sankalpa import DeviceType


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Immutable record of an available hardware execution device."""

    device_id: str
    device_type: DeviceType
    capacity: int
    supported_backends: tuple[str, ...] | None = None
    memory_bytes: int | None = None
    backend_locators: Mapping[str, str] | None = None

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
            elif self.device_type == DeviceType.NETWORK:
                default_backends = ("rest", "http")
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

        if self.backend_locators is not None:
            if not isinstance(self.backend_locators, Mapping):
                raise TypeError(f"backend_locators must be a Mapping, got {type(self.backend_locators).__name__}.")
            cleaned_locators = {
                str(k).strip().lower(): str(v).strip()
                for k, v in self.backend_locators.items()
                if str(k).strip()
            }
            object.__setattr__(self, "backend_locators", MappingProxyType(cleaned_locators))


@dataclass(frozen=True, slots=True)
class DeviceInventory:
    """Immutable collection of available execution devices."""

    devices: tuple[DeviceInfo, ...]
    _device_map: dict[str, DeviceInfo] = field(default_factory=dict, init=False, repr=False)

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

        cleaned_tuple = tuple(cleaned)
        object.__setattr__(self, "devices", cleaned_tuple)
        object.__setattr__(self, "_device_map", {dev.device_id: dev for dev in cleaned_tuple})

    def get_device(self, device_id: str) -> DeviceInfo | None:
        """Return device by device_id or None if not found."""
        return self._device_map.get(device_id)

    def __len__(self) -> int:
        return len(self.devices)

    def __iter__(self):
        return iter(self.devices)

    @classmethod
    def default_inventory(
        cls,
        detect_accelerators: bool = False,
        *,
        gpu_capacity_per_device: int = 4,
        npu_capacity_per_device: int = 2,
        cpu_capacity: int | None = None,
        include_network: bool = False,
    ) -> DeviceInventory:
        """Create a factual default inventory using system CPU capacity, optionally including hardware accelerators.

        When detect_accelerators is True, factual hardware discovery queries runtime backends
        (OpenVINO and CUDA) for physically accessible accelerators. Accelerator capacity is defined
        as a bounded scheduler concurrency limit (default 4 concurrent streams per physical accelerator,
        clamped to physical hardware stream range when available), not fabricated physical compute cores.
        """
        import os

        if cpu_capacity is not None:
            actual_capacity = max(1, cpu_capacity)
        else:
            count_fn = getattr(os, "process_cpu_count", None)
            cpu_count = count_fn() if callable(count_fn) else os.cpu_count()
            actual_capacity = max(1, cpu_count or 1)

        cpu_memory_bytes = None
        try:
            import psutil

            cpu_memory_bytes = int(psutil.virtual_memory().total)
        except Exception:
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "kernel32"):
                    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                        cpu_memory_bytes = int(stat.ullTotalPhys)
            except Exception:
                pass

        devices: list[DeviceInfo] = [
            DeviceInfo(
                device_id="cpu-0",
                device_type=DeviceType.CPU,
                capacity=actual_capacity,
                supported_backends=("cpu", "openvino"),
                backend_locators={"cpu": "CPU", "openvino": "CPU"},
                memory_bytes=cpu_memory_bytes,
            ),
        ]

        if include_network:
            devices.append(
                DeviceInfo(
                    device_id="network-0",
                    device_type=DeviceType.NETWORK,
                    capacity=16,
                    supported_backends=("rest", "http"),
                    backend_locators={"rest": "NETWORK", "http": "NETWORK"},
                )
            )

        if detect_accelerators:
            # Safely probe OpenVINO accelerators
            ov_gpus: list[str] = []
            ov_npus: list[str] = []
            core = None
            try:
                import os

                os.environ["OPENVINO_TELEMETRY_OPTOUT"] = "1"
                os.environ["TELEMETRY_OPTOUT"] = "1"
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

            # Add OpenVINO GPUs
            for idx, ov_name in enumerate(ov_gpus):
                dev_id = f"gpu-{idx}"
                backends = ["openvino"]
                locators: dict[str, str] = {"openvino": ov_name}

                eff_gpu_cap = gpu_capacity_per_device
                if core is not None:
                    try:
                        stream_range = core.get_property(ov_name, "RANGE_FOR_STREAMS")
                        if isinstance(stream_range, (tuple, list)) and len(stream_range) >= 2:
                            max_hw = int(stream_range[1])
                            if max_hw > 0:
                                eff_gpu_cap = min(eff_gpu_cap, max_hw)
                    except Exception:
                        pass

                devices.append(
                    DeviceInfo(
                        device_id=dev_id,
                        device_type=DeviceType.GPU,
                        capacity=eff_gpu_cap,
                        supported_backends=tuple(backends),
                        backend_locators=locators,
                    )
                )

            # Add CUDA GPUs independently (not conflated with OpenVINO by enumeration position)
            if cuda_count > 0:
                for idx in range(cuda_count):
                    dev_id = f"gpu-cuda-{idx}"
                    devices.append(
                        DeviceInfo(
                            device_id=dev_id,
                            device_type=DeviceType.GPU,
                            capacity=gpu_capacity_per_device,
                            supported_backends=("cuda",),
                            backend_locators={"cuda": str(idx)},
                        )
                    )

            # Add OpenVINO NPUs
            for idx, ov_name in enumerate(ov_npus):
                dev_id = f"npu-{idx}"
                eff_npu_cap = npu_capacity_per_device
                if core is not None:
                    try:
                        stream_range = core.get_property(ov_name, "RANGE_FOR_STREAMS")
                        if isinstance(stream_range, (tuple, list)) and len(stream_range) >= 2:
                            max_hw = int(stream_range[1])
                            if max_hw > 0:
                                eff_npu_cap = min(eff_npu_cap, max_hw)
                    except Exception:
                        pass

                devices.append(
                    DeviceInfo(
                        device_id=dev_id,
                        device_type=DeviceType.NPU,
                        capacity=eff_npu_cap,
                        supported_backends=("openvino",),
                        backend_locators={"openvino": ov_name},
                    )
                )

        return cls(devices)
