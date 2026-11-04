"""
Keks Passa — real-location resolver (stdlib only).

Why this exists: listing pages (Cartaz Cultural, AgendaLX, ViralAgenda, NoCartaz…) often don't
say *where* an event is, so the scraper used to drop them on a fake "city centre" point (which is
the Coliseu dos Recreios).  The event's own detail page nearly always states the venue/address,
and OpenStreetMap's Nominatim can turn that address into real coordinates.

Rules:
  * never invent a position — if neither the page nor the geocoder gives a Lisbon result, return None
  * be polite to Nominatim: <= 1 request/second, descriptive User-Agent, results cached on disk
    in geocode_cache.json (committed to the repo) so each address is only ever looked up once.
"""

import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request

LISBON_BOUNDS = (38.65, 38.82, -9.25, -9.05)  # lat_min, lat_max, lng_min, lng_max
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geocode_cache.json")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "KeksPassa/1.0 (+https://github.com/Hal-Inc/Keks-Passa; daily Lisbon events map)"

STREET_PREFIX = re.compile(
    r"^(rua|r\.|avenida|av\.|av |travessa|tv\.|largo|pra[cç]a|cal[cç]ada|alameda|beco|campo|estrada|"
    r"cais|p[aá]tio|jardim|azinhaga|bairro|doca|rotunda|escadinhas|t[uú]nel|parque)\b",
    re.IGNORECASE,
)

_cache = None
_last_request_at = 0.0


def _strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", str(text or "")) if unicodedata.category(c) != "Mn")


def in_lisbon(lat, lng):
    return LISBON_BOUNDS[0] <= lat <= LISBON_BOUNDS[1] and LISBON_BOUNDS[2] <= lng <= LISBON_BOUNDS[3]


# ------------------------------------------------------------------------------
# 1. Pull "where is this event" out of an event detail page
# ------------------------------------------------------------------------------
def _walk_jsonld(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _walk_jsonld(value)


def _html_to_lines(html):
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#8217;", "'")
            .replace("&#039;", "'").replace("&quot;", '"'))
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]


def extract_event_location(html):
    """Returns the raw location string found on an event page, or '' (never guesses)."""
    if not html:
        return ""

    # a) schema.org Event.location (name + street address)
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, flags=re.S | re.I):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for node in _walk_jsonld(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if not any(isinstance(t, str) and t.endswith("Event") for t in types):
                continue
            loc = node.get("location")
            loc = loc[0] if isinstance(loc, list) and loc else loc
            if isinstance(loc, dict):
                name = str(loc.get("name") or "").strip()
                addr = loc.get("address")
                if isinstance(addr, dict):
                    addr = ", ".join(str(addr.get(k) or "").strip() for k in ("streetAddress", "addressLocality") if addr.get(k))
                addr = str(addr or "").strip()
                combined = ", ".join(p for p in (name, addr) if p)
                if len(combined) >= 4:
                    return combined

    # b) "📍 Local: …", "Morada: …", "Onde: …" lines in the page text
    label = re.compile(
        r"^(?:[\W_]{0,4})\s*(?:local(?:iza[cç][aã]o)?(?: do evento)?|morada|onde|location|venue|endere[cç]o)\s*[:\-–]\s*(.{4,200})$",
        re.IGNORECASE,
    )
    pin_first, others = [], []
    for ln in _html_to_lines(html):
        m = label.match(ln)
        if m:
            value = re.split(r"\s*(?:\||organiza[cç][aã]o:|hor[aá]rio:|bilhetes?:|pre[cç]o:|data:)", m.group(1), flags=re.I)[0].strip(" .;")
            if len(value) >= 4:
                (pin_first if "📍" in ln else others).append(value)
    if pin_first:
        return pin_first[0]
    if others:
        return others[0]
    return ""


def split_name_and_address(raw):
    """'Emaús Pop-Up Arroios, Rua Carlos Mardel, 23, Lisboa' -> ('Emaús Pop-Up Arroios', 'Rua Carlos Mardel, 23, Lisboa')."""
    parts = [p.strip() for p in re.split(r",\s*", raw) if p.strip()]
    for i, part in enumerate(parts):
        if STREET_PREFIX.match(part):
            name = ", ".join(parts[:i]).strip()
            return name, ", ".join(parts[i:]).strip()
    return raw.strip(), ""


# ------------------------------------------------------------------------------
# 2. Nominatim geocoder with an on-disk cache
# ------------------------------------------------------------------------------
def _load_cache():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def save_cache():
    if _cache is None:
        return
    with open(CACHE_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def _nominatim(query):
    global _last_request_at
    wait = 1.1 - (time.time() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    params = {
        "q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1, "countrycodes": "pt",
        "viewbox": f"{LISBON_BOUNDS[2]},{LISBON_BOUNDS[1]},{LISBON_BOUNDS[3]},{LISBON_BOUNDS[0]}", "bounded": 1,
    }
    req = urllib.request.Request(NOMINATIM_URL + "?" + urllib.parse.urlencode(params), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[Geocoder] Nominatim notice for {query!r}: {exc}")
        return "ERROR"
    finally:
        _last_request_at = time.time()
    if not data:
        return None
    hit = data[0]
    lat, lng = float(hit["lat"]), float(hit["lon"])
    if not in_lisbon(lat, lng):
        return None
    addr = hit.get("address", {})
    area = addr.get("suburb") or addr.get("neighbourhood") or addr.get("quarter") or addr.get("city_district") or ""
    return {"lat": round(lat, 6), "lng": round(lng, 6), "area": area}


def geocode(query):
    """Cached lookup. Returns {'lat','lng','area'} or None. Failed lookups are cached too (except network errors)."""
    query = re.sub(r"\s+", " ", (query or "")).strip(" ,")
    if len(query) < 4:
        return None
    cache = _load_cache()
    key = _strip_accents(query).lower()
    if key in cache:
        return cache[key]
    result = _nominatim(query)
    if result == "ERROR":
        return None
    cache[key] = result
    return result


def geocode_location(raw):
    """Tries address-only, then full string, then venue name.  Returns (result_dict, venue_name) or (None, name)."""
    name, address = split_name_and_address(raw)
    candidates = []
    if address:
        candidates.append(address if re.search(r"lisboa", address, re.I) else address + ", Lisboa")
    candidates.append(raw if re.search(r"lisboa", raw, re.I) else raw + ", Lisboa")
    if name and name != raw:
        candidates.append(name + ", Lisboa")
    seen = set()
    for q in candidates:
        if q in seen:
            continue
        seen.add(q)
        hit = geocode(q)
        if hit:
            return hit, (name or raw)
    return None, (name or raw)


def infer_corridor(lat, lng):
    """Maps lat/lng into one of the 4 Keks Passa zone corridors."""
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return "Axial Spine"

    if lat >= 38.73:
        if lng > -9.13:
            return "Eastern Corridor"
        return "Northern Belt"
    else:
        if lng < -9.16:
            return "Belém Waterfront"
        if lng > -9.13:
            return "Eastern Corridor"
        return "Axial Spine"


def infer_neighborhood(lat, lng, area=""):
    """Infers human-readable neighborhood name from area or lat/lng."""
    if area and str(area).strip():
        return str(area).strip()
    c = infer_corridor(lat, lng)
    if c == "Eastern Corridor":
        return "Marvila / Oriente" if lat >= 38.74 else "Graça / Santa Apolónia"
    elif c == "Belém Waterfront":
        return "Belém / Alcântara"
    elif c == "Northern Belt":
        return "Avenidas Novas / Saldanha"
    return "Centro Histórico"

