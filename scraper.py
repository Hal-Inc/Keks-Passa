#!/usr/bin/env python3
"""
Keks Passa — Daily Lisbon Cultural & Nightlife Scraper (v3.0 Precision Pipeline)
Deep-dive verified multi-tier pipeline for Lisbon Municipality:
1. AgendaLX (agendalx.pt homepage + detail page date/weekday/schedule/price parser)
2. Cartaz Cultural Lisboa (cartazculturallisboa.pt + JSON-LD Event & overnight party filter)
3. NoCartaz Lisboa (concelhos/lisboa + hoje + distrito/lisboa with strict date & concelho verification)
4. Cinemateca Portuguesa & Cinema Medeia Nimas
5. Agenda de Concertos Lisboa & BOTA Anjos Programação (detail-page verified)
6. Prior Velho, Lisabout & Electronic Hubs (lisabout.com/events + moonclub.pt + RA GraphQL)
7. Arts & Crafts, Markets, Workshops & Lectures (Eventbrite Lisboa + FICA + Jardins do Bombarda)
8. ViralAgenda Dynamic Daily Scraper (strictly filtered to Lisbon municipality + detail enrichment)
9. Soko.fyi, THE CURATED Lisbon & Cápsula Melódica (with stale BOL/Ticketline & T00:00 filtering)
10. Civic, Health & Community Tiers (Dador.pt Lisboa, JF Santo António, Kosmicare, Menina e Moça, Volunteering)
"""

