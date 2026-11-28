"""BlueStacks 5: install detection, instance settings and root access.

Every instance setting lives in ``bluestacks.conf`` (``%ProgramData%\\BlueStacks_nxt`` for a
BlueStacks 5 install, ``BlueStacks_msi5`` for MSI App Player). Root is two lines:

    bst.feature.rooting="1"
    bst.instance.<Instance>.enable_root_access="1"

BlueStacks applies them when the instance boots, so a running instance must be restarted before
root shows up. ``adb root`` is *not* supported: it stops adbd inside the guest and the instance
has to be rebooted before ADB answers again. Root here means ``su`` in the guest (adbd stays uid
2000), which is what :func:`catcher.emulator.root_command` handles.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import emulator
from .config import Settings

INSTALL_GLOBS = (
    "BlueStacks_nxt/HD-Player.exe",
    "BlueStacks_msi5/HD-Player.exe",
    "BlueStacks/HD-Player.exe",
)

CONF_DIRS = ("BlueStacks_nxt", "BlueStacks_msi5", "BlueStacks")

PLAYER_PROCESS = "HD-Player.exe"

INSTANCE_LINE = re.compile(
    r'^bst\.instance\.(?P<instance>[^.]+)\.(?P<setting>[A-Za-z0-9_.]+)=(?P<value>.*)$'
)

# Instance names are the Android image they were created from. The suffix (_4, _7) is dropped.
ANDROID_NAMES = {
    "Nougat32": "7.0 Nougat (32-bit)",
    "Nougat64": "7.0 Nougat (64-bit)",
    "Pie64": "9 Pie (64-bit)",
    "Rvc32": "11 (32-bit)",
    "Rvc64": "11 (64-bit)",
    "Tiramisu32": "13 (32-bit)",
    "Tiramisu64": "13 (64-bit)",
}


@dataclass
class Instance:
    """One BlueStacks instance, as recorded in ``bluestacks.conf``."""

    name: str
    adb_port: int | None
    root_enabled: bool
    display_name: str | None
    android: str | None
    conf: Path

    @property
    def serial(self) -> str | None:
        return f"127.0.0.1:{self.adb_port}" if self.adb_port else None


def _roots() -> list[Path]:
    """Places BlueStacks installs itself."""
    bases = list(emulator.PROGRAM_FILES)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        bases.append(Path(local) / "Programs")
    return bases


def install_dir() -> Path | None:
    for base in _roots():
        for pattern in INSTALL_GLOBS:
            candidate = base / pattern
            if candidate.is_file():
                return candidate.parent
    return None


def player_exe() -> Path | None:
    directory = install_dir()
    return directory / PLAYER_PROCESS if directory else None


def adb_exe() -> Path | None:
    directory = install_dir()
    if directory is None:
        return None
    candidate = directory / "HD-Adb.exe"
    return candidate if candidate.is_file() else None


def conf_file() -> Path | None:
    program_data = os.environ.get("ProgramData") or r"C:\ProgramData"
    for name in CONF_DIRS:
        candidate = Path(program_data) / name / "bluestacks.conf"
        if candidate.is_file():
            return candidate
    return None


def read_conf() -> dict[str, dict[str, str]]:
    """``{instance: {setting: value}}`` for every ``bst.instance.*`` line."""
    path = conf_file()
    if path is None:
        return {}
    values: dict[str, dict[str, str]] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                match = INSTANCE_LINE.match(line.strip())
                if not match:
                    continue
                values.setdefault(match["instance"], {})[match["setting"]] = match["value"].strip('"')
    except OSError:
        return {}
    return values


def instances() -> list[Instance]:
    path = conf_file()
    if path is None:
        return []
    out = []
    for name, settings in sorted(read_conf().items()):
        port = settings.get("adb_port") or settings.get("status.adb_port")
        base_name = re.sub(r"_\d+$", "", name)
        out.append(
            Instance(
                name=name,
                adb_port=int(port) if port and port.isdigit() else None,
                root_enabled=settings.get("enable_root_access") == "1",
                display_name=settings.get("display_name"),
                android=ANDROID_NAMES.get(base_name),
                conf=path,
            )
        )
    return out


def pick(instance: str | None = None) -> Instance | None:
    """The named instance, else the first one BlueStacks wrote an ADB port for."""
    found = instances()
    if instance:
        for candidate in found:
            if candidate.name == instance:
                return candidate
        return None
    for candidate in found:
        if candidate.adb_port:
            return candidate
    return found[0] if found else None


def running_pids() -> list[int]:
    """PIDs of running ``HD-Player.exe`` processes (empty off Windows)."""
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {PLAYER_PROCESS}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in (result.stdout or "").splitlines():
        fields = [field.strip('"') for field in line.split('","')]
        if len(fields) >= 2 and fields[0].lower() == PLAYER_PROCESS.lower():
            pid = fields[1].strip('"')
            if pid.isdigit():
                pids.append(int(pid))
    return pids


def running() -> bool:
    return bool(running_pids())


def _set_line(text: str, key: str, value: str) -> str:
    """Set ``key="value"`` in the conf text, keeping its line endings and key order."""
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol)
    pattern = re.compile(r"^" + re.escape(key) + "=")
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f'{key}="{value}"'
            break
    else:
        at = len(lines) - 1 if lines and lines[-1] == "" else len(lines)
        lines.insert(at, f'{key}="{value}"')
    return eol.join(lines)


def set_conf_readonly(flag: bool, path: Path | None = None) -> bool:
    """Make ``bluestacks.conf`` read-only so BlueStacks cannot reset the root flag at boot."""
    target = path or conf_file()
    if target is None or os.name != "nt":
        return False
    try:
        subprocess.run(
            ["attrib", "+R" if flag else "-R", str(target)],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def set_root(instance: str, enabled: bool = True, lock: bool = False) -> dict:
    """Turn root on/off for one instance. BlueStacks must not be running, or it rewrites the conf."""
    report: dict = {"instance": instance, "enabled": enabled, "ok": False, "changed": [], "locked": False}
    path = conf_file()
    if path is None:
        report["reason"] = "bluestacks.conf not found; install BlueStacks 5 or set ProgramData"
        return report
    if running():
        report["reason"] = (
            "BlueStacks is running and rewrites bluestacks.conf on exit: close every instance "
            "first (catcher bluestacks stop), then set root and start it again."
        )
        return report
    if pick(instance) is None:
        known = ", ".join(candidate.name for candidate in instances()) or "none found"
        report["reason"] = f"no instance named {instance!r} (instances: {known})"
        return report

    flag = "1" if enabled else "0"
    set_conf_readonly(False, path)
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            text = fh.read()
    except OSError as exc:
        report["reason"] = f"cannot read {path}: {exc}"
        return report

    for key, value in (
        ("bst.feature.rooting", flag),
        (f"bst.instance.{instance}.enable_root_access", flag),
    ):
        updated = _set_line(text, key, value)
        if updated != text:
            report["changed"].append(f"{key}={value}")
        text = updated

    try:
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    except OSError as exc:
        report["reason"] = f"cannot write {path}: {exc}"
        return report

    if enabled and lock:
        report["locked"] = set_conf_readonly(True, path)

    report["ok"] = True
    report["conf"] = str(path)
    return report


def start(instance: str) -> dict:
    """Launch an instance detached from this process."""
    report: dict = {"instance": instance, "ok": False}
    player = player_exe()
    if player is None:
        report["reason"] = "HD-Player.exe not found; install BlueStacks 5 or set `adb` in catcher.toml"
        return report
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            [str(player), "--instance", instance],
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        report["reason"] = str(exc)
        return report
    report.update({"ok": True, "player": str(player), "pid": process.pid})
    return report


def stop(timeout: int = 30, force: bool = True) -> dict:
    """Close every running BlueStacks player and wait for it to exit.

    ``taskkill`` without ``/F`` asks the window to close, which BlueStacks sometimes ignores;
    ``force`` then kills the process. The guest filesystem is journalled, so a forced stop is
    safe, but unsaved app state in the VM is lost.
    """
    report: dict = {"ok": False, "stopped": [], "forced": False}
    pids = running_pids()
    if not pids:
        report.update({"ok": True, "reason": "no BlueStacks instance is running"})
        return report
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        report["stopped"].append(pid)
    deadline = time.time() + timeout
    while time.time() < deadline and running():
        time.sleep(1)
    if running() and force and os.name == "nt":
        report["forced"] = True
        for pid in running_pids():
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                continue
        deadline = time.time() + 30
        while time.time() < deadline and running():
            time.sleep(1)
    report["ok"] = not running()
    if not report["ok"]:
        report["reason"] = "BlueStacks did not exit; close it from its own window and retry"
    return report


def connect(instance: Instance | None, adb_path: Path | None = None, settings: Settings | None = None) -> bool:
    """``adb connect`` the instance's NAT-forwarded port (BlueStacks only forwards it once)."""
    if instance is None or not instance.serial:
        return False
    try:
        result = emulator.adb(["connect", instance.serial], adb_path=adb_path, settings=settings, timeout=30)
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    output = ((result.stdout or "") + (result.stderr or "")).lower()
    return "connected" in output and "unable" not in output and "failed" not in output


