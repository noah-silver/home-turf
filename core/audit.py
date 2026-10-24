"""Append-only audit trail (GUARDRAILS S14).

One JSON object per line in runtime/audit_log.jsonl. Entries are only ever appended, under a
lock, and long fields are clipped. Secrets are never passed in, and auditing never raises.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

import config
from core.db import now_iso

_LOCK = threading.Lock()
CLIP = 1500


def clip(value: Any, limit: int = CLIP) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"... [clipped {len(value) - limit} chars]"
    return value


def prompt_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def log(event: str, **fields: Any) -> None:
    try:
        entry = {"ts": now_iso(), "event": event, **{k: clip(v) for k, v in fields.items()}}
        line = json.dumps(entry, default=str)
        config.RUNTIME_DIR.mkdir(exist_ok=True)
        with _LOCK, open(config.AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # auditing must never break a request
        pass


def tail(n: int = 60) -> list[dict[str, Any]]:
    if not config.AUDIT_PATH.exists():
        return []
    with _LOCK:
        lines = config.AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-n:]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