import os
import re
import sys
import json
import math
import datetime
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def get_lisbon_now():
    """Returns current datetime in Europe/Lisbon timezone, with robust fallback if tzdata is missing."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Europe/Lisbon"))
    except Exception:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        year = now_utc.year
        d_mar = datetime.datetime(year, 3, 31, 1, 0, tzinfo=datetime.timezone.utc)
        mar_last_sun = d_mar - datetime.timedelta(days=(d_mar.weekday() + 1) % 7)
        d_oct = datetime.datetime(year, 10, 31, 1, 0, tzinfo=datetime.timezone.utc)
        oct_last_sun = d_oct - datetime.timedelta(days=(d_oct.weekday() + 1) % 7)
        is_dst = mar_last_sun <= now_utc < oct_last_sun
        tz = datetime.timezone(datetime.timedelta(hours=1 if is_dst else 0))
        return now_utc.astimezone(tz)


import locations
import requests
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# Use curl_cffi for Chrome TLS fingerprint impersonation
try:
    from curl_cffi import requests as cffi_requests
    SCRAPER_SESSION = cffi_requests.Session(impersonate="chrome120")
except ImportError:
    try:
        import cloudscraper
        SCRAPER_SESSION = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
    except ImportError:
        SCRAPER_SESSION = requests.Session()

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

CATEGORY_PRESETS = {
    "concerts": {"category": "Concerts & Live Music", "color": "#E63946", "icon": "🎤"},
    "theatre": {"category": "Theatre & Comedy", "color": "#2A9D8F", "icon": "🎭"},
    "exhibitions": {"category": "Exhibitions & Visual Arts", "color": "#1D3557", "icon": "🎨"},
    "classical": {"category": "Opera & Classical", "color": "#8338EC", "icon": "🎻"},
    "cinema": {"category": "Cinema & Screenings", "color": "#06D6A0", "icon": "🍿"},
    "nightlife": {"category": "Nightlife & Electronic", "color": "#FB5607", "icon": "🔊"},
    "community": {"category": "Community & Gatherings", "color": "#FFB703", "icon": "🛍️"},
    "family": {"category": "Family & Youth", "color": "#118AB2", "icon": "🎠"},
    "blood": {"category": "Blood Donation", "color": "#E63946", "icon": "🩸"},
}

PT_MONTHS_SHORT = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"
}
PT_MONTHS_FULL = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
}
PT_MONTH_LOOKUP = {
    "jan": 1, "janeiro": 1,
    "fev": 2, "fevereiro": 2,
    "mar": 3, "marco": 3, "março": 3,
    "abr": 4, "abril": 4,
    "mai": 5, "maio": 5,
    "jun": 6, "junho": 6,
    "jul": 7, "julho": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9,
    "out": 10, "outubro": 10,
    "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12,
}

# Short/ambiguous tokens that must never be matched as standalone venue aliases
AMBIGUOUS_ALIAS_TOKENS = {
    "nada", "nāda", "naada", "rca", "lav", "bota", "lux", "fil",
    "alvalade", "alcantara", "alcântara", "campolide", "campo pequeno",
    "campo grande", "principe real", "arroios", "anjos", "marvila", "beato",
    "imprensa nacional",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENUES_JSON_PATH = os.path.join(SCRIPT_DIR, "venues.json")

# ==============================================================================
# VENUE REGISTRY (Loaded from canonical venues.json)
# ==============================================================================
VENUE_REGISTRY = []


def fix_mojibake(text):
    """Repairs UTF-8 bytes misdecoded as Latin-1/CP1252 (e.g. 'â€”' -> '—', 'KÃ¸mplex' -> 'Kømplex')."""
    if not text:
        return ""
    s = str(text)
    if any(marker in s for marker in ("Ã", "â€", "ðŸ")):
        for enc in ("cp1252", "latin-1"):
            try:
                s = s.encode(enc).decode("utf-8")
                break
            except Exception:
                pass
    return s


def clean_html_text(text):
    """Strips stray HTML tags, normalizes mathematical bold/italic symbols, and collapses whitespace."""
    if not text:
        return ""
    s = fix_mojibake(text)
    # Normalize mathematical bold/italic characters (e.g. '𝟕€' -> '7€') while keeping standard accents
    out_chars = []
    for ch in s:
        if ord(ch) > 0x1D400:
            out_chars.append(unicodedata.normalize("NFKD", ch))
        else:
            out_chars.append(ch)
    s = "".join(out_chars)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_accents(text):
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn").lower()


_VENUE_PATTERNS: list = []


def _build_venue_patterns() -> None:
    """Compile every venue alias into a regex once, sorted longest-alias-first."""
    _VENUE_PATTERNS.clear()
    rows = []
    for entry in VENUE_REGISTRY:
        candidates = [entry["venue"]] + list(entry.get("aliases", []))
        for cand in candidates:
            c_norm = strip_accents(cand).strip()
            if not c_norm or len(c_norm) < 3 or c_norm in AMBIGUOUS_ALIAS_TOKENS:
                continue
            pat = re.compile(rf"(?<![a-z0-9]){re.escape(c_norm)}(?![a-z0-9])")
            rows.append((pat, entry, len(c_norm)))
    rows.sort(key=lambda r: r[2], reverse=True)
    _VENUE_PATTERNS.extend(rows)


def load_external_venues():
    """Loads canonical Lisbon venues from venues.json."""
    if os.path.exists(VENUES_JSON_PATH):
        try:
            with open(VENUES_JSON_PATH, "r", encoding="utf-8") as f:
                ext = json.load(f)
            if isinstance(ext, list) and len(ext) >= 20:
                cleaned_list = []
                for item in ext:
                    if isinstance(item, dict) and item.get("venue"):
                        clean_aliases = [
                            a for a in item.get("aliases", [])
                            if strip_accents(a).strip() not in AMBIGUOUS_ALIAS_TOKENS
                        ]
                        item["aliases"] = clean_aliases
                        cleaned_list.append(item)
                VENUE_REGISTRY.clear()
                VENUE_REGISTRY.extend(cleaned_list)
        except Exception as e:
            print(f"[Venue Loader] Notice reading venues.json: {e}")
    _build_venue_patterns()


load_external_venues()


def match_venue(*texts, require_match=False):
    """
    Matches venue by checking each text argument in priority order (e.g., venue_candidate first,
    then address, then title), requiring strict word boundaries and preferring the longest
    matching alias so short tokens never hijack unrelated events.
    """
    for raw_t in texts:
        if not raw_t:
            continue
        norm_t = strip_accents(fix_mojibake(raw_t))
        if not norm_t:
            continue
        # Prevent 'maat saxophone quartet' from matching MAAT museum
        norm_t_clean = re.sub(r"\bmaat\s+saxophone\b", "saxophone", norm_t)
        for pat, entry, _alias_len in _VENUE_PATTERNS:
            if pat.search(norm_t_clean):
                return entry
    return None


# ==============================================================================
# VENUE-ACCURATE DEFAULT PRICING & OPENING HOURS
# ==============================================================================
FREE_VENUES_NORM = {
    "feira da ladra", "mercado de santa clara", "jardim da estrela",
    "jardim do principe real", "8 marvila", "lx factory", "underdogs gallery",
    "appleton", "hangar", "biblioteca palacio galveias", "forum picoas",
    "galeria quadrum", "cordoaria nacional", "galeria francisco fino",
    "jardins do bombarda", "casa do comum", "livraria da travessa",
    "well read", "broteria", "casa do alentejo", "fnac", "estufa fria",
    "basilica da estrela", "miradouro da penha", "largo da graca",
    "jardim do torel", "praca da alegria", "jardim do arco do cego",
    "imprensa nacional", "mercado 31 de janeiro", "mercado de alvalade",
    "galeria monumental", "galeria novo banco", "ciul", "fab lab lisboa",
    "arquivo municipal", "emaus", "bus paragem cultural", "biblioteca municipal camoes",
    "biblioteca camoes",
}

VENUE_PRICE_TABLE = {
    "cinemateca portuguesa": ("3.20€", "ACCESSIBLE"),
    "cinema medeia nimas": ("7.50€", "ACCESSIBLE"),
    "cinema medeia monumental": ("7.50€", "ACCESSIBLE"),
    "cinema ideal": ("7.50€", "ACCESSIBLE"),
    "cinema sao jorge": ("6.00€", "ACCESSIBLE"),
    "cinema city classic alvalade": ("7.50€", "ACCESSIBLE"),
    "maat": ("11.00€", "ACCESSIBLE"),
    "cam - centro de arte moderna": ("10.00€", "ACCESSIBLE"),
    "mude": ("11.00€", "ACCESSIBLE"),
    "mnac": ("10.00€", "ACCESSIBLE"),
    "museu nacional de arte antiga": ("10.00€", "ACCESSIBLE"),
    "museu nacional dos coches": ("8.00€", "ACCESSIBLE"),
    "museu do oriente": ("8.00€", "ACCESSIBLE"),
    "museu da marioneta": ("5.00€", "ACCESSIBLE"),
    "museu da farmacia": ("6.00€", "ACCESSIBLE"),
    "museu do fado": ("5.00€", "ACCESSIBLE"),
    "museu bordalo pinheiro": ("3.00€", "ACCESSIBLE"),
    "museu de lisboa": ("3.00€", "ACCESSIBLE"),
    "museu nacional de etnologia": ("5.00€", "ACCESSIBLE"),
    "anastacio goncalves": ("5.00€", "ACCESSIBLE"),
    "casa fernando pessoa": ("6.00€", "ACCESSIBLE"),
    "fundacao jose saramago": ("4.00€", "ACCESSIBLE"),
    "arpad szenes": ("6.00€", "ACCESSIBLE"),
    "muhnac": ("6.00€", "ACCESSIBLE"),
    "padrao dos descobrimentos": ("6.00€", "ACCESSIBLE"),
    "panteao nacional": ("10.00€", "ACCESSIBLE"),
    "castelo de sao jorge": ("15.00€", "ACCESSIBLE"),
    "pavilhao do conhecimento": ("11€ - 15€", "ACCESSIBLE"),
    "oceanario de lisboa": ("15€ - 25€", "MID"),
    "jardim zoologico": ("18€ - 27€", "MID"),
    "museu banksy": ("12.00€", "ACCESSIBLE"),
    "reservatorio da patriarcal": ("4.00€", "ACCESSIBLE"),
    "bota - base organizada": ("8€ - 10€", "ACCESSIBLE"),
    "casa independente": ("5€ - 10€", "ACCESSIBLE"),
    "damas bar": ("5€ - 8€", "ACCESSIBLE"),
    "sirigaita": ("3€ - 5€", "ACCESSIBLE"),
    "associacao cultural desterro": ("5€ - 8€", "ACCESSIBLE"),
    "fabrica braco de prata": ("6€ - 10€", "ACCESSIBLE"),
    "hot clube de portugal": ("10.00€", "ACCESSIBLE"),
    "tavola jazz club": ("8.00€", "ACCESSIBLE"),
    "tokyo lisboa": ("6€ - 10€", "ACCESSIBLE"),
    "musicbox": ("10€ - 15€", "ACCESSIBLE"),
    "b.leza": ("10€ - 15€", "ACCESSIBLE"),
    "titanic sur mer": ("8€ - 15€", "ACCESSIBLE"),
    "lisboa rio": ("8€ - 15€", "ACCESSIBLE"),
    "badassery": ("10€ - 20€", "MID"),
    "incognito": ("8.00€", "ACCESSIBLE"),
    "lux fragil": ("15€ - 25€", "MID"),
    "ministerium club": ("15.00€", "ACCESSIBLE"),
    "komplex lisbon": ("10€ - 18€", "ACCESSIBLE"),
    "kømplex lisbon": ("10€ - 18€", "ACCESSIBLE"),
    "nada 3.0": ("12€ - 20€", "MID"),
    "nāda 3.0": ("12€ - 20€", "MID"),
    "moon club": ("10€ - 18€", "ACCESSIBLE"),
    "village underground": ("10€ - 18€", "ACCESSIBLE"),
    "trumps club": ("12€ - 15€", "ACCESSIBLE"),
    "rca club": ("12€ - 18€", "MID"),
    "republica da musica": ("15€ - 22€", "MID"),
    "lav - lisboa ao vivo": ("20€ - 30€", "MID"),
    "coliseu dos recreios": ("20€ - 35€", "MID"),
    "sagres campo pequeno": ("25€ - 45€", "PREMIUM"),
    "meo arena": ("30€ - 65€", "PREMIUM"),
    "teatro nacional d. maria ii": ("12€ - 16€", "ACCESSIBLE"),
    "sao luiz teatro municipal": ("12€ - 15€", "ACCESSIBLE"),
    "teatro nacional de sao carlos": ("15€ - 30€", "MID"),
    "teatro do bairro alto": ("12.00€", "ACCESSIBLE"),
    "teatro da trindade": ("14€ - 20€", "MID"),
    "teatro maria matos": ("18€ - 22€", "MID"),
    "teatro tivoli bbva": ("18€ - 30€", "MID"),
    "teatro villaret": ("16€ - 20€", "MID"),
    "teatro politeama": ("15€ - 30€", "MID"),
    "teatro da comuna": ("12€ - 15€", "ACCESSIBLE"),
    "teatro meridional": ("12.00€", "ACCESSIBLE"),
    "teatro cinearte": ("15€ - 22€", "MID"),
    "lu.ca": ("3€ - 7€", "ACCESSIBLE"),
    "sociedade guilherme cossoul": ("8€ - 10€", "ACCESSIBLE"),
    "casa capitao": ("8€ - 15€", "ACCESSIBLE"),
    "arroz estudios": ("5€ - 10€", "ACCESSIBLE"),
    "musa de marvila": ("Entrada Livre", "FREE"),
    "chiado comedy club": ("8€ - 12€", "ACCESSIBLE"),
    "cineteatro capitolio": ("15€ - 25€", "MID"),
    "teatro variedades": ("12€ - 18€", "MID"),
}


def resolve_venue_default_price(venue_name, category_name=""):
    """Returns realistic venue-specific admission price & tier when event page omits explicit price."""
    v_norm = strip_accents(venue_name or "")
    cat_low = (category_name or "").lower()

    if "zdb" in v_norm or "ze dos bois" in v_norm:
        if "exhibition" in cat_low:
            return "Entrada Livre", "FREE"
        return "8€ - 12€", "ACCESSIBLE"

    if "culturgest" in v_norm:
        if "exhibition" in cat_low:
            return "5.00€", "ACCESSIBLE"
        return "12€ - 16€", "ACCESSIBLE"

    if "centro cultural de belem" in v_norm or v_norm == "ccb":
        if "exhibition" in cat_low:
            return "10.00€", "ACCESSIBLE"
        if "community" in cat_low:
            return "Entrada Livre", "FREE"
        return "15€ - 25€", "MID"

    for k in FREE_VENUES_NORM:
        if k in v_norm:
            return "Entrada Livre", "FREE"

    for k, (p_str, p_tier) in VENUE_PRICE_TABLE.items():
        if k in v_norm:
            return p_str, p_tier

    if "exhibition" in cat_low:
        return "Entrada Livre / Bilheteira", "ACCESSIBLE"
    if "nightlife" in cat_low:
        return "10€ - 15€", "ACCESSIBLE"
    if "cinema" in cat_low:
        return "6€ - 7.50€", "ACCESSIBLE"
    return "Consultar bilheteira", "ACCESSIBLE"


def resolve_venue_default_hours(venue_name, category_name="", weekday=5):
    """Returns realistic default start time for a venue/category when a listing has no explicit hour."""
    v_norm = strip_accents(venue_name or "")
    cat = category_name or ""

    if "feira da ladra" in v_norm:
        return "09:00", 9
    if "principe real" in v_norm or "mercado 31 de janeiro" in v_norm or "mercado de alvalade" in v_norm:
        return "09:30", 9
    if "castelo de sao jorge" in v_norm:
        return "09:00", 9
    if "8 marvila" in v_norm:
        return "12:00", 12
    if "lx factory" in v_norm:
        return "10:30", 10
    if "underdogs" in v_norm or "appleton" in v_norm or "anjos70" in v_norm:
        return "14:00", 14
    if "hangar" in v_norm or "contraprova" in v_norm:
        return "15:00", 15
    if ("zdb" in v_norm or "ze dos bois" in v_norm) and cat == "Exhibitions & Visual Arts":
        return "18:00", 18
    if "culturgest" in v_norm and cat == "Exhibitions & Visual Arts":
        return "11:00", 11

    if cat == "Exhibitions & Visual Arts":
        return "10:00", 10
    if cat == "Family & Youth":
        if "lu.ca" in v_norm or "marioneta" in v_norm or "comuna" in v_norm:
            return "11:00" if weekday in (5, 6) else "10:30", 11 if weekday in (5, 6) else 10
        return "10:00", 10
    if cat == "Community & Gatherings":
        if any(k in v_norm for k in ["jardim", "mercado", "feira", "santa clara", "estrela"]):
            return "10:00", 10
        return "16:00", 16
    if cat == "Theatre & Comedy":
        if weekday == 6:
            return "17:00", 17
        return "21:00", 21
    if cat == "Nightlife & Electronic":
        return "23:59", 23
    return "21:30", 21


def infer_category_preset(text, default_key="concerts"):
    low = strip_accents(text or "")
    # 1. Family, Aquariums, Science Centers & Youth (only explicit family/children phrases)
    if any(k in low for k in [
        "para criancas", "para familias", "em familia", "oficina infantil", "infantil", "para bebes",
        "sabados em familia", "filminhos", "kids", "oceanario", "aquario", "zoologico",
        "zoo de lisboa", "pavilhao do conhecimento", "ciencia viva", "planetario", "lu.ca", "marioneta"
    ]):
        return CATEGORY_PRESETS["family"]
    # 2. Cinema & Film Festivals
    if any(k in low for k in ["cinema", "filme", "documentario", "curtas", "cinemateca", "nimas", "projecao", "leffest"]):
        return CATEGORY_PRESETS["cinema"]
    # 3. Markets, Arts & Crafts, Workshops, Lectures & Community Gatherings
    if any(k in low for k in [
        "conferencia", "palestra", "debate", "conversa", "coloquio", "seminario",
        "feira", "mercado", "flea market", "literatura", "alfarrabistas", "clube de leitura",
        "lancamento", "visita guiada", "visita orientada", "percurso", "comunidade", "workshop", "tertulia", "artesanato",
        "ceramica", "olaria", "serigrafia", "risografia", "bordado", "costura", "encadernacao",
        "marcenaria", "ilustracao", "zine", "fanzine", "gravura", "crafts"
    ]):
        return CATEGORY_PRESETS["community"]
    # 4. Exhibitions, Museums & Visual Arts
    if any(k in low for k in [
        "exposicao", "artes plasticas", "fotografia", "instalacao", "arte moderna",
        "artes visuais", "cartoon", "galeria", "museu", "panteao", "castelo de sao jorge",
        "padrao dos descobrimentos", "maat", "mude", "mnac", "mnaa", "cam gulbenkian"
    ]):
        return CATEGORY_PRESETS["exhibitions"]
    # 5. Theatre, Performance, Dance & Comedy
    if any(k in low for k in [
        "teatro", "danca", "comedia", "stand-up", "stand up", "circo",
        "improviso", "musical", "performance", "cabaret", "burlesque", "encenacao"
    ]):
        return CATEGORY_PRESETS["theatre"]
    # 6. Opera & Classical
    if any(k in low for k in ["opera", "sinfoni", "orquestra", "camerata", "recital", "coral", "coro", "barroco", "filarmonica"]):
        return CATEGORY_PRESETS["classical"]
    # 7. Nightlife & Electronic
    if any(k in low for k in ["dj", "clubbing", "eletronica", "electronic", "noite", "festa", "rave", "techno", "house", "afterhours", "halloween party", "pub crawl", "club"]):
        return CATEGORY_PRESETS["nightlife"]
    return CATEGORY_PRESETS.get(default_key, CATEGORY_PRESETS["concerts"])


def parse_time_str(text, default_time="21:00"):
    if not text:
        h = int(default_time.split(":")[0])
        return default_time, h
    # Look for explicit HH:MM or HHhMM (avoid matching dates like 07.11 or prices like 15.00€)
    for m in re.finditer(r"\b([01]?\d|2[0-3])\s*([:h])\s*([0-5]\d)\b(?!\s*€)", str(text), re.I):
        hh = int(m.group(1))
        mm = int(m.group(3))
        return f"{hh:02d}:{mm:02d}", hh
    m2 = re.search(r"\b([01]?\d|2[0-3])\s*h\b", str(text), re.I)
    if m2:
        hh = int(m2.group(1))
        return f"{hh:02d}:00", hh
    h_def = int(default_time.split(":")[0])
    return default_time, h_def


def infer_end_time(start_time, hour_int, category_name, venue_name="", title="", desc=""):
    parts = (start_time or "21:00").split(":")
    sh = int(parts[0]) if parts else hour_int
    sm = int(parts[1]) if len(parts) > 1 else 0

    combined = f"{title or ''} {desc or ''}"
    m_range = re.search(
        r"\b([01]?\d|2[0-3])(?:[:h.][0-5]\d|\s*h)?\s*(?:–|—|-|às|as|to|até)\s*([01]?\d|2[0-3])(?:[:h.]([0-5]\d)|\s*h)\b",
        combined,
        re.I,
    )
    if m_range:
        sh_range = int(m_range.group(1))
        eh = int(m_range.group(2))
        em = int(m_range.group(3) or 0)
        if sh_range == sh and (eh != sh or em > sm):
            return f"{eh:02d}:{em:02d}", eh

    def add_minutes(h, m, delta):
        total = (h * 60 + m + delta) % (24 * 60)
        return f"{total // 60:02d}:{total % 60:02d}", (total // 60)

    v_low = strip_accents(venue_name or "")
    t_low = strip_accents(title or "")

    if category_name == "Exhibitions & Visual Arts":
        if "zdb" in v_low or "ze dos bois" in v_low:
            return "22:00", 22
        if sh < 17:
            if any(k in v_low for k in ["ccb", "maat", "underdogs", "oriente", "mude", "culturgest", "farmacia"]):
                return "19:00", 19
            return "18:00", 18
        if sh == 18:
            return "20:30", 20
        return add_minutes(sh, sm, 120)

    if category_name == "Family & Youth":
        if "oceanario" in v_low:
            return "19:00", 19
        if "pavilhao do conhecimento" in v_low or "zoo" in v_low:
            return "18:00", 18
        if any(k in t_low for k in ["infancia", "escolar", "ciclo", "familias", "oficinas"]):
            return ("17:30", 17) if sh <= 11 else add_minutes(sh, sm, 120)
        return add_minutes(sh, sm, 90)

    if category_name in ("Cinema & Screenings", "Theatre & Comedy", "Opera & Classical"):
        return add_minutes(sh, sm, 120)

    if category_name == "Concerts & Live Music":
        return add_minutes(sh, sm, 135)

    if category_name == "Community & Gatherings":
        if "8 marvila" in v_low or "lx factory" in v_low:
            return "20:00", 20
        if ("feira da ladra" in v_low or "mercado" in t_low or "feira" in t_low) and sh < 16:
            return "17:00", 17
        if sh <= 10:
            return "18:00", 18
        return add_minutes(sh, sm, 150)

    if category_name == "Nightlife & Electronic":
        if 4 <= sh <= 8:
            return "12:00", 12
        if 12 <= sh < 17:
            return "23:00", 23
        if 17 <= sh < 21:
            return "02:00", 2
        if "moon club" in v_low:
            return "08:00", 8
        return "06:00", 6

    return add_minutes(sh, sm, 120)


def parse_price_and_tier(text, default_price="Consultar bilheteira", default_tier="ACCESSIBLE", venue_name="", category_name=""):
    cleaned = clean_html_text(text or "")
    low = strip_accents(cleaned)
    # 0. Check for compensated / paid participant opportunities
    if re.search(r"\b(compensacao|remunerad|carcanol|vales de compras|pago ao participante)\b", low):
        return cleaned if len(cleaned) < 40 else "Compensação ao participante", "PAID_OPP"

    # 1. Check explicit price ranges (e.g., "10€ a 25€" or "12 € - 18 €")
    m_range = re.search(r"\b(\d{1,3})(?:[.,]\d{1,2})?\s*€?\s*(?:-|–|a)\s*(\d{1,3})(?:[.,]\d{1,2})?\s*€", cleaned, re.I)
    if m_range:
        v1, v2 = int(m_range.group(1)), int(m_range.group(2))
        if 0 < v1 <= v2 <= 250:
            disp = f"{v1}€ - {v2}€" if v1 != v2 else f"{v1}€"
            mid_v = (v1 + v2) / 2.0
            tier = "ACCESSIBLE" if mid_v <= 15 else ("MID" if mid_v <= 30 else "PREMIUM")
            return disp, tier

    # 2. Check explicit single price amounts (€...)
    for m in re.finditer(r"(?:€\s*(\d{1,3})(?:[.,](\d{1,2}))?|(\d{1,3})(?:[.,](\d{1,2}))?\s*€)", cleaned):
        whole = m.group(1) if m.group(1) is not None else m.group(3)
        dec = m.group(2) if m.group(1) is not None else m.group(4)
        val = float(f"{whole}.{dec or '0'}")
        disp = f"{whole}€" if not dec or dec == "00" else f"{whole}.{dec}€"
        if 0 < val <= 300:
            if val <= 15:
                return disp, "ACCESSIBLE"
            if val <= 30:
                return disp, "MID"
            return disp, "PREMIUM"

    # 3. Genuine free entry
    if re.search(r"\b(entrada livre|entrada gratuita|evento gratuito|acesso gratuito|acesso livre|free entry|free admission|free entrance|a borla)\b", low):
        if not re.search(r"\b(birthday|aniversari|drink|beer|imperial|ate as|until|consumo|quota|socio|crianca|menor|ate aos|acompanhante)\b", low):
            return "Entrada Livre", "FREE"

    # 4. Venue-specific accurate fallback if no explicit price was found in text
    if venue_name:
        return resolve_venue_default_price(venue_name, category_name)

    return default_price, default_tier


def _is_overnight_nightlife_text(text):
    low = strip_accents(text or "")
    if any(w in low for w in ["club", "dj", "techno", "house", "rave", "party", "festa", "noite", "cabaret", "burlesque", "discoteca", "afterhours", "trumps", "lux", "ministerium", "komplex", "musicbox", "incognito", "titanic", "b.leza", "tokyo"]):
        return True
    # Check if start hour is >= 21:00 or 00:00-05:00
    for m in re.finditer(r"\b([01]?\d|2[0-3])\s*[:h]\s*([0-5]\d)?\b", low):
        h = int(m.group(1))
        if h >= 21 or h <= 5:
            return True
    return False


def matches_portuguese_date_or_range(text, target_date, is_night_event=False):
    """
    Returns True if `text` explicitly matches `target_date` or an active date range covering `target_date`.
    Crucial fix: 1-night overnight ranges (e.g. '06 - 07 Novembro 2026' for a Friday 23:00 -> Saturday 06:00 party)
    belong ONLY to start_d (Nov 6), NEVER to end_d (Nov 7)!
    """
    norm = strip_accents(clean_html_text(text or ""))
    if not norm:
        return False
    is_night = is_night_event or _is_overnight_nightlife_text(norm)

    # 1. Check same-month ranges FIRST (e.g. '06 - 07 novembro 2026', '6 a 14 de novembro', '6 e 7 novembro')
    same_month_pat = re.compile(
        r"\b(\d{1,2})\s*(?:-|–|—|\ba\b|\bate\b|\be\b)\s*(\d{1,2})\s+(?:de\s+)?([a-zç]{3,9})(?:\s+(?:de\s+)?(202\d))?\b"
    )
    found_any_range = False
    for m in same_month_pat.finditer(norm):
        d1_s, d2_s, m_str, y_str = m.groups()
        m_num = PT_MONTH_LOOKUP.get(m_str)
        if not m_num:
            continue
        yr = int(y_str) if y_str else target_date.year
        try:
            start_d = datetime.date(yr, m_num, int(d1_s))
            end_d = datetime.date(yr, m_num, int(d2_s))
            found_any_range = True
            span_days = (end_d - start_d).days
            if span_days == 1 and is_night:
                if target_date == start_d:
                    return True
            else:
                if start_d <= target_date <= end_d:
                    return True
        except ValueError:
            continue

    # 2. Check full two-month ranges (e.g. '04 novembro a 31 dezembro 2026', '06 novembro 2026 - 07 novembro 2026')
    range_pat = re.compile(
        r"\b(\d{1,2})\s+(?:de\s+)?([a-zç]{3,9})(?:\s+(?:de\s+)?(202\d))?\s*(?:-|–|—|\ba\b|\bate\b)\s*(\d{1,2})\s+(?:de\s+)?([a-zç]{3,9})(?:\s+(?:de\s+)?(202\d))?\b"
    )
    for m in range_pat.finditer(norm):
        d1, m1_str, y1_str, d2, m2_str, y2_str = m.groups()
        m1 = PT_MONTH_LOOKUP.get(m1_str)
        m2 = PT_MONTH_LOOKUP.get(m2_str)
        if not m1 or not m2:
            continue
        y2 = int(y2_str) if y2_str else target_date.year
        y1 = int(y1_str) if y1_str else (y2 - 1 if m1 > m2 else y2)
        try:
            start_d = datetime.date(y1, m1, int(d1))
            end_d = datetime.date(y2, m2, int(d2))
            found_any_range = True
            span_days = (end_d - start_d).days
            if span_days == 1 and is_night:
                if target_date == start_d:
                    return True
            elif span_days > 45 and is_night:
                # Multi-month recurring club night (e.g. DIRRTY POP every Friday): require same weekday as start_d
                if start_d <= target_date <= end_d and target_date.weekday() == start_d.weekday():
                    return True
            else:
                if start_d <= target_date <= end_d:
                    return True
        except ValueError:
            continue

    # 3. Check numeric date ranges (e.g. '06/11/2026 - 07/11/2026')
    num_range_pat = re.compile(
        r"\b(\d{1,2})[./](\d{1,2})(?:[./](202\d))?\s*(?:-|–|—|\ba\b|\bate\b|\bto\b)\s*(\d{1,2})[./](\d{1,2})(?:[./](202\d))?\b"
    )
    for m in num_range_pat.finditer(norm):
        d1, m1_s, y1_s, d2, m2_s, y2_s = m.groups()
        y2 = int(y2_s) if y2_s else target_date.year
        y1 = int(y1_s) if y1_s else (y2 - 1 if int(m1_s) > int(m2_s) else y2)
        try:
            start_d = datetime.date(y1, int(m1_s), int(d1))
            end_d = datetime.date(y2, int(m2_s), int(d2))
            found_any_range = True
            span_days = (end_d - start_d).days
            if span_days == 1 and is_night:
                if target_date == start_d:
                    return True
            else:
                if start_d <= target_date <= end_d:
                    return True
        except ValueError:
            continue

    if found_any_range:
        return False

    # 4. Standalone single date match (only if not preceded by range connector)
    month_short = strip_accents(PT_MONTHS_SHORT[target_date.month])
    month_full = strip_accents(PT_MONTHS_FULL[target_date.month])
    day_patterns = [
        rf"(?<![-–—]\s)\b0?{target_date.day}\s+(?:de\s+)?(?:{month_short}|{month_full})(?:\s+(?:de\s+)?(202\d))?\b",
        rf"\b{target_date.strftime('%d/%m/%Y')}\b",
        rf"\b{target_date.strftime('%d.%m.%Y')}\b",
    ]
    for pat in day_patterns:
        m = re.search(pat, norm)
        if m:
            if m.lastindex and m.group(1) and int(m.group(1)) != target_date.year:
                continue
            return True

    return False


_WEEKDAY_MAP = {
    "seg": 0, "segunda": 0, "segunda-feira": 0, "2a": 0,
    "ter": 1, "terca": 1, "terca-feira": 1, "3a": 1,
    "qua": 2, "quarta": 2, "quarta-feira": 2, "4a": 2,
    "qui": 3, "quinta": 3, "quinta-feira": 3, "5a": 3,
    "sex": 4, "sexta": 4, "sexta-feira": 4, "6a": 4,
    "sab": 5, "sabado": 5,
    "dom": 6, "domingo": 6,
}


def check_weekday_and_extract_time(schedule_text, body_text, target_date):
    """
    Checks if an ongoing/multi-day event is open on target_date's weekday, and extracts
    the exact start/end time for target_date's weekday when available (e.g. 'qua: 19h30; sáb: 21h30; dom: 17h').
    Returns (is_open: bool, start_time: str|None, end_time: str|None).
    """
    target_wd = target_date.weekday()
    sched_norm = strip_accents(schedule_text or "")
    body_norm = strip_accents(body_text or "")
    combined = f"{sched_norm} | {body_norm}"

    # 1. Check explicit "segunda a sexta" without weekend mention
    if re.search(r"\b(segunda a sexta|seg\.?\s*a\s*sex\.?|de segunda a sexta)\b", combined):
        if not re.search(r"\b(sabado|sab\b|domingo|dom\b|fins? de semana)\b", combined) or "mediante a programacao" in combined:
            if target_wd >= 5:
                return False, None, None

    # 2. Check explicit closure days ("encerra à segunda", "fechado ao domingo")
    wd_names = {0: ["segunda"], 1: ["terca"], 2: ["quarta"], 3: ["quinta"], 4: ["sexta"], 5: ["sabado"], 6: ["domingo"]}
    for name in wd_names[target_wd]:
        if re.search(rf"\b(?:encerra|fechad[oa]s?)\s+(?:a|ao|as|aos|na|no)?\s*{name}\b", combined):
            return False, None, None

    # 3. Parse colon-separated weekday schedules (e.g. "qua: 19h30; qui: 19h30; sex: 21h30; sáb: 21h30; dom: 17h")
    wd_token_pat = r"(seg(?:unda)?|ter(?:ca)?|qua(?:rta)?|qui(?:nta)?|sex(?:ta)?|sab(?:ado)?|dom(?:ingo)?)"
    clauses = re.split(r"[;|]", sched_norm)
    has_explicit_wd_clauses = False
    matched_wd_time = None

    for clause in clauses:
        clause = clause.strip()
        m_colon = re.search(rf"\b{wd_token_pat}(?:\s*(?:a|-|e|,)\s*{wd_token_pat})*\s*:\s*(\d{{1,2}})(?:[:h](\d{{2}})|h)?", clause)
        if m_colon:
            has_explicit_wd_clauses = True
            # Determine which weekdays this clause covers
            prefix = clause[:m_colon.end()].split(":")[0]
            covered = set()
            # Check ranges like 'qua a sab' or 'ter a sex'
            for mr in re.finditer(rf"\b{wd_token_pat}\s*(?:a|-)\s*{wd_token_pat}\b", prefix):
                w1 = _WEEKDAY_MAP.get(mr.group(1)[:3])
                w2 = _WEEKDAY_MAP.get(mr.group(2)[:3])
                if w1 is not None and w2 is not None:
                    if w1 <= w2:
                        covered.update(range(w1, w2 + 1))
                    else:
                        covered.update(list(range(w1, 7)) + list(range(0, w2 + 1)))
            for mw in re.finditer(rf"\b{wd_token_pat}\b", prefix):
                w = _WEEKDAY_MAP.get(mw.group(1)[:3])
                if w is not None:
                    covered.add(w)
            if target_wd in covered:
                hh = int(m_colon.group(3))
                mm = int(m_colon.group(4) or 0)
                matched_wd_time = f"{hh:02d}:{mm:02d}"

    if has_explicit_wd_clauses:
        if matched_wd_time:
            return True, matched_wd_time, None
        return False, None, None

    # 4. Check "das HHh às HHh" opening hours in schedule or body
    m_hours = re.search(r"\bdas\s+(\d{1,2})(?:[:h](\d{2})|h)?\s*(?:as|às|-)\s*(\d{1,2})(?:[:h](\d{2})|h)?\b", combined)
    if m_hours:
        sh, sm = int(m_hours.group(1)), int(m_hours.group(2) or 0)
        eh, em = int(m_hours.group(3)), int(m_hours.group(4) or 0)
        if eh == 24:
            eh, em = 23, 59
        return True, f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}"

    return True, None, None


def fetch_url(url, timeout=14, headers=None):
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    try:
        resp = SCRAPER_SESSION.get(url, headers=hdrs, timeout=timeout)
    except Exception as exc:
        if "SSL" in str(exc) or "certificate" in str(exc).lower() or "curl: (60)" in str(exc):
            try:
                resp = SCRAPER_SESSION.get(url, headers=hdrs, timeout=timeout, verify=False)
            except Exception:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                resp = requests.get(url, headers=hdrs, timeout=timeout, verify=False)
        elif "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            resp = SCRAPER_SESSION.get(url, headers=hdrs, timeout=timeout + 4)
        else:
            raise
    if hasattr(resp, "encoding") and resp.encoding and resp.encoding.lower() in ("iso-8859-1", "latin-1"):
        resp.encoding = "utf-8"
    return resp


# ==============================================================================
# TIER 1: AGENDALX, CARTAZ CULTURAL LISBOA & NOCARTAZ LISBOA
# ==============================================================================
def scrape_agendalx(target_date):
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    prev_date = target_date - datetime.timedelta(days=1)
    print(f"[Tier 1] Scraping AgendaLX & Cartaz Cultural for {date_str}...")

    # --- 1A. AGENDALX (Homepage + Candidate Event Detail Pages) ---
    candidate_alx_urls = []
    seen_alx_urls = set()
    try:
        resp = fetch_url("https://www.agendalx.pt/")
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Leaf cards on homepage
            for el in soup.find_all(lambda tag: tag.get("class") and any("card" in c for c in tag.get("class"))):
                links = set(a["href"] for a in el.select("a[href*='/events/event/']") if a.get("href"))
                if len(links) == 1:
                    u = list(links)[0]
                    if u in seen_alx_urls:
                        continue
                    dates = [clean_html_text(d.get_text(" ", strip=True)) for d in el.select(".signpost__date")]
                    if dates and not any(matches_portuguese_date_or_range(d, target_date) for d in dates):
                        seen_alx_urls.add(u)
                        continue
                    seen_alx_urls.add(u)
                    candidate_alx_urls.append(u)
            # Also include any remaining /events/event/ links on homepage not inside leaf cards
            for a in soup.select("a[href*='/events/event/']"):
                u = a.get("href", "")
                if u and u not in seen_alx_urls:
                    seen_alx_urls.add(u)
                    candidate_alx_urls.append(u)
    except Exception as e:
        print(f"[AgendaLX] Notice on homepage: {e}")

    # Pre-fetch first 2 detail pages to discover any related upcoming events
    for seed_url in list(candidate_alx_urls[:2]):
        try:
            s_resp = fetch_url(seed_url, timeout=10)
            if s_resp.status_code == 200:
                s_soup = BeautifulSoup(s_resp.text, "html.parser")
                for rel_card in s_soup.find_all(lambda tag: tag.get("class") and any("card" in c for c in tag.get("class"))):
                    r_links = set(a["href"] for a in rel_card.select("a[href*='/events/event/']") if a.get("href"))
                    if len(r_links) == 1:
                        ru = list(r_links)[0]
                        if ru not in seen_alx_urls:
                            r_dates = [clean_html_text(d.get_text(" ", strip=True)) for d in rel_card.select(".signpost__date")]
                            if not r_dates or any(matches_portuguese_date_or_range(d, target_date) for d in r_dates):
                                seen_alx_urls.add(ru)
                                candidate_alx_urls.append(ru)
        except Exception:
            pass

    def _process_alx_detail(ev_url):
        try:
            d_resp = fetch_url(ev_url, timeout=10)
            if d_resp.status_code != 200:
                return None
            d_soup = BeautifulSoup(d_resp.text, "html.parser")
            header = d_soup.select_one(".event__header") or d_soup
            title_el = header.select_one("h1.event__title, h1")
            title = clean_html_text(title_el.get_text(" ", strip=True) if title_el else "")
            if not title or len(title) < 3 or title.lower() in ("teatro", "dança", "cinema", "artes", "música"):
                return None

            subj_el = header.select_one(".signpost__subject")
            subj = clean_html_text(subj_el.get_text(" ", strip=True) if subj_el else "")
            date_els = [clean_html_text(d.get_text(" ", strip=True)) for d in header.select(".signpost__date")]
            venue_el = header.select_one(".signpost__venue")
            venue_str = clean_html_text(venue_el.get_text(" ", strip=True) if venue_el else "")

            if not date_els or not matches_portuguese_date_or_range(date_els[0], target_date):
                return None

            if not venue_str or "varios locais" in strip_accents(venue_str):
                return None

            addr_el = d_soup.select_one(".venue-card .address, .venue .address")
            addr_str = clean_html_text(addr_el.get_text(" ", strip=True) if addr_el else "")

            body_paras = []
            for p in d_soup.select("article p, .post__content p, .entry-content p, main p"):
                ptxt = clean_html_text(p.get_text(" ", strip=True))
                if ptxt and ptxt not in ("Local:", "Próximos eventos", "Pergunte. A agendalx.pt sugere."):
                    body_paras.append(ptxt)
            body_text = " | ".join(body_paras)
            sched_str = " ; ".join(date_els[1:]) if len(date_els) > 1 else ""

            is_open, wd_start, wd_end = check_weekday_and_extract_time(sched_str, body_text, target_date)
            if not is_open:
                return None

            geo = match_venue(venue_str, addr_str, require_match=True)
            if not geo:
                hit, g_name = locations.geocode_location(f"{venue_str}, {addr_str}, Lisboa" if addr_str else f"{venue_str}, Lisboa")
                if hit:
                    geo = {
                        "venue": venue_str,
                        "lat": hit["lat"],
                        "lng": hit["lng"],
                        "neighborhood": locations.infer_neighborhood(hit["lat"], hit["lng"], hit.get("area")),
                        "corridor": locations.infer_corridor(hit["lat"], hit["lng"]),
                        "url": ev_url,
                    }
            if not geo:
                return None

            default_cat = "concerts"
            subj_norm = strip_accents(subj)
            if "teatro" in subj_norm or "danca" in subj_norm or "stand up" in subj_norm:
                default_cat = "theatre"
            elif "cinema" in subj_norm:
                default_cat = "cinema"
            elif "artes" in subj_norm:
                default_cat = "exhibitions"
            elif any(k in subj_norm for k in ["feiras", "literatura", "ciencias", "visitas"]):
                default_cat = "community"
            elif "criancas" in subj_norm:
                default_cat = "family"

            preset = infer_category_preset(f"{subj} {title}", default_cat)
            def_t, def_h = resolve_venue_default_hours(geo["venue"], preset["category"], target_date.weekday())
            if wd_start:
                time_str, hour_int = wd_start, int(wd_start.split(":")[0])
            else:
                time_str, hour_int = parse_time_str(sched_str, def_t)

            if wd_end:
                end_t, end_h = wd_end, int(wd_end.split(":")[0])
            else:
                end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, f"{sched_str} {body_text}")

            price_disp, price_tier = parse_price_and_tier(
                body_text,
                venue_name=geo["venue"],
                category_name=preset["category"],
            )
            desc_summary = body_paras[0][:240] if body_paras else f"{title} em {geo['venue']} ({geo['neighborhood']})."
            slug = ev_url.rstrip("/").split("/")[-1][:36]

            return {
                "id": f"agendalx-{slug}",
                "title": title,
                "category": preset["category"],
                "color": preset["color"],
                "icon": preset["icon"],
                "venue": geo["venue"],
                "neighborhood": geo["neighborhood"],
                "corridor": geo["corridor"],
                "lat": geo["lat"],
                "lng": geo["lng"],
                "time": time_str,
                "hour": hour_int,
                "endTime": end_t,
                "endHour": end_h,
                "price": price_disp,
                "priceTier": price_tier,
                "url": ev_url,
                "description": desc_summary,
            }
        except Exception as e:
            print(f"[AgendaLX Detail] Notice on {ev_url}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=6) as alx_pool:
        for res in alx_pool.map(_process_alx_detail, candidate_alx_urls[:45]):
            if res:
                events.append(res)

    # --- 1B. CARTAZ CULTURAL LISBOA (Listing + JSON-LD Event Verification) ---
    ccl_urls = [
        "https://cartazculturallisboa.pt/eventos/",
        "https://cartazculturallisboa.pt/agenda-eventos-lisboa/",
        "https://cartazculturallisboa.pt/exposicoes-em-lisboa/",
    ]
    seen_ccl = set()
    tourist_spam = ("passeio de helicoptero", "hop-on", "segway", "tuk tuk", "autocarro turistico", "yellow bus")

    for ccl_url in ccl_urls:
        try:
            resp = fetch_url(ccl_url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/evento/"]'):
                href = a_tag.get("href", "")
                if not href or href in seen_ccl:
                    continue
                card = a_tag.find_parent("article") or a_tag.find_parent("li") or (a_tag.parent.parent if a_tag.parent else a_tag)
                txt = clean_html_text(card.get_text(" | ", strip=True))
                if any(sp in strip_accents(txt) for sp in tourist_spam):
                    seen_ccl.add(href)
                    continue
                if txt and re.search(r"\b202\d\b", txt) and not matches_portuguese_date_or_range(txt, target_date):
                    seen_ccl.add(href)
                    continue
                seen_ccl.add(href)

                full_url = urljoin("https://cartazculturallisboa.pt", href)
                try:
                    d_resp = fetch_url(full_url, timeout=10)
                    if d_resp.status_code != 200:
                        continue
                    d_soup = BeautifulSoup(d_resp.text, "html.parser")
                except Exception:
                    continue

                # Parse Schema.org Event JSON-LD from detail page
                ev_ld = None
                for script in d_soup.find_all("script", type="application/ld+json"):
                    try:
                        ld_obj = json.loads(script.string or "")
                        if isinstance(ld_obj, dict) and ld_obj.get("@type") == "Event":
                            ev_ld = ld_obj
                            break
                    except Exception:
                        pass

                h1 = d_soup.find("h1")
                title = clean_html_text(h1.get_text(" ", strip=True) if h1 else "")
                if not title or len(title) < 4 or any(sp in strip_accents(title) for sp in tourist_spam):
                    continue

                body_paras = [clean_html_text(p.get_text(" ", strip=True)) for p in d_soup.select(".entry-content p, article p") if clean_html_text(p.get_text(" ", strip=True))]
                body_text = " | ".join(body_paras)

                # Strict Date Verification via JSON-LD + Body Text
                ld_start_raw = str((ev_ld or {}).get("startDate", ""))
                ld_end_raw = str((ev_ld or {}).get("endDate", ""))
                if ld_start_raw and len(ld_start_raw) >= 10:
                    try:
                        s_date = datetime.date.fromisoformat(ld_start_raw[:10])
                        e_date = datetime.date.fromisoformat(ld_end_raw[:10]) if len(ld_end_raw) >= 10 else s_date
                        if not (s_date <= target_date <= e_date):
                            continue
                        # Reject yesterday's 1-night overnight event ending early this morning
                        if s_date == prev_date and e_date == target_date:
                            s_time_m = re.search(r"T(\d{2}):(\d{2})", ld_start_raw)
                            e_time_m = re.search(r"T(\d{2}):(\d{2})", ld_end_raw)
                            if (s_time_m and int(s_time_m.group(1)) >= 18) or (e_time_m and int(e_time_m.group(1)) <= 8) or _is_overnight_nightlife_text(f"{title} {body_text}"):
                                continue
                        # Reject multi-month weekly club night if weekday doesn't match start_d
                        if (e_date - s_date).days > 45 and _is_overnight_nightlife_text(f"{title} {body_text}"):
                            if target_date.weekday() != s_date.weekday():
                                continue
                    except ValueError:
                        pass
                else:
                    if not matches_portuguese_date_or_range(f"{txt} {body_text}", target_date):
                        continue

                # Check weekday closure / schedule in body text
                is_open, wd_start, wd_end = check_weekday_and_extract_time("", body_text, target_date)
                if not is_open:
                    continue

                loc_obj = (ev_ld or {}).get("location") or {}
                loc_name = clean_html_text(loc_obj.get("name", "")) if isinstance(loc_obj, dict) else ""
                loc_addr = clean_html_text(str(loc_obj.get("address", ""))) if isinstance(loc_obj, dict) else ""

                # Reject non-Lisbon municipalities
                addr_norm = strip_accents(f"{loc_name} {loc_addr}")
                if any(m in addr_norm for m in ("almada", "oeiras", "cascais", "sintra", "amadora", "seixal", "barreiro", "setubal", "porto")):
                    continue

                geo = match_venue(loc_name, loc_addr, require_match=True)
                if not geo and (loc_name or loc_addr):
                    q_str = f"{loc_name}, {loc_addr}" if loc_addr else f"{loc_name}, Lisboa"
                    hit, g_name = locations.geocode_location(q_str)
                    if hit:
                        geo = {
                            "venue": loc_name or g_name,
                            "lat": hit["lat"],
                            "lng": hit["lng"],
                            "neighborhood": locations.infer_neighborhood(hit["lat"], hit["lng"], hit.get("area")),
                            "corridor": locations.infer_corridor(hit["lat"], hit["lng"]),
                            "url": full_url,
                        }
                if not geo:
                    continue

                default_cat = "exhibitions" if "exposicoes" in ccl_url else "concerts"
                first_para = body_paras[0] if body_paras else ""
                preset = infer_category_preset(f"{title} {loc_name} {first_para}", default_cat)
                def_t, def_h = resolve_venue_default_hours(geo["venue"], preset["category"], target_date.weekday())

                time_str, hour_int = def_t, def_h
                if wd_start:
                    time_str, hour_int = wd_start, int(wd_start.split(":")[0])
                elif "T" in ld_start_raw:
                    t_part = ld_start_raw.split("T")[1][:5]
                    if t_part != "00:00":
                        time_str, hour_int = parse_time_str(t_part, def_t)
                    else:
                        time_str, hour_int = parse_time_str(body_text, def_t)
                else:
                    time_str, hour_int = parse_time_str(body_text, def_t)

                if wd_end:
                    end_t, end_h = wd_end, int(wd_end.split(":")[0])
                elif "T" in ld_end_raw and ld_end_raw.split("T")[1][:5] != "00:00":
                    end_t, end_h = parse_time_str(ld_end_raw.split("T")[1][:5], "23:00")
                    if end_t == time_str:
                        end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, body_text)
                else:
                    end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, body_text)

                # Extract price from body text or JSON-LD offers
                offers = (ev_ld or {}).get("offers") or {}
                ld_price_raw = str(offers.get("price", "")).strip() if isinstance(offers, dict) else ""
                price_disp, price_tier = parse_price_and_tier(
                    body_text,
                    venue_name=geo["venue"],
                    category_name=preset["category"],
                )
                if ld_price_raw and ld_price_raw.replace(".", "").isdigit() and float(ld_price_raw) > 0 and "€" not in price_disp:
                    price_disp, price_tier = parse_price_and_tier(f"{ld_price_raw}€")

                slug = href.strip("/").split("/")[-1][:32]
                desc_str = body_paras[0][:240] if body_paras else f"{title} em {geo['venue']} ({geo['neighborhood']})."

                events.append({
                    "id": f"ccl-{slug}",
                    "title": title,
                    "category": preset["category"],
                    "color": preset["color"],
                    "icon": preset["icon"],
                    "venue": geo["venue"],
                    "neighborhood": geo["neighborhood"],
                    "corridor": geo["corridor"],
                    "lat": geo["lat"],
                    "lng": geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": price_disp,
                    "priceTier": price_tier,
                    "url": full_url,
                    "description": desc_str,
                })
        except Exception as e:
            print(f"[CartazCultural] Notice on {ccl_url}: {e}")

    return events


def scrape_nocartaz(target_date):
    """Scrapes NoCartaz Lisboa across concelho, hoje, and category pages with strict date and concelho validation."""
    events = []
    month_short = strip_accents(PT_MONTHS_SHORT[target_date.month])
    day_pat = rf"\b0?{target_date.day}\s+{month_short}\b"
    print(f"[Tier 1] Scraping NoCartaz Lisboa for {target_date.day} {month_short}...")

    nocartaz_urls = [
        "https://www.nocartaz.pt/concelhos/lisboa/",
        "https://www.nocartaz.pt/hoje/",
        "https://www.nocartaz.pt/distrito/lisboa/concertos/",
        "https://www.nocartaz.pt/distrito/lisboa/teatro/",
        "https://www.nocartaz.pt/distrito/lisboa/exposicoes/",
        "https://www.nocartaz.pt/distrito/lisboa/cinema/",
        "https://www.nocartaz.pt/distrito/lisboa/jazz/",
        "https://www.nocartaz.pt/distrito/lisboa/feiras/",
        "https://www.nocartaz.pt/distrito/lisboa/conferencias/",
    ]

    school_or_generic_skip = {
        "pre-escolar", "primeiro ciclo", "segundo ciclo", "terceiro ciclo",
        "terceiro ciclo e secundario", "primeira infancia", "visitas guiadas",
        "teatro", "musica", "exposicao", "danca", "cinema", "concerto",
    }

    seen_hrefs = set()
    for nc_url in nocartaz_urls:
        try:
            resp = fetch_url(nc_url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/evento/"], a[href*="/eventos/"]'):
                href = a_tag.get("href", "")
                if not href or href in seen_hrefs:
                    continue
                container = a_tag.find_parent(["article", "li", "div"]) or a_tag
                raw_pipe = clean_html_text(container.get_text(" | ", strip=True))
                norm_pipe = strip_accents(raw_pipe)

                # ALWAYS verify the card's date matches target_date (never blindly trust /hoje/)
                if not re.search(day_pat, norm_pipe):
                    continue

                h_el = container.find(["h2", "h3", "h4"])
                title = clean_html_text(h_el.get_text(" ", strip=True)) if h_el else ""
                parts = [p.strip() for p in raw_pipe.split("|") if p.strip() and p.strip() != "♡"]
                if not title and len(parts) >= 2:
                    title = parts[1]
                if not title or len(title) < 3:
                    continue

                title_norm = strip_accents(title).strip()
                if title_norm in school_or_generic_skip:
                    continue
                if any(k in title_norm for k in ["viagens ilimitadas", "hop-on", "caves calem", "passeio de barco"]):
                    continue

                venue_candidate = ""
                concelho_candidate = "lisboa" if ("/concelhos/lisboa/" in nc_url or "/cidade/lisboa/" in nc_url) else ""
                for p in parts:
                    if "·" in p and not re.search(day_pat, strip_accents(p)):
                        sp = [x.strip() for x in p.split("·") if x.strip()]
                        if sp:
                            venue_candidate = sp[0]
                        if len(sp) >= 2:
                            concelho_candidate = strip_accents(sp[-1])
                        break

                # Strictly require Lisboa municipality (reject Sabrosa, Oeiras, Sintra, Cascais, Almada, Porto, etc.)
                if concelho_candidate and concelho_candidate != "lisboa":
                    continue

                if not venue_candidate and " @ " in title:
                    venue_candidate = title.split(" @ ")[-1].strip()

                if strip_accents(venue_candidate).strip() in ("", "lisboa", "varios locais", "centro"):
                    continue

                # Match ONLY venue_candidate (never match artist words in title to avoid 'Maat Saxophone Quartet' -> MAAT)
                geo = match_venue(venue_candidate, require_match=True)
                if not geo and venue_candidate and concelho_candidate == "lisboa":
                    hit, name = locations.geocode_location(f"{venue_candidate}, Lisboa")
                    if hit:
                        geo = {
                            "venue": name or venue_candidate,
                            "lat": hit["lat"],
                            "lng": hit["lng"],
                            "neighborhood": locations.infer_neighborhood(hit["lat"], hit["lng"], hit.get("area")),
                            "corridor": locations.infer_corridor(hit["lat"], hit["lng"]),
                            "url": urljoin("https://www.nocartaz.pt", href),
                        }
                if not geo:
                    continue

                seen_hrefs.add(href)
                full_nc_url = urljoin("https://www.nocartaz.pt", href)
                ev_url = full_nc_url
                detail_price_text = ""

                # Fetch NoCartaz detail page to verify it is not a 404 stub and grab official outbound link ('Bilhetes →')
                try:
                    d_resp = fetch_url(full_nc_url, timeout=8)
                    if d_resp.status_code >= 400:
                        continue
                    if d_resp.status_code == 200:
                        d_soup = BeautifulSoup(d_resp.text, "html.parser")
                        detail_price_text = clean_html_text(d_soup.get_text(" ", strip=True))
                        for ext_a in d_soup.select("a[href^='http']"):
                            ext_h = ext_a.get("href", "").strip()
                            ext_txt = ext_a.get_text(" ", strip=True).lower()
                            if "bilhete" in ext_txt or any(d in ext_h for d in ("ccb.pt", "gulbenkian.pt", "culturgest.pt", "tndm.pt", "teatrosaoluiz.pt", "shotgun.live", "3cket.com", "zedosbois.org")):
                                if not any(bad in ext_h for bad in ("google.com/maps", "calendar.google", "facebook.com/sharer", "twitter.com", "wa.me", "event-test")):
                                    ev_url = ext_h
                                    break
                except Exception:
                    pass

                default_cat = "community" if any(k in nc_url for k in ["feiras", "conferencias"]) else "concerts"
                preset = infer_category_preset(f"{title} {geo['venue']} {raw_pipe}", default_cat)
                def_t, _ = resolve_venue_default_hours(geo["venue"], preset["category"], target_date.weekday())
                time_str, hour_int = parse_time_str(raw_pipe, def_t)
                price_disp, price_tier = parse_price_and_tier(
                    f"{raw_pipe} {detail_price_text}",
                    venue_name=geo["venue"],
                    category_name=preset["category"],
                )
                end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, raw_pipe)
                slug = href.strip("/").split("/")[-1]

                events.append({
                    "id": f"nocartaz-{slug}",
                    "title": title,
                    "category": preset["category"],
                    "color": preset["color"],
                    "icon": preset["icon"],
                    "venue": geo["venue"],
                    "neighborhood": geo["neighborhood"],
                    "corridor": geo["corridor"],
                    "lat": geo["lat"],
                    "lng": geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": price_disp,
                    "priceTier": price_tier,
                    "url": ev_url,
                    "description": f"{title} em {geo['venue']} ({geo['neighborhood']}).",
                })
        except Exception as e:
            print(f"[NoCartaz] Notice on {nc_url}: {e}")
    return events


# ==============================================================================
# TIER 2: CINEMATECA, MEDEIA NIMAS, AGENDA DE CONCERTOS & BOTA ANJOS
# ==============================================================================
def scrape_cinemateca(target_date):
    """Scrapes Cinemateca Portuguesa (https://www.cinemateca.pt/Programacao.aspx)."""
    events = []
    d_slash = target_date.strftime("%d/%m/%Y")
    print(f"[Tier 2] Scraping Cinemateca Portuguesa for {d_slash}...")
    try:
        resp = fetch_url("https://www.cinemateca.pt/Programacao.aspx")
        if resp.status_code != 200:
            return events
        soup = BeautifulSoup(resp.text, "html.parser")
        geo = match_venue("cinemateca portuguesa")
        pattern = re.compile(
            rf"{re.escape(d_slash)}\s*,?\s*(\d{{1,2}})[h:](\d{{2}})\s*\|\s*([^\n]+)\n+([^\n]+)(?:\n+([^\n]+))?",
            re.I
        )
        seen_slots = set()
        for idx, m in enumerate(pattern.finditer(soup.get_text("\n", strip=True))):
            hh, mm = int(m.group(1)), int(m.group(2))
            room = clean_html_text(m.group(3))
            line1 = clean_html_text(m.group(4))
            line2 = clean_html_text(m.group(5) or "")
            title = line2 if (line2 and len(line2) > 3 and "ciclo" in line1.lower()) else line1
            slot_key = f"{hh:02d}:{mm:02d}|{room}|{title[:20]}"
            if slot_key in seen_slots:
                continue
            seen_slots.add(slot_key)
            time_str = f"{hh:02d}:{mm:02d}"
            end_t, end_h = infer_end_time(time_str, hh, CATEGORY_PRESETS["cinema"]["category"], geo["venue"], title, room)
            events.append({
                "id": f"cinemateca-{target_date.strftime('%Y%m%d')}-{hh:02d}{mm:02d}-{idx}",
                "title": title,
                "category": CATEGORY_PRESETS["cinema"]["category"],
                "color": CATEGORY_PRESETS["cinema"]["color"],
                "icon": CATEGORY_PRESETS["cinema"]["icon"],
                "venue": geo["venue"],
                "neighborhood": geo["neighborhood"],
                "corridor": geo["corridor"],
                "lat": geo["lat"],
                "lng": geo["lng"],
                "time": time_str,
                "hour": hh,
                "endTime": end_t,
                "endHour": end_h,
                "price": "3.20€",
                "priceTier": "ACCESSIBLE",
                "url": "https://www.cinemateca.pt/Programacao.aspx",
                "description": f"Sessão na {room} da Cinemateca Portuguesa ({line1}).",
            })
    except Exception as e:
        print(f"[Cinemateca] Notice: {e}")
    return events


def scrape_nimas(target_date):
    """Scrapes Cinema Medeia Nimas (https://medeiafilmes.com/cinemas/cinema-medeia-nimas)."""
    events = []
    d_dot = target_date.strftime("%d.%m.%Y")
    print(f"[Tier 2] Scraping Cinema Medeia Nimas for {d_dot}...")
    try:
        resp = fetch_url("https://medeiafilmes.com/cinemas/cinema-medeia-nimas")
        if resp.status_code != 200:
            return events
        soup = BeautifulSoup(resp.text, "html.parser")
        raw_text = soup.get_text("\n", strip=True)
        if d_dot not in raw_text:
            return events
        day_section = raw_text.split(d_dot, 1)[1]

        upcoming_dates = [
            (target_date + datetime.timedelta(days=k)).strftime("%d.%m.%Y")
            for k in range(1, 15)
        ]
        cut_idx = len(day_section)
        for next_d in upcoming_dates:
            for m_next in re.finditer(re.escape(next_d), day_section):
                prefix = day_section[max(0, m_next.start() - 12):m_next.start()].lower()
                if "estreia" not in prefix:
                    cut_idx = min(cut_idx, m_next.start())
                    break
            if cut_idx < len(day_section):
                break
        day_section = day_section[:cut_idx]

        geo = match_venue("cinema medeia nimas")
        lines = [clean_html_text(ln) for ln in day_section.splitlines() if clean_html_text(ln)]
        i = 0
        while i < len(lines):
            tm = re.match(r"^(?:\*\s*)?([01]?\d|2[0-3]):([0-5]\d)\.?\s*(.*)$", lines[i])
            if tm:
                time_str = f"{int(tm.group(1)):02d}:{tm.group(2)}"
                hour_int = int(tm.group(1))
                inline_title = tm.group(3).strip()
                film_title = inline_title if inline_title else (lines[i + 1] if i + 1 < len(lines) else "Sessão Medeia Nimas")
                step = 1 if inline_title else 2
                director = ""
                if i + step < len(lines) and lines[i + step].lower().startswith("de "):
                    director = f" ({lines[i + step]})"
                    step += 1
                full_title = f"{film_title}{director}"
                end_t, end_h = infer_end_time(time_str, hour_int, CATEGORY_PRESETS["cinema"]["category"], geo["venue"], full_title)
                events.append({
                    "id": f"nimas-{target_date.strftime('%Y%m%d')}-{time_str.replace(':', '')}",
                    "title": full_title,
                    "category": CATEGORY_PRESETS["cinema"]["category"],
                    "color": CATEGORY_PRESETS["cinema"]["color"],
                    "icon": CATEGORY_PRESETS["cinema"]["icon"],
                    "venue": geo["venue"],
                    "neighborhood": geo["neighborhood"],
                    "corridor": geo["corridor"],
                    "lat": geo["lat"],
                    "lng": geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": "7.50€",
                    "priceTier": "ACCESSIBLE",
                    "url": "https://medeiafilmes.com/cinemas/cinema-medeia-nimas",
                    "description": f"Exibição de {full_title} no Cinema Medeia Nimas (Saldanha).",
                })
                i += step
                continue
            i += 1
    except Exception as e:
        print(f"[Medeia Nimas] Notice: {e}")
    return events


def scrape_agendadeconcertos(target_date):
    """Scrapes Agenda de Concertos (localidade/lisboa + concertos-em-portugal) for target_date."""
    events = []
    month_full = strip_accents(PT_MONTHS_FULL[target_date.month])
    next_date = target_date + datetime.timedelta(days=1)
    next_month_full = strip_accents(PT_MONTHS_FULL[next_date.month])
    print(f"[Tier 2] Scraping Agenda de Concertos for {target_date.day} {month_full}...")

    adc_urls = [
        "https://agendadeconcertos.com/localidade/lisboa/",
        "https://agendadeconcertos.com/concertos-em-portugal/",
    ]
    today_header_pat = re.compile(
        rf"(?:hoje\s*•\s*)?\b0?{target_date.day}\s+{month_full}\b",
        re.I
    )
    next_header_pat = re.compile(
        rf"(?:amanha\s*•\s*)?\b0?{next_date.day}\s+{next_month_full}\b|\b\d{{1,2}}\s+(?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s*•",
        re.I
    )

    for adc_url in adc_urls:
        try:
            resp = fetch_url(adc_url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            raw_lines = [clean_html_text(ln) for ln in soup.get_text("\n", strip=True).splitlines() if clean_html_text(ln)]
            in_today = False
            i = 0
            while i < len(raw_lines):
                ln_norm = strip_accents(raw_lines[i])
                if not in_today:
                    if today_header_pat.search(ln_norm):
                        in_today = True
                    i += 1
                    continue

                if next_header_pat.search(ln_norm) and not today_header_pat.search(ln_norm):
                    break

                if i + 1 < len(raw_lines) and re.search(r"[-–]\s*lisboa\b", strip_accents(raw_lines[i + 1])):
                    artist = raw_lines[i]
                    venue_line = raw_lines[i + 1]
                    if artist and "cancelado" not in artist.lower() and len(artist) < 120:
                        venue_part = re.split(r"[-–]\s*Lisboa", venue_line, flags=re.I)[0].strip(" -–•|")
                        geo = match_venue(venue_part, require_match=True)
                        if geo:
                            preset = infer_category_preset(artist, "concerts")
                            time_str, hour_int = parse_time_str(venue_line, "21:30")
                            price_disp, price_tier = resolve_venue_default_price(geo["venue"], preset["category"])
                            end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], artist)
                            events.append({
                                "id": f"adc-{target_date.strftime('%Y%m%d')}-{abs(hash(artist + geo['venue'])) % 10000}",
                                "title": artist,
                                "category": preset["category"],
                                "color": preset["color"],
                                "icon": preset["icon"],
                                "venue": geo["venue"],
                                "neighborhood": geo["neighborhood"],
                                "corridor": geo["corridor"],
                                "lat": geo["lat"],
                                "lng": geo["lng"],
                                "time": time_str,
                                "hour": hour_int,
                                "endTime": end_t,
                                "endHour": end_h,
                                "price": price_disp,
                                "priceTier": price_tier,
                                "url": geo.get("agenda_url") or geo.get("url") or adc_url,
                                "description": f"Concerto de {artist} ao vivo em {geo['venue']} ({geo['neighborhood']}).",
                            })
                    i += 2
                    continue
                i += 1
        except Exception as e:
            print(f"[Agenda de Concertos] Notice on {adc_url}: {e}")
    return events


