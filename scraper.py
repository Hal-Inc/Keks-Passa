#!/usr/bin/env python3
"""
Keks Passa — Daily Lisbon Cultural & Nightlife Scraper (v2.1)
Includes:
- Full Lisbon + Prior Velho / Oriente Electronic Venue Registry (Kømplex, Moon Club, NĀDA 3.0, Higher Ground, Music Station, Top Floor)
- Realistic End-Time Extraction & Category Inference (infer_end_time) for Task 5 live expiration
- Fixed Resident Advisor GraphQL Area ID (229 = Lisbon) + strict Lisbon venue filtering
- Dedicated Prior Velho & Electronic Hub Scraper (Lisabout + Moon Club + Shotgun/RA)
"""

import os
import re
import json
import math
import datetime
import unicodedata
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

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
    "concerts": {
        "category": "Concerts & Live Music",
        "color": "#E63946",
        "icon": "🔴",
    },
    "theatre": {
        "category": "Theatre & Comedy",
        "color": "#2A9D8F",
        "icon": "🟢",
    },
    "exhibitions": {
        "category": "Exhibitions & Visual Arts",
        "color": "#1D3557",
        "icon": "🔵",
    },
    "classical": {
        "category": "Opera & Classical",
        "color": "#8338EC",
        "icon": "🟣",
    },
    "cinema": {
        "category": "Cinema & Screenings",
        "color": "#06D6A0",
        "icon": "🩷",
    },
    "nightlife": {
        "category": "Nightlife & Electronic",
        "color": "#FB5607",
        "icon": "🟠",
    },
    "community": {
        "category": "Community & Gatherings",
        "color": "#FFB703",
        "icon": "🟡",
    },
    "family": {
        "category": "Family & Youth",
        "color": "#118AB2",
        "icon": "🩵",
    },
}

