"""Disk space monitoring utilities."""

from __future__ import annotations

import shutil
from pathlib import Path


def get_free_space(path: Path) -> int:
    """Return free disk space in bytes for the volume containing *path*."""
    stat = shutil.disk_usage(str(path))
    return stat.free if hasattr(stat, "free") else stat[2]


def get_total_space(path: Path) -> int:
    """Return total disk space in bytes for the volume containing *path*."""
    stat = shutil.disk_usage(str(path))
    return stat.total if hasattr(stat, "total") else stat[0]


def has_sufficient_space(path: Path, required_bytes: int, safety_margin: float = 1.1) -> bool:
    """Check whether *path*'s volume has at least *required_bytes* × *safety_margin* free."""
    free = get_free_space(path)
    return free >= int(required_bytes * safety_margin)


def format_bytes(n: int) -> str:
    """Human-readable byte size string."""
    if n < 0:
        return f"-{format_bytes(-n)}"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0  # type: ignore[assignment]
    return f"{n:.1f} PB"
