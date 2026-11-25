"""Device and app snapshots written into ``Other/``."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import emulator
from .config import Settings
from .store import slugify

DEVICE_COMMANDS = {
    "getprop.txt": "getprop",
    "dumpsys-package.txt": "dumpsys package {pkg}",
    "pm-dump.txt": "pm dump {pkg}",
    "dumpsys-display.txt": "dumpsys display",
    "dumpsys-connectivity.txt": "dumpsys connectivity",
    "dumpsys-wifi.txt": "dumpsys wifi",
    "dumpsys-activity.txt": "dumpsys activity activities",
    "df.txt": "df -h",
    "uname.txt": "uname -a",
    "uptime.txt": "uptime",
    "packages.txt": "pm list packages",
    "netstat.txt": "netstat -an",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_snapshot(
    settings: Settings,
    serial: str | None = None,
    force: bool = False,
    appdata: bool = True,
    logcat: bool = True,
) -> dict:
    settings.ensure_dirs()
    adb_path = emulator.find_adb(settings)
    if adb_path is None:
        raise FileNotFoundError("adb.exe not found; install an emulator or set `adb` in catcher.toml")

    devices = [d for d in emulator.list_devices(adb_path, settings) if d.get("state") == "device"]
    if not devices:
        raise RuntimeError("no adb device in state 'device' (start the emulator first)")
    serial = serial or devices[0]["serial"]
    if not any(d["serial"] == serial for d in devices):
        raise RuntimeError(f"device {serial} is not connected")

    other = settings.other_dir
    apk_dir = other / "apk"
    device_dir = other / "device"
    logs_dir = other / "logs"
    appdata_dir = other / "appdata"
    for directory in (apk_dir, device_dir, logs_dir, appdata_dir):
        directory.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "device": serial,
        "package": settings.package,
        "steps": [],
    }
    props = emulator.device_props(serial, adb_path, settings)
    report["model"] = props.get("ro.product.model")
    report["android"] = props.get("ro.build.version.release")
    report["sdk"] = props.get("ro.build.version.sdk")
    report["build_type"] = props.get("ro.build.type")
    report["root"] = "uid=0" in emulator.shell(serial, "id", adb_path, settings)
    report["app_version"] = emulator.package_version(serial, settings.package, adb_path, settings)

    # -- apk(s) ----------------------------------------------------------
    paths = emulator.shell(serial, f"pm path {settings.package}", adb_path, settings)
    apks = []
    for line in paths.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        remote = line.split(":", 1)[1]
        remote_name = Path(remote).name or "base.apk"
        local = apk_dir / (remote_name if remote_name.endswith(".apk") else f"{slugify(settings.package, 40)}-{remote_name}")
        if local.is_file() and not force:
            apks.append({"remote": remote, "local": str(local.relative_to(settings.out_root)), "skipped": True})
            continue
        result = emulator.adb(["-s", serial, "pull", remote, str(local)], adb_path=adb_path, settings=settings, timeout=1800)
        entry = {
            "remote": remote,
            "local": str(local.relative_to(settings.out_root)),
            "pull_output": ((result.stdout or "") + (result.stderr or "")).strip(),
        }
        if local.is_file():
            entry["size"] = local.stat().st_size
            entry["sha256"] = _sha256(local)
        apks.append(entry)
    report["apks"] = apks

    # -- device dumps ----------------------------------------------------
    dumps = []
    for name, command in DEVICE_COMMANDS.items():
        output = emulator.shell(serial, command.format(pkg=settings.package), adb_path, settings, timeout=180)
        path = device_dir / name
        path.write_text(output, encoding="utf-8", errors="replace")
        dumps.append({"file": str(path.relative_to(settings.out_root)), "bytes": path.stat().st_size})
    report["device_dumps"] = dumps

    # -- logcat ----------------------------------------------------------
    if logcat:
        output = emulator.shell(serial, "logcat -d -v threadtime", adb_path, settings, timeout=300)
        path = logs_dir / f"logcat-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        path.write_text(output, encoding="utf-8", errors="replace")
        report["logcat"] = {"file": str(path.relative_to(settings.out_root)), "bytes": path.stat().st_size}

    # -- external + internal app data ------------------------------------
    external = ["/sdcard/Android/data/" + settings.package, "/sdcard/Android/obb/" + settings.package]
    external_report = []
    for remote in external:
        listing = emulator.shell(serial, f"ls -la {remote}", adb_path, settings, timeout=60)
        external_report.append({"path": remote, "listing": listing.strip()})
    report["external_data"] = external_report

    if appdata:
        if report["root"]:
            archive = appdata_dir / f"appdata-{slugify(settings.package, 40)}.tar.gz"
            try:
                emulator.run_binary(
                    ["-s", serial, "exec-out", f"tar -czf - /data/data/{settings.package} 2>/dev/null"],
                    archive,
                    adb_path,
                    settings,
                    timeout=3600,
                )
                report["appdata"] = {
                    "file": str(archive.relative_to(settings.out_root)),
                    "bytes": archive.stat().st_size if archive.is_file() else 0,
                    "sha256": _sha256(archive) if archive.is_file() else None,
                }
            except Exception as exc:  # noqa: BLE001 - reported
                report["appdata"] = {"error": str(exc)}
        else:
            report["appdata"] = {
                "skipped": (
                    "device is not rooted; /data/data is unreadable. Run the snapshot again on a rooted "
                    "device (AVD with -writable-system) to archive saves, preferences and downloaded assets."
                )
            }

    report_file = other / "snapshot.json"
    report["report_file"] = str(report_file.relative_to(settings.out_root))
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


PCAP_DIR = "pcap"


def pcap_start(settings: Settings, serial: str, remote_name: str | None = None) -> dict:
    adb_path = emulator.find_adb(settings)
    if adb_path is None:
        raise FileNotFoundError("adb.exe not found")
    if not emulator.is_root(serial, adb_path, settings):
        raise RuntimeError("pcap capture needs root (adb shell tcpdump requires uid 0)")
    name = remote_name or f"catcher-{time.strftime('%Y%m%d-%H%M%S')}.pcap"
    remote = f"/sdcard/{name}"
    emulator.shell(serial, f"rm -f {remote}", adb_path, settings)
    emulator.shell(serial, f"(tcpdump -i any -s 0 -w {remote} >/dev/null 2>&1 &)", adb_path, settings)
    state_dir = settings.other_dir / PCAP_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {"serial": serial, "remote": remote, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (state_dir / "active.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def pcap_stop(settings: Settings) -> dict:
    adb_path = emulator.find_adb(settings)
    if adb_path is None:
        raise FileNotFoundError("adb.exe not found")
    state_dir = settings.other_dir / PCAP_DIR
    state_file = state_dir / "active.json"
    if not state_file.is_file():
        raise RuntimeError("no active pcap capture (run `catcher pcap start` first)")
    state = json.loads(state_file.read_text(encoding="utf-8"))
    serial = state["serial"]
    emulator.shell(serial, "pkill -INT tcpdump", adb_path, settings)
    time.sleep(2)
    local = state_dir / Path(state["remote"]).name
    result = emulator.adb(["-s", serial, "pull", state["remote"], str(local)], adb_path=adb_path, settings=settings, timeout=1800)
    emulator.shell(serial, f"rm -f {state['remote']}", adb_path, settings)
    state_file.unlink(missing_ok=True)
    return {
        "file": str(local),
        "bytes": local.stat().st_size if local.is_file() else 0,
        "pull_output": ((result.stdout or "") + (result.stderr or "")).strip(),
    }
