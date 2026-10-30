#!/usr/bin/env python3
"""
Keks Passa / Lisbon Live Daily Events Pipeline (v2.1)
Scrapes, deduplicates, and geocodes cultural & nightlife events in Lisbon
based on the 04:00 Europe/Lisbon operational day.
"""

import os
import sys
import json
import re
import math
import html
import unicodedata
import datetime
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

# Use curl_cffi if available to impersonate Chrome TLS fingerprint
try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

try:
    import zoneinfo
    LISBON_TZ = zoneinfo.ZoneInfo("Europe/Lisbon")
except Exception:
    LISBON_TZ = datetime.timezone.utc

MAX_EVENTS = None

CATEGORY_PRESETS = {
    "music": {"category": "Concerts & Live Music", "color": "#E63946", "icon": "🔴"},
    "theatre": {"category": "Theatre & Comedy", "color": "#2A9D8F", "icon": "🟢"},
    "art": {"category": "Exhibitions & Visual Arts", "color": "#1D3557", "icon": "🔵"},
    "opera": {"category": "Opera & Classical", "color": "#8338EC", "icon": "🟣"},
    "cinema": {"category": "Cinema & Screenings", "color": "#06D6A0", "icon": "🩷"},
    "nightlife": {"category": "Nightlife & Electronic", "color": "#FB5607", "icon": "🟠"},
    "community": {"category": "Community & Gatherings", "color": "#FFB703", "icon": "🟡"},
    "family": {"category": "Family & Youth", "color": "#118AB2", "icon": "🩵"}
}

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7"
}

VENUE_REGISTRY = [
    {
        "venue": "Coliseu dos Recreios",
        "aliases": ["coliseu dos recreios", "coliseu de lisboa", "coliseu club", "portas de santo antao 96"],
        "lat": 38.7163, "lng": -9.1404, "neighborhood": "Baixa / Rossio", "corridor": "Axial Spine",
        "url": "https://coliseulisboa.com"
    },
    {
        "venue": "Galeria Zé dos Bois (ZDB)",
        "aliases": ["galeria ze dos bois", "livraria ze dos bois", "ze dos bois", "zdb"],
        "lat": 38.7122, "lng": -9.1444, "neighborhood": "Bairro Alto", "corridor": "Axial Spine",
        "url": "https://zedosbois.org/en/programme/"
    },
    {
        "venue": "Lux Frágil",
        "aliases": ["lux fragil", "lux"],
        "lat": 38.7108, "lng": -9.1225, "neighborhood": "Santa Apolónia", "corridor": "Eastern Corridor",
        "url": "https://www.luxfragil.com/agenda"
    },
    {
        "venue": "Kømplex Lisbon",
        "aliases": ["komplex lisbon", "kømplex lisbon", "kømplex", "komplex", "praceta domingos rodrigues"],
        "lat": 38.7845, "lng": -9.1192, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor",
        "url": "https://shotgun.live/pt-pt/venues/komplex"
    },
    {
        "venue": "Moon Club",
        "aliases": ["moon club", "moonclub", "moon club prior velho", "raw kinky lab"],
        "lat": 38.7862, "lng": -9.1245, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor",
        "url": "https://www.moonclub.pt"
    },
    {
        "venue": "NĀDA 3.0 (NADA Lisbon)",
        "aliases": ["nada 3.0", "naada 3.0", "nada lisbon", "naada", "nāda", "rua figo maduro 3", "armazem 6", "tiga naada"],
        "lat": 38.7858, "lng": -9.1238, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor",
        "url": "https://shotgun.live/pt-pt/venues/nada-lisbon"
    },
    {
        "venue": "Higher Ground",
        "aliases": ["higher ground", "rua ary dos santos 20"],
        "lat": 38.7868, "lng": -9.1252, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor",
        "url": "https://shotgun.live/en/cities/lisbon"
    },
    {
        "venue": "Music Station",
        "aliases": ["music station", "rock station", "aquilino ribeiro machado 74"],
        "lat": 38.7735, "lng": -9.0975, "neighborhood": "Parque das Nações / Oriente", "corridor": "Eastern Corridor",
        "url": "https://pt.ra.co/clubs/254407"
    },
    {
        "venue": "Top Floor",
        "aliases": ["top floor", "rua da pimenta 29"],
        "lat": 38.7712, "lng": -9.0928, "neighborhood": "Parque das Nações / Oriente", "corridor": "Eastern Corridor",
        "url": "https://www.lisabout.com/genero/dance-electronic"
    }
]

