# Catcher

Records everything Minion Rush sends and receives, and files it into this
archive's `API calls/`, `Contents/` and `Other/` folders. Built to preserve the
game's network behaviour before its online services close on **2027-01-29**.

## Requirements

- Python 3.11+ (tested on 3.15) with `mitmproxy`:
  `python -m pip install -r Catcher/requirements.txt`
- `adb` - auto-detected from Google Play Games on PC, BlueStacks, LDPlayer, or `PATH`.
- For **decrypted** traffic: an Android image whose system trust store you can write to
  (Android Studio AVD built with `-writable-system`, or BlueStacks/LDPlayer with root).
  The Play Games on PC emulator is a `user` build with a read-only `/system`, so it cannot
  trust a CA - see "Which emulator" below.

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
| `catcher pcap start\|stop` | Wire-level pcap via on-device `tcpdump` (root only) |
| `catcher export` | HAR per session, `API calls/endpoints.md|.json`, samples, `Contents/INDEX.md`, `blobs.sha256` |
| `catcher summary` | Per-session exchange counts, hosts and kinds |

All commands accept `--out <dir>` to point at a different archive root.

## Which emulator

**Full plaintext needs a trusted CA in the system store.** Since Android 7, apps built for
targetSdk >= 24 ignore user-installed CAs; Minion Rush is targetSdk 33. And because the game
is Unity-based, its network stack usually ignores Android's `http_proxy` setting as well.

Recommended: an AVD from `google_apis` (a `userdebug` image), launched with

```bat
emulator -avd minioncap -writable-system -http-proxy 127.0.0.1:8080
python -m catcher.cli install-ca --device emulator-5554 --reboot
adb install-multiple -r "Other\apk\base.apk" "Other\apk\split_UnityDataAssetPack.apk" "Other\apk\split_config.arm64_v8a.apk" "Other\apk\split_config.mdpi.apk"
```

`-http-proxy` redirects the emulator's whole TCP stack, so Unity traffic is captured too.
BlueStacks 5 / LDPlayer 9 with root enabled also work; redirect traffic on-device with
`iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-port 8080` and run a proxy
inside the VM.

The Play Games on PC emulator can still be used with `catcher proxy on` for a hostname
inventory, but expect most game traffic to bypass it and no decryption even when it does not.

If handshakes fail after the CA is trusted, the game is certificate-pinning. Escalate with
`frida-server` on the rooted image plus an SSL-unpinning script; the capture side needs no
changes.

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
```

## Honest limitations

- The proxy terminates TLS, so the TLS record framing on the wire is not preserved; the HTTP
  message bytes are. For byte-exact wire capture use `catcher pcap` (root) alongside.
- Certificate-pinned traffic fails to decrypt until pinning is bypassed with Frida.
- QUIC/UDP is not proxied. If the game uses HTTP/3, it will appear only in the pcap.
- `API calls/` redacts credential headers; `Contents/` keeps everything verbatim.
- The archive contains account tokens and chat/purchase traffic. Treat the repo accordingly
  before publishing, and expect to use Git LFS for `Contents/blobs/` and `Other/apk/*.apk`.