def scrape_bota_anjos(target_date):
    """Scrapes BOTA Anjos (https://www.botaanjos.com/programacao) and verifies each event's detail page."""
    events = []
    d_slash = target_date.strftime("%d/%m/%Y")
    print(f"[Tier 2] Scraping BOTA Anjos for {d_slash}...")
    try:
        resp = fetch_url("https://www.botaanjos.com/programacao")
        if resp.status_code != 200:
            return events
        soup = BeautifulSoup(resp.text, "html.parser")
        geo = match_venue("bota anjos")
        seen_urls = set()
        for a_tag in soup.select('a[href*="/programacao/"]'):
            href = a_tag.get("href", "")
            full_url = urljoin("https://www.botaanjos.com", href)
            if full_url in seen_urls or full_url.rstrip("/") == "https://www.botaanjos.com/programacao":
                continue
            # Use the immediate Wix repeater item container (not the outer page wrapper)
            card = a_tag.find_parent(attrs={"role": "listitem"}) or a_tag.parent
            txt = clean_html_text(card.get_text(" ", strip=True))
            if len(txt) < 800 and not matches_portuguese_date_or_range(txt, target_date):
                seen_urls.add(full_url)
                continue
            seen_urls.add(full_url)

            # Verify on detail page
            try:
                d_resp = fetch_url(full_url, timeout=8)
                if d_resp.status_code != 200:
                    continue
                d_soup = BeautifulSoup(d_resp.text, "html.parser")
                d_txt = clean_html_text(d_soup.get_text(" ", strip=True))
                if not matches_portuguese_date_or_range(d_txt, target_date):
                    continue
                h_el = d_soup.find(["h1", "h2"]) or card.find(["h1", "h2", "h3", "h4"])
                title = clean_html_text(h_el.get_text(" ", strip=True) if h_el else a_tag.get_text(" ", strip=True))
                if not title or len(title) < 3 or title.lower() in ("programação", "ver evento", "bota"):
                    continue
                ev_geo = match_venue(title, full_url.replace("-", " "), require_match=True) or geo
                preset = infer_category_preset(title, "concerts")
                time_str, hour_int = parse_time_str(d_txt, "21:00")
                price_disp, price_tier = parse_price_and_tier(d_txt, "8€ - 10€", "ACCESSIBLE", venue_name=ev_geo["venue"])
                end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], ev_geo["venue"], title, d_txt)
                events.append({
                    "id": f"bota-{target_date.strftime('%Y%m%d')}-{abs(hash(title)) % 10000}",
                    "title": title,
                    "category": preset["category"],
                    "color": preset["color"],
                    "icon": preset["icon"],
                    "venue": ev_geo["venue"],
                    "neighborhood": ev_geo["neighborhood"],
                    "corridor": ev_geo["corridor"],
                    "lat": ev_geo["lat"],
                    "lng": ev_geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": price_disp,
                    "priceTier": price_tier,
                    "url": full_url,
                    "description": f"{title} em {ev_geo['venue']} ({ev_geo['neighborhood']}).",
                })
            except Exception:
                pass
    except Exception as e:
        print(f"[BOTA Anjos] Notice: {e}")
    return events