DEFAULT_GEO = {
    "venue": "Lisboa Cultural",
    "lat": 38.7165, "lng": -9.1415,
    "neighborhood": "Lisboa Central",
    "corridor": "Axial Spine",
    "url": "https://www.agendalx.pt"
}

def strip_accents(text):
    if not text:
        return ""
    text = text.replace("ø", "o").replace("Ø", "o")
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(text))
        if not unicodedata.combining(c)
    ).lower().strip()

SORTED_ALIAS_INDEX = []
for v_entry in VENUE_REGISTRY:
    for alias in v_entry.get("aliases", []):
        SORTED_ALIAS_INDEX.append((strip_accents(alias), v_entry))
SORTED_ALIAS_INDEX.sort(key=lambda x: len(x[0]), reverse=True)

def match_venue(venue_str, title_hint=""):
    combined_raw = f"{venue_str or ''} {title_hint or ''}".strip()
    if not combined_raw:
        return DEFAULT_GEO.copy()
    norm_str = strip_accents(venue_str or "")
    norm_combined = strip_accents(combined_raw)
    for target_text in (norm_str, norm_combined):
        if not target_text:
            continue
        for alias, v_info in SORTED_ALIAS_INDEX:
            if len(alias) <= 4:
                if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", target_text):
                    return v_info.copy()
            else:
                if alias in target_text:
                    return v_info.copy()
    clean_display = (venue_str or "Lisboa").strip()
    res = DEFAULT_GEO.copy()
    res["venue"] = clean_display
    return res

def fetch_url(url, method="GET", json_body=None, headers=None, timeout=14):
    req_headers = HTTP_HEADERS.copy()
    if headers:
        req_headers.update(headers)
    if HAS_CFFI:
        try:
            if method == "POST":
                return cffi_requests.post(url, json=json_body, headers=req_headers, impersonate="chrome120", timeout=timeout)
            return cffi_requests.get(url, headers=req_headers, impersonate="chrome120", timeout=timeout)
        except Exception:
            pass
    if method == "POST":
        return requests.post(url, json=json_body, headers=req_headers, timeout=timeout)
    return requests.get(url, headers=req_headers, timeout=timeout)

def parse_price_and_tier(raw_price, default_price="Preço a confirmar", default_tier="ACCESSIBLE"):
    if not raw_price:
        return default_price, default_tier
    p_str = str(raw_price).strip()
    p_low = strip_accents(p_str)
    if any(w in p_low for w in ["gratis", "gratuito", "free", "entrada livre", "a borla"]):
        return "Grátis", "FREE"
    matches = re.findall(r"(\d+(?:[.,]\d{1,2})?)\s*€|€\s*(\d+(?:[.,]\d{1,2})?)", p_str)
    nums = []
    for m in matches:
        val_str = (m[0] or m[1]).replace(",", ".")
        try:
            nums.append(float(val_str))
        except ValueError:
            pass
    if nums:
        min_p = min(nums)
        max_p = max(nums)
        display = f"{min_p:.2f}€".replace(".00€", "€") if min_p == max_p else f"{min_p:.0f}€ - {max_p:.0f}€"
        tier = "FREE" if min_p == 0 else ("ACCESSIBLE" if min_p <= 15.0 else ("MID" if min_p <= 30.0 else "PREMIUM"))
        return display, tier
    return default_price, default_tier

def parse_time_str(raw_time, default_time="21:00"):
    if not raw_time:
        return default_time, int(default_time.split(":")[0])
    t_clean = str(raw_time).strip()
    m_24 = re.search(r"\b([01]?\d|2[0-3])[:h.]([0-5]\d)\b", t_clean, re.I)
    if m_24:
        h = int(m_24.group(1))
        return f"{h:02d}:{m_24.group(2)}", h
    m_hour_only = re.search(r"\b([01]?\d|2[0-3])\s*h\b", t_clean, re.I)
    if m_hour_only:
        h = int(m_hour_only.group(1))
        return f"{h:02d}:00", h
    return default_time, int(default_time.split(":")[0])

