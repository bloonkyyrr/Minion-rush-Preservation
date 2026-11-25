"""Catcher configuration.

Priority (low to high): built-in defaults, ``Catcher/catcher.toml``,
``CATCHER_*`` environment variables, explicit keyword overrides (the CLI).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "catcher.toml"

DEFAULTS: dict = {
    "out_root": None,
    "listen_host": "127.0.0.1",
    "listen_port": 8080,
    "max_inline_body": 64 * 1024,
    "package": "com.gameloft.android.ANMP.GloftDMHM",
    "adb": None,
    "session_name": None,
}

ENV_OVERRIDES = {
    "CATCHER_OUT_ROOT": "out_root",
    "CATCHER_LISTEN_HOST": "listen_host",
    "CATCHER_LISTEN_PORT": "listen_port",
    "CATCHER_MAX_INLINE": "max_inline_body",
    "CATCHER_PACKAGE": "package",
    "CATCHER_ADB": "adb",
    "CATCHER_SESSION": "session_name",
}


def catcher_dir() -> Path:
    """The ``Catcher`` directory (the package's parent)."""
    return Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """Resolved paths and capture options."""

    out_root: Path
    listen_host: str = "127.0.0.1"
    listen_port: int = 8080
    max_inline_body: int = 64 * 1024
    package: str = str(DEFAULTS["package"])
    adb: Path | None = None
    session_name: str | None = None

    @property
    def api_dir(self) -> Path:
        return self.out_root / "API calls"

    @property
    def contents_dir(self) -> Path:
        return self.out_root / "Contents"

    @property
    def other_dir(self) -> Path:
        return self.out_root / "Other"

    @property
    def blobs_dir(self) -> Path:
        return self.contents_dir / "blobs"

    def ensure_dirs(self) -> None:
        for path in (self.api_dir, self.contents_dir, self.other_dir, self.blobs_dir):
            path.mkdir(parents=True, exist_ok=True)


def _read_toml() -> dict:
    path = catcher_dir() / CONFIG_NAME
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_settings(**overrides) -> Settings:
    raw: dict = dict(DEFAULTS)
    raw.update(_read_toml())
    for env_name, key in ENV_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value not in (None, ""):
            raw[key] = value
    for key, value in overrides.items():
        if value is not None:
            raw[key] = value

    out_root = Path(raw["out_root"]).expanduser() if raw.get("out_root") else catcher_dir().parent
    adb = Path(raw["adb"]).expanduser() if raw.get("adb") else None
    try:
        max_inline = int(raw.get("max_inline_body") or DEFAULTS["max_inline_body"])
    except (TypeError, ValueError):
        max_inline = int(DEFAULTS["max_inline_body"])
    try:
        port = int(raw.get("listen_port") or DEFAULTS["listen_port"])
    except (TypeError, ValueError):
        port = int(DEFAULTS["listen_port"])

    return Settings(
        out_root=out_root,
        listen_host=str(raw.get("listen_host") or DEFAULTS["listen_host"]),
        listen_port=port,
        max_inline_body=max(0, max_inline),
        package=str(raw.get("package") or DEFAULTS["package"]),
        adb=adb,
        session_name=str(raw["session_name"]) if raw.get("session_name") else None,
    )