# ==============================================================================
# VENUE REGISTRY (Includes Prior Velho & Oriente Nighttime Electronic Cluster)
# ==============================================================================
VENUE_REGISTRY = [
    # --- PRIOR VELHO & ORIENTE ELECTRONIC CLUSTER (Task 4) ---
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
        "aliases": ["nada 3.0", "naada 3.0", "nada lisbon", "naada", "nāda", "rua figo maduro 3", "armazem 6", "tiga naada", "nada temple"],
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
    },

    # --- MARVILA, BEATO & EASTERN CORRIDOR ---
    {
        "venue": "Lux Frágil",
        "aliases": ["lux fragil", "lux", "av. infante d. henrique"],
        "lat": 38.7158, "lng": -9.1213, "neighborhood": "Santa Apolónia", "corridor": "Eastern Corridor",
        "url": "https://www.luxfragil.com"
    },
    {
        "venue": "8 Marvila",
        "aliases": ["8 marvila", "oito marvila", "praca david leandro da silva"],
        "lat": 38.7420, "lng": -9.1026, "neighborhood": "Marvila", "corridor": "Eastern Corridor",
        "url": "https://www.8marvila.com"
    },
    {
        "venue": "LAV — Lisboa ao Vivo",
        "aliases": ["lisboa ao vivo", "lav", "av. marechal gomes da costa"],
        "lat": 38.7554, "lng": -9.1040, "neighborhood": "Marvila / Cabo Ruivo", "corridor": "Eastern Corridor",
        "url": "https://lisboaaovivo.com"
    },
    {
        "venue": "Arroz Estúdios",
        "aliases": ["arroz estudios", "arroz"],
        "lat": 38.7327, "lng": -9.1086, "neighborhood": "Beato", "corridor": "Eastern Corridor",
        "url": "https://arrozestudios.pt"
    },
    {
        "venue": "Fábrica do Braço de Prata",
        "aliases": ["fabrica do braco de prata", "braco de prata"],
        "lat": 38.7460, "lng": -9.1018, "neighborhood": "Braço de Prata", "corridor": "Eastern Corridor",
        "url": "https://www.bracodeprata.com"
    },
    {
        "venue": "Underdogs Gallery",
        "aliases": ["underdogs", "underdogs gallery", "rua fernando palha"],
        "lat": 38.7445, "lng": -9.1012, "neighborhood": "Marvila", "corridor": "Eastern Corridor",
        "url": "https://www.under-dogs.net"
    },
    {
        "venue": "Pavilhão do Conhecimento",
        "aliases": ["pavilhao do conhecimento", "ciencia viva"],
        "lat": 38.7625, "lng": -9.0956, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor",
        "url": "https://www.pavconhecimento.pt"
    },
    {
        "venue": "MEO Arena",
        "aliases": ["meo arena", "altice arena", "sala tejo"],
        "lat": 38.7686, "lng": -9.0940, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor",
        "url": "https://arena.meo.pt"
    },

    # --- AXIAL SPINE (CAIS DO SODRÉ, BAIRRO ALTO, CHIADO, BAIXA, AVENIDA, INTENDENTE) ---
    {
        "venue": "Galeria Zé dos Bois (ZDB)",
        "aliases": ["zdb", "galeria ze dos bois", "ze dos bois", "rua da barrosa"],
        "lat": 38.7124, "lng": -9.1444, "neighborhood": "Bairro Alto", "corridor": "Axial Spine",
        "url": "https://zedosbois.org"
    },
    {
        "venue": "Musicbox",
        "aliases": ["musicbox", "music box", "rua nova do carvalho"],
        "lat": 38.7072, "lng": -9.1436, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://musicboxlisboa.com"
    },
    {
        "venue": "Ministerium Club",
        "aliases": ["ministerium", "ministerium club", "terreiro do paco"],
        "lat": 38.7082, "lng": -9.1360, "neighborhood": "Terreiro do Paço", "corridor": "Axial Spine",
        "url": "https://pt.ra.co/clubs/66945"
    },
    {
        "venue": "Incógnito",
        "aliases": ["incognito", "rua de poiais de sao bento"],
        "lat": 38.7135, "lng": -9.1528, "neighborhood": "São Bento", "corridor": "Axial Spine",
        "url": "https://incognitobar.com"
    },
    {
        "venue": "Plano B /Bica & Cais",
        "aliases": ["bicaense", "damas", "casa independente", "desterro", "bus paragem cultural"],
        "lat": 38.7218, "lng": -9.1352, "neighborhood": "Intendente / Anjos", "corridor": "Axial Spine",
        "url": "https://www.agendalx.pt"
    },
    {
        "venue": "B.Leza",
        "aliases": ["b.leza", "bleza", "cais da ribeira nova"],
        "lat": 38.7062, "lng": -9.1465, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://www.agendalx.pt"
    },
    {
        "venue": "Titanic Sur Mer",
        "aliases": ["titanic sur mer", "cais da ribeira nova"],
        "lat": 38.7060, "lng": -9.1472, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://www.agendalx.pt"
    },
    {
        "venue": "Cineteatro Capitólio",
        "aliases": ["capitolio", "cineteatro capitolio", "parque mayer"],
        "lat": 38.7186, "lng": -9.1462, "neighborhood": "Parque Mayer / Avenida", "corridor": "Axial Spine",
        "url": "https://www.cineteatrocapitolio.pt"
    },
    {
        "venue": "Coliseu dos Recreios",
        "aliases": ["coliseu", "coliseu dos recreios", "rua das portas de santo antao"],
        "lat": 38.7168, "lng": -9.1408, "neighborhood": "Baixa / Rossio", "corridor": "Axial Spine",
        "url": "https://www.coliseulisboa.com"
    },
    {
        "venue": "Teatro Nacional D. Maria II",
        "aliases": ["d. maria ii", "dona maria ii", "tndmii"],
        "lat": 38.7146, "lng": -9.1396, "neighborhood": "Rossio", "corridor": "Axial Spine",
        "url": "https://www.tndm.pt"
    },
    {
        "venue": "Teatro São Luiz",
        "aliases": ["sao luiz", "teatro sao luiz", "sao luis"],
        "lat": 38.7095, "lng": -9.1426, "neighborhood": "Chiado", "corridor": "Axial Spine",
        "url": "https://www.teatrosaoluiz.pt"
    },
    {
        "venue": "Teatro Nacional de São Carlos",
        "aliases": ["sao carlos", "teatro nacional de sao carlos"],
        "lat": 38.7097, "lng": -9.1415, "neighborhood": "Chiado", "corridor": "Axial Spine",
        "url": "https://saocarlos.pt"
    },
    {
        "venue": "Teatro da Trindade INATEL",
        "aliases": ["teatro da trindade", "trindade inatel"],
        "lat": 38.7128, "lng": -9.1425, "neighborhood": "Chiado / Bairro Alto", "corridor": "Axial Spine",
        "url": "https://teatrodatrindade.inatel.pt"
    },
    {
        "venue": "Teatro Tivoli BBVA",
        "aliases": ["tivoli", "tivoli bbva", "teatro tivoli"],
        "lat": 38.7209, "lng": -9.1456, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine",
        "url": "https://www.teatrotivolibbva.pt"
    },
    {
        "venue": "Cinemateca Portuguesa",
        "aliases": ["cinemateca", "cinemateca portuguesa", "rua barata salgueiro"],
        "lat": 38.7219, "lng": -9.1482, "neighborhood": "Avenida / Marquês", "corridor": "Axial Spine",
        "url": "https://www.cinemateca.pt"
    },
    {
        "venue": "Cinema São Jorge",
        "aliases": ["cinema sao jorge", "sao jorge"],
        "lat": 38.7212, "lng": -9.1453, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine",
        "url": "https://cinemasaojorge.pt"
    },
    {
        "venue": "Cinema Ideal",
        "aliases": ["cinema ideal", "rua do loreto"],
        "lat": 38.7107, "lng": -9.1449, "neighborhood": "Chiado / Camões", "corridor": "Axial Spine",
        "url": "https://cinemaideal.pt"
    },
    {
        "venue": "MNAC — Museu do Chiado",
        "aliases": ["mnac", "museu do chiado", "museu nacional de arte contemporanea"],
        "lat": 38.7088, "lng": -9.1412, "neighborhood": "Chiado", "corridor": "Axial Spine",
        "url": "http://www.museuartecontemporanea.gov.pt"
    },
    {
        "venue": "MUDE — Museu do Design",
        "aliases": ["mude", "museu do design", "rua augusta"],
        "lat": 38.7094, "lng": -9.1370, "neighborhood": "Baixa", "corridor": "Axial Spine",
        "url": "https://www.mude.pt"
    },
    {
        "venue": "Museu do Fado",
        "aliases": ["museu do fado", "largo do chafariz de dentro"],
        "lat": 38.7112, "lng": -9.1277, "neighborhood": "Alfama", "corridor": "Axial Spine",
        "url": "https://www.museudofado.pt"
    },

    # --- NORTHERN BELT (SALDANHA, GULBENKIAN, CAMPO PEQUENO, ALVALADE, BENFICA) ---
    {
        "venue": "Fundação Calouste Gulbenkian",
        "aliases": ["gulbenkian", "fundacao calouste gulbenkian", "cam gulbenkian", "centro de arte moderna"],
        "lat": 38.7376, "lng": -9.1545, "neighborhood": "Avenidas Novas / Praça de Espanha", "corridor": "Northern Belt",
        "url": "https://gulbenkian.pt"
    },
    {
        "venue": "Culturgest",
        "aliases": ["culturgest", "arco do cego"],
        "lat": 38.7402, "lng": -9.1412, "neighborhood": "Campo Pequeno / Arco do Cego", "corridor": "Northern Belt",
        "url": "https://www.culturgest.pt"
    },
    {
        "venue": "Cinema Medeia Nimas",
        "aliases": ["nimas", "cinema nimas", "medeia nimas", "av. 5 de outubro"],
        "lat": 38.7322, "lng": -9.1462, "neighborhood": "Saldanha", "corridor": "Northern Belt",
        "url": "https://medeias.pt"
    },
    {
        "venue": "Teatro Maria Matos",
        "aliases": ["maria matos", "teatro maria matos", "av. frei miguel contreiras"],
        "lat": 38.7463, "lng": -9.1380, "neighborhood": "Roma / Areeiro", "corridor": "Northern Belt",
        "url": "https://teatromariamatos.pt"
    },
    {
        "venue": "República da Música",
        "aliases": ["republica da musica", "alvalade"],
        "lat": 38.7562, "lng": -9.1456, "neighborhood": "Alvalade", "corridor": "Northern Belt",
        "url": "https://www.agendalx.pt"
    },
    {
        "venue": "Sagres Campo Pequeno",
        "aliases": ["campo pequeno", "sagres campo pequeno"],
        "lat": 38.7425, "lng": -9.1452, "neighborhood": "Campo Pequeno", "corridor": "Northern Belt",
        "url": "https://www.campopequeno.com"
    },

    # --- BELÉM WATERFRONT & ALCÂNTARA ---
    {
        "venue": "CCB — Centro Cultural de Belém",
        "aliases": ["ccb", "centro cultural de belem", "mac/ccb", "museu de arte contemporanea"],
        "lat": 38.6956, "lng": -9.2064, "neighborhood": "Belém", "corridor": "Belém Waterfront",
        "url": "https://www.ccb.pt"
    },
    {
        "venue": "MAAT — Museu de Arte, Arquitetura e Tecnologia",
        "aliases": ["maat", "central tejo"],
        "lat": 38.6959, "lng": -9.1945, "neighborhood": "Belém", "corridor": "Belém Waterfront",
        "url": "https://www.maat.pt"
    },
    {
        "venue": "LX Factory / Village Underground",
        "aliases": ["lx factory", "lxfactory", "village underground", "alcântara", "alcantara"],
        "lat": 38.7035, "lng": -9.1788, "neighborhood": "Alcântara", "corridor": "Belém Waterfront",
        "url": "https://lxfactory.com"
    },
    {
        "venue": "Museu do Oriente",
        "aliases": ["museu do oriente", "av. brasilia"],
        "lat": 38.7027, "lng": -9.1714, "neighborhood": "Alcântara", "corridor": "Belém Waterfront",
        "url": "https://www.foriente.pt"
    },
    {
        "venue": "LU.CA — Teatro Luís de Camões",
        "aliases": ["lu.ca", "luca", "teatro luis de camoes", "calcada da ajuda"],
        "lat": 38.7005, "lng": -9.2015, "neighborhood": "Belém / Ajuda", "corridor": "Belém Waterfront",
        "url": "https://lucateatroluisdecamoes.pt"
    },
]


