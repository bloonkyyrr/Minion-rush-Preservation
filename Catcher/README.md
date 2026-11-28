# Catcher

Records everything Minion Rush sends and receives, and files it into this
archive's `API calls/`, `Contents/` and `Other/` folders. Built to preserve the
game's network behaviour before its online services close on **2027-01-29**.

## Requirements

- Python 3.11+ (tested on 3.15) with `mitmproxy`:
  `python -m pip install -r Catcher/requirements.txt`
- `adb` - auto-detected; BlueStacks 5's `HD-Adb.exe` is preferred, then Google Play Games on PC,
  LDPlayer, Nox and `PATH`.
- A BlueStacks 5 instance with Minion Rush installed. `catcher bluestacks status` prints its ADB
  port, root flags and whether the guest actually hands out `su`.
- For **decrypted** traffic: either a rooted image whose `/system` can be written (system trust
  store) or the repacked APK below, which needs no root at all.

## Quick start

```bat
Catcher\run.bat
```

This starts mitmproxy on `127.0.0.1:8080` and creates a new session folder under
`Contents/`. While it runs, play the game; every exchange is written immediately.

Then rebuild the indexes:

```bat
python -m catcher.cli export
```

## Commands

| Command | What it does |
| --- | --- |
| `catcher run` | Start the proxy (`--port`, `--session`, `--max-inline`, extra mitmdump args pass through) |
| `catcher doctor` | adb path, devices, Android version, root state, system CA state, `http_proxy`, game version |
| `catcher install-ca` | Push the mitmproxy CA into a rooted device's `/system/etc/security/cacerts` and verify |
| `catcher snapshot` | Archive APK, device dumps, logcat and (with root) `/data/data/<pkg>` into `Other/` |
| `catcher proxy on\|off\|status` | Set/clear Android's global `http_proxy` (works for OkHttp-style traffic only) |
| `catcher bluestacks status\|root\|start\|stop` | BlueStacks 5 instances: ADB port, `bst.feature.rooting`/`enable_root_access`, guest `su` diagnostic, start/stop the player |
| `catcher pcap start\|stop` | Wire-level pcap via on-device `tcpdump` (root only) |
| `catcher export` | HAR per session, `API calls/endpoints.md|.json`, samples, `Contents/INDEX.md`, `blobs.sha256`, and `Other/dns-notes.md|websockets.md|capture-log.md` |
| `catcher summary` | Per-session exchange counts, hosts and kinds |

All commands accept `--out <dir>` to point at a different archive root.

## Which emulator: BlueStacks 5

The current setup is BlueStacks 5, a Pie 64-bit instance (`Pie64`, Android 9). ADB is
`C:\Program Files\BlueStacks_nxt\HD-Adb.exe`; the instance listens on `127.0.0.1:5555`, and adb
often lists the same guest as `emulator-5554` as well - either serial works.

```bat
python -m catcher.cli bluestacks status                   :: instances, ADB port, root, guest su
python -m catcher.cli bluestacks root --instance Pie64    :: bst.feature.rooting + enable_root_access
python -m catcher.cli bluestacks start --instance Pie64
python -m catcher.cli doctor                              :: root should read "yes (su -c)"
```

`catcher bluestacks root` writes the two flags BlueStacks reads at boot, and refuses to run while
an instance is up because BlueStacks rewrites `bluestacks.conf` on exit. Root is applied at boot,
never live: restart the instance after changing it. On builds that reset `bst.feature.rooting`
to `0` at boot, `--lock` marks the conf read-only so the flag survives (`root --off` unlocks it).

Do not run `adb root`: BlueStacks does not support it, adbd stops, and the instance has to be
rebooted before ADB answers again. Use `catcher bluestacks stop` / `start` instead.

**Root on 5.22 builds.** BlueStacks 5.22.296 ships a setuid `/system/xbin/su` that returns
nothing even with both flags set; `catcher bluestacks status` shows exactly that (`su -c id` ->
no output, `root: unavailable`). Since 5.22 BlueStacks gates root behind a disk-integrity check,
so a stock instance of this build is not rootable without patching it; an older or patched
instance reports `root: yes (su -c)` and the root-only commands below start working. The
archive's default capture path therefore stays the repacked APK, which needs no root.

With root on a writable `/system` (an R/W-patched instance or a `-writable-system` AVD):

```bat
python -m catcher.cli install-ca --device 127.0.0.1:5555
python -m catcher.cli snapshot --device 127.0.0.1:5555
```

**Full plaintext needs a trusted CA in the system store.** Since Android 7, apps built for
targetSdk >= 24 ignore user-installed CAs; Minion Rush is targetSdk 33. And because the game
is Unity-based, its network stack usually ignores Android's `http_proxy` setting as well.

Routing traffic from a BlueStacks guest into the proxy:

```bat
python -m catcher.cli proxy on --device 127.0.0.1:5555 --address 10.0.2.2:8080
adb reverse tcp:8080 tcp:8080
```

`10.0.2.2` is the host's loopback as seen from the guest, so the proxy is reachable without
`adb reverse`. Apps that honour Android's proxy setting (OkHttp, WebView, and this build's Unity
libcurl) are captured; anything that ignores it needs the on-device redirect or a pcap. A rooted
instance can redirect all TCP with `iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT
--to-port 8080`, but that needs a transparent proxy (Linux/macOS host or an in-guest relay) -
mitmproxy on Windows only serves explicit-proxy mode.

An AVD from `google_apis` (a `userdebug` image) remains the simplest rooted target:

```bat
emulator -avd minioncap -writable-system -http-proxy 127.0.0.1:8080
python -m catcher.cli install-ca --device emulator-5554 --reboot
adb install-multiple -r "Other\apk\base.apk" "Other\apk\split_UnityDataAssetPack.apk" "Other\apk\split_config.arm64_v8a.apk" "Other\apk\split_config.mdpi.apk"
```

`-http-proxy` redirects the emulator's whole TCP stack, so Unity traffic is captured too.

If handshakes fail after the CA is trusted, the game is certificate-pinning. Two ways to
bypass it (the capture side needs no changes):

- **Rooted instance:** run `frida-server` on the device plus an SSL-unpinning script.
- **Non-rooted instance:** inject the Frida gadget into the repacked APK and re-sign:
  ```bat
  python -m objection patchapk -s base-mitm.apk -a arm64-v8a \
      -c gadget-config.json -l ssl_unpin.js -d -k --ignore-nativelibs
  ```
  `Catcher/tools/ssl_unpin.js` is the universal unpinning script and
  `Catcher/tools/work/patched/gadget-config.json` is the matching gadget config.
  Re-sign the resulting APK with the same keystore as the splits, then
  `adb install-multiple`. Pinned endpoints (e.g. `config.uca.cloud.unity3d.com`,
  `cdp.cloud.unity3d.com`) are then decrypted and recorded normally.

## What to exercise in a capture session

Each session captures whatever the game does while the proxy runs, so cover the flows a revival
server has to reproduce. Start a fresh session per flow when possible (`catcher run --session <name>`):

- First launch on a clean install: guest profile creation, tutorial/onboarding, first asset download.
- Gameloft account: sign-in, sign-out, account linking, wrong-password and expired-token errors.
- Cloud save: upload a save, wipe local data, restore from cloud, conflict resolution.
- Leaderboards: open, submit a score, refresh a friend/global board.
- Live events: event list, event entry, event progress and rewards.
- Store: catalogue, in-app purchase flow up to the store sheet (do not complete a real payment),
  inventory and item grants, daily rewards, spins.
- Social: friends, gifting, messages/chat if present.
- Support: help/FAQ and the Helpshift conversation endpoints.

After each session run `catcher export` so `API calls/` and the derived `Other/` notes stay current.

## What gets recorded

Per HTTP exchange: method, URL, HTTP version, headers in wire order/case, request and response
bodies (raw bytes plus decoded form), sha256 and size, TLS details (SNI, ALPN, cipher,
version, peer certificate), client/server addresses, timing, and any proxy error.
WebSocket frames are recorded per connection in `ws/*.jsonl`.

Layout:

```
Contents/<session>/
  session.json            session metadata
  manifest.jsonl          one JSON object per exchange (headers, hashes, timings, classification)
  http/00001-host-path.req/.res   raw message; small bodies inline
  ws/00001-host-path.jsonl        WebSocket frames, both directions
  har/<session>.har       HAR 1.2 for DevTools / viewers
  session.log             capture log
Contents/blobs/<xx>/<sha256>      bodies larger than max_inline_body, deduplicated
Contents/blobs.sha256             every blob with size (kept in git even when blobs are not)
Contents/INDEX.md                 session and blob overview
API calls/endpoints.md|.json      distinct endpoint signatures, counts, statuses, samples
API calls/samples/                one redacted request/response pair per endpoint
Other/                            apk/, device/, appdata/, logs/, pcap/, snapshot.json
Other/dns-notes.md|websockets.md|capture-log.md   derived notes from `catcher export`
```

## Honest limitations

- The proxy terminates TLS, so the TLS record framing on the wire is not preserved; the HTTP
  message bytes are. For byte-exact wire capture use `catcher pcap` (root) alongside.
- Certificate-pinned traffic fails to decrypt until pinning is bypassed with Frida.
- QUIC/UDP is not proxied. If the game uses HTTP/3, it will appear only in the pcap.
- `API calls/` redacts credential headers; `Contents/` keeps everything verbatim.
- The archive contains account tokens and chat/purchase traffic. Treat the repo accordingly
  before publishing, and expect to use Git LFS for `Contents/blobs/` and `Other/apk/*.apk`.
