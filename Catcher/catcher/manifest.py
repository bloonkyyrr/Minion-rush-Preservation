"""Manifest reading and export: HAR 1.2, ``API calls/`` index, archive index, gitignore."""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import classify
from .config import Settings
from .store import slugify

KINDS = ("api", "asset", "analytics", "platform", "other")
GITHUB_LIMIT = 100 * 1024 * 1024


def read_manifest(session_dir: Path) -> list[dict]:
    path = session_dir / "manifest.jsonl"
    records: list[dict] = []
    if not path.is_file():
        return records
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def session_dirs(settings: Settings) -> list[Path]:
    if not settings.contents_dir.is_dir():
        return []
    return sorted(
        (path for path in settings.contents_dir.iterdir() if path.is_dir() and (path / "manifest.jsonl").is_file()),
        key=lambda path: path.name,
    )


def _iso(timestamp: float | None) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _har_headers(headers) -> list[dict]:
    return [{"name": str(name), "value": str(value)} for name, value in headers]


def _query_pairs(path: str) -> list[dict]:
    if "?" not in (path or ""):
        return []
    pairs = []
    for chunk in path.split("?", 1)[1].split("&"):
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        pairs.append({"name": key, "value": value})
    return pairs


def _body_har(body: dict | None, inline_preview: str | None) -> tuple[dict, int, int]:
    if not body:
        return {"size": 0, "mimeType": ""}, 0, 0
    content = {
        "size": body.get("size", 0),
        "mimeType": body.get("content_type") or "",
        "_stored": body.get("stored"),
        "_blob": body.get("blob"),
        "_sha256": body.get("sha256"),
    }
    if inline_preview is not None and body.get("stored") == "inline":
        content["text"] = inline_preview
    return content, body.get("size", 0), 0


def build_har(records: list[dict], session_name: str) -> dict:
    entries = []
    for record in records:
        if record.get("type") != "http" or not record.get("response"):
            continue
        request = record["request"]
        response = record["response"]
        request_content, request_size, _ = _body_har(request.get("body"), (request.get("body") or {}).get("preview"))
        response_content, response_size, _ = _body_har(response.get("body"), (response.get("body") or {}).get("preview"))
        entry = {
            "startedDateTime": _iso(record.get("time_start")),
            "time": record.get("duration_ms", 0),
            "request": {
                "method": request.get("method"),
                "url": request.get("url"),
                "httpVersion": request.get("http_version"),
                "headers": _har_headers(request.get("headers") or []),
                "queryString": _query_pairs(request.get("path") or ""),
                "cookies": [],
                "headersSize": -1,
                "bodySize": request_size,
                "postData": {"mimeType": request_content.get("mimeType", ""), "text": request_content.get("text", ""), "size": request_size},
            },
            "response": {
                "status": response.get("status"),
                "statusText": response.get("reason") or "",
                "httpVersion": response.get("http_version"),
                "headers": _har_headers(response.get("headers") or []),
                "cookies": [],
                "content": response_content,
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": response_size,
            },
            "cache": {},
            "timings": {"send": 0, "wait": record.get("duration_ms", 0), "receive": 0},
            "serverIPAddress": (record.get("server") or {}).get("address") or "",
            "connection": str((record.get("server") or {}).get("id") or ""),
            "_catcher": {
                "session": session_name,
                "seq": record.get("seq"),
                "kind": (record.get("classification") or {}).get("kind"),
                "endpoint": (record.get("endpoint") or {}).get("key"),
                "tls": (record.get("server") or {}).get("tls"),
                "request_file": request.get("file"),
                "response_file": response.get("file"),
                "error": record.get("error"),
            },
        }
        entries.append(entry)
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "Minion Rush Catcher", "version": "1.0"},
            "comment": f"Session {session_name} - headers/bodies as seen by the Catcher proxy. Full bytes live under Contents/.",
            "entries": entries,
        }
    }