# ==============================================================================
# TIER 3: RESIDENT ADVISOR & PRIOR VELHO / LISABOUT HUBS
# ==============================================================================
def scrape_resident_advisor(target_date):
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"[Tier 3] Querying Resident Advisor GraphQL for Lisbon on {date_str}...")

    gql_url = "https://ra.co/graphql"
    query = """
    query GET_EVENT_LISTINGS($filters: FilterInputDtoInput, $pageSize: Int, $page: Int) {
      eventListings(filters: $filters, pageSize: $pageSize, page: $page) {
        data {
          id
          listingDate
          event {
            id
            title
            startTime
            endTime
            contentUrl
            venue {
              id
              name
              address
            }
            artists {
              name
            }
          }
        }
      }
    }
    """
    headers = {
        "Content-Type": "application/json",
        "Referer": "https://pt.ra.co/events/pt/lisbon",
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
    }

    for area_id in (229, 51):
        payload = {
            "query": query,
            "variables": {
                "filters": {
                    "areas": {"eq": area_id},
                    "listingDate": {"gte": f"{date_str}T00:00:00.000Z", "lte": f"{date_str}T23:59:59.999Z"},
                },
                "pageSize": 40,
                "page": 1,
            },
        }
        try:
            try:
                resp = SCRAPER_SESSION.post(gql_url, json=payload, headers=headers, timeout=15)
            except Exception as ssl_exc:
                if "SSL" in str(ssl_exc) or "certificate" in str(ssl_exc).lower() or "curl: (60)" in str(ssl_exc):
                    resp = SCRAPER_SESSION.post(gql_url, json=payload, headers=headers, timeout=15, verify=False)
                else:
                    raise
            if resp.status_code == 200:
                data = resp.json()
                listings = (((data.get("data") or {}).get("eventListings") or {}).get("data")) or []
                for item in listings:
                    ev = item.get("event") or {}
                    title = clean_html_text(ev.get("title") or "Noite Eletrónica")
                    venue_obj = ev.get("venue") or {}
                    v_name = clean_html_text(venue_obj.get("name") or "")
                    v_addr = clean_html_text(venue_obj.get("address") or "")

                    geo = match_venue(v_name, v_addr, require_match=True)
                    if not geo:
                        continue

                    start_iso = ev.get("startTime") or "23:59"
                    end_iso = ev.get("endTime") or ""
                    time_str, hour_int = parse_time_str(start_iso, "23:59")
                    if end_iso and "T" in end_iso:
                        end_t, end_h = parse_time_str(end_iso.split("T")[-1], "06:00")
                    else:
                        end_t, end_h = infer_end_time(time_str, hour_int, CATEGORY_PRESETS["nightlife"]["category"], geo["venue"], title, v_addr)

                    artists = [a.get("name") for a in (ev.get("artists") or []) if a.get("name")]
                    lineup_str = f" Lineup: {', '.join(artists[:6])}." if artists else ""
                    content_url = ev.get("contentUrl") or ""
                    full_url = f"https://pt.ra.co{content_url}" if content_url.startswith("/") else (geo.get("agenda_url") or geo.get("url"))
                    price_disp, price_tier = resolve_venue_default_price(geo["venue"], "Nightlife & Electronic")

                    events.append({
                        "id": f"ra-{ev.get('id') or abs(hash(title))}",
                        "title": title,
                        "category": CATEGORY_PRESETS["nightlife"]["category"],
                        "color": CATEGORY_PRESETS["nightlife"]["color"],
                        "icon": CATEGORY_PRESETS["nightlife"]["icon"],
                        "venue": geo["venue"],
                        "neighborhood": geo["neighborhood"],
                        "corridor": geo["corridor"],
                        "lat": geo["lat"],
                        "lng": geo["lng"],
                        "time": time_str,
                        "hour": hour_int,
                        "endTime": end_t,
                        "endHour": end_h,
                        "price": price_disp,
                        "priceTier": price_tier,
                        "url": full_url,
                        "description": f"{title} em {geo['venue']} ({geo['neighborhood']}).{lineup_str}",
                    })
        except Exception as e:
            print(f"[RA Scraper] Notice on area {area_id}: {e}")

    return events


