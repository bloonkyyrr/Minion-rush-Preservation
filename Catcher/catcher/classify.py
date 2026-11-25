"""Classification, endpoint templating and redaction helpers.

Nothing here changes the preserved data: redaction is only applied to the
human-facing copies in ``API calls/``. ``Contents/`` always keeps the exact bytes.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

API_HOST_HINTS = ("gameloft", "gloft", "glft", "minionrush")
ANALYTICS_HINTS = (
    "firebase",
    "crashlytics",
    "app-measurement",
    "google-analytics",
    "analytics.google",
    "doubleclick",
    "googletagmanager",
    "unity3d.com",
    "unityads",
    "appsflyer",
    "adjust.com",
    "app.adjust",
    "facebook.com",
    "fbcdn",
    "graph.facebook",
    "sentry",
    "appcenter.ms",
    "amplitude",
    "mixpanel",
    "braze",
    "onesignal",
    "kochava",
    "singular.net",
    "tenjin",
)
PLATFORM_HINTS = (
    "googleapis.com",
    "gstatic.com",
    "play.googleapis",
    "android.clients.google.com",
    "googleusercontent.com",
    "gvt1.com",
    "accounts.google.com",
    "play.google.com",
)
ASSET_HINTS = (
    "cdn",
    "cloudfront",
    "akamai",
    "edgekey",
    "amazonaws",
    "azureedge",
    "fastly",
    "gcdn",
    "asset",
    "bundle",
    "obb",
    "storage.googleapis",
)
BINARY_TYPES = (
    "application/octet-stream",
    "application/zip",
    "application/x-gzip",
    "image/",
    "audio/",
    "video/",
    "font/",
    "application/binary",
    "application/x-binary",
)

SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-auth-token",
    "x-access-token",
    "x-api-key",
    "x-session-id",
    "x-session-token",
    "x-csrf-token",
    "x-refresh-token",
}

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX = re.compile(r"^[0-9a-fA-F]{16,}$")
_NUM = re.compile(r"^\d+$")
_MIXED_ID = re.compile(r"^[A-Za-z0-9_.\-]{12,}$")
_EMAIL = re.compile(r"^[^/@\s]+@[^/@\s]+$")
_DATE = re.compile(r"^\d{4}[-_]\d{2}[-_]\d{2}")


def _matches(host: str, hints) -> bool:
    host = host.lower()
    return any(hint in host for hint in hints)


def is_binary_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    lowered = content_type.lower()
    return any(lowered.startswith(kind) for kind in BINARY_TYPES)


def classify(
    host: str,
    path: str,
    method: str,
    request_ct: str | None = None,
    response_ct: str | None = None,
) -> dict:
    """Roughly label an exchange so the archive is easy to browse."""
    host = host or ""
    if _matches(host, ANALYTICS_HINTS):
        kind, group = "analytics", "analytics"
    elif _matches(host, PLATFORM_HINTS):
        kind, group = "platform", "google-platform"
    else:
        host_group = "gameloft" if _matches(host, API_HOST_HINTS) else "third-party"
        looks_like_api = (
            method.upper() != "GET"
            or "json" in (request_ct or "").lower()
            or "json" in (response_ct or "").lower()
            or any(part in path.lower() for part in ("/api", "/v1", "/v2", "/v3", "/graph", "/service"))
        )
        if _matches(host, API_HOST_HINTS) and looks_like_api:
            kind = "api"
        elif _matches(host, ASSET_HINTS) or (method.upper() == "GET" and is_binary_type(response_ct)):
            kind = "asset"
        elif _matches(host, API_HOST_HINTS):
            kind = "api"
        elif is_binary_type(response_ct):
            kind = "asset"
        else:
            kind = "other"
        return {
            "kind": kind,
            "host_group": host_group,
            "template": template_path(path),
            "endpoint": endpoint_key(method, host, path),
        }

    return {
        "kind": kind,
        "host_group": group,
        "template": template_path(path),
        "endpoint": endpoint_key(method, host, path),
    }


def _template_segment(segment: str) -> str:
    if not segment:
        return segment
    if _NUM.fullmatch(segment):
        return "{id}"
    if _UUID.fullmatch(segment):
        return "{uuid}"
    if _HEX.fullmatch(segment):
        return "{hash}"
    if _EMAIL.fullmatch(segment):
        return "{email}"
    if _DATE.match(segment) and len(segment) <= 24:
        return "{date}"
    if (
        _MIXED_ID.fullmatch(segment)
        and re.search(r"\d", segment)
        and re.search(r"[A-Za-z]", segment)
        and not segment.lower().endswith((".json", ".xml", ".png", ".jpg", ".txt", ".proto"))
    ):
        return "{id}"
    return segment


def template_path(path: str) -> str:
    """``/v1/player/83721/state?ts=1`` -> ``/v1/player/{id}/state?ts={v}``."""
    parts = urlsplit(path or "/")
    segments = [_template_segment(segment) for segment in parts.path.split("/")]
    templated = "/".join(segments) or "/"
    if parts.query:
        keys: list[str] = []
        for pair in parts.query.split("&"):
            key = pair.split("=", 1)[0]
            if key and key not in keys:
                keys.append(key)
        templated += "?" + "&".join(f"{key}={{v}}" for key in keys)
    return templated


def endpoint_key(method: str, host: str, path: str) -> str:
    return f"{(method or 'GET').upper()} {host}{template_path(path)}"


def redact_headers(headers) -> list[list[str]]:
    out = []
    for name, value in headers:
        if str(name).lower() in SENSITIVE_HEADERS:
            out.append([name, f"<redacted: {len(str(value))} chars>"])
        else:
            out.append([name, value])
    return out


def redact_message(data: bytes) -> bytes:
    """Redact credential headers in a raw HTTP message, leaving the body untouched."""
    head, sep, body = data.partition(b"\r\n\r\n")
    if not sep:
        return data
    lines = head.decode("latin-1", "replace").split("\r\n")
    if not lines:
        return data
    rebuilt = [lines[0]]
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() in SENSITIVE_HEADERS:
            rebuilt.append(f"{name}: <redacted: {len(value.strip())} chars>")
        else:
            rebuilt.append(line)
    return ("\r\n".join(rebuilt).encode("latin-1", "replace")) + sep + body
