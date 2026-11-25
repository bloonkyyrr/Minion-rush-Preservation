"""adb discovery, emulator diagnostics, proxy control and system-CA installation."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .config import Settings

PROGRAM_FILES = (Path("C:/Program Files"), Path("C:/Program Files (x86)"))

ADB_GLOBS = (
    "Google/Play Games*/current/emulator/adb.exe",
    "Google/Play Games Developer Emulator*/current/emulator/adb.exe",
    "BlueStacks_nxt/HD-Adb.exe",
    "Nox/bin/adb.exe",
    "LDPlayer/LDPlayer*/adb.exe",
    "Microvirt/MEmu/adb.exe",
)


def adb_candidates(settings: Settings | None = None):
    if settings is not None and settings.adb is not None:
        yield Path(settings.adb)
    which = shutil.which("adb")
    if which:
        yield Path(which)
    local = os.environ.get("LOCALAPPDATA")
    for base in PROGRAM_FILES:
        for pattern in ADB_GLOBS:
            try:
                yield from sorted(base.glob(pattern), reverse=True)
            except OSError:
                continue
    if local:
        for pattern in ADB_GLOBS:
            try:
                yield from sorted((Path(local) / "Android").glob(pattern), reverse=True)
            except OSError:
                continue


def find_adb(settings: Settings | None = None) -> Path | None:
    for candidate in adb_candidates(settings):
        try:
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        except OSError:
            continue
    return None


def adb(args, adb_path: Path | None = None, settings: Settings | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    exe = adb_path or find_adb(settings)
    if exe is None:
        raise FileNotFoundError(
            "adb.exe not found. Install an Android emulator, or set `adb` in Catcher/catcher.toml."
        )
    command = [str(exe)] + [str(arg) for arg in args]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def run_binary(args, out_path: Path, adb_path: Path | None = None, settings: Settings | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    """Run adb with binary stdout redirected into ``out_path``."""
    exe = adb_path or find_adb(settings)
    if exe is None:
        raise FileNotFoundError("adb.exe not found")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        return subprocess.run(
            [str(exe)] + [str(arg) for arg in args],
            stdout=fh,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )


def list_devices(adb_path: Path | None = None, settings: Settings | None = None) -> list[dict]:
    try:
        result = adb(["devices", "-l"], adb_path=adb_path, settings=settings, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    devices = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        entry = {"serial": parts[0], "state": parts[1]}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                entry[key] = value
        devices.append(entry)
    return devices


def shell(serial: str, command: str, adb_path: Path | None = None, settings: Settings | None = None, timeout: int = 120) -> str:
    result = adb(["-s", serial, "shell", command], adb_path=adb_path, settings=settings, timeout=timeout)
    return (result.stdout or "") + (result.stderr or "")


def device_props(serial: str, adb_path: Path | None = None, settings: Settings | None = None) -> dict:
    props = {}
    for line in shell(serial, "getprop", adb_path, settings).splitlines():
        line = line.strip()
        if not line.startswith("[") or "]: [" not in line:
            continue
        key, value = line[1:].split("]: [", 1)
        props[key] = value.rstrip("]")
    return props


def is_root(serial: str, adb_path: Path | None = None, settings: Settings | None = None) -> bool:
    return "uid=0" in shell(serial, "id", adb_path, settings)


def proxy_setting(serial: str, adb_path: Path | None = None, settings: Settings | None = None) -> str | None:
    value = shell(serial, "settings get global http_proxy", adb_path, settings).strip()
    if value in ("", "null", "none", ":0"):
        return None
    return value


def set_proxy(serial: str, address: str, adb_path: Path | None = None, settings: Settings | None = None) -> bool:
    out = shell(serial, f"settings put global http_proxy {address}", adb_path, settings)
    return proxy_setting(serial, adb_path, settings) == address and "Exception" not in out


def clear_proxy(serial: str, adb_path: Path | None = None, settings: Settings | None = None) -> bool:
    shell(serial, "settings put global http_proxy :0", adb_path, settings)
    shell(serial, "settings delete global http_proxy", adb_path, settings)
    return proxy_setting(serial, adb_path, settings) is None


def package_version(serial: str, package: str, adb_path: Path | None = None, settings: Settings | None = None) -> str | None:
    out = shell(serial, f"dumpsys package {package}", adb_path, settings, timeout=60)
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("versionName="):
            return stripped.split("=", 1)[1]
    return None


def mitmproxy_ca_cert() -> Path | None:
    home = Path.home() / ".mitmproxy"
    for name in ("mitmproxy-ca-cert.pem", "mitmproxy-ca-cert.cer", "mitmproxy-ca-cert.p12"):
        candidate = home / name
        if candidate.is_file():
            return candidate
    return None


def ca_subject_hash(cert_path: Path) -> str:
    """OpenSSL ``X509_NAME_hash_old`` that Android uses for cacerts filenames."""
    from cryptography import x509

    data = Path(cert_path).read_bytes()
    if b"BEGIN CERTIFICATE" in data:
        cert = x509.load_pem_x509_certificate(data)
    else:
        cert = x509.load_der_x509_certificate(data)
    try:
        der = cert.subject.public_bytes()
    except AttributeError:  # very old cryptography
        from cryptography.hazmat.primitives.serialization import Encoding

        der = cert.subject.public_bytes(Encoding.DER)
    digest = hashlib.md5(der).digest()[:4]
    return f"{int.from_bytes(digest, 'little'):08x}"


def system_ca_present(serial: str, cert_hash: str, adb_path: Path | None = None, settings: Settings | None = None) -> bool:
    listing = shell(serial, f"ls /system/etc/security/cacerts/{cert_hash}.0", adb_path, settings, timeout=60)
    return cert_hash in listing and "No such file" not in listing and "Permission denied" not in listing


def install_system_ca(serial: str, cert_path: Path, adb_path: Path | None = None, settings: Settings | None = None, reboot: bool = False) -> dict:
    """Install the mitmproxy CA into the system trust store of a rooted device."""
    report: dict = {"serial": serial, "cert": str(cert_path), "steps": [], "ok": False}
    if not is_root(serial, adb_path, settings):
        report["reason"] = (
            "device is not rooted (uid != 0). Android 7+ apps ignore user-installed CAs, so HTTPS "
            "content cannot be decrypted on this device. Use a rootable image (AVD google_apis with "
            "-writable-system, or BlueStacks/LDPlayer with root enabled)."
        )
        return report

    cert_hash = ca_subject_hash(cert_path)
    target = f"/system/etc/security/cacerts/{cert_hash}.0"
    steps = [
        ["-s", serial, "remount"],
        ["-s", serial, "push", str(cert_path), target],
        ["-s", serial, "shell", "chmod", "644", target],
        ["-s", serial, "shell", "chcon", "u:object_r:system_file:s0", target],
        ["-s", serial, "shell", "ls", "-l", target],
    ]
    for step in steps:
        try:
            result = adb(step, adb_path=adb_path, settings=settings, timeout=120)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            report["steps"].append({"cmd": " ".join(step), "error": str(exc)})
            break
        output = (result.stdout or "") + (result.stderr or "")
        report["steps"].append({"cmd": " ".join(step), "returncode": result.returncode, "output": output.strip()})
        if result.returncode != 0 and "chcon" not in " ".join(step):
            break

    report["hash"] = cert_hash
    report["target"] = target
    report["ok"] = system_ca_present(serial, cert_hash, adb_path, settings)
    if reboot:
        adb(["-s", serial, "reboot"], adb_path=adb_path, settings=settings, timeout=60)
        report["rebooted"] = True
    return report


def free_space_gb(path: Path) -> float:
    try:
        usage = shutil.disk_usage(path)
        return round(usage.free / (1024**3), 1)
    except OSError:
        return 0.0