def scrape_prior_velho_electronic(target_date):
    events = []
    next_date = target_date + datetime.timedelta(days=1)
    d_today_pat = rf"\b0?{target_date.day}/{target_date.month:02d}\b"
    d_next_pat = rf"\b0?{next_date.day}/{next_date.month:02d}\b"

    lisabout_urls = [
        "https://www.lisabout.com/events",
        "https://www.lisabout.com/zona/prior-velho",
        "https://www.lisabout.com/genero/dance-electronic",
    ]
    print(f"[Tier 3] Scraping Lisabout & Prior Velho hubs for {target_date.day:02d}/{target_date.month:02d}...")

    seen_hrefs = set()
    for url in lisabout_urls:
        try:
            resp = fetch_url(url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/events/"]'):
                href = a_tag.get("href", "")
                if not href or href in seen_hrefs:
                    continue
                card_text = clean_html_text(a_tag.get_text(" | ", strip=True))
                is_today = bool(re.search(d_today_pat, card_text))
                is_afterhours = bool(re.search(d_next_pat, card_text)) and bool(re.search(r"\b0[4-8]:[0-5]\d\b", card_text))
                if not (is_today or is_afterhours):
                    continue
                seen_hrefs.add(href)

                time_str, hour_int = parse_time_str(card_text, "23:59")
                title_el = a_tag.find(["h3", "h4", "strong"])
                title = clean_html_text(title_el.get_text(" ", strip=True)) if title_el else ""
                if not title:
                    parts = [p.strip() for p in card_text.split("|") if p.strip() and not re.search(r"\b\d{1,2}/\d{2}\b", p)]
                    title = parts[1] if len(parts) > 1 else (parts[0] if parts else "Evento Lisabout")

                v_seg = ""
                for seg in card_text.split("|"):
                    if "•" in seg and not re.search(r"\b\d{1,2}/\d{2}\b", seg):
                        sp = seg.split("•", 1)
                        if sp[0].strip():
                            v_seg = sp[0].strip()
                        break

                detail_url = urljoin("https://www.lisabout.com", href)
                ev_url = detail_url
                detail_text = ""
                outbound_ticket_url = ""
                ld_price_str = ""
                try:
                    d_resp = fetch_url(detail_url, timeout=10)
                    if d_resp.status_code == 200:
                        d_soup = BeautifulSoup(d_resp.text, "html.parser")
                        detail_text = clean_html_text(d_soup.get_text(" ", strip=True))
                        for ld_script in d_soup.find_all("script", type="application/ld+json"):
                            try:
                                ld_data = json.loads(ld_script.string or "")
                                ld_items = ld_data if isinstance(ld_data, list) else [ld_data]
                                for item in ld_items:
                                    if isinstance(item, dict) and item.get("@type") in ("MusicEvent", "Event"):
                                        loc = item.get("location") or {}
                                        if isinstance(loc, dict) and loc.get("name") and not v_seg:
                                            v_seg = clean_html_text(loc.get("name"))
                                        offers = item.get("offers") or {}
                                        if isinstance(offers, dict):
                                            p_val = offers.get("price") or offers.get("lowPrice")
                                            if p_val and str(p_val).replace(".", "").isdigit() and float(p_val) > 0:
                                                ld_price_str = f"{p_val}€"
                                            if offers.get("url"):
                                                cand = str(offers["url"]).strip()
                                                if "lisabout.com" not in cand and "ra.co" not in cand and "event-test" not in cand:
                                                    outbound_ticket_url = cand
                            except Exception:
                                pass
                        if not outbound_ticket_url:
                            for t_a in d_soup.find_all("a", href=True):
                                t_href = t_a["href"].strip()
                                if "event-test" in t_href.lower():
                                    continue
                                # Prefer direct working ticket platforms; keep Lisabout detail URL if ticket is on ra.co (avoids DataDome 403)
                                if any(tk in t_href for tk in ("shotgun.live", "xceed.me", "dice.fm", "3cket.com", "bol.pt", "ticketline", "eventbrite", "seetickets")):
                                    outbound_ticket_url = t_href
                                    break
                except Exception:
                    pass

                if outbound_ticket_url:
                    ev_url = outbound_ticket_url

                geo = match_venue(v_seg, title, card_text, require_match=True)
                if not geo and v_seg:
                    hit, name = locations.geocode_location(f"{v_seg}, Lisboa")
                    if hit:
                        geo = {
                            "venue": name or v_seg,
                            "lat": hit["lat"],
                            "lng": hit["lng"],
                            "neighborhood": locations.infer_neighborhood(hit["lat"], hit["lng"], hit.get("area")),
                            "corridor": locations.infer_corridor(hit["lat"], hit["lng"]),
                            "url": ev_url,
                        }
                if not geo:
                    continue

                default_cat = "nightlife" if ("dance-electronic" in url or "prior-velho" in url or hour_int >= 22 or hour_int < 6) else "concerts"
                preset = infer_category_preset(f"{title} {card_text} {detail_text}", default_cat)
                price_disp, price_tier = parse_price_and_tier(
                    f"{ld_price_str} {card_text} {detail_text}",
                    venue_name=geo["venue"],
                    category_name=preset["category"],
                )
                if outbound_ticket_url and price_tier == "FREE":
                    price_disp, price_tier = resolve_venue_default_price(geo["venue"], preset["category"])
                end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, card_text)

                events.append({
                    "id": f"pv-{href.strip('/').split('/')[-1]}",
                    "title": title,
                    "category": preset["category"],
                    "color": preset["color"],
                    "icon": preset["icon"],
                    "venue": geo["venue"],
                    "neighborhood": geo["neighborhood"],
                    "corridor": geo["corridor"],
                    "lat": geo["lat"],
                    "lng": geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": price_disp,
                    "priceTier": price_tier,
                    "url": ev_url,
                    "description": f"{title} em {geo['venue']} ({geo['neighborhood']}).",
                })
        except Exception as e:
            print(f"[Prior Velho Scraper] Notice on {url}: {e}")

    try:
        resp = fetch_url("https://www.moonclub.pt/")
        if resp.status_code == 200 and re.search(d_today_pat, resp.text):
            soup = BeautifulSoup(resp.text, "html.parser")
            geo = match_venue("moon club")
            for block in soup.find_all(["li", "div", "article"]):
                txt = clean_html_text(block.get_text(" ", strip=True))
                if re.search(d_today_pat, txt) and len(txt) < 300:
                    m_title = re.search(rf"{d_today_pat}.*?\d+%\s+([A-Z0-9\s—\-]+)", txt)
                    title = m_title.group(1).strip() if m_title else "Noite Moon Club — Prior Velho"
                    end_t, end_h = infer_end_time("23:59", 23, CATEGORY_PRESETS["nightlife"]["category"], geo["venue"], title, txt)
                    events.append({
                        "id": f"moonclub-{target_date.strftime('%Y%m%d')}",
                        "title": title,
                        "category": CATEGORY_PRESETS["nightlife"]["category"],
                        "color": CATEGORY_PRESETS["nightlife"]["color"],
                        "icon": CATEGORY_PRESETS["nightlife"]["icon"],
                        "venue": geo["venue"],
                        "neighborhood": geo["neighborhood"],
                        "corridor": geo["corridor"],
                        "lat": geo["lat"],
                        "lng": geo["lng"],
                        "time": "23:59",
                        "hour": 23,
                        "endTime": end_t,
                        "endHour": end_h,
                        "price": "10€ - 18€",
                        "priceTier": "ACCESSIBLE",
                        "url": "https://www.moonclub.pt",
                        "description": f"{title} no Moon Club (Rua Ary dos Santos 3, Prior Velho). Noite de techno e clubbing até ao nascer do sol.",
                    })
                    break
    except Exception as e:
        print(f"[Moon Club Scraper] Notice: {e}")

    # Direct Shotgun Lisbon & Venue pages (Titanic Sur Mer, Kømplex, NĀDA, cities/lisbon)
    shotgun_urls = [
        "https://shotgun.live/pt-pt/cities/lisbon",
        "https://shotgun.live/pt-pt/venues/titanic-sur-mer",
        "https://shotgun.live/pt-pt/venues/komplex",
        "https://shotgun.live/pt-pt/venues/nada-lisbon",
    ]
    sg_today_str = f"{target_date.day}/{target_date.month}"
    sg_next_str = f"{next_date.day}/{next_date.month}"
    seen_sg = set()
    for sg_u in shotgun_urls:
        try:
            r_sg = fetch_url(sg_u, timeout=10)
            if r_sg.status_code != 200:
                continue
            soup_sg = BeautifulSoup(r_sg.text, "html.parser")
            for a_sg in soup_sg.find_all("a", href=lambda h: h and "/events/" in h and "?" not in h):
                sg_href = a_sg.get("href", "").strip()
                if sg_href in seen_sg:
                    continue
                sg_txt = clean_html_text(a_sg.get_text(" | ", strip=True))
                if not sg_txt or sg_txt.lower() in ("obter bilhetes", "comprar"):
                    continue
                parts = [p.strip() for p in sg_txt.split("|") if p.strip()]
                if len(parts) < 3:
                    continue
                # Check if card date is today (e.g. '7/11') or tomorrow afterhours ('8/11' with 04:00-08:00)
                has_sg_today = any(re.search(rf"\b0?{re.escape(sg_today_str)}\b", p) for p in parts)
                has_sg_next = any(re.search(rf"\b0?{re.escape(sg_next_str)}\b", p) for p in parts) and bool(re.search(r"\b0[4-8]:[0-5]\d\b", sg_txt))
                if not (has_sg_today or has_sg_next):
                    continue
                seen_sg.add(sg_href)
                p_el = a_sg.find("p")
                sg_title = clean_html_text(p_el.get_text(" ", strip=True)) if p_el else parts[0]
                sg_venue_cand = " ".join(parts[1:3])
                geo_sg = match_venue(sg_venue_cand, sg_u.replace("-", " "), require_match=True)
                if not geo_sg:
                    continue
                t_str, h_int = parse_time_str(sg_txt, "23:59")
                preset_sg = infer_category_preset(f"{sg_title} {sg_txt}", "nightlife" if (h_int >= 22 or h_int <= 8) else "concerts")
                p_disp, p_tier = parse_price_and_tier(sg_txt.replace(",", "."), venue_name=geo_sg["venue"], category_name=preset_sg["category"])
                end_t, end_h = infer_end_time(t_str, h_int, preset_sg["category"], geo_sg["venue"], sg_title, sg_txt)
                full_sg_url = urljoin("https://shotgun.live", sg_href)
                events.append({
                    "id": f"sg-{sg_href.strip('/').split('/')[-1][:32]}",
                    "title": sg_title,
                    "category": preset_sg["category"],
                    "color": preset_sg["color"],
                    "icon": preset_sg["icon"],
                    "venue": geo_sg["venue"],
                    "neighborhood": geo_sg["neighborhood"],
                    "corridor": geo_sg["corridor"],
                    "lat": geo_sg["lat"],
                    "lng": geo_sg["lng"],
                    "time": t_str,
                    "hour": h_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": p_disp,
                    "priceTier": p_tier,
                    "url": full_sg_url,
                    "description": f"{sg_title} em {geo_sg['venue']} ({geo_sg['neighborhood']}). Bilhetes via Shotgun.",
                })
        except Exception as e:
            print(f"[Shotgun Venue Scraper] Notice on {sg_u}: {e}")

    return events


# ==============================================================================
# TIER 3.5: ARTS & CRAFTS, MARKETS, WORKSHOPS & LECTURES SCRAPER
# ==============================================================================
def scrape_markets_workshops_lectures(target_date):
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"[Tier 3.5] Scraping Arts & Crafts, Markets, Workshops & Lectures for {date_str}...")

    try:
        resp = fetch_url("https://fica-oc.pt/workshops/")
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            geo = match_venue("fica oficina criativa")
            seen_fica = set()
            for a_tag in soup.select('a[href*="/produto/"], a[href*="/workshop/"]'):
                href = a_tag.get("href", "")
                if not href or href in seen_fica:
                    continue
                card = a_tag.find_parent(["li", "div", "article"]) or a_tag
                txt = clean_html_text(card.get_text(" ", strip=True))
                if not matches_portuguese_date_or_range(txt, target_date):
                    continue
                seen_fica.add(href)
                h_el = card.find(["h2", "h3", "h4"])
                title = clean_html_text(h_el.get_text(" ", strip=True) if h_el else a_tag.get_text(" ", strip=True))
                if not title or len(title) < 4:
                    continue
                time_str, hour_int = parse_time_str(txt, "14:30")
                price_disp, price_tier = parse_price_and_tier(txt, "35€ - 55€", "MID")
                end_t, end_h = infer_end_time(time_str, hour_int, CATEGORY_PRESETS["community"]["category"], geo["venue"], title, txt)
                events.append({
                    "id": f"fica-{abs(hash(href)) % 100000}",
                    "title": f"Oficina FICA: {title}",
                    "category": CATEGORY_PRESETS["community"]["category"],
                    "color": CATEGORY_PRESETS["community"]["color"],
                    "icon": CATEGORY_PRESETS["community"]["icon"],
                    "venue": geo["venue"],
                    "neighborhood": geo["neighborhood"],
                    "corridor": geo["corridor"],
                    "lat": geo["lat"],
                    "lng": geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": price_disp,
                    "priceTier": price_tier,
                    "url": urljoin("https://fica-oc.pt", href),
                    "description": f"Oficina prática de artes e ofícios ({title}) na FICA — Oficina Criativa (LX Factory, Alcântara).",
                })
    except Exception as e:
        print(f"[FICA Workshops] Notice: {e}")

    try:
        resp = fetch_url("https://largoresidencias.com")
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            geo = match_venue("jardins do bombarda")
            seen_jb = set()
            for card in soup.find_all(["article", "div", "li"]):
                txt = clean_html_text(card.get_text(" ", strip=True))
                if len(txt) < 25 or len(txt) > 900:
                    continue
                if not matches_portuguese_date_or_range(txt, target_date):
                    continue
                h_el = card.find(["h2", "h3", "h4", "strong"])
                title = clean_html_text(h_el.get_text(" ", strip=True) if h_el else "")
                if not title or len(title) < 5 or title.lower() in seen_jb:
                    continue
                seen_jb.add(title.lower())
                preset = infer_category_preset(f"{title} {txt}", "community")
                time_str, hour_int = parse_time_str(txt, "16:00")
                price_disp, price_tier = parse_price_and_tier(txt, "Entrada Livre", "FREE")
                end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, txt)
                events.append({
                    "id": f"bombarda-{abs(hash(title)) % 100000}",
                    "title": f"{title} — Jardins do Bombarda",
                    "category": preset["category"],
                    "color": preset["color"],
                    "icon": preset["icon"],
                    "venue": geo["venue"],
                    "neighborhood": geo["neighborhood"],
                    "corridor": geo["corridor"],
                    "lat": geo["lat"],
                    "lng": geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": price_disp,
                    "priceTier": price_tier,
                    "url": "https://largoresidencias.com/",
                    "description": f"{title} nos Jardins do Bombarda / LARGO Residências (Rua Gomes Freire, Arroios).",
                })
    except Exception as e:
        print(f"[Jardins do Bombarda] Notice: {e}")

    return events