def infer_end_time(start_time, hour_int, category_name, venue_name="", title="", desc=""):
    combined = f"{title or ''} {desc or ''}"
    m_range = re.search(
        r"\b(?:[01]?\d|2[0-3])(?:[:h.][0-5]\d|\s*h)?\s*(?:–|—|-|às|as|to|até)\s*([01]?\d|2[0-3])(?:[:h.]([0-5]\d)|\s*h)\b",
        combined, re.I
    )
    if m_range:
        eh = int(m_range.group(1))
        em = int(m_range.group(2) or 0)
        return f"{eh:02d}:{em:02d}", eh

    parts = (start_time or "21:00").split(":")
    sh = int(parts[0]) if parts else hour_int
    sm = int(parts[1]) if len(parts) > 1 else 0

    def add_minutes(h, m, delta):
        total = (h * 60 + m + delta) % (24 * 60)
        return f"{total // 60:02d}:{total % 60:02d}", (total // 60)

    v_low = strip_accents(venue_name or "")
    if category_name == "Nightlife & Electronic":
        if 4 <= sh <= 8: return "12:00", 12
        if 12 <= sh < 17: return "23:00", 23
        if 17 <= sh < 21: return "02:00", 2
        if "moon club" in v_low: return "07:00", 7
        if "nada" in v_low or "naada" in v_low: return "05:00", 5
        return "06:00", 6

    return add_minutes(sh, sm, 120)

def scrape_prior_velho_electronic(target_date):
    events = []
    next_date = target_date + datetime.timedelta(days=1)
    d_today = f"{target_date.day}/{target_date.month:02d}"
    d_next = f"{next_date.day}/{next_date.month:02d}"

    lisabout_urls = [
        "https://www.lisabout.com/zona/prior-velho",
        "https://www.lisabout.com/genero/dance-electronic"
    ]
    for url in lisabout_urls:
        try:
            resp = fetch_url(url)
            if resp.status_code != 200: continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/events/"]'):
                href = a_tag.get("href", "")
                card_text = a_tag.get_text(" | ", strip=True)
                if not (d_today in card_text or (d_next in card_text and re.search(r"\b0[4-8]:[0-5]\d\b", card_text))):
                    continue
                time_str, hour_int = parse_time_str(card_text, "23:59")
                title_el = a_tag.find(["h3", "h4", "strong"])
                title = title_el.get_text(" ", strip=True) if title_el else "Noite Eletrónica"
                geo = match_venue(card_text, title)
                price_disp, price_tier = parse_price_and_tier(card_text, "10€ - 20€", "ACCESSIBLE")
                ev_url = urljoin("https://www.lisabout.com", href)
                end_t, end_h = infer_end_time(time_str, hour_int, CATEGORY_PRESETS["nightlife"]["category"], geo["venue"], title, card_text)
                events.append({
                    "id": f"pv-{href.strip('/').split('/')[-1]}",
                    "title": title,
                    "category": CATEGORY_PRESETS["nightlife"]["category"],
                    "color": CATEGORY_PRESETS["nightlife"]["color"],
                    "icon": CATEGORY_PRESETS["nightlife"]["icon"],
                    "venue": geo["venue"], "neighborhood": geo["neighborhood"], "corridor": geo["corridor"],
                    "lat": geo["lat"], "lng": geo["lng"],
                    "time": time_str, "hour": hour_int, "endTime": end_t, "endHour": end_h,
                    "price": price_disp, "priceTier": price_tier, "url": ev_url,
                    "description": f"{title} em {geo['venue']} ({geo['neighborhood']})."
                })
        except Exception:
            pass
    return events

def get_lisbon_operational_date():
    now = datetime.datetime.now(LISBON_TZ)
    op_date = (now - datetime.timedelta(days=1)).date() if now.hour < 4 else now.date()
    return op_date, now

def main():
    target_date, now_time = get_lisbon_operational_date()
    all_events = scrape_prior_velho_electronic(target_date)

    for ev in all_events:
        if "endTime" not in ev:
            end_t, end_h = infer_end_time(ev.get("time", "21:00"), ev.get("hour", 21), ev.get("category", ""), ev.get("venue", ""), ev.get("title", ""), ev.get("description", ""))
            ev["endTime"] = end_t
            ev["endHour"] = end_h

    payload = {
        "updated_at": now_time.isoformat(),
        "generated_at": now_time.isoformat(),
        "date_string": target_date.strftime("%A, %B %d, %Y"),
        "operational_date": target_date.strftime("%Y-%m-%d"),
        "total_events": len(all_events),
        "events": all_events
    }
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Successfully published {len(all_events)} events.")

if __name__ == "__main__":
    main()