def load_external_venues():
    """Merges any user-curated entries from venues.json if present."""
    if os.path.exists("venues.json"):
        try:
            with open("venues.json", "r", encoding="utf-8") as f:
                ext = json.load(f)
            if isinstance(ext, list):
                existing = {v["venue"].lower() for v in VENUE_REGISTRY}
                for item in ext:
                    if isinstance(item, dict) and item.get("venue") and item["venue"].lower() not in existing:
                        VENUE_REGISTRY.append(item)
        except Exception as e:
            print(f"[Venue Loader] Notice reading venues.json: {e}")


def strip_accents(text):
    if not text:
        return ""
    norm = unicodedata.normalize("NFD", str(text))
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn").lower()


def match_venue(*texts, require_match=False):
    combined = strip_accents(" ".join(t for t in texts if t))
    for entry in VENUE_REGISTRY:
        for alias in entry.get("aliases", []):
            if strip_accents(alias) in combined:
                return entry
        if strip_accents(entry["venue"]) in combined:
            return entry
    if require_match:
        return None
    return {
        "venue": "Lisboa (Ver Local no Link)",
        "lat": 38.7169,
        "lng": -9.1399,
        "neighborhood": "Centro Histórico",
        "corridor": "Axial Spine",
        "url": "https://www.agendalx.pt",
    }


