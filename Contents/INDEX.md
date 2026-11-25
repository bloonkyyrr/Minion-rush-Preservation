# Contents index

Generated 2026-11-25 17:31:36.

| Session | Exchanges | WebSocket events | Manifest | HAR |
| --- | --- | --- | --- | --- |

Blobs: 0 files, 0 B (0 over GitHub's 100 MB per-file limit).
`Contents/blobs.sha256` lists every blob with its hash and size.

## Reading an exchange

`manifest.jsonl` has one JSON object per exchange; `http/NNNNN-*.req`/`.res` hold the message.
Bodies smaller than `max_inline_body` are inside those files; larger ones are content-addressed
in `Contents/blobs/<xx>/<sha256>` and referenced by the manifest (`body.blob`).

## WebSockets

Frames are in `ws/*.jsonl` (one file per connection), referenced by `websocket_start`/`websocket_end`
manifest records.