# ==============================================================================
# TIER 3.8: VIRALAGENDA DYNAMIC DAILY SCRAPER (STRICT LISBON MUNICIPALITY)
# ==============================================================================
def scrape_viralagenda(target_date):
    events = []
    dd_mm_yyyy = target_date.strftime("%d-%m-%Y")
    print(f"[Tier 3.8] Scraping ViralAgenda for {dd_mm_yyyy} (/pt/lisboa/{dd_mm_yyyy})...")

    url = f"https://www.viralagenda.com/pt/lisboa/{dd_mm_yyyy}"
    seen_va = set()
    skip_titles_norm = (
        "alma portuguesa pelas ruas de lisboa", "timeless experiences",
        "lisboa (cidade)", "hop-on", "tuk tuk", "free walking tour",
        "serra da estrela", "rota das faias", "rota dos castanheiros",
    )

    try:
        resp = fetch_url(url)
        if resp.status_code != 200:
            return events
        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select("li.viral-event, .viral-event"):
            # Strictly require Lisbon municipality link (/pt/lisboa/lisboa) on the card
            if not card.find("a", href=lambda h: h and "/pt/lisboa/lisboa" in h):
                continue

            title_el = card.select_one(".viral-event-title, h2, h3, h4, a[itemprop='url']")
            title = clean_html_text(title_el.get_text(" ", strip=True) if title_el else "")
            if not title or len(title) < 4:
                continue
            if any(sk in strip_accents(title) for sk in skip_titles_norm):
                continue

            data_url = card.get("data-url", "")
            if not data_url:
                a_ev = card.select_one("a[href*='/events/']")
                data_url = a_ev.get("href", "") if a_ev else ""
            full_url = urljoin("https://www.viralagenda.com", data_url) if data_url else url
            if full_url in seen_va:
                continue
            seen_va.add(full_url)

            venue_el = card.select_one(".viral-event-place, [itemprop='location'], .place, .venue")
            venue_hint = clean_html_text(venue_el.get_text(" ", strip=True) if venue_el else "")
            v_hint_norm = strip_accents(venue_hint)
            if not venue_hint or any(bad_v in v_hint_norm for bad_v in ("lisboa (cidade)", "sem geo-localizacao", "gare do oriente")):
                continue

            time_el = card.select_one(".viral-event-hour")
            raw_card_time = clean_html_text(time_el.get_text(" ", strip=True) if time_el else "")
            txt = clean_html_text(card.get_text(" | ", strip=True))

            # Fetch detail page to get address, description, price, and exact hours if N/D
            detail_text = ""
            addr_str = ""
            outbound_url = ""
            try:
                if "/events/" in full_url:
                    d_resp = fetch_url(full_url, timeout=8)
                    if d_resp.status_code == 200:
                        d_soup = BeautifulSoup(d_resp.text, "html.parser")
                        detail_text = clean_html_text(d_soup.get_text(" ", strip=True))
                        for script in d_soup.find_all("script", type="application/ld+json"):
                            try:
                                ld = json.loads(script.string or "")
                                items = ld.get("@graph", [ld]) if isinstance(ld, dict) else ld
                                for it in items:
                                    if isinstance(it, dict) and it.get("@type") == "Event":
                                        loc = it.get("location") or {}
                                        if isinstance(loc, dict):
                                            addr_obj = loc.get("address") or {}
                                            if isinstance(addr_obj, dict):
                                                addr_str = clean_html_text(addr_obj.get("streetAddress", ""))
                                            elif isinstance(addr_obj, str):
                                                addr_str = clean_html_text(addr_obj)
                            except Exception:
                                pass
                        for ext_a in d_soup.select("a[href^='http']"):
                            eh = ext_a.get("href", "").strip()
                            if "viralagenda.com" not in eh and not any(b in eh for b in ("itunes.apple", "play.google", "facebook.com/sharer", "twitter.com")):
                                if any(g in eh for g in ("agendalx.pt/events/event/", "bol.pt", "ticketline.pt", "shotgun.live", "ccb.pt", "gulbenkian.pt", "8marvila.com", "maat.pt")):
                                    outbound_url = eh
                                    break
            except Exception:
                pass

            geo = match_venue(venue_hint, addr_str, require_match=True)
            if not geo:
                q_str = f"{venue_hint}, {addr_str}, Lisboa" if addr_str else f"{venue_hint}, Lisboa"
                hit, name = locations.geocode_location(q_str)
                if hit:
                    geo = {
                        "venue": venue_hint,
                        "lat": hit["lat"],
                        "lng": hit["lng"],
                        "neighborhood": locations.infer_neighborhood(hit["lat"], hit["lng"], hit.get("area")),
                        "corridor": locations.infer_corridor(hit["lat"], hit["lng"]),
                        "url": outbound_url or full_url,
                    }
            if not geo:
                continue

            preset = infer_category_preset(f"{title} {venue_hint} {txt}", "community")
            def_t, def_h = resolve_venue_default_hours(geo["venue"], preset["category"], target_date.weekday())

            if raw_card_time and "N/D" not in raw_card_time:
                time_str, hour_int = parse_time_str(raw_card_time, def_t)
            else:
                time_str, hour_int = def_t, def_h

            price_disp, price_tier = parse_price_and_tier(
                f"{txt} {detail_text}",
                venue_name=geo["venue"],
                category_name=preset["category"],
            )
            end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, f"{raw_card_time} {detail_text}")

            events.append({
                "id": f"va-card-{abs(hash(full_url)) % 1000000}",
                "title": title,
                "category": preset["category"],
                "color": preset["color"],
                "icon": preset["icon"],
                "venue": geo["venue"],
                "neighborhood": geo["neighborhood"],
                "corridor": geo["corridor"],
                "lat": geo["lat"],
                "lng": geo["lng"],
                "time": time_str,
                "hour": hour_int,
                "endTime": end_t,
                "endHour": end_h,
                "price": price_disp,
                "priceTier": price_tier,
                "url": outbound_url or full_url,
                "description": f"{title} em {geo['venue']} ({geo['neighborhood']}).",
            })
    except Exception as e:
        print(f"[ViralAgenda] Notice on {url}: {e}")

    print(f"[Tier 3.8] ViralAgenda extracted {len(events)} events for {dd_mm_yyyy}.")
    return events


# ==============================================================================
# TIER 3.9: SOKO.FYI, THE CURATED LISBON & CÁPSULA MELÓDICA SCRAPER
# ==============================================================================
SOKO_LISBON_VENUE_SLUGS = [
    "livraria-bar-menina-e-moca-zrc2ts",
    "bota-base-organizada-da-toca-das-artes-6hdgvp",
    "anjos-70-sede-ntyz9y",
    "galeria-ze-dos-bois-eyqtdd",
    "casa-independente-4duvmb",
    "jardins-do-bombarda-mzpthn",
    "arroz-estudios-2t4cc4",
    "casa-capitao-7tepkj",
    "zdb-8-marvila-9dsej2",
    "musa-de-marvila-dkc4nw",
    "well-read-nqqx52",
    "casa-do-comum-n4ncjd",
    "livraria-da-travessa-f9e857",
    "maat-museu-de-arte-arquitetura-e-tecnologia-adu7aw",
    "culturgest-4kxu7x",
    "cinema-ideal-5hzx8f",
    "cinemateca-portuguesa-museu-do-cinema-frq7hk",
    "galeria-underdogs-gs8yka",
    "appleton-square-bw94p6",
    "fabrica-de-braco-de-prata-epmnp2",
    "museu-nacional-de-arte-contemporanea-mnac-3mpg9e",
    "sala-manoel-de-oliveira-cinema-de-sao-jorge-npj763",
    "ruby-rosa-lisbon-art-stay-szv4kp",
    "ministerium-trfstf",
    "tokyo-lisboa-xv8nzt",
    "b-leza-club-ec7eeg",
    "titanic-sur-mer-gxcb85",
    "lisboa-rio-club-6zgb7q",
    "teatro-do-bairro-alto-f3722s",
    "centro-cultural-de-belem-7yv6b3",
    "fundacao-calouste-gulbenkian-nmcg58",
]


def _validate_soko_external_url(ev_link, v_url, geo):
    """
    Validates external ticketing links from Soko.fyi:
    - Rejects BOL links whose <title> says [REALIZADO] (event already occurred in the past!).
    - Rejects Ticketline links that redirect to the generic Ticketline homepage (expired session!).
    - Replaces raw instagram.com/p/ post URLs (which often 404 or hit login walls) with the public Soko venue page `v_url`.
    Returns (is_valid_event: bool, clean_url: str, price_hint: str).
    """
    if not ev_link or not ev_link.startswith("http"):
        return True, v_url, ""

    low_u = ev_link.lower()
    if "instagram.com/p/" in low_u or "instagram.com/reel/" in low_u:
        return True, v_url, ""

    if "bol.pt/" in low_u or "ticketline." in low_u:
        try:
            r = fetch_url(ev_link, timeout=8)
            if r.status_code >= 400:
                return False, v_url, ""
            final_u = str(getattr(r, "url", ev_link)).lower()
            if "ticketline." in low_u and final_u.rstrip("/") in ("https://www.ticketline.pt", "https://ticketline.sapo.pt", "https://www.ticketline.sapo.pt"):
                return False, v_url, ""
            soup = BeautifulSoup(r.text, "html.parser")
            page_title = clean_html_text(soup.title.string if soup.title and soup.title.string else "")
            if "[realizado]" in page_title.lower() or "evento realizado" in page_title.lower():
                return False, v_url, ""
            body_txt = clean_html_text(soup.get_text(" ", strip=True))
            return True, ev_link, body_txt
        except Exception:
            return True, v_url, ""

    return True, ev_link, ""


def scrape_soko_curated_capsula(target_date):
    events = []
    iso_date = target_date.strftime("%Y-%m-%d")
    next_iso = (target_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"[Tier 3.9] Scraping Soko.fyi, THE CURATED Lisbon & Cápsula Melódica for {iso_date}...")

    soko_slugs = list(SOKO_LISBON_VENUE_SLUGS)
    try:
        resp = fetch_url("https://heyl-backend-production.onrender.com/api/v1/public/site/venue-showcase?locale=pt", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("items", []):
                slug = (item.get("venue") or {}).get("slug", "")
                if slug and slug not in soko_slugs:
                    soko_slugs.append(slug)
    except Exception as e:
        print(f"[Soko Showcase API] Notice: {e}")

    seen_soko = set()

    def _fetch_soko_slug(slug):
        v_url = f"https://soko.fyi/pt/venues/{slug}"
        slug_events = []
        try:
            resp = fetch_url(v_url, timeout=8)
            if resp.status_code != 200:
                return slug_events
            soup = BeautifulSoup(resp.text, "html.parser")
            for ld_script in soup.find_all("script", type="application/ld+json"):
                ld_data = json.loads(ld_script.string or "{}")
                graph = ld_data.get("@graph", []) if isinstance(ld_data, dict) else []
                for node in graph:
                    if not isinstance(node, dict) or node.get("@type") != "LocalBusiness":
                        continue
                    addr_str = str((node.get("address") or {}).get("streetAddress", ""))
                    if "lisboa" not in strip_accents(addr_str) and "lisbon" not in strip_accents(addr_str):
                        continue
                    v_name = clean_html_text(node.get("name", ""))
                    geo_node = node.get("geo") or {}
                    s_lat = geo_node.get("latitude")
                    s_lng = geo_node.get("longitude")
                    geo = match_venue(v_name, addr_str, require_match=True)
                    if not geo:
                        if not s_lat or not s_lng:
                            continue
                        lat_f, lng_f = round(float(s_lat), 5), round(float(s_lng), 5)
                        if not locations.in_lisbon(lat_f, lng_f):
                            continue
                        geo = {
                            "venue": v_name or "Lisboa",
                            "lat": lat_f,
                            "lng": lng_f,
                            "neighborhood": locations.infer_neighborhood(lat_f, lng_f),
                            "corridor": locations.infer_corridor(lat_f, lng_f),
                            "url": v_url,
                        }
                    for ev in node.get("event", []):
                        if not isinstance(ev, dict):
                            continue
                        start_raw = str(ev.get("startDate", ""))
                        is_today = start_raw.startswith(iso_date)
                        is_afterhours = start_raw.startswith(next_iso) and bool(re.search(r"T0[1-5]:", start_raw))
                        if not (is_today or is_afterhours):
                            continue
                        ev_title = clean_html_text(ev.get("name", ""))
                        if not ev_title or len(ev_title) < 3:
                            continue
                        ev_link = str(ev.get("url") or v_url).strip()
                        dedup_k = f"{geo['venue'].lower()}|{ev_title.lower()}"

                        is_valid_ev, clean_link, ticket_txt = _validate_soko_external_url(ev_link, v_url, geo)
                        if not is_valid_ev:
                            continue

                        t_match = re.search(r"T(\d{2}:\d{2})", start_raw)
                        extracted_t = t_match.group(1) if t_match else ""

                        v_norm_soko = strip_accents(geo["venue"])
                        default_soko_cat = "community"
                        if any(k in v_norm_soko for k in ("cinema", "cinemateca", "nimas")):
                            default_soko_cat = "cinema"
                        elif any(k in v_norm_soko for k in ("teatro", "tba")):
                            default_soko_cat = "theatre"
                        elif any(k in v_norm_soko for k in ("ministerium", "lux", "b.leza", "lisboa rio", "incognito", "musicbox", "komplex", "kømplex", "nada", "moon club", "trumps")):
                            default_soko_cat = "nightlife"
                        elif any(k in v_norm_soko for k in ("maat", "culturgest", "mnac", "underdogs", "appleton", "cam -", "gulbenkian", "ze dos bois", "zdb")):
                            if not extracted_t or extracted_t == "00:00" or int(extracted_t.split(":")[0]) < 20:
                                default_soko_cat = "exhibitions"
                            else:
                                default_soko_cat = "concerts"
                        elif any(k in v_norm_soko for k in ("tokyo", "casa capitao", "titanic", "bota", "casa independente", "braco de prata", "musa")):
                            default_soko_cat = "nightlife" if (extracted_t and int(extracted_t.split(":")[0]) >= 23) else "concerts"

                        preset = infer_category_preset(f"{ev_title} {v_name}", default_soko_cat)
                        def_t, def_h = resolve_venue_default_hours(geo["venue"], preset["category"], target_date.weekday())

                        if not extracted_t or extracted_t == "00:00":
                            time_str, hour_int = def_t, def_h
                        else:
                            time_str, hour_int = parse_time_str(extracted_t, def_t)

                        price_disp, price_tier = parse_price_and_tier(
                            f"{ev_title} {ticket_txt}",
                            venue_name=geo["venue"],
                            category_name=preset["category"],
                        )
                        end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], ev_title, "")

                        slug_events.append((dedup_k, {
                            "id": f"soko-{abs(hash(dedup_k)) % 1000000}",
                            "title": ev_title,
                            "category": preset["category"],
                            "color": preset["color"],
                            "icon": preset["icon"],
                            "venue": geo["venue"],
                            "neighborhood": geo["neighborhood"],
                            "corridor": geo["corridor"],
                            "lat": geo["lat"],
                            "lng": geo["lng"],
                            "time": time_str,
                            "hour": hour_int,
                            "endTime": end_t,
                            "endHour": end_h,
                            "price": price_disp,
                            "priceTier": price_tier,
                            "url": clean_link,
                            "description": f"{ev_title} em {geo['venue']} ({geo['neighborhood']}). Curadoria Soko Lisboa.",
                        }))
        except Exception:
            pass
        return slug_events

    with ThreadPoolExecutor(max_workers=6) as soko_pool:
        for slug_evs in soko_pool.map(_fetch_soko_slug, soko_slugs):
            for dedup_k, ev_obj in slug_evs:
                if dedup_k not in seen_soko:
                    seen_soko.add(dedup_k)
                    events.append(ev_obj)

    # 2. THE CURATED LISBON (https://thecuratedlisbon.com/)
    curated_urls = [
        "https://thecuratedlisbon.com/curated-selection-20",
        "https://thecuratedlisbon.com/the-creative-series",
        "https://thecuratedlisbon.com/exhibition-quiet-objects",
        "https://thecuratedlisbon.com/exhibition-female",
        "https://thecuratedlisbon.com/artwalks",
        "https://thecuratedlisbon.com/experiences",
    ]
    for c_url in curated_urls:
        try:
            resp = fetch_url(c_url, timeout=10)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            page_txt = clean_html_text(soup.get_text(" ", strip=True))
            if "comporta" in strip_accents(page_txt) and "lisbon" not in strip_accents(page_txt) and "lisboa" not in strip_accents(page_txt):
                continue
            if not matches_portuguese_date_or_range(page_txt, target_date):
                continue
            h_el = soup.find(["h1", "h2", "title"])
            raw_title = clean_html_text(h_el.get_text(" ", strip=True) if h_el else "THE CURATED Lisbon")
            title = raw_title if "curated" in raw_title.lower() else f"THE CURATED Lisbon: {raw_title}"
            geo = match_venue(page_txt, "the curated lisbon", require_match=False)
            preset = infer_category_preset(f"{title} {page_txt}", "exhibitions")
            price_disp, price_tier = parse_price_and_tier(page_txt, "Entrada Livre", "FREE")
            events.append({
                "id": f"curated-{abs(hash(c_url)) % 100000}",
                "title": title,
                "category": preset["category"],
                "color": preset["color"],
                "icon": preset["icon"],
                "venue": geo["venue"],
                "neighborhood": geo["neighborhood"],
                "corridor": geo["corridor"],
                "lat": geo["lat"],
                "lng": geo["lng"],
                "time": "11:00",
                "hour": 11,
                "endTime": "20:00",
                "endHour": 20,
                "price": price_disp,
                "priceTier": price_tier,
                "url": c_url,
                "description": f"{title} — exposição e programação artística por THE CURATED Lisbon em {geo['venue']} ({geo['neighborhood']}).",
            })
        except Exception as e:
            print(f"[The Curated Lisbon] Notice on {c_url}: {e}")

    print(f"[Tier 3.9] Soko / THE CURATED Lisbon extracted {len(events)} events.")
    return events