def parse_time_str(text, default_time="21:00"):
    if not text:
        h = int(default_time.split(":")[0])
        return default_time, h
    m = re.search(r"\b([01]?\d|2[0-3])\s*[:h.]\s*([0-5]\d)\b", str(text), re.I)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        return f"{hh:02d}:{mm:02d}", hh
    m2 = re.search(r"\b([01]?\d|2[0-3])\s*h\b", str(text), re.I)
    if m2:
        hh = int(m2.group(1))
        return f"{hh:02d}:00", hh
    h_def = int(default_time.split(":")[0])
    return default_time, h_def


def infer_end_time(start_time, hour_int, category_name, venue_name="", title="", desc=""):
    """
    Task 5: Extracts explicit end time from text ('18h-22h', '05:00 — 12:00', '14:00 - 23:00')
    or infers realistic closing time by category & venue so finished events are
    removed from the map and listing 1 minute after finishing.
    """
    combined = f"{title or ''} {desc or ''}"
    m_range = re.search(
        r"\b(?:[01]?\d|2[0-3])(?:[:h.][0-5]\d|\s*h)?\s*(?:–|—|-|às|as|to|até)\s*([01]?\d|2[0-3])(?:[:h.]([0-5]\d)|\s*h)\b",
        combined,
        re.I,
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
    t_low = strip_accents(title or "")

    if category_name == "Exhibitions & Visual Arts":
        if "zdb" in v_low or "ze dos bois" in v_low:
            return "22:00", 22
        if sh < 17:
            if any(k in v_low for k in ["ccb", "maat", "underdogs", "oriente"]):
                return "19:00", 19
            return "18:00", 18
        if sh == 18:
            return "20:30", 20
        return add_minutes(sh, sm, 120)

    if category_name == "Family & Youth":
        if "pavilhao do conhecimento" in v_low:
            return "18:00", 18
        if any(k in t_low for k in ["infancia", "escolar", "ciclo", "familias", "oficinas"]):
            return ("17:30", 17) if sh <= 11 else add_minutes(sh, sm, 150)
        return add_minutes(sh, sm, 120)

    if category_name in ("Cinema & Screenings", "Theatre & Comedy", "Opera & Classical"):
        return add_minutes(sh, sm, 120)

    if category_name == "Concerts & Live Music":
        return add_minutes(sh, sm, 150)

    if category_name == "Community & Gatherings":
        if "8 marvila" in v_low:
            return "20:00", 20
        if sh <= 10:
            return "18:00", 18
        return add_minutes(sh, sm, 120)

    if category_name == "Nightlife & Electronic":
        if 4 <= sh <= 8:
            return "12:00", 12
        if 12 <= sh < 17:
            return "23:00", 23
        if 17 <= sh < 21:
            return "02:00", 2
        if "moon club" in v_low:
            return "07:00", 7
        if "nada" in v_low or "naada" in v_low:
            return "05:00", 5
        return "06:00", 6

    return add_minutes(sh, sm, 120)


def parse_price_and_tier(text, default_price="Preço a confirmar", default_tier="ACCESSIBLE"):
    low = strip_accents(text or "")
    if any(k in low for k in ["entrada livre", "gratuito", "gratis", "free", "borla"]):
        return "Entrada Livre", "FREE"
    m = re.search(r"(\d{1,3})(?:[.,](\d{1,2}))?\s*€", str(text))
    if m:
        val = float(m.group(1))
        disp = f"{m.group(1)}€" if not m.group(2) else f"{m.group(1)},{m.group(2)}€"
        if val == 0:
            return "Entrada Livre", "FREE"
        if val <= 15:
            return disp, "ACCESSIBLE"
        if val <= 30:
            return disp, "MID"
        return disp, "PREMIUM"
    return default_price, default_tier


def fetch_url(url, timeout=18, headers=None):
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    return SCRAPER_SESSION.get(url, headers=hdrs, timeout=timeout)


# ==============================================================================
# SCRAPER MODULES
# ==============================================================================
def scrape_agendalx(target_date):
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"[Tier 1] Scraping AgendaLX for {date_str}...")
    try:
        resp = fetch_url("https://www.agendalx.pt/events/")
        if resp.status_code != 200:
            return events
        soup = BeautifulSoup(resp.text, "html.parser")
        for art in soup.select("article, .event-card, .card"):
            txt = art.get_text(" ", strip=True)
            a_tag = art.find("a", href=True)
            if not a_tag:
                continue
            title_el = art.find(["h2", "h3", "h4"])
            title = title_el.get_text(" ", strip=True) if title_el else a_tag.get_text(" ", strip=True)
            if not title or len(title) < 3:
                continue

            low = strip_accents(txt)
            preset = CATEGORY_PRESETS["concerts"]
            if any(k in low for k in ["exposicao", "artes plasticas", "fotografia", "instalacao"]):
                preset = CATEGORY_PRESETS["exhibitions"]
            elif any(k in low for k in ["teatro", "danca", "comedia", "stand-up", "circo"]):
                preset = CATEGORY_PRESETS["theatre"]
            elif any(k in low for k in ["cinema", "filme", "documentario"]):
                preset = CATEGORY_PRESETS["cinema"]
            elif any(k in low for k in ["opera", "classica", "sinfonica", "coro"]):
                preset = CATEGORY_PRESETS["classical"]
            elif any(k in low for k in ["criancas", "familia", "oficina", "infantil", "jovens"]):
                preset = CATEGORY_PRESETS["family"]
            elif any(k in low for k in ["dj", "clubbing", "eletronica", "noite", "festa"]):
                preset = CATEGORY_PRESETS["nightlife"]

            default_t = "10:00" if preset == CATEGORY_PRESETS["exhibitions"] else "21:00"
            time_str, hour_int = parse_time_str(txt, default_t)
            geo = match_venue(txt, title)
            price_disp, price_tier = parse_price_and_tier(txt)
            end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, txt)

            events.append({
                "id": f"agendalx-{abs(hash(title + geo['venue'])) % 1000000}",
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
                "url": a_tag["href"],
                "description": f"{title} em {geo['venue']} ({geo['neighborhood']}).",
            })
    except Exception as e:
        print(f"[AgendaLX] Notice: {e}")
    return events