def connect_running(adb_path: Path | None = None, settings: Settings | None = None) -> list[str]:
    """Connect every instance that has an ADB port; returns the serials tried."""
    tried = []
    for instance in instances():
        if instance.adb_port and connect(instance, adb_path, settings):
            tried.append(instance.serial or instance.name)
    return tried


def summary() -> dict:
    return {
        "install": str(install_dir()) if install_dir() else None,
        "conf": str(conf_file()) if conf_file() else None,
        "running": running(),
        "instances": instances(),
    }


SU_CANDIDATES = (
    "/system/bin/su",
    "/system/xbin/su",
    "/sbin/su",
    "/system/xbin/daemonsu",
    "/debug_ramdisk/su",
    "/system/bin/magisk",
)


def guest_root_diagnostics(serial: str, adb_path: Path | None = None, settings: Settings | None = None) -> dict:
    """What the booted guest actually offers: root mode, su binaries and the raw su probe."""
    info: dict = {"serial": serial, "mode": emulator.root_mode(serial, adb_path, settings)}
    info["id"] = emulator.shell(serial, "id", adb_path, settings, timeout=30).strip()
    info["su_probes"] = []
    for form in emulator.SU_FORMS:
        command = emulator.su_command(form, "id")
        output = emulator.shell(serial, command, adb_path, settings, timeout=30).strip()
        info["su_probes"].append({"command": command, "output": output})
    found = []
    for path in SU_CANDIDATES:
        listing = emulator.shell(serial, f"ls -l {path} 2>&1", adb_path, settings, timeout=30).strip()
        if "No such file" not in listing and "Permission denied" not in listing and listing:
            found.append(listing)
    info["su_paths"] = found
    props = {}
    for name in ("ro.secure", "ro.debuggable", "ro.build.type", "ro.product.cpu.abi"):
        props[name] = emulator.shell(serial, f"getprop {name}", adb_path, settings, timeout=30).strip()
    info["props"] = props
    return info


def root_image(instance: Instance) -> dict:
    """The instance's ``Root.vhd``: BlueStacks attaches it read-only when root is enabled."""
    directory = install_dir()
    engine = (directory.parent / "Engine" / instance.name) if directory else None
    image = engine / "Root.vhd" if engine else None
    if image is None or not image.is_file():
        return {"path": str(image) if image else None, "present": False}
    return {"path": str(image), "present": True, "bytes": image.stat().st_size}
