# Contents index

Generated 2026-11-25 21:04:16.

| Session | Exchanges | WebSocket events | Manifest | HAR |
| --- | --- | --- | --- | --- |
| 20261125-183957 | 676 | 0 | `Contents/20261125-183957/manifest.jsonl` | `Contents/20261125-183957/har/20261125-183957.har` |
| 20261125-201534 | 93 | 0 | `Contents/20261125-201534/manifest.jsonl` | `Contents/20261125-201534/har/20261125-201534.har` |

Blobs: 91 files, 112.9 MB (0 over GitHub's 100 MB per-file limit).
`Contents/blobs.sha256` lists every blob with its hash and size.

## Reading an exchange

`manifest.jsonl` has one JSON object per exchange; `http/NNNNN-*.req`/`.res` hold the message.
Bodies smaller than `max_inline_body` are inside those files; larger ones are content-addressed
in `Contents/blobs/<xx>/<sha256>` and referenced by the manifest (`body.blob`).

## WebSockets

Frames are in `ws/*.jsonl` (one file per connection), referenced by `websocket_start`/`websocket_end`
manifest records.
