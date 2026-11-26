# Minion Rush Preservation.UNFINISHED, any file that ia commited that has any kind of minion rush data, will always be useful

An archive of everything **Despicable Me: Minion Rush** (`com.gameloft.android.AMAZ.GloftDMAS`)
sends and receives over the network, captured from a running install before Gameloft's online
services close on **29 January 2027**. The goal is to give anyone building a revival server
after the sunset real request/response shapes instead of guesses.


## Timeline

| Date | Event |
| --- | --- |
| 2026-10-30 | Delisted from app stores, in-app purchases disabled. The APK can no longer be downloaded. |
| 2026-11-25 | This archive started; the Unity client 13.4.0 (base + asset/lib/density splits) and the pre-2025 build 10.5.1 were pulled from the Google Play Games on PC emulator. |
| 2027-01-29 | Online services end: live events, leaderboards, cloud saves, accounts, social features. |

The APK in `Other/apk/` is therefore the only remaining copy of the last shipped client.

## What is in here

| Folder | Contents |
| --- | --- |
| `Other/apk/` | The Unity client 13.4.0 (`base.apk` + `split_UnityDataAssetPack` + `split_config.arm64_v8a` + `split_config.mdpi`, 610 MB) and the legacy 10.5.1 APK, with sha256 |
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

Then the game is played on a device whose traffic is routed through the proxy. Full plaintext requires the proxy's CA to be trusted by the client. The Play Games on PC
emulator is a read-only `user` build with no `adb root`, so the CA cannot be added to the
system store there - but the client's own `network_security_config.xml` already trusts bundled
raw roots, so the archive was captured by repacking the shipped APK (`Other/apk/`) with the
proxy CA appended as `res/raw/mitm_ca.pem` and a matching `<certificates src="@raw/mitm_ca"/>`
entry, re-signing all splits with one key, and installing them with `pm install-multiple`.
Traffic is then routed through mitmproxy with `adb reverse tcp:8080 tcp:8080` plus
`settings put global http_proxy 127.0.0.1:8080`. The game's Gameloft endpoints
(`fed.gold0029.gameloft.com`, `iris16-gold.gameloft.com`) and several Unity endpoints are
decrypted; a few Unity endpoints still pin and are recorded as TLS failures. See
`Catcher/README.md` for the exact commands. A rooted image is still an option if you want
system-store trust without repacking.

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
