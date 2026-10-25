"""Map (MapLibre GL in an iframe) with team-logo markers.

Each bar is one marker showing the logos of every team whose fans watch there, ringed in the
color of its verification status. A legend lists every team on the map and toggles its markers.
MapLibre and the CARTO Positron vector style load from public CDNs; no API key.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections import OrderedDict

from ui.team_logos import LEAGUE_ORDER, lookup

RING = {"confirmed": "#1f7a4d", "partner": "#b8902f", "likely": "#b7791f", "suggested": "#7a5bc4", "unverified": "#8a94a6", "allgames": "#2f6db3"}
LABEL = {"confirmed": "Verified", "partner": "Home Turf partner (demo)", "likely": "Likely", "suggested": "Fan-suggested", "unverified": "Unverified", "allgames": "Shows every game"}


def _team_info(team: str, sport: str = "") -> dict:
    t = lookup(team, sport)
    return {"logo": t["logo"], "color": t["color"], "abbr": t["abbr"], "name": t["name"], "group": t.get("group", "Other")}


def map_html(points: list[dict], highlight: list[str] | None = None, center: dict | None = None, zoom: int = 11, title: str = "") -> str:
    hl = {h.lower() for h in (highlight or [])}
    markers = []
    legend: dict[str, dict] = {}
    for p in points:
        teams = []
        for t in p["teams"]:
            info = _team_info(t["team"], t.get("sport", ""))
            teams.append({**t, **info, "hl": t["team"].lower() in hl, "ring": RING.get(t["status"], "#8a94a6"), "label": LABEL.get(t["status"], t["status"])})
            leg = legend.setdefault(t["team"], {**info, "team": t["team"], "count": 0, "hl": t["team"].lower() in hl})
            leg["count"] += 1
        teams.sort(key=lambda t: (not t["hl"]))
        markers.append({
            "lat": p["lat"], "lon": p["lon"], "bar": p["bar_name"], "address": p.get("address") or "",
            "bar_id": p.get("bar_id"), "teams": teams, "hl": any(t["hl"] for t in teams),
        })
    legend_rows = sorted(legend.values(), key=lambda x: (not x["hl"], LEAGUE_ORDER.index(x["group"]) if x["group"] in LEAGUE_ORDER else 99, -x["count"], x["team"]))
    data = json.dumps({"markers": markers, "legend": legend_rows, "center": center, "zoom": zoom, "title": title, "leagues": LEAGUE_ORDER})
    return TEMPLATE.replace("__DATA__", data.replace("</", "<\\/"))


TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
html, body, #map { margin: 0; height: 100%; width: 100%; font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
.pin { display: flex; align-items: center; gap: 2px; background: #fff; border: 3px solid #8a94a6; border-radius: 999px; padding: 2px 4px;
       box-shadow: 0 3px 10px rgba(15,34,64,.35); white-space: nowrap; cursor: pointer; }
.pin img { width: 26px; height: 26px; object-fit: contain; display: block; }
.pin .mono { width: 26px; height: 26px; border-radius: 50%; color: #fff; font: 700 9px/26px -apple-system, sans-serif; text-align: center; }
.pin.hl { border-width: 4px; padding: 3px 6px; }
.pin.hl img, .pin.hl .mono { width: 38px; height: 38px; line-height: 38px; font-size: 12px; }
.pin.dim { opacity: .8; }
.pin .more { font: 700 11px -apple-system, sans-serif; color: #0f2240; padding: 0 3px; }
.maplibregl-popup-content { border-radius: 10px; padding: 12px 14px; box-shadow: 0 6px 20px rgba(15,34,64,.25); }
.pop h3 { margin: 0 0 2px; font: 700 15px Georgia, serif; color: #0f2240; }
.pop .addr { color: #5d6b82; font-size: 12px; margin-bottom: 8px; }
.pop .row { display: flex; align-items: center; gap: 8px; margin: 5px 0; font-size: 12.5px; }
.pop .row img, .pop .row .mono { width: 24px; height: 24px; object-fit: contain; flex: none; }
.pop .row .mono { border-radius: 50%; color: #fff; font: 700 8px/24px sans-serif; text-align: center; }
.pop .st { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; padding: 1px 6px; border-radius: 999px; color: #fff; margin-left: auto; white-space: nowrap; }
.pop a.btn { display: inline-block; margin-top: 8px; background: #0f2240; color: #fff; padding: 6px 10px; border-radius: 7px; text-decoration: none; font-size: 12px; font-weight: 600; }
.legend { position: absolute; top: 10px; right: 10px; z-index: 5; background: rgba(255,255,255,.96); border-radius: 10px; box-shadow: 0 3px 14px rgba(15,34,64,.2); padding: 8px 10px; max-height: 60%; overflow-y: auto; min-width: 190px; }
.legend h4 { margin: 0 0 6px; font: 700 11px -apple-system, sans-serif; text-transform: uppercase; letter-spacing: .08em; color: #b8902f; }
.legend label { display: flex; align-items: center; gap: 7px; font-size: 12px; margin: 3px 0; cursor: pointer; color: #1b2433; }
.legend label.hl { font-weight: 700; }
.legend img, .legend .mono { width: 20px; height: 20px; object-fit: contain; flex: none; }
.legend .mono { border-radius: 50%; color: #fff; font: 700 7px/20px sans-serif; text-align: center; }
.legend .n { margin-left: auto; padding-left: 8px; color: #5d6b82; font-size: 11px; }
.key { position: absolute; bottom: 28px; left: 10px; z-index: 5; background: rgba(255,255,255,.95); border-radius: 10px; box-shadow: 0 3px 14px rgba(15,34,64,.2); padding: 6px 10px; font-size: 11px; color: #1b2433; }
.key span { display: inline-flex; align-items: center; gap: 4px; margin-right: 8px; }
.key i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; border: 2px solid; background: #fff; }
.leagues { position: absolute; top: 10px; left: 50px; z-index: 6; display: flex; gap: 6px; flex-wrap: wrap; max-width: 60%; }
.leagues button { border: 1px solid #d5dbe6; background: rgba(255,255,255,.96); color: #0f2240; border-radius: 999px; padding: 5px 11px; font: 600 12px -apple-system, sans-serif;
  cursor: pointer; box-shadow: 0 2px 8px rgba(15,34,64,.15); }
.leagues button.on { background: #0f2240; color: #fff; border-color: #0f2240; }
.leagues button .c { opacity: .65; margin-left: 3px; font-weight: 500; }
.legend .grp { font: 700 10px -apple-system, sans-serif; color: #5d6b82; text-transform: uppercase; letter-spacing: .06em; margin: 7px 0 2px; }
.empty { position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); z-index: 5; background: #fff; padding: 14px 18px; border-radius: 10px; box-shadow: 0 3px 14px rgba(15,34,64,.2); font-size: 13px; color: #5d6b82; text-align: center; }
</style></head><body><div id="map"></div>
<script>
const D = __DATA__;
const RING = {confirmed:'#1f7a4d', partner:'#b8902f', likely:'#b7791f', suggested:'#7a5bc4', unverified:'#8a94a6', allgames:'#2f6db3'};
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function badge(t){ return t.logo ? `<img src="${esc(t.logo)}" alt="${esc(t.name)}" title="${esc(t.team)}">`
  : `<div class="mono" style="background:${esc(t.color)}" title="${esc(t.team)}">${esc(t.abbr)}</div>`; }
const map = new maplibregl.Map({container: 'map', style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
  center: [-96.5, 39.5], zoom: 3.3, attributionControl: false});
map.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-left');
map.addControl(new maplibregl.AttributionControl({customAttribution: 'logos via ESPN', compact: true}));
const anyHl = D.markers.some(m => m.hl);
const markers = D.markers.map(m => {
  const el = document.createElement('div');
  el.className = 'pin ' + (m.hl ? 'hl' : (anyHl ? 'dim' : ''));
  el.style.borderColor = m.teams[0].ring;
  el.innerHTML = m.teams.slice(0, 3).map(badge).join('') + (m.teams.length > 3 ? `<span class="more">+${m.teams.length - 3}</span>` : '');
  if (m.hl) el.style.zIndex = 10;
  const rows = m.teams.map(t => `<div class="row">${badge(t)}<div><b>${esc(t.team)}</b>${t.club ? '<br><span style="color:#5d6b82">' + esc(t.club) + '</span>' : ''}</div>
     <span class="st" style="background:${t.ring}">${esc(t.label)}</span></div>`).join('');
  const link = m.bar_id ? `<a class="btn" target="_top" href="/bar/${m.bar_id}">Bar page, photos &amp; reviews →</a>` : '';
  const popup = new maplibregl.Popup({offset: 22, maxWidth: '300px'}).setHTML(`<div class="pop"><h3>${esc(m.bar)}</h3><div class="addr">${esc(m.address)}</div>${rows}${link}</div>`);
  const mk = new maplibregl.Marker({element: el}).setLngLat([m.lon, m.lat]).setPopup(popup).addTo(map);
  mk.teams = m.teams.map(t => t.team); mk.hl = m.hl;
  return mk;
});
function fit() {
  const focus = markers.filter(x => x.hl); const pts = (focus.length ? focus : markers).map(x => x.getLngLat());
  if (pts.length > 1) { const b = new maplibregl.LngLatBounds(pts[0], pts[0]); pts.forEach(p => b.extend(p)); map.fitBounds(b, {padding: 80, maxZoom: 13, duration: 0}); }
  else if (pts.length === 1) map.jumpTo({center: pts[0], zoom: 13});
  else if (D.center) map.jumpTo({center: [D.center.lon, D.center.lat], zoom: D.zoom || 11});
}
fit();
if (!markers.length) { const e = document.createElement('div'); e.className = 'empty';
  e.innerHTML = esc(D.title || 'Search a team and a city to see where fans watch.'); document.body.appendChild(e); }
if (D.legend.length) {
  const div = document.createElement('div'); div.className = 'legend';
  let last = null;
  div.innerHTML = `<h4>${esc(D.title || 'Teams on this map')}</h4>` + D.legend.map(t => {
    const head = (!t.hl && t.group !== last) ? `<div class="grp" data-league="${esc(t.group)}">${esc(t.group)}</div>` : '';
    if (!t.hl) last = t.group;
    return head + `<label class="${t.hl ? 'hl' : ''}" data-league="${esc(t.group)}"><input type="checkbox" checked data-team="${esc(t.team)}">${badge(t)}<span>${esc(t.team)}</span><span class="n">${t.count}</span></label>`;
  }).join('');
  document.body.appendChild(div);
  const teamLeague = Object.fromEntries(D.legend.map(t => [t.team, t.group]));
  let league = 'All';
  function apply() {
    const on = new Set([...div.querySelectorAll('input:checked')].map(x => x.dataset.team).filter(t => league === 'All' || teamLeague[t] === league));
    markers.forEach(mk => { const vis = mk.teams.some(t => on.has(t)); mk.getElement().style.display = vis ? '' : 'none'; });
    div.querySelectorAll('[data-league]').forEach(el => { el.style.display = (league === 'All' || el.dataset.league === league) ? '' : 'none'; });
  }
  div.addEventListener('change', apply);
  // League filter chips: All · NFL · NCAA · MLB · NBA · NHL · Soccer ...
  const counts = {}; D.legend.forEach(t => counts[t.group] = (counts[t.group] || 0) + 1);
  const groups = Object.keys(counts);
  if (groups.length > 1) {
    const bar = document.createElement('div'); bar.className = 'leagues';
    bar.innerHTML = ['All', ...D.leagues.filter(g => counts[g])].map(g =>
      `<button data-g="${esc(g)}" class="${g === 'All' ? 'on' : ''}">${esc(g)}<span class="c">${g === 'All' ? D.legend.length : counts[g]}</span></button>`).join('');
    bar.addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; league = b.dataset.g;
      bar.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); apply(); });
    document.body.appendChild(bar);
  }
}
const key = document.createElement('div'); key.className = 'key';
key.innerHTML = [['confirmed','Verified'],['likely','Likely'],['partner','Partner'],['suggested','Fan-suggested'],['allgames','Shows every game']]
  .map(([k, l]) => `<span><i style="border-color:${RING[k]}"></i>${l}</span>`).join('');
document.body.appendChild(key);
</script></body></html>"""


_FRAMES: "OrderedDict[str, str]" = OrderedDict()
_LOCK = threading.Lock()
MAX_FRAMES = 300


def map_src(points: list[dict], **kwargs) -> str:
    """Store a rendered map and return its URL. Served by app.py at /mapframe/<id> (same origin,
    which MapLibre's tile workers need; an inline srcdoc iframe has a null origin)."""
    page = map_html(points, **kwargs)
    token = uuid.uuid4().hex[:16]
    with _LOCK:
        _FRAMES[token] = page
        while len(_FRAMES) > MAX_FRAMES:
            _FRAMES.popitem(last=False)
    return f"/mapframe/{token}"


def get_frame(token: str) -> str | None:
    with _LOCK:
        return _FRAMES.get(token)


def iframe_style(height: str = "100%") -> dict:
    return {"width": "100%", "height": height, "border": "0", "display": "block"}

