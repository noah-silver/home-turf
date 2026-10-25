"""Marketplace actions humans take in the app: edit profiles, send pitches, accept bars,
propose and approve rivalry events, post reviews. Agents never call these (GUARDRAILS S7):
every commitment here is triggered by a person clicking a button.
"""

from __future__ import annotations

import json
from typing import Any

import config
from agents.guard import screen
from core import audit, db

PROFILE_TEXT_FIELDS = ("sound_policy", "specials", "pitch_line", "teams_hosted")
APPROVAL_PARTIES = ("club_a", "club_b", "bar")


def user(user_id: str | None) -> dict | None:
    return db.one("SELECT * FROM users WHERE id = ?", (user_id,)) if user_id else None


def who(user_id: str | None) -> str:
    u = user(user_id)
    return u["display_name"].split(" · ")[0] if u else (user_id or "unknown")


def bar(bar_id: int) -> dict | None:
    return db.one("SELECT * FROM bars WHERE id = ?", (bar_id,))


def club(club_id: int) -> dict | None:
    return db.one("SELECT * FROM clubs WHERE id = ?", (club_id,))


def clubs_in_city(city: str) -> list[dict]:
    key = city.split(",")[0].strip().lower()
    return [c for c in db.query("SELECT * FROM clubs ORDER BY name") if c["city"].split(",")[0].strip().lower() == key]


# ---- bar profiles ----------------------------------------------------------------------

def update_bar_profile(bar_id: int, changes: dict[str, Any], session_id: str) -> dict:
    """Screen free-text fields with the Guard before saving (bars may try to game rankings)."""
    current = bar(bar_id)
    numbers = {k: changes.get(k, current[k]) for k in ("capacity", "tvs")}
    text = "\n".join(f"{k}: {changes[k]}" for k in PROFILE_TEXT_FIELDS if changes.get(k))
    for k, v in numbers.items():
        if v is not None and (not isinstance(v, int) or v < 0 or v > 5000):
            return {"ok": False, "message": f"{k} must be a whole number between 0 and 5,000."}
    if any(len(str(changes.get(k) or "")) > config.MAX_PROFILE_FIELD_CHARS for k in PROFILE_TEXT_FIELDS):
        return {"ok": False, "message": f"Keep each text field under {config.MAX_PROFILE_FIELD_CHARS} characters."}
    if text:
        verdict = screen("profile", text, context=f"capacity {numbers['capacity']}, tvs {numbers['tvs']}", session_id=session_id)
        if not verdict["allow"]:
            return {"ok": False, "message": f"Not saved. Guard: {verdict['reason']}", "guard": verdict}
    db.update("bars", bar_id, changes)
    audit.log("profile_saved", bar_id=bar_id, fields=list(changes))
    return {"ok": True, "message": "Profile saved."}


def claim_bar(bar_id: int, user_id: str) -> dict:
    db.update("bars", bar_id, {"claimed": 1})
    db.execute("UPDATE users SET bar_id = ? WHERE id = ?", (bar_id, user_id))
    audit.log("bar_claimed", bar_id=bar_id, user_id=user_id)
    return {"ok": True, "message": "Claimed. In production this needs business verification (phone or email at the bar's domain)."}


# ---- pitches -----------------------------------------------------------------------------

def send_pitch(bar_id: int, club_id: int, subject: str, body: str, session_id: str, user_id: str) -> dict:
    """A human bar manager sends a (possibly edited) pitch to a club's in-app inbox."""
    from agents.pitch_writer import facts_text, invented_numbers  # local import avoids a cycle
    from agents.schedule import cache_key

    b, c = bar(bar_id), club(club_id)
    facts = f"capacity {b['capacity']}, tvs {b['tvs']}, sound: {b['sound_policy']}, specials: {b['specials']}"
    sched = db.cache_get(cache_key(c["team"]), 24 * 365) or {}
    allowed = facts_text(b, c, sched.get("games", []))
    bad = invented_numbers(f"{subject} {body}", allowed)
    if bad:
        audit.log("pitch_blocked_numbers", bar_id=bar_id, club_id=club_id, numbers=bad)
        db.insert("guard_log", {"ts": db.now_iso(), "kind": "pitch", "layer": "code", "allowed": 0, "category": "false_claim",
                                "reason": f"numbers not in profile: {bad}", "excerpt": body[:240]})
        return {"ok": False, "message": f"Not sent. These numbers aren't backed by your profile: {', '.join(bad)}. Add them to your profile first or remove them."}
    verdict = screen("pitch", f"{subject}\n{body}", context=facts, session_id=session_id)
    if not verdict["allow"]:
        return {"ok": False, "message": f"Not sent. Guard: {verdict['reason']}", "guard": verdict}
    pid = db.insert(
        "pitches",
        {"bar_id": bar_id, "club_id": club_id, "subject": subject, "body": body, "status": "in_club_inbox",
         "created_at": db.now_iso(), "updated_at": db.now_iso()},
    )
    audit.log("pitch_sent_in_app", pitch_id=pid, bar_id=bar_id, club_id=club_id, by=user_id)
    return {"ok": True, "message": "Delivered to the club president's Home Turf inbox."}


