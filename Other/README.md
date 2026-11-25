# Other

Everything that is not a captured HTTP exchange lives here.

| Path | What it is |
| --- | --- |
| `apk/` | The shipped client: `base.apk` (v10.5.1) and its sha256. Pulled from the emulator on 2026-11-25, after the game left the app stores. |
| `device/` | Device and package fingerprint: `getprop`, `dumpsys package`, `pm dump`, display, connectivity, storage, package list. |
| `logs/` | `logcat` dumps. Includes the game's own network and startup logging. |
| `appdata/` | App data snapshot and external/OBB listings. Internal `/data/data` needs a rooted device; `appdata-listing` files are recorded either way. |
| `pcap/` | Optional wire-level capture from on-device `tcpdump` (`catcher pcap start` / `stop`, root only). |
| `snapshot.json` | Machine-readable record of the last `catcher snapshot`: device, version, what was pulled, what was skipped and why. |

## What is not captured

- **DNS and UDP** (including QUIC/HTTP3). The Catcher is an HTTP proxy: it sees TCP that
  connects through it. Names still appear as SNI and `Host` in the HTTP records, and a
  `catcher pcap` capture covers anything the proxy cannot.
- **Wire framing** of TLS. The proxy terminates TLS, so the preserved bytes are the HTTP
  messages, not the encrypted records.
- **Traffic from apps other than the game** - capture only the game session, since the proxy
  records whatever is routed to it.

## Why the APK matters

The game was delisted on 2026-10-30 and cannot be downloaded again. `apk/base.apk` is the
only copy of the final client; keep its sha256 so a corrupted file is noticed.
