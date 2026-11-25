"""mitmproxy addon: records every exchange that passes through the Catcher proxy.

Launched by ``catcher run`` as::

    mitmdump -s catcher/addon.py --listen-host 127.0.0.1 --listen-port 8080

All options arrive through ``CATCHER_*`` environment variables (see config.py),
so the same file works under a pip-installed mitmdump or the standalone build.
"""

from __future__ import annotations

import base64
import sys
import time
import traceback
from pathlib import Path

_ADDON_DIR = Path(__file__).resolve().parent
for _entry in (str(_ADDON_DIR.parent), str(_ADDON_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from mitmproxy import ctx  # noqa: E402

from catcher import classify  # noqa: E402
from catcher.config import load_settings  # noqa: E402
from catcher.store import Session, slugify  # noqa: E402


def _headers(fields) -> list[list[str]]:
    out: list[list[str]] = []
    for name, value in fields:
        try:
            out.append([name.decode("latin-1"), value.decode("latin-1")])
        except Exception:
            out.append([str(name), str(value)])
    return out


def _cert_summary(cert) -> dict:
    """Normalise mitmproxy's certificate object into plain JSON fields."""
    info: dict = {}
    parsed = None
    try:  # mitmproxy's Cert carries PEM; cryptography gives the full picture
        from cryptography import x509

        if hasattr(cert, "to_pem"):
            parsed = x509.load_pem_x509_certificate(cert.to_pem())
        elif hasattr(cert, "public_bytes"):
            parsed = cert
    except Exception:
        parsed = None

    if parsed is not None:
        from cryptography.hazmat.primitives import hashes

        try:
            info["subject"] = parsed.subject.rfc4514_string()
        except Exception:
            info["subject"] = str(parsed.subject)
        try:
            info["issuer"] = parsed.issuer.rfc4514_string()
        except Exception:
            info["issuer"] = str(parsed.issuer)
        for key, attr in (("not_before", "not_valid_before_utc"), ("not_after", "not_valid_after_utc")):
            try:
                info[key] = getattr(parsed, attr).isoformat()
            except Exception:
                pass
        try:
            info["serial"] = hex(parsed.serial_number)
        except Exception:
            pass
        try:
            info["sha256"] = parsed.fingerprint(hashes.SHA256()).hex()
        except Exception:
            pass
        try:
            from cryptography import x509 as _x509

            san = parsed.extensions.get_extension_for_class(_x509.SubjectAlternativeName).value
            info["san_dns"] = san.get_values_for_type(_x509.DNSName)
        except Exception:
            pass
        return info

    subject = getattr(cert, "subject", None)
    if isinstance(subject, (list, tuple)):
        info["subject"] = ", ".join(f"{name}={value}" for name, value in subject)
    else:
        info["subject"] = str(subject)
    altnames = getattr(cert, "altnames", None)
    if isinstance(altnames, (list, tuple)):
        info["san_dns"] = [value for kind, value in altnames if str(kind).upper() == "DNS"]
    return info


def _text(value):
    """mitmproxy exposes some TLS fields as bytes; the manifest is JSON."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("latin-1", "replace")
    return str(value)


def _tls_summary(conn) -> dict | None:
    if conn is None:
        return None
    try:
        if not getattr(conn, "tls_established", False):
            return None
    except Exception:
        return None
    info: dict = {
        "sni": _text(getattr(conn, "sni", None)),
        "alpn": _text(getattr(conn, "alpn", None)),
        "version": _text(getattr(conn, "tls_version", None)),
    }
    cipher = getattr(conn, "cipher", None)
    if isinstance(cipher, (tuple, list)) and cipher:
        info["cipher"] = _text(cipher[0])
    elif cipher is not None:
        info["cipher"] = _text(cipher)
    try:
        certs = getattr(conn, "certificate_list", None) or []
        info["peer_cert_count"] = len(certs)
        if certs:
            info["peer_cert"] = _cert_summary(certs[0])
    except Exception:
        pass
    return info


def _raw_head(start_line: str, headers: list[list[str]]) -> bytes:
    lines = [start_line] + [f"{name}: {value}" for name, value in headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", "replace")


def _preview(body: bytes | None) -> str | None:
    if not body:
        return None
    if len(body) > 4096:
        body = body[:4096]
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


class Catcher:
    def __init__(self) -> None:
        self.session: Session | None = None
        self._ws: dict[str, dict] = {}

    # -- lifecycle --------------------------------------------------------
    def load(self, loader) -> None:
        settings = load_settings()
        self.session = Session(settings)
        self.session.log("addon loaded")
        ctx.log.info(f"[catcher] session: {self.session.dir}")
        print(f"[catcher] writing to {self.session.dir}", flush=True)

    def running(self) -> None:
        if self.session:
            self.session.log(f"proxy running on {self.session.settings.listen_host}:{self.session.settings.listen_port}")

    def done(self) -> None:
        if self.session:
            self.session.close()

    # -- http -------------------------------------------------------------
    def response(self, flow) -> None:
        try:
            self._record(flow, error=None)
        except Exception:
            if self.session:
                self.session.log("ERROR recording response: " + traceback.format_exc())

    def error(self, flow) -> None:
        try:
            err = getattr(flow, "error", None)
            info = {
                "type": type(err).__name__ if err is not None else "error",
                "message": getattr(err, "msg", str(err)),
            }
            self._record(flow, error=info)
        except Exception:
            if self.session:
                self.session.log("ERROR recording error: " + traceback.format_exc())

    def _record(self, flow, error: dict | None) -> None:
        if self.session is None:
            return
        request = flow.request
        response = flow.response
        seq = self.session.next_seq()

        host = request.pretty_host or request.host
        started = float(getattr(request, "timestamp_start", None) or time.time())
        ended = float(getattr(response, "timestamp_end", None) or time.time()) if response is not None else time.time()

        request_headers = _headers(request.headers.fields)
        request_raw = request.raw_content or b""
        request_decoded = request.content or b""
        request_ct = request.headers.get("content-type")

        response_headers = _headers(response.headers.fields) if response is not None else []
        response_raw = (response.raw_content or b"") if response is not None else b""
        response_decoded = (response.content or b"") if response is not None else b""
        response_ct = response.headers.get("content-type") if response is not None else None

        request_body = self.session.save_body(request_raw)
        request_body["content_type"] = request_ct
        request_body["preview"] = _preview(request_decoded)
        if request_decoded and request_decoded != request_raw:
            request_body["decoded"] = self.session.save_body(request_decoded)

        response_body = self.session.save_body(response_raw)
        response_body["content_type"] = response_ct
        response_body["preview"] = _preview(response_decoded)
        if response_decoded and response_decoded != response_raw:
            response_body["decoded"] = self.session.save_body(response_decoded)

        base = f"{seq:05d}-{slugify(host + request.path, 80)}"
        request_path = self.session.http_dir / f"{base}.req"
        response_path = self.session.http_dir / f"{base}.res"

        request_blob = request_raw if request_body["stored"] == "inline" else b""
        self.session.atomic_write(
            request_path,
            _raw_head(f"{request.method} {request.path} {request.http_version}", request_headers) + request_blob,
        )
        if response is not None:
            response_blob = response_raw if response_body["stored"] == "inline" else b""
            self.session.atomic_write(
                response_path,
                _raw_head(
                    f"{response.http_version} {response.status_code} {response.reason or ''}".rstrip(),
                    response_headers,
                )
                + response_blob,
            )

        classification = classify.classify(
            host=host,
            path=request.path,
            method=request.method,
            request_ct=request_ct,
            response_ct=response_ct,
        )

        record = {
            "schema": 1,
            "type": "http",
            "seq": seq,
            "session": self.session.name,
            "time_start": started,
            "time_end": ended,
            "duration_ms": round(max(0.0, ended - started) * 1000, 3),
            "flow_id": getattr(flow, "id", None),
            "client": {
                "address": _addr(getattr(flow, "client_conn", None)),
                "id": str(getattr(getattr(flow, "client_conn", None), "id", "")),
            },
            "server": {
                "address": _addr(getattr(flow, "server_conn", None)),
                "id": str(getattr(getattr(flow, "server_conn", None), "id", "")),
                "tls": _tls_summary(getattr(flow, "server_conn", None)),
            },
            "request": {
                "method": request.method,
                "scheme": request.scheme,
                "host": host,
                "port": request.port,
                "path": request.path,
                "url": request.url,
                "http_version": request.http_version,
                "headers": request_headers,
                "body": request_body,
                "file": self.session.rel(request_path),
            },
            "response": {
                "status": response.status_code,
                "reason": response.reason,
                "http_version": response.http_version,
                "headers": response_headers,
                "body": response_body,
                "file": self.session.rel(response_path),
            }
            if response is not None
            else None,
            "error": error,
            "classification": classification,
            "endpoint": {
                "key": classification["endpoint"],
                "template": classification["template"],
                "kind": classification["kind"],
            },
        }
        self.session.append(record)

    # -- websockets -------------------------------------------------------
    def websocket_start(self, flow) -> None:
        if self.session is None:
            return
        host = flow.request.pretty_host or flow.request.host
        seq = self.session.next_seq()
        path = self.session.ws_dir / f"{seq:05d}-{slugify(host + flow.request.path, 70)}.jsonl"
        self._ws[str(flow.id)] = {"path": path, "seq": seq, "count": 0, "host": host}
        self.session.append(
            {
                "schema": 1,
                "type": "websocket_start",
                "seq": seq,
                "session": self.session.name,
                "time_start": float(getattr(flow.request, "timestamp_start", None) or time.time()),
                "url": flow.request.url,
                "host": host,
                "endpoint": classify.endpoint_key("WS", host, flow.request.path),
                "file": self.session.rel(path),
            }
        )

    def websocket_message(self, flow) -> None:
        if self.session is None:
            return
        entry = self._ws.get(str(flow.id))
        if entry is None:
            return
        message = flow.websocket.messages[-1]
        content = message.content or b""
        entry["count"] += 1
        body = self.session.save_body(content)
        body["content_type"] = getattr(message, "type", None)
        record = {
            "seq": entry["seq"],
            "n": entry["count"],
            "time": float(getattr(message, "timestamp", time.time())),
            "from_client": bool(message.from_client),
            "type": getattr(message, "type", None),
            "size": len(content),
            "sha256": body["sha256"],
            "blob": body["blob"],
            "text": content.decode("utf-8", "replace") if len(content) <= 16384 else None,
            "base64": base64.b64encode(content).decode("ascii") if len(content) <= 16384 else None,
        }
        with entry["path"].open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(_json(record) + "\n")

    def websocket_end(self, flow) -> None:
        if self.session is None:
            return
        entry = self._ws.pop(str(flow.id), None)
        if entry is None:
            return
        self.session.append(
            {
                "schema": 1,
                "type": "websocket_end",
                "seq": entry["seq"],
                "session": self.session.name,
                "time_end": time.time(),
                "host": entry["host"],
                "frames": entry["count"],
                "file": self.session.rel(entry["path"]),
            }
        )


def _addr(conn) -> str | None:
    address = getattr(conn, "address", None) if conn is not None else None
    if not address:
        return None
    try:
        return f"{address[0]}:{address[1]}"
    except Exception:
        return str(address)


def _json(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


addons = [Catcher()]