def pitches_for_club(club_id: int) -> list[dict]:
    return db.query(
        "SELECT p.*, b.name bar_name FROM pitches p JOIN bars b ON b.id = p.bar_id WHERE p.club_id = ? ORDER BY p.id DESC",
        (club_id,),
    )


def pitches_from_bar(bar_id: int) -> list[dict]:
    return db.query(
        "SELECT p.*, c.name club_name FROM pitches p JOIN clubs c ON c.id = p.club_id WHERE p.bar_id = ? ORDER BY p.id DESC",
        (bar_id,),
    )


def respond_to_pitch(pitch_id: int, accept: bool, user_id: str) -> dict:
    p = db.one("SELECT * FROM pitches WHERE id = ?", (pitch_id,))
    db.update("pitches", pitch_id, {"status": "accepted" if accept else "declined", "updated_at": db.now_iso()})
    if accept:
        set_home_bar(p["club_id"], p["bar_id"], user_id)
    audit.log("pitch_response", pitch_id=pitch_id, accepted=accept, by=user_id)
    return {"ok": True}


def set_home_bar(club_id: int, bar_id: int, user_id: str) -> dict:
    """Human-only commitment: a president confirms a season home bar."""
    db.execute("UPDATE bookings SET status = 'replaced' WHERE club_id = ? AND season = ? AND status = 'confirmed'", (club_id, config.CURRENT_SEASON))
    db.insert("bookings", {"bar_id": bar_id, "club_id": club_id, "season": config.CURRENT_SEASON, "status": "confirmed", "confirmed_by": user_id, "created_at": db.now_iso()})
    db.update("clubs", club_id, {"home_bar_id": bar_id})
    audit.log("home_bar_confirmed", club_id=club_id, bar_id=bar_id, by=user_id)
    return {"ok": True}


# ---- rivalry events ------------------------------------------------------------------------

def propose_event(result: dict, bar_id: int, user_id: str) -> int:
    plan = result["plan"]
    game = result["game"]
    approvals = {p: "pending" for p in APPROVAL_PARTIES}
    approvals["club_a"] = f"approved by {who(user_id)}"  # the proposing president
    eid = db.insert(
        "events",
        {"kind": "rivalry", "title": plan["title"], "bar_id": bar_id, "club_a": result["club_a"]["id"],
         "club_b": result["club_b"]["id"], "game": f"{game['date']} {game['kickoff_et']} ({game['tv']})",
         "starts_at": game["date"], "plan": json.dumps(plan), "approvals": json.dumps(approvals),
         "status": "awaiting approvals", "created_at": db.now_iso()},
    )
    audit.log("event_proposed", event_id=eid, bar_id=bar_id, by=user_id)
    return eid


def events_for(club_id: int | None = None, bar_id: int | None = None) -> list[dict]:
    if club_id is not None:
        rows = db.query("SELECT * FROM events WHERE club_a = ? OR club_b = ? ORDER BY id DESC", (club_id, club_id))
    else:
        rows = db.query("SELECT * FROM events WHERE bar_id = ? ORDER BY id DESC", (bar_id,))
    for r in rows:
        r["approvals"] = json.loads(r["approvals"])
        r["plan"] = json.loads(r["plan"])
    return rows


