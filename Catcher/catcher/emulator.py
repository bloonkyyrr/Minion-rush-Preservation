"""adb discovery, emulator diagnostics, proxy control and system-CA installation."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from .config import Settings

PROGRAM_FILES = (Path("C:/Program Files"), Path("C:/Program Files (x86)"))

ADB_GLOBS = (
    "BlueStacks_nxt/HD-Adb.exe",
    "BlueStacks_msi5/HD-Adb.exe",
    "BlueStacks/HD-Adb.exe",
    "Google/Play Games*/current/emulator/adb.exe",
    "Google/Play Games Developer Emulator*/current/emulator/adb.exe",
    "Nox/bin/adb.exe",
    "LDPlayer/LDPlayer*/adb.exe",
    "Microvirt/MEmu/adb.exe",
)

SU_BINARY = "su"

NO_ROOT_REASON = (
    "no root: adb shell is uid 2000 and `su` does not grant uid 0. BlueStacks 5 keeps adbd "
    "non-root and only answers `su` on builds where root is enabled for the instance "
    "(`catcher bluestacks root --instance <name>`, then restart it); since 5.22 the stock build "
    "ignores the flag and needs a patched instance. Run `catcher bluestacks status` for the "
    "guest-side detail."
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


# su dialects differ per image: AOSP/toolbox uses `su 0 <cmd>`, BlueStacks' su uses `su -c <cmd>`.
SU_FORMS = ("-c", "0")


def su_command(form: str, command: str) -> str:
    """Wrap a guest command for the given su dialect."""
    quoted = shlex.quote(command)
    if form == "-c":
        return f"{SU_BINARY} -c {quoted}"
    return f"{SU_BINARY} {form} sh -c {quoted}"


def root_mode(serial: str, adb_path: Path | None = None, settings: Settings | None = None) -> str | None:
    """How root is reachable: ``"adbd"`` when the shell is uid 0, else ``"su -c"``/``"su 0"``."""
    if "uid=0" in shell(serial, "id", adb_path, settings, timeout=60):
        return "adbd"
    # BlueStacks keeps adbd as the shell user and exposes root through a setuid su binary instead.
    for form in SU_FORMS:
        if "uid=0" in shell(serial, su_command(form, "id"), adb_path, settings, timeout=60):
            return f"su {form}"
    return None


def is_root(serial: str, adb_path: Path | None = None, settings: Settings | None = None) -> bool:
    return root_mode(serial, adb_path, settings) is not None


def root_command(mode: str, command: str) -> str:
    """Guest command line that runs ``command`` as root for the given :func:`root_mode`."""
    if mode == "adbd":
        return command
    return su_command(mode.split(" ", 1)[1], command)


def root_shell(
    serial: str,
    command: str,
    adb_path: Path | None = None,
    settings: Settings | None = None,
    timeout: int = 120,
) -> str:
    """Run a guest command as root; raises ``PermissionError`` when the device is not rooted."""
    mode = root_mode(serial, adb_path, settings)
    if mode is None:
        raise PermissionError(NO_ROOT_REASON)
    return shell(serial, root_command(mode, command), adb_path, settings, timeout)


def root_exec_args(serial: str, command: str, mode: str) -> list[str]:
    """adb arguments that stream a root command's binary stdout (``adb exec-out``)."""
    return ["-s", serial, "exec-out", root_command(mode, command)]


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
    try:
        listing = root_shell(serial, f"ls /system/etc/security/cacerts/{cert_hash}.0", adb_path, settings, timeout=60)
    except PermissionError:
        listing = shell(serial, f"ls /system/etc/security/cacerts/{cert_hash}.0", adb_path, settings, timeout=60)
    return cert_hash in listing and "No such file" not in listing and "Permission denied" not in listing


def install_system_ca(serial: str, cert_path: Path, adb_path: Path | None = None, settings: Settings | None = None, reboot: bool = False) -> dict:
    """Install the mitmproxy CA into the system trust store of a rooted device.

    Handles both root flavours: a writable ``/system`` with root adbd (AVD) and BlueStacks,
    where adbd stays non-root and every command goes through ``su``.
    """
    report: dict = {"serial": serial, "cert": str(cert_path), "steps": [], "ok": False}
    mode = root_mode(serial, adb_path, settings)
    if mode is None:
        report["reason"] = NO_ROOT_REASON
        return report
    report["root"] = mode

    cert_hash = ca_subject_hash(cert_path)
    target = f"/system/etc/security/cacerts/{cert_hash}.0"
    staged = "/data/local/tmp/catcher-ca.pem"
    report["hash"] = cert_hash
    report["target"] = target

    steps = [
        ["-s", serial, "push", str(cert_path), staged],
        # /system is read-only on BlueStacks until it is remounted; an AVD's adbd is already root.
        ["-s", serial, "shell", root_command(mode, "mount -o rw,remount /system 2>/dev/null || mount -o rw,remount /")],
        ["-s", serial, "shell", root_command(mode, f"cp {staged} {target}")],
        ["-s", serial, "shell", root_command(mode, f"chmod 644 {target}")],
        ["-s", serial, "shell", root_command(mode, f"chown root:root {target}")],
        ["-s", serial, "shell", root_command(mode, f"chcon u:object_r:system_file:s0 {target}")],
        ["-s", serial, "shell", root_command(mode, f"ls -l {target}")],
    ]
    for step in steps:
        try:
            result = adb(step, adb_path=adb_path, settings=settings, timeout=120)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            report["steps"].append({"cmd": " ".join(step), "error": str(exc)})
            break
        output = (result.stdout or "") + (result.stderr or "")
        report["steps"].append({"cmd": " ".join(step), "returncode": result.returncode, "output": output.strip()})
        if "push" in step and result.returncode != 0:
            break

    report["ok"] = system_ca_present(serial, cert_hash, adb_path, settings)
    if not report["ok"] and "reason" not in report:
        report["reason"] = (
            f"{target} is missing after the install, so /system was still read-only. Enable root for "
            "the instance and restart it before retrying."
        )
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


def connect(serial: str, adb_path: Path | None = None, settings: Settings | None = None) -> bool:
    """``adb connect`` a TCP serial (BlueStacks forwards ``127.0.0.1:<port>``)."""
    try:
        result = adb(["connect", serial], adb_path=adb_path, settings=settings, timeout=30)
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    output = ((result.stdout or "") + (result.stderr or "")).lower()
    return "connected" in output and "unable" not in output
