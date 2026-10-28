#!/usr/bin/env python3
"""Build events.json for Keks Passa from public event calendars.

The scraper prefers Schema.org Event JSON-LD and falls back to date-stamped
cards in the official listing pages below. It deliberately fails rather than
publishing an empty dataset if every source fails or no current-day events can
be identified; that keeps a bad scrape from silently erasing the live agenda.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

TZ = ZoneInfo("Europe/Lisbon")
RESET_HOUR = 4
OUTPUT = Path(__file__).with_name("events.json")
USER_AGENT = "KeksPassaEventCalendar/1.0 (+https://hal-inc.github.io/Keks-Passa/; public event listing aggregator)"
REQUEST_TIMEOUT = 22

SOURCES = [
    {"name": "CCB", "url": "https://www.ccb.pt/eventos/", "venue": "CCB – Centro Cultural de Belém", "neighborhood": "Belém"},
    {"name": "Galeria Zé dos Bois", "url": "https://zedosbois.org/programa/", "venue": "Galeria Zé dos Bois (ZDB)", "neighborhood": "Bairro Alto"},
    {"name": "BOTA", "url": "https://www.botaanjos.com/programacao/", "venue": "BOTA (Base Organizada da Toca das Artes)", "neighborhood": "Anjos"},
    {"name": "Gulbenkian", "url": "https://gulbenkian.pt/agenda/", "venue": "Fundação Calouste Gulbenkian", "neighborhood": "São Sebastião"},
    {"name": "MAAT", "url": "https://maat.pt/pt/agenda", "venue": "MAAT", "neighborhood": "Belém"},
    {"name": "Culturgest", "url": "https://www.culturgest.pt/pt/programacao/", "venue": "Culturgest", "neighborhood": "Campo Pequeno"},
    {"name": "Teatro Maria Matos", "url": "https://teatromariamatos.pt/", "venue": "Teatro Maria Matos", "neighborhood": "Alvalade / Roma"},
    {"name": "Coliseu dos Recreios", "url": "https://coliseulisboa.com/o-coliseu/programacao/", "venue": "Coliseu dos Recreios", "neighborhood": "Baixa / Rossio"},
    {"name": "Museu de Lisboa", "url": "https://www.museudelisboa.pt/pt/agenda.html", "venue": "Museu de Lisboa", "neighborhood": "Lisboa"},
    {"name": "Museu Bordalo Pinheiro", "url": "https://museubordalopinheiro.pt/", "venue": "Museu Bordalo Pinheiro", "neighborhood": "Campo Grande"},
    {"name": "Cinemateca Portuguesa", "url": "https://www.cinemateca.pt/programacao.aspx", "venue": "Cinemateca Portuguesa", "neighborhood": "Príncipe Real"},
    {"name": "Teatro do Bairro Alto", "url": "https://teatrodobairroalto.pt/pt/programa?a=1", "venue": "Teatro do Bairro Alto", "neighborhood": "Bairro Alto"},
    {"name": "EGEAC — Agenda Municipal", "url": "https://egeac.pt/programacao-espacos-culturais/", "venue": "", "neighborhood": "Lisboa", "parser": "egeac"},
]

MONTHS = {
    "janeiro": 1, "jan": 1, "january": 1,
    "fevereiro": 2, "fev": 2, "february": 2, "feb": 2,
    "marco": 3, "mar": 3, "march": 3,
    "abril": 4, "abr": 4, "april": 4, "apr": 4,
    "maio": 5, "may": 5,
    "junho": 6, "jun": 6, "june": 6,
    "julho": 7, "jul": 7, "july": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "setembro": 9, "set": 9, "september": 9, "sep": 9,
    "outubro": 10, "out": 10, "october": 10, "oct": 10,
    "novembro": 11, "nov": 11, "november": 11,
    "dezembro": 12, "dez": 12, "december": 12, "dec": 12,
}

CATEGORY_META = {
    "Concerts & Live Music": ("#E63946", "🔴"),
    "Theatre & Comedy": ("#2A9D8F", "🟢"),
    "Exhibitions & Visual Arts": ("#1D3557", "🔵"),
    "Opera & Classical": ("#8338EC", "🟣"),
    "Cinema & Screenings": ("#06D6A0", "🩷"),
    "Nightlife & Electronic": ("#FB5607", "🟠"),
    "Community & Gatherings": ("#FFB703", "🟡"),
    "Family & Youth": ("#118AB2", "🩵"),
}

# Approximate coordinates for common venues. JSON-LD geo coordinates, when
# available, take precedence over these fallbacks.
VENUES = [
    ("centro cultural de belem", "CCB – Centro Cultural de Belém", "Belém", 38.6956, -9.2086),
    ("ccb", "CCB – Centro Cultural de Belém", "Belém", 38.6956, -9.2086),
    ("ze dos bois", "Galeria Zé dos Bois (ZDB)", "Bairro Alto", 38.7122, -9.1444),
    ("zdb", "Galeria Zé dos Bois (ZDB)", "Bairro Alto", 38.7122, -9.1444),
    ("bota", "BOTA (Base Organizada da Toca das Artes)", "Anjos", 38.7247, -9.1345),
    ("maat", "MAAT", "Belém", 38.6959, -9.1938),
    ("gulbenkian", "Fundação Calouste Gulbenkian", "São Sebastião", 38.7371, -9.1542),
    ("culturgest", "Culturgest", "Campo Pequeno", 38.7379, -9.1465),
    ("maria matos", "Teatro Maria Matos", "Alvalade / Roma", 38.7461, -9.1415),
    ("coliseu", "Coliseu dos Recreios", "Baixa / Rossio", 38.7163, -9.1404),
    ("museu de lisboa", "Museu de Lisboa – Palácio Pimenta", "Campo Grande", 38.7584, -9.1557),
    ("bordalo pinheiro", "Museu Bordalo Pinheiro", "Campo Grande", 38.7580, -9.1578),
    ("cinemateca", "Cinemateca Portuguesa", "Príncipe Real", 38.7201, -9.1491),
    ("bairro alto", "Teatro do Bairro Alto", "Bairro Alto", 38.7126, -9.1458),
    ("teatro sao luiz", "Teatro São Luiz", "Chiado", 38.7102, -9.1395),
    ("galeria da boavista", "Galeria da Boavista", "São Paulo / Cais do Sodré", 38.7107, -9.1484),
    ("luca", "LU.CA — Teatro Luís de Camões", "Ajuda", 38.7058, -9.1978),
    ("teatro luis de camoes", "LU.CA — Teatro Luís de Camões", "Ajuda", 38.7058, -9.1978),
    ("teatro romano", "Museu de Lisboa — Teatro Romano", "Sé", 38.7102, -9.1320),
    ("capitolio", "Capitólio", "Parque Mayer", 38.7210, -9.1463),
    ("museu do fado", "Museu do Fado", "Alfama", 38.7121, -9.1272),
    ("galeria quadrum", "Galeria Quadrum", "Campo Grande", 38.7550, -9.1550),
    ("casa fernando pessoa", "Casa Fernando Pessoa", "Campo de Ourique", 38.7188, -9.1663),
    ("teatro variedades", "Teatro Variedades", "Parque Mayer", 38.7207, -9.1468),
    ("teatro meridional", "Teatro Meridional", "Marvila", 38.7430, -9.0992),
    ("teatro nacional d. maria ii", "Teatro Nacional D. Maria II", "Rossio", 38.7135, -9.1393),
    ("d. maria ii", "Teatro Nacional D. Maria II", "Rossio", 38.7135, -9.1393),
    ("castelo de sao jorge", "Castelo de São Jorge", "Castelo", 38.7139, -9.1334),
    ("museu de lisboa - palacio pimenta", "Museu de Lisboa — Palácio Pimenta", "Campo Grande", 38.7584, -9.1557),
    ("museu de lisboa - santo antonio", "Museu de Lisboa — Santo António", "Sé", 38.7108, -9.1322),
    ("meo arena", "MEO Arena", "Parque das Nações", 38.7682, -9.0940),
    ("fabbrica braco de prata", "Fábrica Braço de Prata", "Marvila", 38.7428, -9.0988),
]

FREE_RE = re.compile(r"entrada\s+livre|gratuit[oa]s?|gr[aá]tis|\bfree(?:\s+entry)?\b", re.I)
PRICE_RE = re.compile(r"(?:€\s*\d+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?\s*€|\d+(?:[.,]\d{1,2})?\s*(?:euros?))", re.I)
TIME_RE = re.compile(r"\b(?:às?\s*)?(\d{1,2})\s*(?::|h)(\d{2})\b", re.I)
DATE_RE = re.compile(r"\b(\d{1,2})\s*(?:de\s+)?([a-zA-ZÀ-ÿ]+)(?:\s+(?:de\s+)?(20\d{2}))?\b", re.I)
DATE_GROUP_RE = re.compile(r"\b((?:\d{1,2}\s*(?:,|e|and)\s*)*\d{1,2})\s*(?:de\s+)?([a-zA-ZÀ-ÿ]+)(?:\s*,?\s*(?:de\s+)?(20\d{2}))?\b", re.I)
NUMERIC_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?(?!\d)", re.I)
COMPACT_DATE_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2})(?=\d{1,2}:\d{2})", re.I)
COMPACT_DATE_TIME_FULL_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2})(\d{1,2}):(\d{2})", re.I)
NUMERIC_RANGE_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s*(?:—|–|-| a | to )\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?(?!\d)", re.I)
NAMED_MONTH_RANGE_RE = re.compile(r"\b(\d{1,2})\s*(?:de\s+)?([a-zA-ZÀ-ÿ]{3,12})(?:\s*\([^)]*\))?\s*(?:—|–|-|\ba\b|\bat[eé]\b|\bto\b)\s*(\d{1,2})\s*(?:de\s+)?([a-zA-ZÀ-ÿ]{3,12})(?:\s*\([^)]*\))?(?:\s*(?:de\s*)?(20\d{2}))?\b", re.I)


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def operational_date(now: datetime | None = None) -> date:
    local_now = (now or datetime.now(TZ)).astimezone(TZ)
    if local_now.hour < RESET_HOUR:
        return local_now.date() - timedelta(days=1)
    return local_now.date()


def clean_text(value: Any, limit: int = 600) -> str:
    if not value:
        return ""
    text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def absolute_http_url(url: str, base_url: str) -> str | None:
    if not url:
        return None
    full = urljoin(base_url, url.strip())
    parsed = urlparse(full)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if any(x in parsed.path.lower() for x in ("/wp-login", "/wp-admin", "javascript:")):
        return None
    return full.split("#", 1)[0]


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    except (ValueError, TypeError):
        return None


def category_for(text: str) -> str:
    t = normalize(text)
    if any(k in t for k in ("familia", "familias", "criancas", "infancia", "infantil", "family", "kids")):
        return "Family & Youth"
    if any(k in t for k in ("exposic", "exhibition", "galeria", "museu", "instalacao", "artes visuais", "visual art")):
        return "Exhibitions & Visual Arts"
    if any(k in t for k in ("opera", "orquestra", "musica classica", "classical", "recital", "sinfonica", "symphony")):
        return "Opera & Classical"
    if any(k in t for k in ("cinema", "filme", "film screening", "screening", "doclisboa", "curta-metragem")):
        return "Cinema & Screenings"
    if any(k in t for k in ("teatro", "theatre", "theater", "comedia", "comedy", "stand-up", "stand up", "performance teatral")):
        return "Theatre & Comedy"
    if any(k in t for k in ("dj set", "dj-set", "eletronica", "electronic", "techno", "house music", "rave", "clubbing", "club night")):
        return "Nightlife & Electronic"
    if any(k in t for k in ("comunidade", "encontro", "conversa", "debate", "mercado", "passeio", "walk", "community", "storytelling")):
        return "Community & Gatherings"
    return "Concerts & Live Music"


def infer_place(venue_name: str, source: dict[str, str], geo: Any = None, address: Any = None) -> tuple[str, str, str, float | None, float | None, str]:
    venue = clean_text(venue_name, 160) or source.get("venue", "Lisboa")
    neighborhood = source.get("neighborhood", "Lisboa")
    lat = lng = None
    corridor = "Axial Spine"
    if isinstance(geo, dict):
        try:
            lat = float(geo.get("latitude"))
            lng = float(geo.get("longitude"))
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                lat = lng = None
        except (TypeError, ValueError):
            lat = lng = None
    haystack = normalize(f"{venue} {address or ''} {source.get('venue','')}")
    for key, fallback_venue, fallback_neighborhood, fallback_lat, fallback_lng in sorted(VENUES, key=lambda row: len(row[0]), reverse=True):
        if key in haystack:
            venue = venue or fallback_venue
            neighborhood = fallback_neighborhood
            if lat is None or lng is None:
                lat, lng = fallback_lat, fallback_lng
            break
    if any(x in normalize(f"{venue} {neighborhood}") for x in ("belem", "maat", "ccb")):
        corridor = "Belém Waterfront"
    elif any(x in normalize(f"{venue} {neighborhood}") for x in ("marvila", "parque das nacoes", "oriente", "anjos", "bota")):
        corridor = "Eastern Corridor"
    elif any(x in normalize(f"{venue} {neighborhood}") for x in ("alvalade", "saldanha", "campo grande", "gulbenkian", "sao sebastiao")):
        corridor = "Northern Belt"
    # Try to assign coordinates from the source venue when the event has no venue field.
    if (lat is None or lng is None) and source.get("venue"):
        source_text = normalize(source["venue"])
        for key, fallback_venue, fallback_neighborhood, fallback_lat, fallback_lng in VENUES:
            if key in source_text:
                venue = venue or fallback_venue
                neighborhood = fallback_neighborhood
                lat, lng = fallback_lat, fallback_lng
                break
    if not venue:
        venue = "Local a confirmar"
    return venue, neighborhood, corridor, lat, lng, clean_text(address, 200)


def price_details(value: Any, context: str = "") -> tuple[str, str]:
    raw = clean_text(value, 80)
    combined = f"{raw} {context}"
    if FREE_RE.search(combined):
        if raw and FREE_RE.search(raw):
            return raw, "FREE"
        return "Entrada livre", "FREE"
    match = PRICE_RE.search(raw) or PRICE_RE.search(context)
    if match:
        price = clean_text(match.group(0), 50).replace("euros", "€").replace("euro", "€")
        numeric = re.search(r"\d+(?:[.,]\d{1,2})?", price)
        amount = float(numeric.group(0).replace(",", ".")) if numeric else None
        if amount == 0:
            return "Entrada livre", "FREE"
        if amount is not None and amount < 15:
            tier = "ACCESSIBLE"
        elif amount is not None and amount <= 30:
            tier = "MID"
        elif amount is not None:
            tier = "PREMIUM"
        else:
            tier = "UNKNOWN"
        return price, tier
    return raw or "Consultar", "UNKNOWN"


def parse_times(text: str, start: datetime | None = None) -> tuple[str, int]:
    if start and (start.hour or start.minute):
        return start.strftime("%H:%M"), start.hour
    compact = COMPACT_DATE_TIME_FULL_RE.search(normalize(text or ""))
    if compact:
        hour, minute = int(compact.group(4)), int(compact.group(5))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}", hour
    found = []
    for match in TIME_RE.finditer(text or ""):
        candidate = f"{int(match.group(1)):02d}:{match.group(2)}"
        if candidate not in found:
            found.append(candidate)
        if len(found) == 3:
            break
    if found:
        return " / ".join(found), int(found[0][:2])
    return "Durante o dia", 12


def date_mentioned(text: str, target: date) -> bool:
    normalized = normalize(text)
    if re.search(r"\bhoje\b|\btoday\b", normalized):
        return True
    # Handles single dates and grouped dates such as "28 e 30 outubro" or
    # "8, 15, 22 e 29 outubro", where only the final day is followed by a month.
    for match in DATE_GROUP_RE.finditer(normalized):
        days = [int(n) for n in re.findall(r"\d{1,2}", match.group(1))]
        month_name = normalize(match.group(2)).rstrip(".")
        month = MONTHS.get(month_name) or MONTHS.get(month_name[:3])
        year = int(match.group(3)) if match.group(3) else target.year
        if target.day in days and month == target.month and year == target.year:
            return True
    # Compact dates are common on underground venue calendars; ZDB can concatenate
    # weekday, date and time into a token such as "qua28.10.2621:00".
    for match in COMPACT_DATE_TIME_RE.finditer(normalized):
        day, month, year_raw = int(match.group(1)), int(match.group(2)), match.group(3)
        year = int(year_raw) + 2000
        if day == target.day and month == target.month and year == target.year:
            return True
    # Other numeric dates, e.g. "28.10.2026".
    for match in NUMERIC_DATE_RE.finditer(normalized):
        day, month = int(match.group(1)), int(match.group(2))
        year_raw = match.group(3)
        year = int(year_raw) if year_raw else target.year
        if year < 100:
            year += 2000
        if day == target.day and month == target.month and year == target.year:
            return True
    # Textual date ranges such as "15 Out (Outubro) — 29 Out (Outubro) 2026".
    for match in NAMED_MONTH_RANGE_RE.finditer(normalized):
        start_day, start_month_raw, end_day, end_month_raw, year_raw = match.groups()
        start_month_name = normalize(start_month_raw).rstrip(".")
        end_month_name = normalize(end_month_raw).rstrip(".")
        start_month = MONTHS.get(start_month_name) or MONTHS.get(start_month_name[:3])
        end_month = MONTHS.get(end_month_name) or MONTHS.get(end_month_name[:3])
        if not start_month or not end_month:
            continue
        end_year = int(year_raw) if year_raw else target.year
        start_year = end_year - 1 if start_month > end_month else end_year
        try:
            range_start = date(start_year, start_month, int(start_day))
            range_end = date(end_year, end_month, int(end_day))
        except ValueError:
            continue
        if range_start <= target <= range_end:
            return True
    # Date spans such as "23.05 — 22.11.26" describe exhibitions currently running.
    if any(word in normalized for word in ("exposic", "exhibition", "instalacao", "artes visuais")):
        for match in NUMERIC_RANGE_RE.finditer(normalized):
            sd, sm, sy, ed, em, ey = match.groups()
            start_year = int(sy) if sy else (int(ey) if ey else target.year)
            end_year = int(ey) if ey else start_year
            if start_year < 100: start_year += 2000
            if end_year < 100: end_year += 2000
            if not sy and ey and int(sd) > int(ed) and int(sm) > int(em):
                start_year = end_year - 1
            try:
                range_start = date(start_year, int(sm), int(sd))
                range_end = date(end_year, int(em), int(ed))
            except ValueError:
                continue
            if range_start <= target <= range_end:
                return True
    # Ongoing exhibition cards often show only their end date (e.g. "até 1 novembro").
    if any(word in normalized for word in ("exposic", "exhibition", "instalacao")) and re.search(r"\b(at[eé]|until|permanente|permanent)\b", normalized):
        until_matches = re.findall(r"\b(?:at[eé]|until)\s+(\d{1,2})\s*(?:de\s+)?([a-zA-ZÀ-ÿ]+)(?:\s+(?:de\s+)?(20\d{2}))?", normalized)
        for day_s, month_name, year_s in until_matches:
            month = MONTHS.get(normalize(month_name).rstrip(".")) or MONTHS.get(normalize(month_name)[:3])
            year = int(year_s) if year_s else target.year
            try:
                end_date = date(year, month, int(day_s)) if month else None
            except ValueError:
                end_date = None
            if end_date and end_date >= target:
                return True
        if "permanente" in normalized or "permanent" in normalized:
            return True
    return False


def is_exhibition(text: str, category: str) -> bool:
    return category == "Exhibitions & Visual Arts" or any(word in normalize(text) for word in ("exposic", "exhibition", "instalacao"))


def event_hash(title: str, url: str, target: date) -> str:
    raw = f"{normalize(title)}|{url}|{target.isoformat()}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:10]


def base_record(title: str, url: str, source: dict[str, str], target: date, text: str, venue: str = "", neighborhood: str = "", geo: Any = None, address: Any = None, start: datetime | None = None, end: datetime | None = None, description: str = "", price_raw: Any = "", category_override: str = "") -> dict[str, Any] | None:
    title = clean_text(title, 180)
    full_url = absolute_http_url(url, source["url"])
    if not title or len(title) < 3 or not full_url:
        return None
    category = category_override or category_for(f"{title} {text} {description}")
    ongoing = is_exhibition(f"{title} {text} {description}", category)
    if start:
        start_date = start.date()
        end_date = end.date() if end else start_date
        if ongoing:
            if not (start_date <= target <= end_date):
                # Event cards can represent exhibitions that began earlier with only an end date.
                if not date_mentioned(text, target):
                    return None
        elif start_date != target:
            return None
    elif not date_mentioned(text, target):
        return None
    venue, neighborhood, corridor, lat, lng, parsed_address = infer_place(venue, source, geo, address)
    price, tier = price_details(price_raw, text)
    time_text, hour = parse_times(text, start)
    color, icon = CATEGORY_META[category]
    clean_description = clean_text(description, 300)
    if not clean_description:
        clean_description = "Consulta a página oficial para confirmar horários, local e bilhetes."
    record = {
        "id": event_hash(title, full_url, target), "title": title, "category": category,
        "color": color, "icon": icon, "venue": venue, "neighborhood": neighborhood,
        "corridor": corridor, "lat": lat, "lng": lng, "time": time_text, "hour": hour,
        "price": price, "priceTier": tier, "url": full_url, "description": clean_description,
        "event_date": target.isoformat(), "source": source["name"],
    }
    return record


def iter_jsonld_objects(value: Any):
    if isinstance(value, list):
        for child in value:
            yield from iter_jsonld_objects(child)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if any("event" in str(t).lower() and "venue" not in str(t).lower() for t in types):
            yield value
        # Walk nested graphs and item lists, where calendars commonly place Events.
        for key in ("@graph", "itemListElement", "mainEntity", "item"):
            if key in value:
                yield from iter_jsonld_objects(value[key])


def parse_jsonld_events(soup: BeautifulSoup, source: dict[str, str], target: date) -> list[dict[str, Any]]:
    records = []
    seen = set()
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for obj in iter_jsonld_objects(data):
            status = normalize(obj.get("eventStatus", ""))
            if "cancelled" in status or "canceled" in status:
                continue
            name = clean_text(obj.get("name"), 180)
            start = parse_datetime(obj.get("startDate"))
            end = parse_datetime(obj.get("endDate"))
            if not name or not start:
                continue
            event_url = obj.get("url") or obj.get("@id") or source["url"]
            location = obj.get("location") or {}
            if isinstance(location, list):
                location = location[0] if location else {}
            location_name = location.get("name", "") if isinstance(location, dict) else ""
            address = location.get("address", "") if isinstance(location, dict) else ""
            if isinstance(address, dict):
                address = ", ".join(str(address.get(k, "")) for k in ("streetAddress", "addressLocality", "postalCode") if address.get(k))
            geo = location.get("geo") if isinstance(location, dict) else None
            description = clean_text(obj.get("description", ""), 300)
            category_raw = obj.get("about") or obj.get("genre") or obj.get("keywords") or ""
            if isinstance(category_raw, list):
                category_raw = " ".join(clean_text(x) for x in category_raw)
            category_override = ""
            if isinstance(obj.get("@type"), str) and "exhibit" in obj.get("@type", "").lower():
                category_override = "Exhibitions & Visual Arts"
            offer = obj.get("offers") or {}
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            price_raw = ""
            if isinstance(offer, dict):
                raw_price = offer.get("price")
                if raw_price is not None:
                    currency = offer.get("priceCurrency", "EUR")
                    price_raw = "Entrada livre" if str(raw_price) == "0" else f"{raw_price} €" if currency == "EUR" else f"{raw_price} {currency}"
            text = f"{name} {description} {category_raw}"
            rec = base_record(name, event_url, source, target, text, venue=location_name, address=address, geo=geo, start=start, end=end, description=description, price_raw=price_raw, category_override=category_override)
            if rec:
                dedupe = (normalize(rec["title"]), rec["url"])
                if dedupe not in seen:
                    records.append(rec)
                    seen.add(dedupe)
    return records


def is_candidate_container(tag: Tag) -> bool:
    if tag.name in ("article", "li", "div", "section"):
        return True
    classes = " ".join(tag.get("class", [])).lower()
    return any(k in classes for k in ("event", "evento", "card", "agenda", "program", "listing", "result", "item", "view-row", "views-row"))


def useful_title(anchor: Tag) -> str:
    title = clean_text(anchor.get("aria-label") or anchor.get("title") or anchor.get_text(" ", strip=True), 180)
    bad = {"ver mais", "saber mais", "comprar", "bilhetes", "tickets", "mais info", "read more", "ver evento", "reservar", "eventos"}
    if normalize(title) in bad or len(title) < 4:
        return ""
    if len(title.split()) == 1 and len(title) < 8:
        return ""
    return title



# Venue names shown on EGEAC's multi-venue cultural programme page. These are
# matched against the whole card so events keep their actual venue rather than
# all being pinned to EGEAC's office.
EGEAC_VENUES = [
    "Museu de Lisboa - Palácio Pimenta",
    "Museu de Lisboa - Santo António",
    "Museu de Lisboa - Teatro Romano",
    "Teatro Nacional D. Maria II",
    "LU.CA - Teatro Luís de Camões",
    "Museu Bordalo Pinheiro",
    "Galeria da Boavista",
    "Teatro do Bairro Alto",
    "Teatro São Luiz",
    "Teatro Meridional",
    "Teatro Variedades",
    "Casa Fernando Pessoa",
    "Museu do Fado",
    "Galeria Quadrum",
    "Castelo de São Jorge",
    "Centro Cultural de Belém",
    "Cossoul",
    "Capitólio",
    "Teatro São Carlos",
    "LU.CA",
]
EGEAC_CATEGORY_PREFIX_RE = re.compile(
    r"^(?:m[uú]sica|teatro|dan[cç]a|feira|oficina|percursos|visita orientada|visita guiada|visita|stand\s*up|festa|exposi[cç][aã]o|inaugura[cç][aã]o|apresenta[cç][aã]o(?:\s*/\s*lan[cç]amento)?|debate/conversa/confer[eê]ncia|cinema)\s+",
    re.I,
)
EGEAC_DATE_TEXT_RE = re.compile(
    r"\b\d{1,2}\s+(?:de\s+)?(?:janeiro|jan|fevereiro|fev|mar[cç]o|mar|abril|abr|maio|may|junho|jun|julho|jul|agosto|ago|setembro|set|outubro|out|novembro|nov|dezembro|dez)"
    r"(?:\s*\([^)]*\))?(?:\s*(?:—|–|-)\s*\d{1,2}\s+(?:de\s+)?(?:janeiro|jan|fevereiro|fev|mar[cç]o|mar|abril|abr|maio|may|junho|jun|julho|jul|agosto|ago|setembro|set|outubro|out|novembro|nov|dezembro|dez)(?:\s*\([^)]*\))?)?"
    r"(?:\s*(?:de\s*)?20\d{2})?\b",
    re.I,
)

def egeac_metadata(container_text: str, anchor_text: str, target: date) -> tuple[str, str]:
    """Extract a useful event title and its venue from an EGEAC calendar card."""
    venue = ""
    normalized_container = normalize(container_text)
    # Longest-first prevents 'Museu de Lisboa' swallowing a more specific site.
    for candidate_venue in sorted(EGEAC_VENUES, key=len, reverse=True):
        if normalize(candidate_venue) in normalized_container:
            venue = candidate_venue
            break

    candidate = clean_text(anchor_text, 500) or clean_text(container_text, 500)
    # Some EGEAC cards wrap title, date and venue in one anchor; others link only
    # the title. In the latter case keep the short anchor as-is.
    candidate_normalized = normalize(candidate)
    contains_metadata = bool(EGEAC_DATE_TEXT_RE.search(candidate)) or (venue and normalize(venue) in candidate_normalized)
    if not contains_metadata:
        candidate = clean_text(anchor_text, 500) or clean_text(container_text, 500)
    else:
        for known_venue in EGEAC_VENUES:
            candidate = re.sub(re.escape(known_venue), " ", candidate, flags=re.I)
        candidate = EGEAC_DATE_TEXT_RE.sub(" ", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip(" -–—|,;:·")
        candidate = EGEAC_CATEGORY_PREFIX_RE.sub("", candidate).strip(" -–—|,;:·")

    if len(candidate) > 180:
        candidate = candidate[:180].rsplit(" ", 1)[0]
    return candidate, venue


def card_description(container: Tag, title: str, target: date) -> str:
    candidates = []
    selectors = (
        "p", "[class*=description]", "[class*=excerpt]", "[class*=summary]",
        "[class*=teaser]", "[class*=intro]",
    )
    title_norm = normalize(title)
    controls = ("exibir evento", "ver evento", "saber mais", "exibir mais", "google agenda", "comprar", "bilhetes", "tickets")
    for node in container.select(",".join(selectors)):
        text = clean_text(node.get_text(" ", strip=True), 450)
        normalized = normalize(text)
        if len(text) < 35 or normalized == title_norm or any(word in normalized for word in controls):
            continue
        if date_mentioned(text, target) and len(text) < 80:
            continue
        if TIME_RE.search(text) and len(text) < 55:
            continue
        if text not in candidates:
            candidates.append(text)
    return max(candidates, key=len, default="")

def parse_card_events(soup: BeautifulSoup, source: dict[str, str], target: date) -> list[dict[str, Any]]:
    records = []
    seen = set()
    # The event pages use a mix of WordPress and custom card structures; choose
    # the smallest date-stamped event/card/article/list item around each title link.
    for container in soup.find_all(is_candidate_container):
        text = clean_text(container.get_text(" ", strip=True), 1200)
        if len(text) < 20 or len(text) > 650 or not date_mentioned(text, target):
            continue
        anchors = container.find_all("a", href=True)
        if not anchors or len(anchors) > 12:
            continue
        candidates = sorted(((len(useful_title(a)), a) for a in anchors), key=lambda pair: pair[0], reverse=True)
        picked = None
        for score, anchor in candidates:
            if score >= 4:
                picked = anchor
                break
        if not picked:
            continue
        title = useful_title(picked)
        card_venue = source.get("venue", "")
        if source.get("parser") == "egeac":
            title, card_venue = egeac_metadata(text, clean_text(picked.get("aria-label") or picked.get("title") or picked.get_text(" ", strip=True), 500), target)
            if not title or not card_venue:
                continue
        url = absolute_http_url(picked.get("href", ""), source["url"])
        if not url or url.rstrip("/") == source["url"].rstrip("/"):
            continue
        # Avoid generic page-navigation destinations and file links.
        path = urlparse(url).path.lower()
        if path.endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp", ".svg")):
            continue
        category = category_for(f"{title} {text}")
        description = card_description(container, title, target)
        record = base_record(title, url, source, target, text, venue=card_venue, neighborhood=source.get("neighborhood", "Lisboa"), description=description, price_raw="", category_override=category)
        if not record:
            continue
        dedupe = (normalize(record["title"]), record["url"])
        if dedupe not in seen:
            records.append(record)
            seen.add(dedupe)
    return records


def scrape_source(session: requests.Session, source: dict[str, str], target: date) -> tuple[int, list[dict[str, Any]], str]:
    try:
        response = session.get(source["url"], timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        if not response.encoding or response.encoding.lower() in ("iso-8859-1", "ascii"):
            response.encoding = response.apparent_encoding or "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        jsonld = parse_jsonld_events(soup, source, target)
        cards = parse_card_events(soup, source, target)
        combined = {}
        for event in jsonld + cards:
            combined[(normalize(event["title"]), event["url"])] = event
        return 1, list(combined.values()), f"OK HTTP 200 ({len(jsonld)} JSON-LD, {len(cards)} eventos reconhecidos nos cartões, {len(combined)} únicos; zero pode significar sem evento hoje ou seletor desatualizado)"
    except Exception as exc:  # Keep a single broken source from stopping the remaining sources.
        return 0, [], f"ERRO: {type(exc).__name__}: {str(exc)[:180]}"


def main() -> int:
    now = datetime.now(TZ)
    target = operational_date(now)
    print(f"Keks Passa — data operacional: {target.isoformat()} (Europe/Lisbon, dia começa às {RESET_HOUR:02d}:00)")
    session = requests.Session()
    all_events: dict[tuple[str, str], dict[str, Any]] = {}
    successful_sources = 0
    for source in SOURCES:
        success, events, status = scrape_source(session, source, target)
        successful_sources += success
        print(f"[{source['name']}] {status}")
        for event in events:
            key = (normalize(event["title"]), event["url"])
            all_events[key] = event
        time.sleep(0.35)
    if successful_sources == 0:
        print("ERRO: nenhuma fonte respondeu; events.json não foi alterado.", file=sys.stderr)
        return 1
    events = sorted(all_events.values(), key=lambda e: (int(e.get("hour", 12)), normalize(e.get("title"))))
    # Fail closed if our page parsers stop recognizing events; never publish a blank agenda by accident.
    if not events:
        print("ERRO: as fontes responderam, mas não foi possível identificar eventos para esta data. events.json não foi alterado.", file=sys.stderr)
        print("Sugestão: abrir os logs por fonte e ajustar os seletores ou a lista SOURCES.", file=sys.stderr)
        return 2
    generated = datetime.now(TZ)
    weekday = generated.strftime("%A")
    # Produce an explicit Portuguese date for the site; JS has a fallback if this is absent.
    date_string = generated.strftime("%d/%m/%Y")
    try:
        date_string = __import__("babel.dates", fromlist=["format_date"]).format_date(target, format="EEEE, d 'de' MMMM", locale="pt_PT")
    except Exception:
        weekdays = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
        months = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
        date_string = f"{weekdays[target.weekday()]}, {target.day} de {months[target.month-1]}"
    payload = {
        "date": target.isoformat(),
        "date_string": date_string,
        "timezone": "Europe/Lisbon",
        "reset_hour": RESET_HOUR,
        "generated_at": generated.isoformat(timespec="seconds"),
        "event_count": len(events),
        "events": events,
    }
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUTPUT)
    print(f"OK: gravados {len(events)} eventos em {OUTPUT.name} para {target.isoformat()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
