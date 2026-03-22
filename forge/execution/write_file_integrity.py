"""
write_file payload integrity: diagnostics and post-write verification.

Set environment variable ``FORGE_LOG_WRITE_FILE_PAYLOAD=1`` to log character/byte
lengths and a short sha256 prefix at parse time and immediately before/after disk write.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

_LOG = logging.getLogger("forge.execution.write_file")


def _env_log_payload() -> bool:
    v = os.environ.get("FORGE_LOG_WRITE_FILE_PAYLOAD", "").strip().lower()
    return v in ("1", "true", "yes")


def sha256_utf8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def log_write_file_payload_stage(
    rel_path: str, body: str, stage: str, *, line_no: int | None = None
) -> None:
    """Log length + hash prefix when FORGE_LOG_WRITE_FILE_PAYLOAD is enabled."""
    if not _env_log_payload():
        return
    n_chars = len(body)
    raw = body.encode("utf-8")
    n_bytes = len(raw)
    short = sha256_utf8(body)[:16]
    loc = f" line={line_no}" if line_no is not None else ""
    _LOG.info(
        "write_file payload [%s] rel_path=%r%s: %s chars, %s bytes, sha256_prefix=%s",
        stage,
        rel_path,
        loc,
        n_chars,
        n_bytes,
        short,
    )


def verify_write_file_disk_matches(
    path: Path, expected: str, *, rel_path: str
) -> None:
    """
    After ``path.write_text(expected)``, read back and require exact equality.

    Raises :exc:`WriteFileIntegrityError` if the file on disk does not match the
    canonical payload byte-for-byte (UTF-8).
    """
    got = path.read_text(encoding="utf-8")
    if got == expected:
        if _env_log_payload():
            _LOG.info(
                "write_file payload [after_write_verified] rel_path=%r: %s chars (matches)",
                rel_path,
                len(got),
            )
        return
    exp_b = expected.encode("utf-8")
    got_b = got.encode("utf-8")
    raise WriteFileIntegrityError(
        rel_path=rel_path,
        path=str(path),
        expected_len=len(expected),
        got_len=len(got),
        expected_bytes=len(exp_b),
        got_bytes=len(got_b),
        expected_sha256=sha256_utf8(expected),
        got_sha256=sha256_utf8(got),
        diff_at=_first_mismatch_index(expected, got),
    )


def _first_mismatch_index(a: str, b: str) -> int | None:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return None


class WriteFileIntegrityError(ValueError):
    """Raised when written file content does not match the canonical write_file body."""

    def __init__(
        self,
        *,
        rel_path: str,
        path: str,
        expected_len: int,
        got_len: int,
        expected_bytes: int,
        got_bytes: int,
        expected_sha256: str,
        got_sha256: str,
        diff_at: int | None,
    ) -> None:
        self.rel_path = rel_path
        self.path = path
        self.expected_len = expected_len
        self.got_len = got_len
        self.expected_bytes = expected_bytes
        self.got_bytes = got_bytes
        self.expected_sha256 = expected_sha256
        self.got_sha256 = got_sha256
        self.diff_at = diff_at
        msg = (
            f"write_file integrity failure for {rel_path!r}: disk content does not match "
            f"canonical body (chars: expected {expected_len}, got {got_len}; "
            f"bytes: expected {expected_bytes}, got {got_bytes}; "
            f"sha256 expected {expected_sha256}, got {got_sha256}"
        )
        if diff_at is not None:
            msg += f"; first mismatch at character index {diff_at}"
        msg += f"). Path: {path}"
        super().__init__(msg)
