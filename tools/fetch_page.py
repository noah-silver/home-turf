"""Fetch a source page so the Verifier can re-check the Scout's claim.

Safety (GUARDRAILS S3, S8): URLs come from model output, so only public http(s) hosts are
allowed. Loopback, private, and link-local addresses are refused (no SSRF into the machine
running the app). Responses are size-capped and turned into plain text.
"""

from __future__ import annotations

import ipaddress
import socket
import time
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


_PAGE_CACHE: dict[str, tuple[float, dict]] = {}
PAGE_CACHE_SECONDS = 600


def fetch_text(url: str) -> dict:
    """Return {'ok', 'status', 'text', 'error'}; never raises. Pages are cached for 10 minutes."""
    hit = _PAGE_CACHE.get(url)
    if hit and time.time() - hit[0] < PAGE_CACHE_SECONDS:
        return hit[1]
    result = _fetch_text(url)
    _PAGE_CACHE[url] = (time.time(), result)
    if len(_PAGE_CACHE) > 500:
        _PAGE_CACHE.pop(next(iter(_PAGE_CACHE)))
    return result


def _fetch_text(url: str) -> dict:
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


def site_photos(url: str, limit: int = 4) -> list[str]:
    """Photos a bar publishes on its own website: the social-preview image first, then page images.

    Public https only; logos, icons, and tiny graphics are skipped. Images are linked, not copied.
    """
    photos: list[str] = []
    try:
        check_url(url)
        with httpx.Client(follow_redirects=True, timeout=8, headers=HEADERS) as client:
            resp = client.get(url)
            check_url(str(resp.url))
        if resp.status_code >= 400:
            return []
        soup = BeautifulSoup(resp.content[:MAX_BYTES], "html.parser")
        for attrs in ({"property": "og:image"}, {"name": "og:image"}, {"name": "twitter:image"}, {"property": "twitter:image"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content", "").startswith("https://"):
                photos.append(tag["content"])
        skip = ("logo", "icon", "sprite", "favicon", "badge", "pixel", "spacer", "avatar")
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            low = src.lower()
            if not src.startswith("https://") or any(k in low for k in skip) or low.endswith((".svg", ".gif")):
                continue
            if src not in photos:
                photos.append(src)
            if len(photos) >= limit:
                break
    except Exception:  # noqa: BLE001
        return photos[:limit]
    return photos[:limit]