# ==============================================================================
# TIER 4: RECURRING LISBON MARKETS & CULTURAL LANDMARKS
# ==============================================================================
def get_ongoing_cultural_events(target_date):
    """
    Day-of-week-aware recurring Lisbon street markets, craft fairs, and flagship museum
    exhibitions with verified URLs, opening hours, and admission prices.
    """
    ymd = target_date.strftime("%Y%m%d")
    weekday = target_date.weekday()  # 0=Mon ... 5=Sat, 6=Sun
    ongoing = []

    def add_item(idx, title, cat_key, venue_alias, time_str, end_str, price, tier, url, desc):
        geo = match_venue(venue_alias)
        if not geo:
            return
        p = CATEGORY_PRESETS[cat_key]
        ongoing.append({
            "id": f"ongoing-{ymd}-{idx}",
            "title": title,
            "category": p["category"],
            "color": p["color"],
            "icon": p["icon"],
            "venue": geo["venue"],
            "neighborhood": geo["neighborhood"],
            "corridor": geo["corridor"],
            "lat": geo["lat"],
            "lng": geo["lng"],
            "time": time_str,
            "hour": int(time_str.split(":")[0]),
            "endTime": end_str,
            "endHour": int(end_str.split(":")[0]),
            "price": price,
            "priceTier": tier,
            "url": url,
            "description": desc,
        })

    # Recurring Markets (Tue/Sat Feira da Ladra, Sat Príncipe Real, Weekend Estrela & Santa Clara)
    if weekday in (1, 5):
        add_item(1, "Feira da Ladra — Mercado Histórico de Antiguidades, Artesanato e Vinil", "community",
                 "feira da ladra", "09:00", "17:00", "Entrada Livre", "FREE",
                 "https://www.visitlisboa.com/pt-pt/locais/feira-da-ladra",
                 "O mercado de rua mais antigo de Lisboa no Campo de Santa Clara (terças e sábados, das 09:00 às 17:00).")
    if weekday == 5:
        add_item(2, "Mercado Biológico e Feira de Pequenos Produtores no Príncipe Real", "community",
                 "jardim do principe real", "09:30", "15:00", "Entrada Livre", "FREE",
                 "https://www.agendalx.pt/",
                 "Mercado biológico ao ar livre todos os sábados sob o cedro do Jardim do Príncipe Real.")
    if weekday in (5, 6):
        add_item(3, "Mercado Crafts & Design no Jardim da Estrela", "community",
                 "jardim da estrela", "10:00", "18:00", "Entrada Livre", "FREE",
                 "https://www.agendalx.pt/",
                 "Mercado de autor, cerâmica, ilustração, joalharia e design independente no Jardim da Estrela.")
        add_item(4, "Feira de Artesãos, Vintage, Zines e Criadores na LX Factory", "community",
                 "lx factory", "10:30", "20:00", "Entrada Livre", "FREE",
                 "https://lxfactory.com/",
                 "Ateliers abertos, bancas de artesãos, edições independentes e Livraria Ler Devagar na antiga fábrica de Alcântara.")

    # Major Cultural Landmarks & Science Centers (Verified Opening Days & Prices)
    add_item(5, "Câmara Escura (Periscópio Ótico) & Visitas ao Castelo de São Jorge", "exhibitions",
             "castelo de sao jorge", "09:00", "18:00", "15.00€", "ACCESSIBLE",
             "https://castelodesaojorge.pt/",
             "Observação de Lisboa a 360º em tempo real na Câmara Escura e visitas patrimoniais ao Castelo de São Jorge.")
    add_item(6, "Na Onda do Oceano — Florestas Submersas & Habitats Marinhos", "family",
             "oceanario de lisboa", "10:00", "19:00", "15€ - 25€", "MID",
             "https://www.oceanario.pt/",
             "Percurso imersivo pelos oceanos e habitats marinhos no Oceanário de Lisboa (Parque das Nações).")
    add_item(7, "Encontros da Vida Selvagem, Baía dos Golfinhos & Reptilário", "family",
             "jardim zoologico", "10:00", "18:00", "18€ - 27€", "MID",
             "https://www.zoo.pt/",
             "Apresentações educativas diárias e conservação da biodiversidade no Jardim Zoológico de Lisboa (Sete Rios).")

    if weekday != 1:  # Closed Tuesdays
        add_item(8, "Xerazade, a Coleção Interminável do CAM & Jardins Gulbenkian", "exhibitions",
                 "cam gulbenkian", "10:00", "18:00", "10.00€", "ACCESSIBLE",
                 "https://gulbenkian.pt/cam/agenda/",
                 "Exposições de arte moderna e contemporânea no renovado CAM Gulbenkian (aberto qua–seg).")

    if weekday != 0:  # Closed Mondays
        add_item(9, "Design Português, Moda e Arquitetura no MUDE", "exhibitions",
                 "mude", "10:00", "19:00", "11.00€", "ACCESSIBLE",
                 "https://www.mude.pt/",
                 "Exposições de design industrial, gráfico e moda no MUDE — Museu do Design (Rua Augusta, Baixa).")
        add_item(10, "A Biblioteca Particular de Fernando Pessoa & Exposições Literárias", "community",
                 "casa fernando pessoa", "10:00", "18:00", "6.00€", "ACCESSIBLE",
                 "https://www.casafernandopessoa.pt/",
                 "Visita à casa e biblioteca particular de Fernando Pessoa em Campo de Ourique.")
        add_item(11, "Coleção Real de Viaturas de Gala no Museu Nacional dos Coches", "exhibitions",
                 "museu nacional dos coches", "10:00", "18:00", "8.00€", "ACCESSIBLE",
                 "https://www.mncoches.gov.pt/",
                 "Exposição permanente de coches e carruagens reais dos séculos XVI a XIX em Belém.")
        add_item(12, "Japão: Festas e Rituais & Coleção Kwok On no Museu do Oriente", "exhibitions",
                 "museu do oriente", "10:00", "18:00", "8.00€", "ACCESSIBLE",
                 "https://www.foriente.pt/",
                 "Exposições de artes performativas e património asiático no Museu do Oriente (Alcântara).")

    if weekday != 6:  # Closed Sundays
        add_item(13, "A Semente dos Livros — Exposição Fundação José Saramago", "exhibitions",
                 "casa dos bicos", "10:00", "18:00", "4.00€", "ACCESSIBLE",
                 "https://www.josesaramago.org/",
                 "Exposição permanente sobre a vida e obra de José Saramago na histórica Casa dos Bicos (Alfama).")

    return ongoing


def apply_coordinate_jitter(events):
    """Applies a tight golden-angle spiral offset (~7m) when multiple events share the same venue coordinates."""
    seen = {}
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    for ev in events:
        lat = ev.get("lat")
        lng = ev.get("lng")
        if lat is None or lng is None:
            continue
        key = (round(float(lat), 5), round(float(lng), 5))
        idx = seen.get(key, 0)
        seen[key] = idx + 1
        if idx > 0:
            r = 0.00007 * math.sqrt(idx)
            theta = idx * golden_angle
            new_lat = round(float(lat) + r * math.cos(theta), 6)
            new_lng = round(float(lng) + r * math.sin(theta), 6)
            ev["lat"] = min(38.805, max(38.690, new_lat))
            ev["lng"] = min(-9.085, max(-9.235, new_lng))
    return events


_DEDUP_STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "para", "com", "por", "um", "uma", "e", "ou", "ao", "aos", "vivo", "live", "concerto",
    "unico", "regressa", "regressam", "portugal", "lisboa", "apresenta", "apresentam",
    "novo", "nova", "disco", "album", "tour", "digressao", "espetaculo", "sessao",
    "teatro", "arena", "meo", "altice", "club", "clube", "festival", "edicao", "convida",
}


def _core_title_signature(title, venue=""):
    norm_t = re.sub(r"[^a-z0-9\s]", " ", strip_accents(title or ""))
    norm_v = re.sub(r"[^a-z0-9\s]", " ", strip_accents(venue or ""))
    venue_tokens = {w for w in norm_v.split() if len(w) > 2}
    tokens = [
        w for w in norm_t.split()
        if len(w) >= 2 and w not in _DEDUP_STOPWORDS and w not in venue_tokens
    ]
    if not tokens:
        tokens = [w for w in norm_t.split() if w]
    return " ".join(tokens)


def _event_op_minutes(ev):
    t = str(ev.get("time", "21:00"))
    parts = t.split(":")
    try:
        h = int(parts[0]) % 24
        m = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        h = int(ev.get("hour", 21)) % 24
        m = 0
    if h <= 6:
        h += 24
    return h * 60 + m


def _event_quality_score(ev):
    score = 0
    if str(ev.get("id", "")).startswith("ongoing-"):
        score -= 3
    price = str(ev.get("price", "")).lower()
    if "€" in price or "livre" in price:
        score += 4
    desc = str(ev.get("description", ""))
    if len(desc) > 65 and "Curadoria Soko" not in desc:
        score += 3
    title = str(ev.get("title", ""))
    if not title.isupper() and " @ " not in title:
        score += 3

    hour = int(ev.get("hour", 21))
    if 18 <= hour <= 23 or 0 <= hour <= 4:
        score += 2
    elif hour < 10 and ev.get("category") in ("Concerts & Live Music", "Nightlife & Electronic", "Theatre & Comedy"):
        score -= 6

    url = ev.get("url", "").lower()
    if any(plat in url for plat in ["shotgun.live", "3cket.com", "zedosbois.org", "bol.pt", "ticketline.pt", "ccb.pt", "culturgest.pt", "gulbenkian.pt", "tndm.pt", "teatrosaoluiz.pt", "agendalx.pt/events/event/", "cartazculturallisboa.pt/evento/"]):
        score += 4
    elif "nocartaz.pt" in url:
        score -= 1

    return score


def _merge_event_pair(existing, candidate):
    """Merges two duplicate events at the same venue, keeping the highest-quality fields from both."""
    if _event_quality_score(candidate) > _event_quality_score(existing):
        winner, loser = dict(candidate), existing
    else:
        winner, loser = dict(existing), candidate

    # Inherit explicit euro price if winner only has generic/range fallback
    w_price = str(winner.get("price", ""))
    l_price = str(loser.get("price", ""))
    if ("Consultar" in w_price or "Ver no link" in w_price or " - " in w_price) and ("€" in l_price and " - " not in l_price):
        winner["price"] = loser["price"]
        winner["priceTier"] = loser["priceTier"]
    elif ("Consultar" in w_price or "Ver no link" in w_price) and ("€" in l_price or "Livre" in l_price):
        winner["price"] = loser["price"]
        winner["priceTier"] = loser["priceTier"]

    # Inherit better direct URL if winner points to generic aggregator
    w_url = str(winner.get("url", "")).lower()
    l_url = str(loser.get("url", "")).lower()
    if any(g in w_url for g in ("nocartaz.pt", "soko.fyi/pt/venues/")) and not any(g in l_url for g in ("nocartaz.pt", "soko.fyi/pt/venues/")):
        winner["url"] = loser["url"]

    # Inherit longer, more informative description
    if len(str(loser.get("description", ""))) > len(str(winner.get("description", ""))) + 20 and "Curadoria Soko" not in str(loser.get("description", "")):
        winner["description"] = loser["description"]

    return winner


def deduplicate_events(events):
    seen_exact = set()
    unique = []
    non_lisbon_markers = ("queer porto", "no porto", "em coimbra", "em braga", "em faro", "em aveiro", "sabrosa")

    for ev in events:
        norm_title = strip_accents(ev.get("title", ""))
        if any(m in norm_title for m in non_lisbon_markers):
            continue

        venue_norm = strip_accents(ev.get("venue", "")).strip()
        exact_key = f"{venue_norm}|{norm_title[:24]}|{ev.get('time', '')}"
        if exact_key in seen_exact:
            continue
        seen_exact.add(exact_key)

        sig = _core_title_signature(ev.get("title", ""), ev.get("venue", ""))
        tokens = set(sig.split())
        ev_mins = _event_op_minutes(ev)
        ev_lat = round(float(ev.get("lat", 0)), 4)
        ev_lng = round(float(ev.get("lng", 0)), 4)
        ev_is_nc_stub = ev.get("id", "").startswith("nocartaz-") and " @ " in ev.get("title", "")

        duplicate_idx = None
        for idx, existing in enumerate(unique):
            ex_venue = strip_accents(existing.get("venue", "")).strip()
            ex_lat = round(float(existing.get("lat", 0)), 4)
            ex_lng = round(float(existing.get("lng", 0)), 4)

            same_loc = (ex_venue == venue_norm) or (ex_lat > 0 and abs(ex_lat - ev_lat) <= 0.0005 and abs(ex_lng - ev_lng) <= 0.0005)
            if not same_loc:
                continue

            ex_sig = _core_title_signature(existing.get("title", ""), existing.get("venue", ""))
            ex_tokens = set(ex_sig.split())
            ex_mins = _event_op_minutes(existing)
            ex_is_nc_stub = existing.get("id", "").startswith("nocartaz-") and " @ " in existing.get("title", "")

            # 1. Exact signature match -> always duplicate
            if sig and ex_sig and sig == ex_sig:
                duplicate_idx = idx
                break

            # 2. Token overlap at the same venue
            if tokens and ex_tokens:
                common = tokens.intersection(ex_tokens)
                min_len = min(len(tokens), len(ex_tokens))
                if len(common) >= 2 and (len(common) / min_len >= 0.5):
                    duplicate_idx = idx
                    break
                # Single-word artist match (e.g. 'Alite @ Ministerium' vs 'Lost & Found: Qzb, Hlz, Alite' or 'Sam Alone @ Tokyo' vs 'Sam Alone')
                if min_len == 1 and len(common) == 1 and abs(ev_mins - ex_mins) <= 240:
                    duplicate_idx = idx
                    break

            # 3. Consolidate NoCartaz '@ Venue' lineup stubs happening at the exact same club/venue within 180 mins
            if (ev_is_nc_stub or ex_is_nc_stub) and abs(ev_mins - ex_mins) <= 180:
                if ev.get("category") in ("Nightlife & Electronic", "Concerts & Live Music") and existing.get("category") in ("Nightlife & Electronic", "Concerts & Live Music"):
                    duplicate_idx = idx
                    break

            # 4. Consolidate ongoing-* baseline items when a live-scraped event already covers the exact same venue & category
            ev_is_ongoing = str(ev.get("id", "")).startswith("ongoing-")
            ex_is_ongoing = str(existing.get("id", "")).startswith("ongoing-")
            if (ev_is_ongoing != ex_is_ongoing) and ev.get("category") == existing.get("category"):
                duplicate_idx = idx
                break

        if duplicate_idx is not None:
            unique[duplicate_idx] = _merge_event_pair(unique[duplicate_idx], ev)
        else:
            unique.append(ev)

    return unique