def _aggregate(all_records: dict[str, list[dict]]) -> list[dict]:
    endpoints: dict[str, dict] = {}
    for session_name, records in all_records.items():
        for record in records:
            if record.get("type") != "http":
                continue
            request = record.get("request") or {}
            response = record.get("response") or {}
            key = (record.get("endpoint") or {}).get("key") or classify.endpoint_key(
                request.get("method", "GET"), request.get("host", ""), request.get("path", "/")
            )
            entry = endpoints.setdefault(
                key,
                {
                    "key": key,
                    "method": request.get("method"),
                    "host": request.get("host"),
                    "template": (record.get("endpoint") or {}).get("template"),
                    "kind": (record.get("classification") or {}).get("kind", "other"),
                    "host_group": (record.get("classification") or {}).get("host_group"),
                    "count": 0,
                    "sessions": [],
                    "first_seen": None,
                    "last_seen": None,
                    "statuses": Counter(),
                    "content_types": Counter(),
                    "bytes_down": 0,
                    "bytes_up": 0,
                    "sample": None,
                },
            )
            entry["count"] += 1
            if session_name not in entry["sessions"]:
                entry["sessions"].append(session_name)
            started = record.get("time_start") or 0
            if started and (not entry["first_seen"] or started < entry["first_seen"]):
                entry["first_seen"] = started
                entry["sample"] = {
                    "session": session_name,
                    "seq": record.get("seq"),
                    "request_file": request.get("file"),
                    "response_file": response.get("file"),
                    "url": request.get("url"),
                }
            if started and (not entry["last_seen"] or started > entry["last_seen"]):
                entry["last_seen"] = started
            if response.get("status") is not None:
                entry["statuses"][str(response["status"])] += 1
            content_type = ((response.get("body") or {}).get("content_type") or "").split(";")[0].strip()
            if content_type:
                entry["content_types"][content_type] += 1
            entry["bytes_down"] += int(((response.get("body") or {}).get("size") or 0))
            entry["bytes_up"] += int(((request.get("body") or {}).get("size") or 0))
    ordered = []
    for entry in endpoints.values():
        entry["statuses"] = dict(entry["statuses"])
        entry["content_types"] = dict(entry["content_types"].most_common(5))
        entry["first_seen"] = _iso(entry["first_seen"])
        entry["last_seen"] = _iso(entry["last_seen"])
        ordered.append(entry)
    ordered.sort(key=lambda item: (KINDS.index(item["kind"]) if item["kind"] in KINDS else len(KINDS), -item["count"], item["key"]))
    return ordered


def _human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _samples(settings: Settings, endpoints: list[dict]) -> None:
    sample_dir = settings.api_dir / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    for index, entry in enumerate(endpoints, start=1):
        sample = entry.get("sample")
        if not sample:
            continue
        for kind, source_key in (("req", "request_file"), ("res", "response_file")):
            relative = sample.get(source_key)
            if not relative:
                continue
            source = settings.out_root / relative
            if not source.is_file():
                continue
            name = f"{index:03d}-{slugify(entry['key'], 70)}.{kind}.txt"
            data = classify.redact_message(source.read_bytes())
            (sample_dir / name).write_bytes(data)
            sample[f"{kind}_sample"] = str((sample_dir / name).relative_to(settings.out_root))
        entry["sample"] = sample


