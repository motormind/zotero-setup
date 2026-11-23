"""Minimal Zotero Web API v3 client (stdlib only).

Handles: auth header, pagination via Link header, Backoff / Retry-After,
write tokens, batched writes and the 4-step file upload flow.
Docs: https://www.zotero.org/support/dev/web_api/v3/basics
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WEB_BASE = "https://api.zotero.org"
LOCAL_BASE = "http://localhost:23119/api"
USER_AGENT = "zotero-setup/0.1 (+https://www.zotero.org/support/dev/web_api/v3/start)"
WRITE_BATCH = 50


class ZoteroError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


HINTS = {
    403: "Key missing/invalid or lacks access to this library. Check with `zt whoami`.",
    404: "Library/collection/item not found. Check library_type (user vs group) and IDs.",
    412: "Library changed in the meantime (version conflict). Re-run the command.",
}


def _origin(url: str) -> tuple[str, str]:
    u = urllib.parse.urlsplit(url)
    return u.scheme.lower(), u.netloc.lower()


class _StripKeyOnRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the API key to another origin when following a redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _origin(newurl) != _origin(req.full_url):
            for store in (new.headers, new.unredirected_hdrs):
                for k in [k for k in store if k.lower() in {"zotero-api-key", "authorization"}]:
                    del store[k]
        return new


_opener = urllib.request.build_opener(_StripKeyOnRedirect)


class Zotero:
    def __init__(self, prefix: str, api_key: str = "", local: bool = False, base: str | None = None):
        self.base = base or (LOCAL_BASE if local else WEB_BASE)
        scheme, netloc = _origin(self.base)
        host = netloc.rsplit(":", 1)[0]
        if api_key and scheme != "https" and host not in {"localhost", "127.0.0.1", "[::1]"}:
            raise ZoteroError(0, f"refusing to send the API key over unencrypted {scheme}:// to {host}")
        self.prefix = prefix
        self._key = api_key
        self.local = local
        self._templates: dict[str, dict] = {}
        self.last_version: int | None = None

    # ------------------------------------------------------------------ http
    def _url(self, path: str, params: dict | None = None) -> str:
        if path.startswith("http"):
            url = path
        else:
            if not path.startswith("/"):
                path = f"{self.prefix}/{path}"
            url = self.base + path
        if params:
            sep = "&" if "?" in url else "?"
            url += sep + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return url

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: bytes | None = None,
        headers: dict | None = None,
        auth: bool = True,
        retries: int = 5,
    ) -> tuple[int, dict, bytes]:
        url = self._url(path, params)
        h = {"Zotero-API-Version": "3", "User-Agent": USER_AGENT}
        # the key is only ever sent to the API origin itself (exact scheme+host match)
        if auth and self._key and _origin(url) == _origin(self.base):
            h["Zotero-API-Key"] = self._key
        h.update(headers or {})

        delay = 2.0
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=body, method=method, headers=h)
            try:
                with _opener.open(req, timeout=60) as resp:
                    status, rh, data = resp.status, dict(resp.headers), resp.read()
            except urllib.error.HTTPError as e:
                status, rh, data = e.code, dict(e.headers or {}), e.read()
            except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError) as e:
                if self.local:
                    raise ZoteroError(0, "Zotero desktop not reachable on localhost:23119 "
                                         "(running? local API enabled in Settings > Advanced?)") from e
                if attempt < retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ZoteroError(0, str(getattr(e, "reason", e))) from e

            rh = {k.lower(): v for k, v in rh.items()}
            if "last-modified-version" in rh:
                self.last_version = int(rh["last-modified-version"])
            if status in (429, 503) and attempt < retries:
                wait = float(rh.get("retry-after") or delay)
                print(f"  rate limited ({status}), waiting {wait:.0f}s ...", file=sys.stderr)
                time.sleep(wait)
                delay *= 2
                continue
            if status >= 400:
                msg = data.decode("utf-8", "replace").strip()[:500]
                hint = HINTS.get(status)
                raise ZoteroError(status, f"{msg}" + (f"\n  hint: {hint}" if hint else ""))
            if "backoff" in rh:
                time.sleep(float(rh["backoff"]))
            return status, rh, data
        raise ZoteroError(429, "giving up after repeated rate limiting")

    def get_json(self, path: str, params: dict | None = None):
        _, _, data = self.request("GET", path, params)
        return json.loads(data or b"null")

    def paginate(self, path: str, params: dict | None = None):
        """Yield raw page bodies, following the Link: rel="next" header."""
        params = dict(params or {})
        params.setdefault("limit", 100)
        url = self._url(path, params)
        while url:
            _, rh, data = self.request("GET", url)
            yield data
            m = re.search(r'<([^>]+)>;\s*rel="next"', rh.get("link", ""))
            url = m.group(1) if m else None

    def iter_json(self, path: str, params: dict | None = None):
        for page in self.paginate(path, params):
            yield from json.loads(page)

    # ------------------------------------------------------------- reading
    def key_info(self) -> dict:
        return self.get_json(f"/keys/{self._key}", None) if self._key else {}

    def collections(self) -> list[dict]:
        return list(self.iter_json("collections"))

    def export(self, fmt: str, collection: str = "", params: dict | None = None) -> str:
        path = f"collections/{collection}/items/top" if collection else "items/top"
        p = {"format": fmt, "sort": "dateAdded", "direction": "asc", "limit": 100}
        p.update(params or {})
        chunks = [page.decode("utf-8").strip() for page in self.paginate(path, p)]
        return "\n\n".join(c for c in chunks if c) + "\n"

    def template(self, item_type: str, link_mode: str | None = None) -> dict:
        k = f"{item_type}/{link_mode}"
        if k not in self._templates:
            params = {"itemType": item_type}
            if link_mode:
                params["linkMode"] = link_mode
            # templates are global; always fetch from the web API (works without key)
            _, _, data = self.request("GET", WEB_BASE + "/items/new", params, auth=False)
            self._templates[k] = json.loads(data)
        return json.loads(json.dumps(self._templates[k]))

    # ------------------------------------------------------------- writing
    def _require_web(self):
        if self.local:
            raise ZoteroError(0, "Writes are not supported via the local API in this tool. Unset ZOTERO_LOCAL.")

    def create_items(self, items: list[dict]) -> list[tuple[dict, str | None, str | None]]:
        """Create items in batches of 50. Returns (item, key, error) per input item."""
        self._require_web()
        out: list[tuple[dict, str | None, str | None]] = []
        for i in range(0, len(items), WRITE_BATCH):
            batch = items[i:i + WRITE_BATCH]
            _, _, data = self.request(
                "POST", "items", body=json.dumps(batch).encode(),
                headers={"Content-Type": "application/json", "Zotero-Write-Token": secrets.token_hex(16)},
            )
            res = json.loads(data)
            ok, failed = res.get("successful", {}), res.get("failed", {})
            unchanged = res.get("unchanged", {})
            for j, item in enumerate(batch):
                s = str(j)
                if s in ok:
                    out.append((item, ok[s]["key"], None))
                elif s in unchanged:
                    out.append((item, unchanged[s], None))
                else:
                    err = failed.get(s, {})
                    out.append((item, None, f"{err.get('code')}: {err.get('message')}"))
        return out

    def children(self, item_key: str) -> list[dict]:
        return list(self.iter_json(f"items/{item_key}/children"))

    def upload_pdf(self, path: Path, parent_key: str | None, collection: str | None = None,
                   title: str | None = None) -> str:
        """Create an imported_file attachment and upload the file (Zotero storage)."""
        self._require_web()
        att = self.template("attachment", "imported_file")
        att.update({
            "title": title or path.name,
            "filename": path.name,
            "contentType": "application/pdf",
        })
        if parent_key:  # child attachments must not carry collections
            att["parentItem"] = parent_key
            att.pop("collections", None)
        else:
            att.pop("parentItem", None)
            att["collections"] = [collection] if collection else []
        content = path.read_bytes()
        if not content.startswith(b"%PDF"):
            raise ZoteroError(0, f"{path.name} is not a PDF file (missing %PDF header)")
        [(_, key, err)] = self.create_items([att])
        if err or not key:
            raise ZoteroError(400, f"creating attachment failed: {err}")
        try:
            self._upload_file(key, path, content)
        except Exception:
            # do not leave an attachment item without a file behind
            try:
                version = self.get_json(f"items/{key}")["version"]
                self.request("DELETE", f"items/{key}", headers={"If-Unmodified-Since-Version": str(version)})
            except Exception:
                print(f"  warning: could not remove incomplete attachment {key}", file=sys.stderr)
            raise
        return key

    def _upload_file(self, key: str, path: Path, content: bytes) -> None:
        form = urllib.parse.urlencode({
            "md5": hashlib.md5(content).hexdigest(),
            "filename": path.name,
            "filesize": len(content),
            "mtime": int(os.path.getmtime(path) * 1000),
        }).encode()
        form_h = {"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"}
        _, _, data = self.request("POST", f"items/{key}/file", body=form, headers=form_h)
        auth = json.loads(data)
        if auth.get("exists"):
            return
        # upload to storage (not api.zotero.org -> no API key sent)
        self.request(
            "POST", auth["url"],
            body=auth["prefix"].encode() + content + auth["suffix"].encode(),
            headers={"Content-Type": auth["contentType"]}, auth=False,
        )
        self.request(
            "POST", f"items/{key}/file",
            body=urllib.parse.urlencode({"upload": auth["uploadKey"]}).encode(), headers=form_h,
        )