# ==============================================================================
# TIER 8: CIVIC, HEALTH & COMMUNITY TIERS
# ==============================================================================
def scrape_dador_sessions(target_date):
    """Fetches real-time blood donation sessions from dador.pt API strictly within Lisbon municipality."""
    events = []
    url = "https://dador.pt/api/sessions"
    print(f"[Tier 8] Fetching blood donation sessions from dador.pt for {target_date}...")
    try:
        data = None
        try:
            resp = fetch_url(url, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
        except Exception:
            pass

        if not data:
            import urllib.request, ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={
                "User-Agent": DEFAULT_HEADERS["User-Agent"],
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, context=ctx, timeout=12) as uresp:
                data = json.loads(uresp.read().decode("utf-8"))

        if data:
            sessions = data.get("data", {}).get("Sessoes", [])
            target_fmt = target_date.strftime("%d-%m-%Y")

            for s in sessions:
                concelho = (s.get("DesConcelho") or "").strip().upper()
                # Strictly require LISBOA municipality (excludes Amadora, Sintra, Loures, etc.)
                if concelho != "LISBOA":
                    continue

                session_date = (s.get("DataBrigada") or "").strip()
                if session_date != target_fmt:
                    continue

                geo_ref = (s.get("GeoReferencia") or "").strip()
                if not geo_ref or "," not in geo_ref:
                    continue
                try:
                    lat_str, lng_str = geo_ref.split(",", 1)
                    lat = round(float(lat_str.strip()), 6)
                    lng = round(float(lng_str.strip()), 6)
                except (ValueError, TypeError):
                    continue

                if not locations.in_lisbon(lat, lng):
                    continue

                hora_raw = (s.get("HoraBrigada") or "").strip()
                times = hora_raw.split()
                time_str = times[0] if times else "09:00"
                end_t = times[1] if len(times) > 1 else (times[-1] if len(times) > 2 else "18:00")

                try:
                    hour_int = int(time_str.split(":")[0])
                except (ValueError, IndexError):
                    hour_int = 9
                try:
                    end_h = int(end_t.split(":")[0])
                except (ValueError, IndexError):
                    end_h = 18

                des_brigada = (s.get("DesBrigada") or "Dádiva de Sangue").strip()
                local = (s.get("Local") or "").strip()
                tipo = (s.get("DesTipoSessao") or "Colheita").strip()

                matched_v = match_venue(local, des_brigada, require_match=True)
                if matched_v:
                    venue_name = matched_v["venue"]
                    neighborhood = matched_v["neighborhood"]
                    corridor = matched_v["corridor"]
                    lat, lng = matched_v["lat"], matched_v["lng"]
                else:
                    venue_name = (local.split(" - ")[0].strip() if " - " in local else des_brigada).title()
                    corridor = locations.infer_corridor(lat, lng)
                    neighborhood = locations.infer_neighborhood(lat, lng)

                title = f"Dádiva de Sangue: {des_brigada.title()}"
                s_id = f"dador-{s.get('Id', abs(hash(des_brigada + geo_ref)) % 10000)}"
                desc = f"Sessão de dádiva e colheita de sangue ({tipo}) em {local or des_brigada}. Horário: {time_str} às {end_t}. Dá sangue, salva vidas!"

                events.append({
                    "id": s_id,
                    "title": title,
                    "category": "Blood Donation",
                    "color": "#E63946",
                    "icon": "🩸",
                    "venue": venue_name,
                    "neighborhood": neighborhood,
                    "corridor": corridor,
                    "lat": lat,
                    "lng": lng,
                    "time": time_str,
                    "hour": hour_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": "Entrada Livre",
                    "priceTier": "FREE",
                    "url": "https://dador.pt/sessoes",
                    "description": desc,
                })
    except Exception as exc:
        print(f"[Dador.pt] Notice: {exc}")

    return events


def scrape_junta_santo_antonio(target_date):
    events = []
    base_url = "https://www.jfsantoantonio.pt"
    agenda_url = f"{base_url}/index.php/freguesia/agenda"
    target_fmt = target_date.strftime("%d-%m-%Y")
    print(f"[Tier 8] Checking Junta de Freguesia de Santo António agenda for {target_date}...")

    try:
        resp = fetch_url(agenda_url, timeout=12)
        if resp.status_code == 200:
            html = resp.text
            blocks = re.findall(r'<div[^>]*class="[^"]*eb-event-wrapper[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*eb-event-wrapper|\Z)', html, re.S)

            for block in blocks:
                date_m = re.search(r'(\d{2}-\d{2}-\d{4})', block)
                if not date_m:
                    continue
                ev_date = date_m.group(1)

                range_m = re.search(r'(\d{2}-\d{2}-\d{4})\s*-\s*(\d{2}-\d{2}-\d{4})', block)
                date_matches = False
                if range_m:
                    d1 = datetime.datetime.strptime(range_m.group(1), "%d-%m-%Y").date()
                    d2 = datetime.datetime.strptime(range_m.group(2), "%d-%m-%Y").date()
                    if d1 <= target_date <= d2:
                        date_matches = True
                elif ev_date == target_fmt:
                    date_matches = True

                if not date_matches:
                    continue

                title_m = re.search(r'class="eb-event-title"[^>]*>([^<]+)</a>', block)
                title = title_m.group(1).strip() if title_m else "Evento Santo António"

                href_m = re.search(r'href="([^"]+)"', block)
                href = href_m.group(1) if href_m else ""
                ev_url = href if href.startswith("http") else (base_url + href)

                time_m = re.search(r'class="eb-time">\s*([0-9:]+)', block)
                time_str = time_m.group(1).strip() if time_m else "18:00"
                try:
                    hour_int = int(time_str.split(":")[0])
                except (ValueError, IndexError):
                    hour_int = 18

                desc = ""
                venue_name = "Junta de Freguesia de Santo António"
                lat, lng = 38.72485, -9.14394
                end_t = f"{min(23, hour_int + 2):02d}:00"
                end_h = min(23, hour_int + 2)

                try:
                    d_resp = fetch_url(ev_url, timeout=8)
                    if d_resp.status_code == 200:
                        clean_d = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', d_resp.text, flags=re.S | re.I)
                        clean_d = re.sub(r'<[^>]+>', ' ', clean_d)
                        clean_d = re.sub(r'\s+', ' ', clean_d)

                        if "praça da alegria" in clean_d.lower() or "praca da alegria" in clean_d.lower():
                            venue_name = "Praça da Alegria"
                            lat, lng = 38.71802, -9.14482
                        elif "bacs" in clean_d.lower() or "cosmelli" in clean_d.lower():
                            venue_name = "Biblioteca Arquitecto Cosmelli Sant'Anna (BACS)"
                            lat, lng = 38.72120, -9.15180
                        elif "torel" in clean_d.lower():
                            venue_name = "Jardim do Torel"
                            lat, lng = 38.71962, -9.14081

                        h_m = re.search(r'entre as\s*(\d{1,2})h(\d{2})?\s*e as\s*(\d{1,2})h(\d{2})?', clean_d, re.I)
                        if h_m:
                            time_str = f"{int(h_m.group(1)):02d}:{h_m.group(2) or '00'}"
                            hour_int = int(h_m.group(1))
                            end_t = f"{int(h_m.group(3)):02d}:{h_m.group(4) or '00'}"
                            end_h = int(h_m.group(3))

                        m_text = re.search(r'No dia.*?(\.|\n)', clean_d, re.I)
                        if m_text:
                            desc = m_text.group(0).strip()
                        else:
                            desc = f"{title} na {venue_name}, Santo António."
                except Exception:
                    pass

                if not desc:
                    desc = f"{title} em {venue_name}, Lisboa."

                slug = ev_url.rstrip("/").split("/")[-1]
                events.append({
                    "id": f"jf-sa-{slug}",
                    "title": title,
                    "category": "Community & Gatherings",
                    "color": "#FFB703",
                    "icon": "🌰" if "magusto" in title.lower() else "🛍️",
                    "venue": venue_name,
                    "neighborhood": "Santo António",
                    "corridor": "Axial Spine",
                    "lat": lat,
                    "lng": lng,
                    "time": time_str,
                    "hour": hour_int,
                    "endTime": end_t,
                    "endHour": end_h,
                    "price": "Entrada Livre",
                    "priceTier": "FREE",
                    "url": ev_url,
                    "description": desc,
                })
    except Exception as exc:
        print(f"[JFSantoAntónio] Notice: {exc}")

    return events


def scrape_kosmicare(target_date):
    events = []
    if target_date.weekday() in (1, 2):
        print(f"[Tier 8] Adding Kosmicare Drug Checking session for {target_date}...")
        events.append({
            "id": f"kosmicare-{target_date.strftime('%Y%m%d')}",
            "title": "Kosmicare — Drug Checking & Redução de Riscos",
            "category": "Community & Gatherings",
            "color": "#000000",
            "icon": "kosmicare",
            "venue": "Kosmicare",
            "neighborhood": "Penha de França / Anjos",
            "corridor": "Eastern Corridor",
            "lat": 38.728816,
            "lng": -9.129387,
            "time": "16:00",
            "hour": 16,
            "endTime": "21:00",
            "endHour": 21,
            "price": "Entrada Livre (Gratuito & Confidencial)",
            "priceTier": "FREE",
            "url": "https://kosmicare.org/drugchecking/",
            "description": "Serviço anónimo, confidencial e gratuito de análise de substâncias (drug checking), informação e apoio à redução de riscos na vida noturna e festivais. Terças e quartas-feiras, das 16:00 às 21:00, na Rua Cesário Verde 17B.",
        })
    return events


def scrape_menina_e_moca(target_date):
    events = []
    if target_date.year == 2026 and target_date.month == 11:
        day = target_date.day
        if day in (1, 8, 15, 22, 29):
            events.append({
                "id": f"menina-moca-jam-{target_date.strftime('%Y%m%d')}",
                "title": "A Jam Mais Bonita da Cidade — Jam Session",
                "category": "Concerts & Live Music",
                "color": "#E63946",
                "icon": "🎤",
                "venue": "Menina e Moça",
                "neighborhood": "Cais do Sodré",
                "corridor": "Axial Spine",
                "lat": 38.70723,
                "lng": -9.14362,
                "time": "20:00",
                "hour": 20,
                "endTime": "23:30",
                "endHour": 23,
                "price": "Entrada Livre (Consumo opcional)",
                "priceTier": "FREE",
                "url": "https://www.instagram.com/meninaemocalivrariabar/?hl=en",
                "description": "A Jam Mais Bonita da Cidade todos os domingos na livraria-bar Menina e Moça, no Cais do Sodré. Música ao vivo, improvisação, poesia e tertúlia num dos espaços mais acolhedores de Lisboa.",
            })
        elif day == 19:
            events.append({
                "id": f"menina-moca-filo-{target_date.strftime('%Y%m%d')}",
                "title": "Café Filosófico com Alice dos Santos",
                "category": "Community & Gatherings",
                "color": "#FFB703",
                "icon": "☕",
                "venue": "Menina e Moça",
                "neighborhood": "Cais do Sodré",
                "corridor": "Axial Spine",
                "lat": 38.70723,
                "lng": -9.14362,
                "time": "18:30",
                "hour": 18,
                "endTime": "20:30",
                "endHour": 20,
                "price": "Entrada Livre",
                "priceTier": "FREE",
                "url": "https://www.instagram.com/meninaemocalivrariabar/?hl=en",
                "description": "Café Filosófico na livraria-bar Menina e Moça, com Alice dos Santos. Conversa aberta, reflexão e debate de ideias em ambiente informal no Cais do Sodré.",
            })
        elif day == 26:
            events.append({
                "id": f"menina-moca-livro-{target_date.strftime('%Y%m%d')}",
                "title": "Clube de Leitura: «Perdeu-se Relógio de Senhora», de Alice Brito",
                "category": "Community & Gatherings",
                "color": "#FFB703",
                "icon": "📖",
                "venue": "Menina e Moça",
                "neighborhood": "Cais do Sodré",
                "corridor": "Axial Spine",
                "lat": 38.70723,
                "lng": -9.14362,
                "time": "18:30",
                "hour": 18,
                "endTime": "20:30",
                "endHour": 20,
                "price": "Entrada Livre",
                "priceTier": "FREE",
                "url": "https://www.instagram.com/meninaemocalivrariabar/?hl=en",
                "description": "Sessão do Clube de Leitura da livraria-bar Menina e Moça dedicada à obra «Perdeu-se Relógio de Senhora», de Alice Brito. Entrada livre e discussão literária.",
            })
    return events


def scrape_volunteer_and_studies(target_date):
    events = []
    if target_date.weekday() < 5:
        events.append({
            "id": f"estudo-iscte-{target_date.strftime('%Y%m%d')}",
            "title": "Estudos Comportamentais & Cognição — Painel Experimental (ISCTE & ULisboa)",
            "category": "Community & Gatherings",
            "color": "#118AB2",
            "icon": "🔬",
            "venue": "ISCTE — Instituto Universitário de Lisboa",
            "neighborhood": "Cidade Universitária / Entre-Campos",
            "corridor": "Northern Belt",
            "lat": 38.74880,
            "lng": -9.15390,
            "time": "10:00",
            "hour": 10,
            "endTime": "18:00",
            "endHour": 18,
            "price": "Compensação 10€ - 20€ / Vales",
            "priceTier": "PAID_OPP",
            "url": "https://www.iscte-iul.pt",
            "description": "Participação voluntária em estudos de psicologia cognitiva, perceção e tomada de decisão no laboratório experimental universitário. Sessões de 30 a 60 minutos com compensação de deslocação/vales. Maiores de 18 anos.",
        })
        events.append({
            "id": f"estudo-ulisboa-{target_date.strftime('%Y%m%d')}",
            "title": "Estudos de Neurociência & Cognição — Participação Remunerada (ULisboa)",
            "category": "Community & Gatherings",
            "color": "#118AB2",
            "icon": "🔬",
            "venue": "Faculdade de Psicologia da ULisboa (FPCE)",
            "neighborhood": "Cidade Universitária",
            "corridor": "Northern Belt",
            "lat": 38.75160,
            "lng": -9.15840,
            "time": "10:30",
            "hour": 10,
            "endTime": "17:30",
            "endHour": 17,
            "price": "Compensação 15€ / Sessão",
            "priceTier": "PAID_OPP",
            "url": "https://www.psicologia.ulisboa.pt/",
            "description": "Participação voluntária em experiências comportamentais e EEG/Eye-tracking no laboratório de investigação da ULisboa. Sessões de 45 a 60 min com compensação monetária ou vales de compras aos participantes elegíveis.",
        })

    events.append({
        "id": f"voluntariado-refood-{target_date.strftime('%Y%m%d')}",
        "title": "Voluntariado Comunitário — Resgate Alimentar & Apoio de Bairro",
        "category": "Community & Gatherings",
        "color": "#2A9D8F",
        "icon": "🤝",
        "venue": "Fábrica de Alternativas",
        "neighborhood": "Penha de França",
        "corridor": "Eastern Corridor",
        "lat": 38.72915,
        "lng": -9.12785,
        "time": "18:30",
        "hour": 18,
        "endTime": "21:00",
        "endHour": 21,
        "price": "Entrada Livre (Ação Solidária)",
        "priceTier": "FREE",
        "url": "https://re-food.org/",
        "description": "Turno de voluntariado comunitário para recolha, embalamento e distribuição de refeições contra o desperdício alimentar. Aberto a quem queira juntar-se para apoiar famílias da Penha de França, Graça e Arroios.",
    })

    if target_date.weekday() < 5:
        events.append({
            "id": f"cedace-medula-{target_date.strftime('%Y%m%d')}",
            "title": "Registo de Dadores de Medula Óssea (CEDACE / IPST)",
            "category": "Blood Donation",
            "color": "#E63946",
            "icon": "🩸",
            "venue": "Pavilhão 17 — Parque de Saúde de Lisboa",
            "neighborhood": "Alvalade",
            "corridor": "Northern Belt",
            "lat": 38.75683,
            "lng": -9.14805,
            "time": "08:00",
            "hour": 8,
            "endTime": "19:30",
            "endHour": 19,
            "price": "Entrada Livre (Voluntário)",
            "priceTier": "FREE",
            "url": "https://dador.pt/",
            "description": "Registo voluntário oficial no Centro Nacional de Dadores de Células Estaminais Hematopoiéticas (CEDACE / IPST). Colheita simples e rápida de amostra de sangue (18 aos 45 anos). Salva vidas!",
        })

    return events


TIER_CACHE_PATH = os.path.join(SCRIPT_DIR, "tier_cache.json")


def _load_same_day_tier_cache(date_str):
    if os.path.exists(TIER_CACHE_PATH):
        try:
            with open(TIER_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("operational_date") == date_str:
                return data.get("tiers", {})
        except Exception:
            pass
    return {}


def _save_same_day_tier_cache(date_str, tiers_dict):
    try:
        with open(TIER_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"operational_date": date_str, "tiers": tiers_dict}, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def main():
    load_external_venues()

    now_lx = get_lisbon_now()
    env_date = os.environ.get("KEKS_TARGET_DATE", "").strip()
    if env_date:
        target_date = datetime.date.fromisoformat(env_date)
    else:
        target_date = now_lx.date()

    date_str = target_date.strftime("%Y-%m-%d")
    print(f"=== Keks Passa Scraper v3.0 — Operational Date: {date_str} ===")

    lkg_tiers = _load_same_day_tier_cache(date_str)
    updated_tiers = dict(lkg_tiers)

    def run_tier(tier_key, fn):
        fresh = []
        try:
            fresh = fn(target_date) or []
        except Exception as exc:
            print(f"[Tier LKG] Notice in {tier_key}: {exc}")
        cached = lkg_tiers.get(tier_key, [])
        if len(fresh) >= len(cached) or not cached:
            updated_tiers[tier_key] = fresh
            return fresh
        # Merge fresh + same-day LKG cached items so transient timeouts never drop events mid-day
        combined = list(fresh) + list(cached)
        updated_tiers[tier_key] = combined
        return combined

    live_raw = []
    live_raw.extend(run_tier("agendalx", scrape_agendalx))
    live_raw.extend(run_tier("nocartaz", scrape_nocartaz))
    live_raw.extend(run_tier("cinemateca", scrape_cinemateca))
    live_raw.extend(run_tier("nimas", scrape_nimas))
    live_raw.extend(run_tier("adc", scrape_agendadeconcertos))
    live_raw.extend(run_tier("bota", scrape_bota_anjos))
    live_raw.extend(run_tier("ra", scrape_resident_advisor))
    live_raw.extend(run_tier("prior_velho", scrape_prior_velho_electronic))
    live_raw.extend(run_tier("markets", scrape_markets_workshops_lectures))
    live_raw.extend(run_tier("viralagenda", scrape_viralagenda))
    live_raw.extend(run_tier("soko", scrape_soko_curated_capsula))
    live_raw.extend(run_tier("dador", scrape_dador_sessions))
    live_raw.extend(run_tier("jfsa", scrape_junta_santo_antonio))
    live_raw.extend(scrape_kosmicare(target_date))
    live_raw.extend(scrape_menina_e_moca(target_date))
    live_raw.extend(scrape_volunteer_and_studies(target_date))
    live_raw.extend(get_ongoing_cultural_events(target_date))

    _save_same_day_tier_cache(date_str, updated_tiers)

    all_events = deduplicate_events(live_raw)

    # Final validation & URL sanitization pass
    validated = []
    for ev in all_events:
        ev["title"] = clean_html_text(ev.get("title", "Evento"))
        ev["description"] = clean_html_text(ev.get("description", ""))
        if "endTime" not in ev or not ev.get("endTime"):
            end_t, end_h = infer_end_time(
                ev.get("time", "21:00"),
                ev.get("hour", 21),
                ev.get("category", ""),
                ev.get("venue", ""),
                ev.get("title", ""),
                ev.get("description", ""),
            )
            ev["endTime"] = end_t
            ev["endHour"] = end_h

        lat_val = ev.get("lat")
        lng_val = ev.get("lng")
        if lat_val is None or lng_val is None:
            continue
        try:
            lat = float(lat_val)
            lng = float(lng_val)
        except (ValueError, TypeError):
            continue

        if not locations.in_lisbon(lat, lng):
            continue

        ev["lat"] = round(lat, 6)
        ev["lng"] = round(lng, 6)

        ev_url = str(ev.get("url", "")).strip()
        if not ev_url.startswith("http") or "facebook.com/sharer" in ev_url or "twitter.com/intent" in ev_url:
            v_match = match_venue(ev.get("venue", ""), require_match=True)
            ev["url"] = (v_match.get("agenda_url") or v_match.get("url")) if v_match else "https://www.agendalx.pt/"

        validated.append(ev)

    def op_sort_key(e):
        t_parts = str(e.get("time", "21:00")).split(":")
        h = int(t_parts[0]) if t_parts and t_parts[0].isdigit() else int(e.get("hour", 21))
        m = int(t_parts[1]) if len(t_parts) > 1 and t_parts[1].isdigit() else 0
        op_h = h + 24 if h <= 6 else h
        return (op_h * 60 + m, e.get("title", ""))

    validated.sort(key=op_sort_key)
    validated = apply_coordinate_jitter(validated)

    locations.save_cache()

    payload = {
        "generated_at": now_lx.isoformat(),
        "operational_date": date_str,
        "date_string": date_str,
        "total_events": len(validated),
        "events": validated,
    }

    events_out_path = os.path.join(SCRIPT_DIR, "events.json")
    with open(events_out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"=== Saved {len(validated)} events to events.json for {date_str} ===")


if __name__ == "__main__":
    main()
