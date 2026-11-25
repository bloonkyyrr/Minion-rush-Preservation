# Minion Rush Preservation

An archive of everything **Despicable Me: Minion Rush** (`com.gameloft.android.AMAZ.GloftDMAS`)
sends and receives over the network, captured from a running install before Gameloft's online
services close on **29 January 2027**. The goal is to give anyone building a revival server
after the sunset real request/response shapes instead of guesses.

## Timeline

| Date | Event |
| --- | --- |
| 2026-10-30 | Delisted from app stores, in-app purchases disabled. The APK can no longer be downloaded. |
| 2026-11-25 | This archive started; APK 10.5.1 pulled from the installed Google Play Games on PC emulator. |
| 2027-01-29 | Online services end: live events, leaderboards, cloud saves, accounts, social features. |

The APK in `Other/apk/` is therefore the only remaining copy of the last shipped client.

## What is in here

| Folder | Contents |
| --- | --- |
| `Other/apk/` | `base.apk` (v10.5.1, 118 MB) plus sha256 - the last shipped client |
| `Other/device/` | Device fingerprint: `getprop`, package dump, display, connectivity, storage, package list |
| `Other/logs/` | Logcat dumps, including the game's own startup/network logging |
| `Other/appdata/` | App data snapshot (needs a rooted device), external/OBB listings, `snapshot.json` |
| `Other/pcap/` | Optional wire-level pcap from on-device `tcpdump` |
| `Contents/<session>/` | Every HTTP exchange: raw `.req`/`.res` pairs, `manifest.jsonl`, HAR, WebSocket frames |
| `Contents/blobs/` | Response bodies above the inline threshold, content-addressed by sha256 |
| `API calls/` | Distinct endpoint signatures with counts, statuses and one sample pair each |
| `Catcher/` | The capture tool that produces the folders above |

## How the captures are made

`Catcher/` runs [mitmproxy](https://mitmproxy.org) as a recording proxy and files each exchange
straight into this repository:

```bat
Catcher\run.bat
```

Then the game is played on a device whose traffic is routed through the proxy. Full plaintext
requires a CA in the *system* trust store, because Android ignores user-installed CAs for apps
built against targetSdk 24+ (Minion Rush is targetSdk 33), so capture runs on a rootable Android
image (Android Studio AVD with `-writable-system`, or BlueStacks/LDPlayer with root) rather than
the read-only Play Games on PC emulator. See `Catcher/README.md` for the exact commands.

Every exchange is recorded as: method, URL, HTTP version, headers in wire order and case,
request/response bodies (raw bytes and decoded form), sha256, TLS details (SNI, ALPN, cipher,
peer certificate), timing, client and server addresses. Bodies up to 64 KiB are inline in the
`.req`/`.res` files; larger ones (asset bundles) are deduplicated in `Contents/blobs/`.

## Using this for a revival

- `API calls/endpoints.md` lists every distinct endpoint signature with method, host, path
  template, hit count and status codes; `API calls/samples/` has one request/response pair per
  endpoint with credential headers redacted.
- `Contents/<session>/manifest.jsonl` is the authoritative index: each line points at the raw
  `.req`/`.res` files, the body blob hash, the TLS certificate that served it and the timings.
- `Contents/<session>/har/` opens directly in Chrome DevTools or any HAR viewer.
- `Contents/INDEX.md` summarises sessions and blob counts; `Contents/blobs.sha256` lists every
  large body by hash and size so a missing blob can at least be identified.
- Asset and CDN URLs appear under "Assets and CDN downloads" in `endpoints.md`; those responses
  are the content bundles the client loads, and they only exist until the servers go dark.

## Publishing notes

The captures contain real account tokens, device identifiers and gameplay traffic. Review before
publishing. GitHub rejects files over 100 MB, so `Contents/blobs/` and `Other/apk/*.apk` are
git-ignored by default; track them with Git LFS (`git lfs track "Contents/blobs/**" "Other/apk/*.apk"`)
if you want them in the repository.

## Credits and legal

Captured by the community for preservation and interoperability. Minion Rush, Despicable Me and
related marks belong to Gameloft and Illumination; this archive is not affiliated with or
endorsed by either. Game data is archived so the game can keep being studied and played after
the official service ends.