def approve_event(event_id: int, party: str, user_id: str, approve: bool = True) -> dict:
    e = db.one("SELECT * FROM events WHERE id = ?", (event_id,))
    approvals = json.loads(e["approvals"])
    approvals[party] = f"approved by {who(user_id)}" if approve else f"declined by {who(user_id)}"
    if not approve:
        status = "declined"
    elif all(v.startswith("approved") for v in approvals.values()):
        status = "confirmed"
    else:
        status = "awaiting approvals"
    db.execute("UPDATE events SET approvals = ?, status = ? WHERE id = ?", (json.dumps(approvals), status, event_id))
    audit.log("event_approval", event_id=event_id, party=party, approve=approve, by=user_id, status=status)
    return {"ok": True, "status": status}


# ---- reviews -------------------------------------------------------------------------------

def post_review(bar_id: int, user_id: str, author: str, team: str, rating: int, text: str, session_id: str) -> dict:
    verdict = screen("review", text, session_id=session_id)
    status = "posted" if verdict["allow"] else "blocked"
    db.insert(
        "reviews",
        {"bar_id": bar_id, "user_id": user_id, "author": author, "team": team, "rating": rating, "text": text[:config.MAX_REVIEW_CHARS],
         "status": status, "guard_category": verdict["category"], "guard_reason": verdict["reason"], "is_seed": 0, "created_at": db.now_iso()},
    )
    return {"ok": verdict["allow"], "verdict": verdict}


def reviews_for(bar_id: int) -> list[dict]:
    return db.query("SELECT * FROM reviews WHERE bar_id = ? AND status = 'posted' ORDER BY id DESC", (bar_id,))


# ---- fan suggestions ------------------------------------------------------------------------

def suggest_spot(bar_name: str, address: str, city: str, team: str, source_url: str, user_id: str | None, session_id: str) -> dict:
    """A fan adds a watch spot we missed. Guard-screened, geocoded, and verified if a link is given."""
    from core.orchestrator import _link_bar  # local import avoids a cycle
    from tools.fetch_page import fetch_text
    from tools.geocode import geocode

    bar_name, address, city, team, source_url = (x.strip()[:200] for x in (bar_name, address, city, team, source_url or ""))
    if not (bar_name and city and team):
        return {"ok": False, "message": "Please give the bar's name, the team, and the city."}
    verdict = screen("review", f"Suggested watch spot: {bar_name}, {address}, {city}, for {team} fans. Source: {source_url}", session_id=session_id)
    if not verdict["allow"]:
        return {"ok": False, "message": f"Not added. Guard: {verdict['reason']}"}
    geo = geocode(address, city) if address else None
    geo = geo or geocode(f"{bar_name}, {city}")
    status, reason = "suggested", "Added by a fan; not yet verified."
    if source_url:
        page = fetch_text(source_url)
        if page["ok"] and all(w in page["text"].lower() for w in bar_name.lower().split()[:2]) and team.split()[-1].lower() in page["text"].lower():
            status, reason = "verified", "The linked page names this bar and the team."
        elif not page["ok"]:
            reason = f"Added by a fan; the link could not be checked ({page['error']})."
    spot = {"bar_name": bar_name, "address": address or "unknown", "lat": geo["lat"] if geo else None, "lon": geo["lon"] if geo else None,
            "status": "confirmed" if status == "verified" else "likely", "team": team, "source_url": source_url, "official_source": False}
    bar_id = _link_bar(spot, city)
    db.insert("suggestions", {"bar_name": bar_name, "address": address, "city": city, "team": team, "source_url": source_url, "note": "",
                              "lat": spot["lat"], "lon": spot["lon"], "bar_id": bar_id, "user_id": user_id or "guest", "status": status,
                              "verify_reason": reason, "created_at": db.now_iso()})
    audit.log("spot_suggested", bar=bar_name, city=city, team=team, status=status, by=user_id or "guest")
    where = "" if geo else " We couldn't place the address on the map yet."
    return {"ok": True, "message": f"Thanks! Added as {'verified' if status == 'verified' else 'fan-suggested'}: {reason}{where}", "status": status}


def suggestions_for(team: str, city: str) -> list[dict]:
    key = city.split(",")[0].strip().lower()
    return [s for s in db.query("SELECT * FROM suggestions WHERE lower(team) = lower(?) AND status != 'blocked' ORDER BY id DESC", (team,))
            if s["city"].split(",")[0].strip().lower() == key]