def scrape_resident_advisor(target_date):
    """
    Task 4 Fix: Queries Resident Advisor GraphQL strictly for Area ID 229 (Lisbon)
    and drops any event that does not match a known Lisbon / Prior Velho venue or keyword.
    """
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"[Tier 2] Querying Resident Advisor GraphQL for Lisbon (Area 229) on {date_str}...")

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
    payload = {
        "query": query,
        "variables": {
            "filters": {
                "areas": {"eq": 229},
                "listingDate": {"gte": f"{date_str}T00:00:00.000Z", "lte": f"{date_str}T23:59:59.999Z"},
            },
            "pageSize": 40,
            "page": 1,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Referer": "https://pt.ra.co/events/pt/lisbon",
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
    }

    try:
        resp = SCRAPER_SESSION.post(gql_url, json=payload, headers=headers, timeout=18)
        if resp.status_code == 200:
            data = resp.json()
            listings = (((data.get("data") or {}).get("eventListings") or {}).get("data")) or []
            for item in listings:
                ev = item.get("event") or {}
                title = ev.get("title") or "Noite Eletrónica"
                venue_obj = ev.get("venue") or {}
                v_name = venue_obj.get("name") or ""
                v_addr = venue_obj.get("address") or ""

                # Strictly verify venue belongs to Lisbon / Prior Velho
                geo = match_venue(v_name, v_addr, title, require_match=True)
                if not geo:
                    addr_low = strip_accents(f"{v_name} {v_addr}")
                    if not any(k in addr_low for k in ["lisboa", "lisbon", "prior velho", "marvila", "beato", "cais", "alcantara", "oriente"]):
                        continue
                    geo = match_venue(v_name, v_addr, title, require_match=False)

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
                full_url = f"https://pt.ra.co{content_url}" if content_url.startswith("/") else "https://pt.ra.co/events/pt/lisbon"

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
                    "price": "10€ - 20€",
                    "priceTier": "ACCESSIBLE",
                    "url": full_url,
                    "description": f"{title} em {geo['venue']} ({geo['neighborhood']}).{lineup_str}",
                })
    except Exception as e:
        print(f"[RA Scraper] Notice: {e}")

    return events