def _markdown(endpoints: list[dict], all_records: dict[str, list[dict]], generated: str) -> str:
    total = sum(len(records) for records in all_records.values())
    lines = [
        "# Minion Rush API calls",
        "",
        f"Generated {generated} from {len(all_records)} session(s), {total} recorded exchanges.",
        "",
        "Every row is a distinct endpoint signature (numeric ids, UUIDs and long hashes are templated).",
        "Credential headers are redacted **only here** - `Contents/` keeps the exact bytes.",
        "",
    ]
    titles = {
        "api": "Game API",
        "asset": "Assets and CDN downloads",
        "analytics": "Analytics / telemetry",
        "platform": "Google platform services",
        "other": "Other",
    }
    for kind in KINDS:
        rows = [entry for entry in endpoints if entry["kind"] == kind]
        if not rows:
            continue
        lines += [f"## {titles[kind]}", "", "| Method | Host | Path template | Calls | Statuses | Sample |", "| --- | --- | --- | --- | --- | --- |"]
        for entry in rows:
            statuses = ", ".join(f"{code} x{count}" for code, count in sorted(entry["statuses"].items()))
            sample = entry.get("sample") or {}
            sample_link = Path(sample["res_sample"]).name if sample.get("res_sample") else "-"
            lines.append(
                f"| {entry['method']} | {entry['host']} | `{entry['template']}` | {entry['count']} | {statuses or '-'} | {sample_link} |"
            )
        lines.append("")
    hosts = defaultdict(int)
    for records in all_records.values():
        for record in records:
            if record.get("type") == "http":
                hosts[(record.get("request") or {}).get("host", "")] += 1
    lines += ["## Hosts seen", "", "| Host | Exchanges |", "| --- | --- |"]
    for host, count in sorted(hosts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {host or '-'} | {count} |")
    lines.append("")
    return "\n".join(lines)


def _write_gitignore(settings: Settings) -> None:
    path = settings.out_root / ".gitignore"
    marker = "# --- managed by catcher export ---"
    managed = "\n".join(
        [
            marker,
            "# Capture blobs are kept locally; GitHub rejects files over 100 MB.",
            "# To publish them use Git LFS:  git lfs track \"Contents/blobs/**\" \"Other/apk/*.apk\"",
            "Contents/blobs/",
            "Other/apk/*.apk",
            "*.tmp",
            "",
        ]
    )
    existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if marker in existing:
        head = existing.split(marker)[0].rstrip("\n")
        path.write_text((head + "\n\n" if head else "") + managed, encoding="utf-8")
    else:
        body = existing.rstrip("\n")
        path.write_text((body + "\n\n" if body else "") + managed, encoding="utf-8")


def _write_blob_index(settings: Settings) -> dict:
    blobs = []
    total = 0
    for path in sorted(settings.blobs_dir.rglob("*")):
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        blobs.append({"sha256": path.name, "bytes": size, "file": str(path.relative_to(settings.out_root).as_posix())})
    index = settings.contents_dir / "blobs.sha256"
    index.write_text("\n".join(f"{entry['sha256']}  {entry['bytes']}  {entry['file']}" for entry in blobs) + ("\n" if blobs else ""), encoding="utf-8")
    large = [entry for entry in blobs if entry["bytes"] > GITHUB_LIMIT]
    if large:
        (settings.contents_dir / "blobs-over-100mb.txt").write_text(
            "\n".join(f"{entry['sha256']}  {entry['bytes']}  {entry['file']}" for entry in large) + "\n",
            encoding="utf-8",
        )
    return {"count": len(blobs), "bytes": total, "over_github_limit": len(large)}


def write_exports(settings: Settings) -> dict:
    settings.ensure_dirs()
    sessions = session_dirs(settings)
    all_records = {path.name: read_manifest(path) for path in sessions}

    for name, records in all_records.items():
        har = build_har(records, name)
        har_path = settings.contents_dir / name / "har" / f"{name}.har"
        har_path.parent.mkdir(parents=True, exist_ok=True)
        har_path.write_text(json.dumps(har, indent=1, ensure_ascii=False), encoding="utf-8")

    endpoints = _aggregate(all_records)
    _samples(settings, endpoints)
    generated = time.strftime("%Y-%m-%d %H:%M:%S")

    (settings.api_dir / "endpoints.json").write_text(
        json.dumps({"generated": generated, "sessions": sorted(all_records), "endpoints": endpoints}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (settings.api_dir / "endpoints.md").write_text(_markdown(endpoints, all_records, generated), encoding="utf-8")

    blob_stats = _write_blob_index(settings)
    _write_gitignore(settings)

    index_lines = ["# Contents index", "", f"Generated {generated}.", "", "| Session | Exchanges | WebSocket events | Manifest | HAR |", "| --- | --- | --- | --- | --- |"]
    for name, records in all_records.items():
        http_count = sum(1 for record in records if record.get("type") == "http")
        ws_count = sum(1 for record in records if str(record.get("type", "")).startswith("websocket"))
        index_lines.append(
            f"| {name} | {http_count} | {ws_count} | `Contents/{name}/manifest.jsonl` | `Contents/{name}/har/{name}.har` |"
        )
    index_lines += [
        "",
        f"Blobs: {blob_stats['count']} files, {_human_bytes(blob_stats['bytes'])} "
        f"({blob_stats['over_github_limit']} over GitHub's 100 MB per-file limit).",
        "`Contents/blobs.sha256` lists every blob with its hash and size.",
        "",
        "## Reading an exchange",
        "",
        "`manifest.jsonl` has one JSON object per exchange; `http/NNNNN-*.req`/`.res` hold the message.",
        "Bodies smaller than `max_inline_body` are inside those files; larger ones are content-addressed",
        "in `Contents/blobs/<xx>/<sha256>` and referenced by the manifest (`body.blob`).",
        "",
        "## WebSockets",
        "",
        "Frames are in `ws/*.jsonl` (one file per connection), referenced by `websocket_start`/`websocket_end`",
        "manifest records.",
        "",
    ]
    (settings.contents_dir / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")

    return {
        "sessions": len(all_records),
        "exchanges": sum(len(records) for records in all_records.values()),
        "endpoints": len(endpoints),
        "blobs": blob_stats,
        "har_dir": str(settings.contents_dir),
        "api_md": str(settings.api_dir / "endpoints.md"),
    }


def summary(settings: Settings) -> dict:
    sessions = {}
    for path in session_dirs(settings):
        records = read_manifest(path)
        http = [record for record in records if record.get("type") == "http"]
        hosts = Counter((record.get("request") or {}).get("host", "") for record in http)
        kinds = Counter((record.get("classification") or {}).get("kind", "other") for record in http)
        sessions[path.name] = {
            "exchanges": len(http),
            "hosts": dict(hosts.most_common(10)),
            "kinds": dict(kinds),
            "bytes_down": sum(int(((record.get("response") or {}).get("body") or {}).get("size") or 0) for record in http),
        }
    return sessions
