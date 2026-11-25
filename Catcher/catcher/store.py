"""Session storage: directories, sequencing, content-addressed blobs, manifests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import time
from pathlib import Path

from .config import Settings

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(text: str, limit: int = 90) -> str:
    """Filesystem-safe, length-limited slug."""
    slug = _UNSAFE.sub("-", text).strip("-._")
    return (slug or "item")[: max(1, limit)]


def session_label(settings: Settings) -> str:
    if settings.session_name:
        return slugify(settings.session_name, 60)
    return time.strftime("%Y%m%d-%H%M%S")


def _json_default(obj):
    """Keep unexpected binary values (proxy internals) rather than losing the record."""
    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj).decode("latin-1", "replace")
    return str(obj)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class Session:
    """One capture run writing into ``Contents/<session>/``."""

    def __init__(self, settings: Settings, name: str | None = None):
        self.settings = settings
        settings.ensure_dirs()
        self.name = name or session_label(settings)
        self.dir = settings.contents_dir / self.name
        self.http_dir = self.dir / "http"
        self.ws_dir = self.dir / "ws"
        self.har_dir = self.dir / "har"
        for directory in (self.http_dir, self.ws_dir, self.har_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self.manifest_path = self.dir / "manifest.jsonl"
        self.log_path = self.dir / "session.log"
        self._lock = threading.Lock()
        self._seq = self._count_existing()
        self._manifest = self.manifest_path.open("a", encoding="utf-8", buffering=1)
        self.write_json(
            self.dir / "session.json",
            {
                "session": self.name,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "host": socket.gethostname(),
                "out_root": str(settings.out_root),
                "listen": f"{settings.listen_host}:{settings.listen_port}",
                "package": settings.package,
                "max_inline_body": settings.max_inline_body,
                "schema": 1,
            },
        )
        self.log(f"session {self.name} started")

    # -- sequence ---------------------------------------------------------
    def _count_existing(self) -> int:
        if not self.manifest_path.is_file():
            return 0
        with self.manifest_path.open("r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for line in fh if line.strip())

    def next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    # -- writers ----------------------------------------------------------
    def rel(self, path: Path) -> str:
        """Path relative to the archive root, POSIX separators."""
        try:
            return path.resolve().relative_to(self.settings.out_root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def atomic_write(self, path: Path, data: bytes) -> None:
        _atomic_write(path, data)

    def write_json(self, path: Path, obj) -> None:
        _atomic_write(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))

    def save_body(self, body: bytes | None) -> dict:
        """Describe a body; keep small ones inline in the .req/.res, large ones in blobs/."""
        if not body:
            return {"size": 0, "sha256": None, "blob": None, "stored": "empty"}
        sha = hashlib.sha256(body).hexdigest()
        if len(body) <= self.settings.max_inline_body:
            return {"size": len(body), "sha256": sha, "blob": None, "stored": "inline"}
        blob = self.settings.blobs_dir / sha[:2] / sha
        if not blob.is_file():
            _atomic_write(blob, body)
        return {"size": len(body), "sha256": sha, "blob": self.rel(blob), "stored": "blob"}

    def append(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=_json_default)
        with self._lock:
            self._manifest.write(line + "\n")

    def log(self, message: str) -> None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            with self.log_path.open("a", encoding="utf-8", errors="replace") as fh:
                fh.write(f"{stamp} {message}\n")
        except OSError:
            pass

    def close(self) -> None:
        try:
            self.log("session ended")
            self._manifest.close()
        except Exception:
            pass
