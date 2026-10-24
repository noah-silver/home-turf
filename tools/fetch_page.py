"""Fetch a source page so the Verifier can re-check the Scout's claim.

Safety (GUARDRAILS S3, S8): URLs come from model output, so only public http(s) hosts are
allowed. Loopback, private, and link-local addresses are refused (no SSRF into the machine
running the app). Responses are size-capped and turned into plain text.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 HomeTurf/1.0",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_BYTES = 1_500_000


class UnsafeURL(ValueError):
    pass


def check_url(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeURL("Only public http(s) links are allowed.")
    host = parsed.hostname
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeURL("Local addresses are not allowed.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURL("The link's host does not exist.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeURL("Private network addresses are not allowed.")
    return url


def fetch_text(url: str) -> dict:
    """Return {'ok', 'status', 'text', 'error'}; never raises."""
    try:
        check_url(url)
        with httpx.Client(follow_redirects=True, timeout=10, headers=HEADERS) as client:
            resp = client.get(url)
            # Re-check the final host after redirects.
            check_url(str(resp.url))
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "text": "", "error": f"HTTP {resp.status_code}"}
        content = resp.content[:MAX_BYTES]
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        return {"ok": True, "status": resp.status_code, "text": text, "error": ""}
    except UnsafeURL as exc:
        return {"ok": False, "status": 0, "text": "", "error": f"blocked: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": 0, "text": "", "error": type(exc).__name__}