def scrape_prior_velho_electronic(target_date):
    """
    Task 4: Scrapes Prior Velho & Lisbon electronic events from Lisabout (Prior Velho &
    Dance/Electronic feeds) and Moon Club (moonclub.pt). Also captures early-morning
    afterhours (04:00-08:00 next calendar morning) that belong to tonight's operational night.
    """
    events = []
    next_date = target_date + datetime.timedelta(days=1)
    d_today = f"{target_date.day}/{target_date.month:02d}"
    d_next = f"{next_date.day}/{next_date.month:02d}"

    lisabout_urls = [
        "https://www.lisabout.com/zona/prior-velho",
        "https://www.lisabout.com/genero/dance-electronic",
    ]
    print(f"[Tier 2/3] Scraping Prior Velho & Electronic hubs for {d_today} (and afterhours {d_next})...")

    for url in lisabout_urls:
        try:
            resp = fetch_url(url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/events/"]'):
                href = a_tag.get("href", "")
                card_text = a_tag.get_text(" | ", strip=True)
                is_today = d_today in card_text
                is_afterhours = d_next in card_text and bool(re.search(r"\b0[4-8]:[0-5]\d\b", card_text))
                if not (is_today or is_afterhours):
                    continue

                time_str, hour_int = parse_time_str(card_text, "23:59")
                title_el = a_tag.find(["h3", "h4", "strong"])
                title = title_el.get_text(" ", strip=True) if title_el else ""
                if not title:
                    parts = [p.strip() for p in card_text.split("|") if p.strip() and not re.search(r"\b\d{1,2}/\d{2}\b", p)]
                    title = parts[1] if len(parts) > 1 else parts[0]

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
                    "description": f"{title} em {geo['venue']} ({geo['neighborhood']}). Programação eletrónica e clubbing.",
                })
        except Exception as e:
            print(f"[Prior Velho Scraper] Notice on {url}: {e}")

    # Direct Moon Club Prior Velho scraper (moonclub.pt)
    try:
        resp = fetch_url("https://www.moonclub.pt/")
        if resp.status_code == 200 and d_today in resp.text:
            soup = BeautifulSoup(resp.text, "html.parser")
            geo = match_venue("moon club")
            for block in soup.find_all(["li", "div", "article"]):
                txt = block.get_text(" ", strip=True)
                if d_today in txt and len(txt) < 300:
                    m_title = re.search(rf"{re.escape(d_today)}.*?\d+%\s+([A-Z0-9\s—\-]+)", txt)
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
                        "price": "10€ - 15€",
                        "priceTier": "ACCESSIBLE",
                        "url": "https://www.moonclub.pt",
                        "description": f"{title} no Moon Club (Rua Ary dos Santos 3, Prior Velho). Noite de techno e clubbing até ao nascer do sol.",
                    })
                    break
    except Exception as e:
        print(f"[Moon Club Scraper] Notice: {e}")

    return events


