"""Standard-library-only system health observations."""

from __future__ import annotations

import os
import platform
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    """Safe, read-only host information available to diagnostics."""

    platform: str
    python_version: str
    cpu_count: int
    load_average: tuple[float, ...] | None
    disk_free_bytes: int
    captured_at: float


class SystemMonitor:
    """Collect read-only process and workspace health information."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def snapshot(self) -> SystemSnapshot:
        load = os.getloadavg() if hasattr(os, "getloadavg") else None
        disk = shutil.disk_usage(self.workspace_root)
        return SystemSnapshot(
            platform=platform.platform(),
            python_version=platform.python_version(),
            cpu_count=os.cpu_count() or 1,
            load_average=load,
            disk_free_bytes=disk.free,
            captured_at=time.time(),
        )

    def healthy(self, minimum_free_bytes: int = 1) -> bool:
        return self.snapshot().disk_free_bytes >= minimum_free_bytes
