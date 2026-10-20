"""Incremental SHA-256 hashing utilities for large files."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import IO

from photoport.config import HASH_CHUNK_SIZE


def sha256_file(path: Path, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Compute SHA-256 hex digest of a file using incremental reads.

    Handles arbitrarily large files without loading them into memory.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


compute_file_sha256 = sha256_file


def sha256_stream(stream: IO[bytes], chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Compute SHA-256 hex digest from a readable binary stream."""
    h = hashlib.sha256()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()