def apply_coordinate_jitter(events):
    """Applies a golden-angle spiral offset when multiple events share the same venue coordinates."""
    seen = {}
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    for ev in events:
        lat = ev.get("lat")
        lng = ev.get("lng")
        if lat is None or lng is None:
            continue
        key = (round(float(lat), 4), round(float(lng), 4))
        idx = seen.get(key, 0)
        seen[key] = idx + 1
        if idx > 0:
            r = 0.00022 * math.sqrt(idx)
            theta = idx * golden_angle
            ev["lat"] = round(float(lat) + r * math.cos(theta), 6)
            ev["lng"] = round(float(lng) + r * math.sin(theta), 6)
    return events


def deduplicate_events(events):
    seen_keys = set()
    unique = []
    for ev in events:
        k = f"{strip_accents(ev.get('venue', ''))}|{strip_accents(ev.get('title', ''))[:22]}|{ev.get('time', '')}"
        if k not in seen_keys:
            seen_keys.add(k)
            unique.append(ev)
    return unique


def main():
    load_external_venues()

    # Determine operational date in Europe/Lisbon with 04:00 AM cutoff
    now_lx = datetime.datetime.now(ZoneInfo("Europe/Lisbon"))
    target_date = (now_lx - datetime.timedelta(hours=4)).date()
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"=== Keks Passa Scraper — Operational Date: {date_str} ===")

    existing_events = []
    if os.path.exists("events.json"):
        try:
            with open("events.json", "r", encoding="utf-8") as f:
                old_payload = json.load(f)
            if old_payload.get("operational_date") == date_str:
                # Keep existing valid Lisbon events for today, dropping any old area_id=51 leaks
                bad_venues = {"exit reality", "rasa", "mdlr", "66 chambers", "earworm"}
                existing_events = [
                    e for e in (old_payload.get("events") or [])
                    if str(e.get("venue", "")).lower().strip() not in bad_venues
                ]
        except Exception as e:
            print(f"[Main] Notice reading existing events.json: {e}")

    live_raw = []
    live_raw.extend(scrape_agendalx(target_date))
    live_raw.extend(scrape_resident_advisor(target_date))
    live_raw.extend(scrape_prior_velho_electronic(target_date))

    all_events = deduplicate_events(existing_events + live_raw)

    # Ensure every event has endTime and endHour for Task 5 live expiration
    for ev in all_events:
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

    # Sort chronologically along the 04:00 AM operational day
    def op_sort_key(e):
        t_parts = str(e.get("time", "21:00")).split(":")
        h = int(t_parts[0]) if t_parts and t_parts[0].isdigit() else int(e.get("hour", 21))
        m = int(t_parts[1]) if len(t_parts) > 1 and t_parts[1].isdigit() else 0
        op_h = h + 24 if h < 4 else h
        return (op_h * 60 + m, e.get("title", ""))

    all_events.sort(key=op_sort_key)
    all_events = apply_coordinate_jitter(all_events)

    payload = {
        "generated_at": now_lx.isoformat(),
        "operational_date": date_str,
        "date_string": date_str,
        "total_events": len(all_events),
        "events": all_events,
    }

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"=== Saved {len(all_events)} events to events.json for {date_str} ===")


if __name__ == "__main__":
    main()
