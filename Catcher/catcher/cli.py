"""Catcher command line: run, doctor, install-ca, snapshot, proxy, pcap, export, summary."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # direct execution: python catcher/cli.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from catcher import bluestacks, emulator, manifest, snapshot  # noqa: E402
    from catcher.config import catcher_dir, load_settings  # noqa: E402
else:
    from . import bluestacks, emulator, manifest, snapshot  # noqa: E402
    from .config import catcher_dir, load_settings  # noqa: E402


def find_mitmdump() -> Path | None:
    exe = shutil.which("mitmdump")
    if exe:
        return Path(exe)
    candidates = [Path(sys.executable).parent / "Scripts" / ("mitmdump.exe" if os.name == "nt" else "mitmdump")]
    try:
        import site

        candidates.append(Path(site.getuserbase()) / "Scripts" / ("mitmdump.exe" if os.name == "nt" else "mitmdump"))
    except Exception:
        pass
    appdata = os.environ.get("APPDATA")
    if appdata:
        pyver = f"Python{sys.version_info.major}{sys.version_info.minor}"
        candidates.append(Path(appdata) / "Python" / pyver / "Scripts" / "mitmdump.exe")
        try:
            candidates.extend(sorted((Path(appdata) / "Python").glob("*/Scripts/mitmdump.exe"), reverse=True))
        except OSError:
            pass
    candidates.append(catcher_dir() / "tools" / ("mitmdump.exe" if os.name == "nt" else "mitmdump"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _first_device(settings, wanted: str | None = None) -> str | None:
    adb_path = emulator.find_adb(settings)
    if adb_path is None:
        return None
    devices = [device for device in emulator.list_devices(adb_path, settings) if device.get("state") == "device"]
    if not devices:
        # BlueStacks forwards ADB through its own daemon, so a booted instance may need `adb connect`.
        bluestacks.connect_running(adb_path, settings)
        devices = [device for device in emulator.list_devices(adb_path, settings) if device.get("state") == "device"]
    # Prefer the BlueStacks instance when several emulators are connected at once.
    devices.sort(key=lambda device: 0 if device["serial"].startswith("127.0.0.1:") else 1)
    if wanted:
        return wanted if any(device["serial"] == wanted for device in devices) else None
    return devices[0]["serial"] if devices else None


def cmd_run(settings, args) -> int:
    host = args.host or settings.listen_host
    port = args.port or settings.listen_port
    settings.listen_host = host
    settings.listen_port = port
    if args.session:
        settings.session_name = args.session
    if args.max_inline is not None:
        settings.max_inline_body = args.max_inline
    settings.ensure_dirs()

    mitmdump = find_mitmdump()
    addon = catcher_dir() / "catcher" / "addon.py"
    if mitmdump is None:
        print("mitmdump is not installed and Catcher/tools/ has no standalone build.")
        print("  python -m pip install -r Catcher/requirements.txt")
        print("  (or drop the official standalone mitmdump.exe into Catcher/tools/)")
        return 2
    if not port_free(host, port):
        print(f"port {port} is already in use on {host}")
        return 2

    env = os.environ.copy()
    env.update(
        {
            "CATCHER_OUT_ROOT": str(settings.out_root),
            "CATCHER_LISTEN_HOST": host,
            "CATCHER_LISTEN_PORT": str(port),
            "CATCHER_MAX_INLINE": str(settings.max_inline_body),
            "CATCHER_PACKAGE": settings.package,
            "PYTHONPATH": os.pathsep.join(
                [str(catcher_dir())] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
            ),
        }
    )
    if settings.session_name:
        env["CATCHER_SESSION"] = settings.session_name

    ca = emulator.mitmproxy_ca_cert()
    print("Catcher proxy starting", flush=True)
    print(f"  listening   : http://{host}:{port}", flush=True)
    print(f"  archive     : {settings.out_root}", flush=True)
    print(f"  session name: {settings.session_name or '(timestamp)'}", flush=True)
    print(f"  mitmdump    : {mitmdump}", flush=True)
    print(f"  CA bundle   : {ca or '(generated on first run in ' + str(Path.home() / '.mitmproxy') + ')'}", flush=True)
    print("", flush=True)
    print("Route traffic here:", flush=True)
    print("  BlueStacks : catcher bluestacks status                       (instances, root, ADB port)", flush=True)
    print("               catcher proxy on --device 127.0.0.1:5555 --address 10.0.2.2:%d" % port, flush=True)
    print("               catcher install-ca --device 127.0.0.1:5555    (rooted instance: system trust store)", flush=True)
    print("  rooted AVD : emulator -avd <name> -writable-system -http-proxy 127.0.0.1:%d" % port, flush=True)
    print("               catcher install-ca --device <serial> --reboot", flush=True)
    print("  standalone : curl --proxy http://%s:%d --cacert %s <url>" % (host, port, ca or "<ca.pem>"), flush=True)
    print("", flush=True)

    command = [
        str(mitmdump),
        "-s",
        str(addon),
        "--listen-host",
        host,
        "--listen-port",
        str(port),
        "--set",
        "termlog_verbosity=info",
    ] + list(args.extra or [])
    try:
        # mitmdump quits as soon as stdin hits EOF, so keep an open pipe attached:
        # without it, running the catcher from a background job or a service exits at once.
        code = subprocess.call(command, env=env, stdin=subprocess.PIPE)
    except KeyboardInterrupt:
        code = 0
    print("", flush=True)
    print("Capture stopped. Rebuild indexes with:  catcher export", flush=True)
    return code


def cmd_doctor(settings, args) -> int:
    print("Catcher doctor")
    print(f"  archive root : {settings.out_root}")
    print(f"  Catcher dir  : {catcher_dir()}")
    print(f"  free space   : {emulator.free_space_gb(settings.out_root)} GB")

    ca = emulator.mitmproxy_ca_cert()
    if ca:
        try:
            print(f"  mitmproxy CA : {ca}  (system-store filename {emulator.ca_subject_hash(ca)}.0)")
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            print(f"  mitmproxy CA : {ca}  (hash failed: {exc})")
    else:
        print("  mitmproxy CA : missing - run `catcher run` once so mitmproxy creates ~/.mitmproxy")

    print(f"  mitmdump     : {find_mitmdump() or 'NOT FOUND - python -m pip install -r Catcher/requirements.txt'}")
    adb_path = emulator.find_adb(settings)
    print(f"  adb          : {adb_path or 'NOT FOUND'}")
    if adb_path is None:
        return 1

    info = bluestacks.summary()
    print(f"  BlueStacks   : {info['install'] or 'not installed'}")
    if info["conf"]:
        print(f"  config       : {info['conf']}  (running: {'yes' if info['running'] else 'no'})")
        for instance in info["instances"]:
            print(
                f"    {instance.name:<12} android {instance.android or '?':<16}"
                f" adb {instance.serial or '-':<16} root {'on' if instance.root_enabled else 'off'}"
            )

    devices = emulator.list_devices(adb_path, settings)
    if not devices and bluestacks.connect_running(adb_path, settings):
        devices = emulator.list_devices(adb_path, settings)
    if not devices:
        print("  devices      : none connected")
        return 1

    for device in devices:
        serial = device["serial"]
        print("")
        print(f"  device {serial}  [{device.get('state')}]")
        if device.get("state") != "device":
            continue
        props = emulator.device_props(serial, adb_path, settings)
        print(f"    model      : {props.get('ro.product.model')} ({props.get('ro.product.cpu.abi')})")
        print(f"    android    : {props.get('ro.build.version.release')} / SDK {props.get('ro.build.version.sdk')} / {props.get('ro.build.type')}")
        mode = emulator.root_mode(serial, adb_path, settings)
        root = mode is not None
        print(f"    root       : {('yes (' + mode + ')') if mode else 'no'}")
        if ca:
            try:
                present = emulator.system_ca_present(serial, emulator.ca_subject_hash(ca), adb_path, settings)
                print(f"    system CA  : {'installed' if present else 'missing'}")
            except Exception as exc:  # noqa: BLE001
                print(f"    system CA  : check failed: {exc}")
        proxy = emulator.proxy_setting(serial, adb_path, settings)
        print(f"    http_proxy : {proxy or '(none)'}")
        version = emulator.package_version(serial, settings.package, adb_path, settings)
        print(f"    game       : {settings.package} {version or '(not installed)'}")
        if not root:
            print("    note       : no root, so the system CA store cannot be written and")
            print("                 `catcher snapshot` cannot read /data/data. For BlueStacks 5:")
            print("                 catcher bluestacks stop && catcher bluestacks root --instance <name>")
            print("                 && catcher bluestacks start --instance <name>")
            print("                 (a stock 5.22 build keeps su silent, see `catcher bluestacks status`)")
            print("                 Without root, HTTPS is still decryptable by repacking the APK")
            print("                 with the proxy CA as a bundled raw root (README 'Repacked APK capture'),")
            print("                 and pinned endpoints need Frida (Catcher/tools/ssl_unpin.js).")

    sessions = manifest.summary(settings)
    print("")
    print(f"  sessions     : {len(sessions)}")
    for name, stats in sessions.items():
        print(f"    {name}: {stats['exchanges']} exchanges")
    return 0


def cmd_bluestacks(settings, args) -> int:
    info = bluestacks.summary()
    if args.action == "status":
        print(f"install     : {info['install'] or 'not found'}")
        print(f"config      : {info['conf'] or 'not found'}")
        print(f"running     : {'yes' if info['running'] else 'no'}")
        if not info["instances"]:
            print("instances   : none (create one in the BlueStacks Multi-Instance Manager)")
            return 1
        for instance in info["instances"]:
            print(f"\n  {instance.name}")
            print(f"    android  : {instance.android or 'unknown'}")
            print(f"    adb      : {instance.serial or '(no port recorded)'}")
            print(f"    root     : {'enabled' if instance.root_enabled else 'disabled'}  (bst.instance.{instance.name}.enable_root_access)")
            image = bluestacks.root_image(instance)
            if image["present"]:
                print(f"    root.vhd : {image['path']} ({image['bytes'] / (1024**3):.1f} GB)")
            print(f"    display  : {instance.display_name or '-'}")
        print("")
        print("  bst.feature.rooting is the master switch; some builds rewrite it to 0 at boot,")
        print("  which `catcher bluestacks root --lock` prevents by making the conf read-only.")

        target = bluestacks.pick(args.instance)
        adb_path = emulator.find_adb(settings)
        if target is not None and adb_path is not None and bluestacks.connect(target, adb_path, settings):
            serial = target.serial or target.name
            diagnostics = bluestacks.guest_root_diagnostics(serial, adb_path, settings)
            print("")
            print(f"  guest {serial}")
            print(f"    id       : {diagnostics['id']}")
            for probe in diagnostics["su_probes"]:
                print(f"    {probe['command']:<16}: {probe['output'] or '(no output)'}")
            print(f"    su paths : {', '.join(diagnostics['su_paths']) or 'none found'}")
            print(f"    root     : {diagnostics['mode'] or 'unavailable'}")
        return 0

    if args.action == "root":
        target = bluestacks.pick(args.instance)
        if target is None:
            print("No BlueStacks instance found (see `catcher bluestacks status`).")
            return 2
        report = bluestacks.set_root(target.name, enabled=not args.off, lock=args.lock)
        if not report["ok"]:
            print(report.get("reason") or "could not change root access")
            return 1
        state = "disabled" if args.off else "enabled"
        changed = ", ".join(report["changed"]) or "already set"
        print(f"root {state} for {target.name}  ({changed})")
        print(f"  config : {report['conf']}")
        if report.get("locked"):
            print("  locked : bluestacks.conf is read-only so BlueStacks cannot reset the flag at boot")
            print("           (`catcher bluestacks root --off` unlocks it again)")
        print(f"  next   : catcher bluestacks start --instance {target.name}")
        print("           then `catcher doctor` - root should read 'yes (su)'")
        return 0

    if args.action == "start":
        target = bluestacks.pick(args.instance)
        if target is None:
            print("No BlueStacks instance found (see `catcher bluestacks status`).")
            return 2
        if bluestacks.running():
            print("BlueStacks is already running; close it first (`catcher bluestacks stop`).")
            return 1
        report = bluestacks.start(target.name)
        if not report["ok"]:
            print(report.get("reason") or "could not start the instance")
            return 1
        print(f"started {target.name} (pid {report['pid']})")
        if target.serial:
            print(f"  adb    : {target.serial}  (wait for boot, then `catcher doctor`)")
        return 0

    if args.action == "stop":
        report = bluestacks.stop()
        if report["stopped"]:
            verb = "closed and killed" if report.get("forced") else "closed"
            print(f"{verb} pid(s): " + ", ".join(str(pid) for pid in report["stopped"]))
        print("BlueStacks is not running" if report["ok"] else (report.get("reason") or "still running"))
        return 0 if report["ok"] else 1

    print(f"unknown action {args.action}")
    return 2


def cmd_install_ca(settings, args) -> int:
    cert = Path(args.cert) if args.cert else emulator.mitmproxy_ca_cert()
    if cert is None or not cert.is_file():
        print("mitmproxy CA not found. Run `catcher run` once, then retry (or pass --cert).")
        return 2
    serial = _first_device(settings, args.device)
    if serial is None:
        print("No adb device found (see `catcher doctor`).")
        return 2
    report = emulator.install_system_ca(serial, cert, settings=settings, reboot=args.reboot)
    for step in report["steps"]:
        print(f"  $ {step['cmd']}")
        if step.get("output"):
            print(f"    {step['output']}")
        if step.get("error"):
            print(f"    ERROR: {step['error']}")
    print("")
    if report.get("ok"):
        print(f"CA installed as {report['target']} - restart the game so it picks up the new trust store.")
        return 0
    print(report.get("reason") or "CA installation did not verify; check the output above.")
    return 1


def cmd_snapshot(settings, args) -> int:
    report = snapshot.run_snapshot(
        settings,
        serial=args.device,
        force=args.force,
        appdata=not args.no_appdata,
        logcat=not args.no_logcat,
    )
    print(f"device      : {report['device']} {report.get('model')} / Android {report.get('android')} / root={report['root']}")
    print(f"game        : {settings.package} {report.get('app_version')}")
    for apk in report.get("apks", []):
        state = "kept" if apk.get("skipped") else "pulled"
        print(f"apk         : {state} {apk['local']} ({apk.get('size', '?')} bytes)")
    print(f"device dumps: {len(report.get('device_dumps', []))} files in Other/device")
    if report.get("logcat"):
        print(f"logcat      : {report['logcat']['file']}")
    appdata = report.get("appdata") or {}
    if appdata.get("file"):
        print(f"app data    : {appdata['file']} ({appdata['bytes']} bytes)")
    elif appdata.get("skipped"):
        print(f"app data    : skipped - {appdata['skipped']}")
    elif appdata.get("error"):
        print(f"app data    : failed - {appdata['error']}")
    print(f"report      : {report['report_file']}")
    return 0


def cmd_proxy(settings, args) -> int:
    serial = _first_device(settings, args.device)
    if serial is None:
        print("No adb device found (see `catcher doctor`).")
        return 2
    if args.action == "status":
        print(emulator.proxy_setting(serial, settings=settings) or "(no global http_proxy)")
        return 0
    if args.action == "on":
        ok = emulator.set_proxy(serial, args.address, settings=settings)
        print(f"http_proxy = {emulator.proxy_setting(serial, settings=settings) if ok else 'FAILED'}")
        if ok:
            print("Only apps that honour Android's proxy setting will use it (OkHttp, WebView).")
            print("Unity-based game traffic usually ignores it - use a rooted image with -http-proxy for that.")
        return 0 if ok else 1
    ok = emulator.clear_proxy(serial, settings=settings)
    print("http_proxy cleared" if ok else "could not clear http_proxy")
    return 0 if ok else 1


def cmd_pcap(settings, args) -> int:
    if args.action == "start":
        serial = _first_device(settings, args.device)
        if serial is None:
            print("No adb device found.")
            return 2
        state = snapshot.pcap_start(settings, serial)
        print(f"tcpdump running on {state['serial']} -> {state['remote']}")
        print("Play the game, then run `catcher pcap stop`.")
        return 0
    result = snapshot.pcap_stop(settings)
    print(f"pcap saved: {result['file']} ({result['bytes']} bytes)")
    return 0


def cmd_export(settings, args) -> int:
    result = manifest.write_exports(settings)
    print(f"sessions : {result['sessions']}")
    print(f"exchanges: {result['exchanges']}")
    print(f"endpoints: {result['endpoints']}  -> {result['api_md']}")
    blobs = result["blobs"]
    print(f"blobs    : {blobs['count']} files, {blobs['bytes']} bytes, {blobs['over_github_limit']} over 100 MB")
    notes = result.get("other_notes") or {}
    print(f"Other/   : dns-notes.md ({notes.get('hosts', 0)} hosts), websockets.md ({notes.get('websockets', 0)}), capture-log.md")
    print(f"HARs     : {result['har_dir']}")
    return 0


def cmd_summary(settings, args) -> int:
    sessions = manifest.summary(settings)
    if not sessions:
        print("No captured sessions yet. Run `catcher run`, then play the game.")
        return 0
    for name, stats in sessions.items():
        print(f"{name}: {stats['exchanges']} exchanges, {stats['bytes_down']} bytes down")
        print(f"  kinds: {stats['kinds']}")
        for host, count in stats["hosts"].items():
            print(f"  {host or '(no host)'}: {count}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="catcher", description="Capture everything Minion Rush sends and receives.")
    subparsers = parser.add_subparsers(dest="command")

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--out", help="archive root (default: the folder containing Catcher/)")
        return sub

    run = add("run", "start the capture proxy")
    run.add_argument("--host", default=None, help="listen address (default 127.0.0.1)")
    run.add_argument("--port", type=int, default=None, help="listen port (default 8080)")
    run.add_argument("--session", default=None, help="session folder name (default: timestamp)")
    run.add_argument("--max-inline", type=int, default=None, help="bodies up to this many bytes are stored inline")
    run.add_argument("extra", nargs=argparse.REMAINDER, help="extra arguments passed to mitmdump")

    doctor = add("doctor", "inspect adb, devices, root, CA and proxy state")
    doctor.add_argument("--device", default=None)

    ca = add("install-ca", "install the mitmproxy CA into a rooted device's system trust store")
    ca.add_argument("--device", default=None)
    ca.add_argument("--cert", default=None)
    ca.add_argument("--reboot", action="store_true")

    snap = add("snapshot", "archive APK, device info, logcat and app data into Other/")
    snap.add_argument("--device", default=None)
    snap.add_argument("--force", action="store_true", help="re-pull the APK even if it is already archived")
    snap.add_argument("--no-appdata", action="store_true")
    snap.add_argument("--no-logcat", action="store_true")

    proxy = add("proxy", "set/clear Android's global http_proxy")
    proxy.add_argument("action", choices=["on", "off", "status"])
    proxy.add_argument("--device", default=None)
    proxy.add_argument("--address", default="10.0.2.2:8080", help="proxy address as seen from inside the emulator")

    pcap = add("pcap", "wire-level capture with on-device tcpdump (root only)")
    pcap.add_argument("action", choices=["start", "stop"])
    pcap.add_argument("--device", default=None)

    bs = add("bluestacks", "BlueStacks 5 instances: ADB port, root access, start/stop")
    bs.add_argument("action", choices=["status", "root", "start", "stop"])
    bs.add_argument("--instance", default=None, help="instance name, e.g. Pie64 (default: first with an ADB port)")
    bs.add_argument("--off", action="store_true", help="disable root instead of enabling it")
    bs.add_argument("--lock", action="store_true", help="make bluestacks.conf read-only so BlueStacks cannot reset the flag at boot")

    add("export", "rebuild HARs, the API calls index and the archive index")
    add("summary", "print capture statistics")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    settings = load_settings(out_root=getattr(args, "out", None))
    handlers = {
        "run": cmd_run,
        "doctor": cmd_doctor,
        "install-ca": cmd_install_ca,
        "snapshot": cmd_snapshot,
        "proxy": cmd_proxy,
        "pcap": cmd_pcap,
        "bluestacks": cmd_bluestacks,
        "export": cmd_export,
        "summary": cmd_summary,
    }
    return handlers[args.command](settings, args)


if __name__ == "__main__":
    sys.exit(main())
