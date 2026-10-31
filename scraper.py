#!/usr/bin/env python3
"""
Keks Passa — Daily Lisbon Cultural & Nightlife Scraper (v2.2 Unified Multi-Tier)
Fixes the 04:00 AM operational rollover drop by running all 8 Lisbon tiers:
1. AgendaLX (agendalx.pt) via curl_cffi Chrome TLS impersonation
2. NoCartaz Lisboa (nocartaz.pt/concelhos/lisboa/) with clean pipe-segment parsing
3. Cinemateca Portuguesa (cinemateca.pt/Programacao.aspx)
4. Cinema Medeia Nimas (medeiafilmes.com/cinemas/cinema-medeia-nimas)
5. Agenda de Concertos Lisboa (agendadeconcertos.com/concertos-em-portugal/)
6. BOTA Anjos Programação (botaanjos.com/programacao)
7. Prior Velho & Electronic Hubs (lisabout.com + moonclub.pt + Resident Advisor Area 229)
8. Active Lisbon Museum Exhibitions & Theatre Seasons (day-of-week aware baseline)
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

# Use curl_cffi (installed in GitHub Actions) for Chrome TLS fingerprint impersonation
try:
    from curl_cffi import requests as cffi_requests
    SCRAPER_SESSION = cffi_requests.Session(impersonate="chrome")
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
    "concerts": {"category": "Concerts & Live Music", "color": "#E63946", "icon": "🔴"},
    "theatre": {"category": "Theatre & Comedy", "color": "#2A9D8F", "icon": "🟢"},
    "exhibitions": {"category": "Exhibitions & Visual Arts", "color": "#1D3557", "icon": "🔵"},
    "classical": {"category": "Opera & Classical", "color": "#8338EC", "icon": "🟣"},
    "cinema": {"category": "Cinema & Screenings", "color": "#06D6A0", "icon": "🩷"},
    "nightlife": {"category": "Nightlife & Electronic", "color": "#FB5607", "icon": "🟠"},
    "community": {"category": "Community & Gatherings", "color": "#FFB703", "icon": "🟡"},
    "family": {"category": "Family & Youth", "color": "#118AB2", "icon": "🩵"},
}

PT_MONTHS_SHORT = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"
}
PT_MONTHS_FULL = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
}

# ==============================================================================
# VENUE REGISTRY (75 Verified Lisbon & Prior Velho Venues)
# ==============================================================================
VENUE_REGISTRY = [
    # --- PRIOR VELHO & ORIENTE ELECTRONIC CLUSTER ---
    {"venue": "Kømplex Lisbon", "aliases": ["komplex lisbon", "kømplex lisbon", "kømplex", "komplex", "praceta domingos rodrigues"], "lat": 38.7845, "lng": -9.1192, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor", "url": "https://shotgun.live/pt-pt/venues/komplex"},
    {"venue": "Moon Club", "aliases": ["moon club", "moonclub", "moon club prior velho", "raw kinky lab", "invdrs"], "lat": 38.7862, "lng": -9.1245, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor", "url": "https://www.moonclub.pt"},
    {"venue": "NĀDA 3.0 (NADA Lisbon)", "aliases": ["nada 3.0", "naada 3.0", "nada lisbon", "naada", "nāda", "rua figo maduro 3", "armazem 6", "tiga naada", "nada temple", "balagan"], "lat": 38.7858, "lng": -9.1238, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor", "url": "https://shotgun.live/pt-pt/venues/nada-lisbon"},
    {"venue": "Higher Ground", "aliases": ["higher ground", "rua ary dos santos 20"], "lat": 38.7868, "lng": -9.1252, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor", "url": "https://shotgun.live/en/cities/lisbon"},
    {"venue": "Music Station", "aliases": ["music station", "rock station", "aquilino ribeiro machado 74", "therapy sessions"], "lat": 38.7735, "lng": -9.0975, "neighborhood": "Parque das Nações / Oriente", "corridor": "Eastern Corridor", "url": "https://pt.ra.co/clubs/254407"},
    {"venue": "Top Floor", "aliases": ["top floor", "rua da pimenta 29"], "lat": 38.7712, "lng": -9.0928, "neighborhood": "Parque das Nações / Oriente", "corridor": "Eastern Corridor", "url": "https://www.lisabout.com/genero/dance-electronic"},

    # --- MARVILA, BEATO, ANJOS & EASTERN CORRIDOR ---
    {"venue": "Lux Frágil", "aliases": ["lux fragil", "lux", "av. infante d. henrique"], "lat": 38.7158, "lng": -9.1213, "neighborhood": "Santa Apolónia", "corridor": "Eastern Corridor", "url": "https://www.luxfragil.com"},
    {"venue": "8 Marvila", "aliases": ["8 marvila", "oito marvila", "praca david leandro da silva"], "lat": 38.7420, "lng": -9.1026, "neighborhood": "Marvila", "corridor": "Eastern Corridor", "url": "https://www.8marvila.com"},
    {"venue": "LAV - Lisboa ao Vivo", "aliases": ["lisboa ao vivo", "lav", "av. marechal gomes da costa"], "lat": 38.7475, "lng": -9.1026, "neighborhood": "Marvila / Cabo Ruivo", "corridor": "Eastern Corridor", "url": "https://lisboaaovivo.com"},
    {"venue": "Casa Capitão", "aliases": ["casa capitao", "convento do beato"], "lat": 38.7305, "lng": -9.1082, "neighborhood": "Beato", "corridor": "Eastern Corridor", "url": "https://casa-capitao.com"},
    {"venue": "Musa de Marvila", "aliases": ["musa de marvila", "musa marvila"], "lat": 38.7418, "lng": -9.1032, "neighborhood": "Marvila", "corridor": "Eastern Corridor", "url": "https://cervejamusa.com"},
    {"venue": "Arroz Estúdios", "aliases": ["arroz estudios", "arroz"], "lat": 38.7327, "lng": -9.1086, "neighborhood": "Beato", "corridor": "Eastern Corridor", "url": "https://arrozestudios.pt"},
    {"venue": "Fábrica Braço de Prata", "aliases": ["fabrica do braco de prata", "fabrica braco de prata", "braco de prata"], "lat": 38.7428, "lng": -9.0988, "neighborhood": "Marvila / Braço de Prata", "corridor": "Eastern Corridor", "url": "https://www.bracodeprata.com"},
    {"venue": "Underdogs Gallery", "aliases": ["underdogs", "underdogs gallery", "rua fernando palha"], "lat": 38.7363, "lng": -9.1020, "neighborhood": "Marvila", "corridor": "Eastern Corridor", "url": "https://www.under-dogs.net"},
    {"venue": "Teatro Meridional", "aliases": ["teatro meridional", "meridional"], "lat": 38.7360, "lng": -9.1025, "neighborhood": "Marvila", "corridor": "Eastern Corridor", "url": "https://teatromeridional.net"},
    {"venue": "BOTA - Base Organizada da Toca das Artes", "aliases": ["bota anjos", "bota", "base organizada da toca das artes", "largo de santa barbara"], "lat": 38.7247, "lng": -9.1345, "neighborhood": "Anjos", "corridor": "Eastern Corridor", "url": "https://www.botaanjos.com"},
    {"venue": "Hangar - Centro de Investigação Artística", "aliases": ["hangar", "rua damasceno monteiro", "mafolofolo"], "lat": 38.7198, "lng": -9.1306, "neighborhood": "Graça", "corridor": "Eastern Corridor", "url": "https://hangar.com.pt"},
    {"venue": "Feira da Ladra (Campo de Santa Clara)", "aliases": ["feira da ladra", "campo de santa clara"], "lat": 38.7154, "lng": -9.1255, "neighborhood": "São Vicente / Alfama", "corridor": "Eastern Corridor", "url": "https://www.agendalx.pt"},
    {"venue": "Pavilhão do Conhecimento", "aliases": ["pavilhao do conhecimento", "ciencia viva"], "lat": 38.7626, "lng": -9.0936, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor", "url": "https://www.pavconhecimento.pt"},
    {"venue": "Oceanário de Lisboa", "aliases": ["oceanario", "oceanario de lisboa", "halloweek"], "lat": 38.7635, "lng": -9.0937, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor", "url": "https://www.oceanario.pt"},
    {"venue": "MEO Arena", "aliases": ["meo arena", "altice arena", "sala tejo", "yumala"], "lat": 38.7686, "lng": -9.0940, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor", "url": "https://arena.meo.pt"},

    # --- AXIAL SPINE ---
    {"venue": "Galeria Zé dos Bois (ZDB)", "aliases": ["zdb", "galeria ze dos bois", "ze dos bois", "rua da barrosa"], "lat": 38.7124, "lng": -9.1444, "neighborhood": "Bairro Alto", "corridor": "Axial Spine", "url": "https://zedosbois.org"},
    {"venue": "Musicbox", "aliases": ["musicbox", "music box", "rua nova do carvalho"], "lat": 38.7072, "lng": -9.1436, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://musicboxlisboa.com"},
    {"venue": "Ministerium Club", "aliases": ["ministerium", "ministerium club", "terreiro do paco"], "lat": 38.7082, "lng": -9.1360, "neighborhood": "Terreiro do Paço", "corridor": "Axial Spine", "url": "https://pt.ra.co/clubs/66945"},
    {"venue": "Harbour Music Shelter", "aliases": ["harbour music shelter", "harbour"], "lat": 38.7066, "lng": -9.1448, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Rive Rouge", "aliases": ["rive rouge", "mercado da ribeira", "la papaya"], "lat": 38.7069, "lng": -9.1458, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Tokyo Lisboa", "aliases": ["tokyo lisboa", "tokyo", "rua nova do carvalho"], "lat": 38.7063, "lng": -9.1456, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://tokyolisboa.com"},
    {"venue": "B.Leza", "aliases": ["b.leza", "bleza", "cais da ribeira nova"], "lat": 38.7062, "lng": -9.1465, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://www.agendalx.pt"},
    {"venue": "Titanic Sur Mer", "aliases": ["titanic sur mer"], "lat": 38.7060, "lng": -9.1472, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://www.agendalx.pt"},
    {"venue": "Pátio da Galé", "aliases": ["patio da gale", "praca do comercio", "monkey project"], "lat": 38.7078, "lng": -9.1376, "neighborhood": "Baixa / Terreiro do Paço", "corridor": "Axial Spine", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Palácio Chiado", "aliases": ["palacio chiado", "rua do alecrim", "vralloween"], "lat": 38.7091, "lng": -9.1432, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://palaciochiado.pt"},
    {"venue": "Chiado Comedy Club", "aliases": ["chiado comedy club"], "lat": 38.7104, "lng": -9.1419, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://www.nocartaz.pt/concelhos/lisboa/"},
    {"venue": "Skones & Pátio do Pinzaleiro", "aliases": ["skones", "patio do pinzaleiro", "pinzaleiro"], "lat": 38.7086, "lng": -9.1562, "neighborhood": "Santos / Madragoa", "corridor": "Axial Spine", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Museu da Marioneta", "aliases": ["museu da marioneta", "convento das bernardas"], "lat": 38.7078, "lng": -9.1558, "neighborhood": "Madragoa / Santos", "corridor": "Axial Spine", "url": "https://www.museudamarioneta.pt"},
    {"venue": "Museu da Farmácia", "aliases": ["museu da farmacia"], "lat": 38.7097, "lng": -9.1482, "neighborhood": "Santa Catarina / Chiado", "corridor": "Axial Spine", "url": "https://www.museudafarmacia.pt"},
    {"venue": "Teatro do Bairro Alto (TBA)", "aliases": ["teatro do bairro alto", "tba"], "lat": 38.7197, "lng": -9.1528, "neighborhood": "Príncipe Real", "corridor": "Axial Spine", "url": "https://teatrodobairroalto.pt"},
    {"venue": "Fundação Arpad Szenes-Vieira da Silva", "aliases": ["arpad szenes", "vieira da silva", "praca das amoreiras"], "lat": 38.7215, "lng": -9.1592, "neighborhood": "Amoreiras / Rato", "corridor": "Axial Spine", "url": "https://fasvs.pt"},
    {"venue": "Cineteatro Capitólio", "aliases": ["capitolio", "cineteatro capitolio", "teatro capitolio", "parque mayer"], "lat": 38.7186, "lng": -9.1462, "neighborhood": "Parque Mayer / Avenida", "corridor": "Axial Spine", "url": "https://www.cineteatrocapitolio.pt"},
    {"venue": "Teatro Variedades", "aliases": ["teatro variedades", "variedades"], "lat": 38.7191, "lng": -9.1462, "neighborhood": "Parque Mayer", "corridor": "Axial Spine", "url": "https://teatrovariedades-capitolio.pt"},
    {"venue": "Teatro Politeama", "aliases": ["teatro politeama", "politeama"], "lat": 38.7161, "lng": -9.1408, "neighborhood": "Baixa / Rossio", "corridor": "Axial Spine", "url": "https://filipelaferia.pt"},
    {"venue": "Coliseu dos Recreios", "aliases": ["coliseu", "coliseu dos recreios", "rua das portas de santo antao"], "lat": 38.7168, "lng": -9.1408, "neighborhood": "Baixa / Rossio", "corridor": "Axial Spine", "url": "https://www.coliseulisboa.com"},
    {"venue": "Teatro Nacional D. Maria II", "aliases": ["d. maria ii", "d maria ii", "dona maria ii", "tndmii"], "lat": 38.7146, "lng": -9.1396, "neighborhood": "Rossio", "corridor": "Axial Spine", "url": "https://www.tndm.pt"},
    {"venue": "São Luiz Teatro Municipal", "aliases": ["sao luiz", "teatro sao luiz", "sao luis"], "lat": 38.7095, "lng": -9.1426, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://www.teatrosaoluiz.pt"},
    {"venue": "Teatro Nacional de São Carlos", "aliases": ["sao carlos", "teatro nacional de sao carlos"], "lat": 38.7097, "lng": -9.1415, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://saocarlos.pt"},
    {"venue": "Teatro da Trindade INATEL", "aliases": ["teatro da trindade", "trindade inatel"], "lat": 38.7128, "lng": -9.1425, "neighborhood": "Chiado / Bairro Alto", "corridor": "Axial Spine", "url": "https://teatrodatrindade.inatel.pt"},
    {"venue": "Teatro Tivoli BBVA", "aliases": ["tivoli", "tivoli bbva", "teatro tivoli"], "lat": 38.7209, "lng": -9.1456, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine", "url": "https://www.teatrotivolibbva.pt"},
    {"venue": "Cinemateca Portuguesa", "aliases": ["cinemateca", "cinemateca portuguesa", "rua barata salgueiro"], "lat": 38.7219, "lng": -9.1482, "neighborhood": "Avenida / Marquês", "corridor": "Axial Spine", "url": "https://www.cinemateca.pt"},
    {"venue": "Cinema São Jorge", "aliases": ["cinema sao jorge", "sao jorge"], "lat": 38.7212, "lng": -9.1453, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine", "url": "https://cinemasaojorge.pt"},
    {"venue": "Cinema Ideal", "aliases": ["cinema ideal", "rua do loreto"], "lat": 38.7107, "lng": -9.1449, "neighborhood": "Chiado / Camões", "corridor": "Axial Spine", "url": "https://cinemaideal.pt"},
    {"venue": "MNAC - Museu do Chiado", "aliases": ["mnac", "museu do chiado", "museu nacional de arte contemporanea", "alfarrabistas"], "lat": 38.7088, "lng": -9.1412, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://museuartecontemporanea.gov.pt"},
    {"venue": "MUDE — Museu do Design", "aliases": ["mude", "museu do design", "rua augusta"], "lat": 38.7094, "lng": -9.1370, "neighborhood": "Baixa", "corridor": "Axial Spine", "url": "https://www.mude.pt"},
    {"venue": "Museu do Fado", "aliases": ["museu do fado", "largo do chafariz de dentro"], "lat": 38.7112, "lng": -9.1277, "neighborhood": "Alfama", "corridor": "Axial Spine", "url": "https://www.museudofado.pt"},
    {"venue": "Incógnito", "aliases": ["incognito", "rua de poiais de sao bento"], "lat": 38.7135, "lng": -9.1528, "neighborhood": "São Bento", "corridor": "Axial Spine", "url": "https://incognitobar.com"},
    {"venue": "Plano B / Bica & Cais", "aliases": ["bicaense", "damas", "casa independente", "desterro", "bus paragem cultural"], "lat": 38.7218, "lng": -9.1352, "neighborhood": "Intendente / Anjos", "corridor": "Axial Spine", "url": "https://www.agendalx.pt"},

    # --- NORTHERN BELT ---
    {"venue": "CAM - Centro de Arte Moderna Gulbenkian", "aliases": ["gulbenkian", "fundacao calouste gulbenkian", "cam gulbenkian", "centro de arte moderna"], "lat": 38.7376, "lng": -9.1545, "neighborhood": "Avenidas Novas / Praça de Espanha", "corridor": "Northern Belt", "url": "https://gulbenkian.pt"},
    {"venue": "Reitoria da Universidade NOVA de Lisboa", "aliases": ["reitoria da nova", "universidade nova", "campolide"], "lat": 38.7336, "lng": -9.1602, "neighborhood": "Campolide / Praça de Espanha", "corridor": "Northern Belt", "url": "https://www.unl.pt"},
    {"venue": "Teatro da Comuna", "aliases": ["teatro da comuna", "comuna", "opera-pimba no gelo"], "lat": 38.7367, "lng": -9.1605, "neighborhood": "Praça de Espanha", "corridor": "Northern Belt", "url": "https://www.comunateatropesquisa.pt"},
    {"venue": "Jardim Zoológico de Lisboa", "aliases": ["jardim zoologico", "zoo de lisboa", "halloween no zoo", "reptilario"], "lat": 38.7442, "lng": -9.1712, "neighborhood": "Sete Rios", "corridor": "Northern Belt", "url": "https://www.zoo.pt"},
    {"venue": "Evolution Valbom Rooftop", "aliases": ["evolution valbom", "valbom", "rooftop over lisbon"], "lat": 38.7351, "lng": -9.1485, "neighborhood": "Saldanha", "corridor": "Northern Belt", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Culturgest", "aliases": ["culturgest", "arco do cego"], "lat": 38.7402, "lng": -9.1412, "neighborhood": "Campo Pequeno / Arco do Cego", "corridor": "Northern Belt", "url": "https://www.culturgest.pt"},
    {"venue": "Cinema Medeia Nimas", "aliases": ["nimas", "cinema nimas", "medeia nimas", "av. 5 de outubro"], "lat": 38.7357, "lng": -9.1495, "neighborhood": "Saldanha", "corridor": "Northern Belt", "url": "https://medeiafilmes.com/cinemas/cinema-medeia-nimas"},
    {"venue": "Teatro Maria Matos", "aliases": ["maria matos", "teatro maria matos", "av. frei miguel contreiras"], "lat": 38.7463, "lng": -9.1380, "neighborhood": "Roma / Areeiro", "corridor": "Northern Belt", "url": "https://teatromariamatos.pt"},
    {"venue": "Teatro Bocage", "aliases": ["teatro bocage", "rua manuel da silva leal"], "lat": 38.7429, "lng": -9.1392, "neighborhood": "Areeiro / Alvalade", "corridor": "Northern Belt", "url": "https://www.nocartaz.pt/concelhos/lisboa/"},
    {"venue": "Cinema City Classic Alvalade", "aliases": ["cinema city classic alvalade", "cinema city alvalade", "classic alvalade"], "lat": 38.7534, "lng": -9.1442, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://www.cinemacity.pt"},
    {"venue": "República da Música", "aliases": ["republica da musica", "alvalade"], "lat": 38.7562, "lng": -9.1456, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://www.agendalx.pt"},
    {"venue": "RCA Club", "aliases": ["rca club", "rca", "rua joao saraiva"], "lat": 38.7502, "lng": -9.1261, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://www.rcaclub.com"},
    {"venue": "Távola Jazz Club", "aliases": ["tavola jazz club", "tavola"], "lat": 38.7485, "lng": -9.1398, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://www.tavolajazzclub.com"},
    {"venue": "Sagres Campo Pequeno", "aliases": ["campo pequeno", "sagres campo pequeno"], "lat": 38.7425, "lng": -9.1452, "neighborhood": "Campo Pequeno", "corridor": "Northern Belt", "url": "https://www.campopequeno.com"},
    {"venue": "Pavilhão Carlos Lopes", "aliases": ["pavilhao carlos lopes", "parque eduardo vii"], "lat": 38.7289, "lng": -9.1518, "neighborhood": "Parque Eduardo VII", "corridor": "Northern Belt", "url": "https://www.agendalx.pt"},

    # --- BELÉM WATERFRONT & ALCÂNTARA ---
    {"venue": "Centro Cultural de Belém (CCB)", "aliases": ["ccb", "centro cultural de belem", "mac/ccb", "museu de arte contemporanea"], "lat": 38.6956, "lng": -9.2064, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://www.ccb.pt"},
    {"venue": "MAAT - Museu de Arte, Arquitetura e Tecnologia", "aliases": ["maat", "central tejo"], "lat": 38.6959, "lng": -9.1945, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://www.maat.pt"},
    {"venue": "Museu Nacional dos Coches", "aliases": ["museu nacional dos coches", "museu dos coches"], "lat": 38.6966, "lng": -9.1997, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://www.mncoches.gov.pt"},
    {"venue": "BONANÇA - Associação Naval de Lisboa", "aliases": ["bonanca", "associacao naval de lisboa", "doca de belem"], "lat": 38.6942, "lng": -9.2038, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "MACAM / àCapela", "aliases": ["macam", "acapela", "junqueira"], "lat": 38.6989, "lng": -9.1887, "neighborhood": "Belém / Junqueira", "corridor": "Belém Waterfront", "url": "https://www.nocartaz.pt/concelhos/lisboa/"},
    {"venue": "LX Factory / Village Underground", "aliases": ["lx factory", "lxfactory", "collect lx factory", "village underground", "alcântara", "alcantara", "the hospital"], "lat": 38.7035, "lng": -9.1788, "neighborhood": "Alcântara", "corridor": "Belém Waterfront", "url": "https://lxfactory.com"},
    {"venue": "Docas de Santo Amaro / Cais Rocha Conde de Óbidos", "aliases": ["docas de santo amaro", "rocha conde de obidos", "sunset boat party", "brewclub"], "lat": 38.7008, "lng": -9.1742, "neighborhood": "Alcântara / Docas", "corridor": "Belém Waterfront", "url": "https://www.agendalx.pt"},
    {"venue": "Museu do Oriente", "aliases": ["museu do oriente", "av. brasilia"], "lat": 38.7027, "lng": -9.1714, "neighborhood": "Alcântara", "corridor": "Belém Waterfront", "url": "https://www.foriente.pt"},
    {"venue": "LU.CA — Teatro Luís de Camões", "aliases": ["lu.ca", "luca", "teatro luis de camoes", "calcada da ajuda"], "lat": 38.7005, "lng": -9.2015, "neighborhood": "Belém / Ajuda", "corridor": "Belém Waterfront", "url": "https://lucateatroluisdecamoes.pt"},
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
    """Strips stray HTML tags (like <br>) and normalizes whitespace."""
    if not text:
        return ""
    s = fix_mojibake(text)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_accents(text):
    if not text:
        return ""
    norm = unicodedata.normalize("NFD", str(text))
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn").lower()


def match_venue(*texts, require_match=False):
    combined = strip_accents(" ".join(fix_mojibake(t) for t in texts if t))
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


def infer_category_preset(text, default_key="concerts"):
    low = strip_accents(text or "")
    if any(k in low for k in ["exposicao", "artes plasticas", "fotografia", "instalacao", "arte moderna", "artes visuais", "cartoon"]):
        return CATEGORY_PRESETS["exhibitions"]
    if any(k in low for k in ["teatro", "danca", "comedia", "stand-up", "stand up", "circo", "improviso", "musical", "performance"]):
        return CATEGORY_PRESETS["theatre"]
    if any(k in low for k in ["cinema", "filme", "documentario", "curtas", "animacao"]):
        return CATEGORY_PRESETS["cinema"]
    if any(k in low for k in ["opera", "classica", "sinfonica", "coro", "orquestra", "schubert", "beethoven", "strauss"]):
        return CATEGORY_PRESETS["classical"]
    if any(k in low for k in ["criancas", "familia", "oficina", "infantil", "jovens", "bebes", "kids", "pre-escolar", "ciclo"]):
        return CATEGORY_PRESETS["family"]
    if any(k in low for k in ["dj", "clubbing", "eletronica", "noite", "festa", "rave", "techno", "house", "afterhours", "halloween party", "pub crawl"]):
        return CATEGORY_PRESETS["nightlife"]
    if any(k in low for k in ["conferencia", "feira", "mercado", "literatura", "alfarrabistas", "visita", "comunidade", "workshop", "tertulia"]):
        return CATEGORY_PRESETS["community"]
    return CATEGORY_PRESETS.get(default_key, CATEGORY_PRESETS["concerts"])


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
        if "pavilhao do conhecimento" in v_low or "zoo" in v_low or "oceanario" in v_low:
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
        if "feira da ladra" in v_low:
            return "17:00", 17
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
            return "08:00", 8
        if "nada" in v_low or "naada" in v_low:
            return "06:00", 6
        return "06:00", 6

    return add_minutes(sh, sm, 120)


def parse_price_and_tier(text, default_price="Consultar bilheteira", default_tier="ACCESSIBLE"):
    low = strip_accents(text or "")
    if any(k in low for k in ["entrada livre", "gratuito", "gratis", "free", "borla", "gratuita"]):
        return "Entrada Livre", "FREE"
    m = re.search(r"(\d{1,3})(?:[.,](\d{1,2}))?\s*€", str(text))
    if m:
        val = float(f"{m.group(1)}.{m.group(2) or '0'}")
        disp = f"{m.group(1)}€" if not m.group(2) else f"{m.group(1)}.{m.group(2)}€"
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
    resp = SCRAPER_SESSION.get(url, headers=hdrs, timeout=timeout)
    if hasattr(resp, "encoding") and resp.encoding and resp.encoding.lower() in ("iso-8859-1", "latin-1"):
        resp.encoding = "utf-8"
    return resp


# ==============================================================================
# TIER 1: AGENDALX & NOCARTAZ LISBOA
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
            txt = clean_html_text(art.get_text(" ", strip=True))
            a_tag = art.find("a", href=True)
            if not a_tag:
                continue
            title_el = art.find(["h2", "h3", "h4"])
            title = clean_html_text(title_el.get_text(" ", strip=True) if title_el else a_tag.get_text(" ", strip=True))
            if not title or len(title) < 3:
                continue

            preset = infer_category_preset(txt)
            default_t = "10:00" if preset == CATEGORY_PRESETS["exhibitions"] else "21:00"
            time_str, hour_int = parse_time_str(txt, default_t)
            geo = match_venue(txt, title)
            price_disp, price_tier = parse_price_and_tier(txt, "Entrada sujeita a bilheteira", "ACCESSIBLE")
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
                "url": urljoin("https://www.agendalx.pt", a_tag["href"]),
                "description": f"{title} em {geo['venue']} ({geo['neighborhood']}).",
            })
    except Exception as e:
        print(f"[AgendaLX] Notice: {e}")
    return events


def scrape_nocartaz(target_date):
    """Scrapes NoCartaz Lisboa (https://www.nocartaz.pt/concelhos/lisboa/) for target_date."""
    events = []
    month_short = PT_MONTHS_SHORT[target_date.month]
    day_pat = rf"\b0?{target_date.day}\s+{month_short}\b"
    print(f"[Tier 1] Scraping NoCartaz Lisboa for {target_date.day} {month_short}...")
    try:
        resp = fetch_url("https://www.nocartaz.pt/concelhos/lisboa/")
        if resp.status_code != 200:
            return events
        soup = BeautifulSoup(resp.text, "html.parser")
        seen_hrefs = set()
        for a_tag in soup.select('a[href*="/eventos/"]'):
            href = a_tag.get("href", "")
            if not href or href in seen_hrefs:
                continue
            container = a_tag.find_parent(["article", "li", "div"]) or a_tag
            raw_pipe = clean_html_text(container.get_text(" | ", strip=True))
            if not re.search(day_pat, strip_accents(raw_pipe)):
                continue
            seen_hrefs.add(href)

            h_el = container.find(["h2", "h3", "h4"])
            title = clean_html_text(h_el.get_text(" ", strip=True)) if h_el else ""
            parts = [p.strip() for p in raw_pipe.split("|") if p.strip() and p.strip() != "♡"]
            if not title and len(parts) >= 2:
                title = parts[1]
            if not title or len(title) < 3:
                continue

            # Extract clean venue name from pipe segments without leaking full card text
            venue_candidate = ""
            for p in parts:
                if "· Lisboa" in p or ("·" in p and not re.search(day_pat, strip_accents(p))):
                    venue_candidate = p.split("·")[0].strip()
                    break

            geo = match_venue(venue_candidate, title, raw_pipe, require_match=True)
            if not geo:
                geo = {
                    "venue": venue_candidate if (venue_candidate and len(venue_candidate) < 55) else "Lisboa Central",
                    "lat": 38.7165,
                    "lng": -9.1415,
                    "neighborhood": "Centro Histórico",
                    "corridor": "Axial Spine",
                    "url": "https://www.nocartaz.pt/concelhos/lisboa/",
                }

            preset = infer_category_preset(raw_pipe)
            default_t = "10:00" if preset["category"] in ("Exhibitions & Visual Arts", "Family & Youth") else "21:00"
            time_str, hour_int = parse_time_str(raw_pipe, default_t)
            price_disp, price_tier = parse_price_and_tier(raw_pipe)
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
                "url": urljoin("https://www.nocartaz.pt", href),
                "description": f"{title} ao vivo em {geo['venue']} ({geo['neighborhood']}).",
            })
    except Exception as e:
        print(f"[NoCartaz] Notice: {e}")
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
            rf"{re.escape(d_slash)}\s*,\s*(\d{{1,2}})[h:](\d{{2}})\s*\|\s*([^\n]+)\n+([^\n]+)(?:\n+([^\n]+))?",
            re.I
        )
        for idx, m in enumerate(pattern.finditer(soup.get_text("\n", strip=True))):
            hh, mm = int(m.group(1)), int(m.group(2))
            room = clean_html_text(m.group(3))
            line1 = clean_html_text(m.group(4))
            line2 = clean_html_text(m.group(5) or "")
            title = line2 if (line2 and len(line2) > 3 and "ciclo" in line1.lower()) else line1
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
        next_day_m = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", day_section)
        if next_day_m:
            day_section = day_section[:next_day_m.start()]

        geo = match_venue("cinema medeia nimas")
        lines = [clean_html_text(ln) for ln in day_section.splitlines() if clean_html_text(ln)]
        i = 0
        while i < len(lines):
            tm = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", lines[i])
            if tm and i + 1 < len(lines):
                time_str = f"{int(tm.group(1)):02d}:{tm.group(2)}"
                hour_int = int(tm.group(1))
                film_title = lines[i + 1]
                director = ""
                if i + 2 < len(lines) and lines[i + 2].lower().startswith("de "):
                    director = f" ({lines[i + 2]})"
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
                i += 2
                continue
            i += 1
    except Exception as e:
        print(f"[Medeia Nimas] Notice: {e}")
    return events


def scrape_agendadeconcertos(target_date):
    """Scrapes Agenda de Concertos (https://agendadeconcertos.com/concertos-em-portugal/) for Lisbon."""
    events = []
    month_full = PT_MONTHS_FULL[target_date.month]
    header_pat = rf"\b{target_date.day}\s+{month_full}\b"
    print(f"[Tier 2] Scraping Agenda de Concertos for {target_date.day} {month_full}...")
    try:
        resp = fetch_url("https://agendadeconcertos.com/concertos-em-portugal/")
        if resp.status_code != 200:
            return events
        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.select('a[href*="/concertos/"]'):
            parent_txt = clean_html_text(a_tag.parent.get_text(" ", strip=True) if a_tag.parent else "")
            if "lisboa" not in strip_accents(parent_txt):
                continue
            prev_heading = a_tag.find_previous(["h2", "h3", "h4", "strong"])
            heading_txt = clean_html_text(prev_heading.get_text(" ", strip=True)) if prev_heading else ""
            if heading_txt and not re.search(header_pat, strip_accents(heading_txt), re.I):
                continue

            artist = clean_html_text(a_tag.get_text(" ", strip=True))
            if not artist or "cancelado" in artist.lower():
                continue
            venue_part = parent_txt.replace(artist, "").split("–")[0].strip(" -–•|")
            geo = match_venue(venue_part, artist)
            preset = infer_category_preset(f"{artist} {venue_part}", "concerts")
            time_str, hour_int = parse_time_str(parent_txt, "21:30")
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
                "price": "Consultar bilheteira",
                "priceTier": "ACCESSIBLE",
                "url": a_tag["href"],
                "description": f"Concerto de {artist} ao vivo em {geo['venue']} ({geo['neighborhood']}).",
            })
    except Exception as e:
        print(f"[Agenda de Concertos] Notice: {e}")
    return events


def scrape_bota_anjos(target_date):
    """Scrapes BOTA Anjos (https://www.botaanjos.com/programacao)."""
    events = []
    d_slash = target_date.strftime("%d/%m/%Y")
    month_full = PT_MONTHS_FULL[target_date.month]
    d_long = f"{target_date.day} de {month_full}"
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
            if full_url in seen_urls:
                continue
            card = a_tag.find_parent(["article", "div", "li"]) or a_tag
            txt = clean_html_text(card.get_text(" ", strip=True))
            if d_slash not in txt and d_long not in strip_accents(txt):
                continue
            title_el = card.find(["h1", "h2", "h3", "h4"])
            title = clean_html_text(title_el.get_text(" ", strip=True) if title_el else a_tag.get_text(" ", strip=True))
            if not title or len(title) < 3 or title.lower() in ("programação", "ver evento"):
                continue
            seen_urls.add(full_url)
            preset = infer_category_preset(f"{title} {txt}", "concerts")
            time_str, hour_int = parse_time_str(txt, "21:00")
            end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, txt)
            events.append({
                "id": f"bota-{target_date.strftime('%Y%m%d')}-{abs(hash(title)) % 10000}",
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
                "price": "5€ - 10€",
                "priceTier": "ACCESSIBLE",
                "url": full_url,
                "description": f"{title} na BOTA Anjos (Largo de Santa Bárbara, Anjos).",
            })
    except Exception as e:
        print(f"[BOTA Anjos] Notice: {e}")
    return events


# ==============================================================================
# TIER 3: RESIDENT ADVISOR & PRIOR VELHO / ELECTRONIC HUBS
# ==============================================================================
def scrape_resident_advisor(target_date):
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"[Tier 3] Querying Resident Advisor GraphQL for Lisbon (Area 229) on {date_str}...")

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
                title = clean_html_text(ev.get("title") or "Noite Eletrónica")
                venue_obj = ev.get("venue") or {}
                v_name = clean_html_text(venue_obj.get("name") or "")
                v_addr = clean_html_text(venue_obj.get("address") or "")

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
    events = []
    next_date = target_date + datetime.timedelta(days=1)
    d_today = f"{target_date.day}/{target_date.month:02d}"
    d_next = f"{next_date.day}/{next_date.month:02d}"

    lisabout_urls = [
        "https://www.lisabout.com/zona/prior-velho",
        "https://www.lisabout.com/genero/dance-electronic",
    ]
    print(f"[Tier 3] Scraping Prior Velho & Electronic hubs for {d_today} (and afterhours {d_next})...")

    for url in lisabout_urls:
        try:
            resp = fetch_url(url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/events/"]'):
                href = a_tag.get("href", "")
                card_text = clean_html_text(a_tag.get_text(" | ", strip=True))
                is_today = d_today in card_text
                is_afterhours = d_next in card_text and bool(re.search(r"\b0[4-8]:[0-5]\d\b", card_text))
                if not (is_today or is_afterhours):
                    continue

                time_str, hour_int = parse_time_str(card_text, "23:59")
                title_el = a_tag.find(["h3", "h4", "strong"])
                title = clean_html_text(title_el.get_text(" ", strip=True)) if title_el else ""
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

    try:
        resp = fetch_url("https://www.moonclub.pt/")
        if resp.status_code == 200 and d_today in resp.text:
            soup = BeautifulSoup(resp.text, "html.parser")
            geo = match_venue("moon club")
            for block in soup.find_all(["li", "div", "article"]):
                txt = clean_html_text(block.get_text(" ", strip=True))
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
                        "price": "10€ - 18€",
                        "priceTier": "ACCESSIBLE",
                        "url": "https://www.moonclub.pt",
                        "description": f"{title} no Moon Club (Rua Ary dos Santos 3, Prior Velho). Noite de techno e clubbing até ao nascer do sol.",
                    })
                    break
    except Exception as e:
        print(f"[Moon Club Scraper] Notice: {e}")

    return events


# ==============================================================================
# TIER 4: ACTIVE LISBON MUSEUM EXHIBITIONS & THEATRE RUNS (DAILY BASELINE)
# ==============================================================================
def get_ongoing_cultural_events(target_date):
    """
    Generates day-of-week-aware ongoing Lisbon museum exhibitions, cultural hubs,
    and active theatre runs so 04:00 AM rollovers always include major resident programming.
    """
    ymd = target_date.strftime("%Y%m%d")
    weekday = target_date.weekday()  # 0=Mon ... 5=Sat, 6=Sun
    ongoing = []

    def add_item(idx, title, cat_key, venue_alias, time_str, end_str, price, tier, url, desc):
        geo = match_venue(venue_alias)
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

    # Museums & Cultural Centers (Open daily or Tue-Sun)
    add_item(1, "Xerazade, a Coleção Interminável do CAM & Inês Zenha: Águas Turvas", "exhibitions",
             "cam gulbenkian", "10:00", "18:00", "8.00€", "ACCESSIBLE",
             "https://gulbenkian.pt/cam/agenda/", "Exposições de arte moderna e contemporânea no renovado CAM Gulbenkian.")
    add_item(2, "Exposições Interativas de Ciência Viva em Família", "family",
             "pavilhao do conhecimento", "10:00", "18:00", "11€ - 15€", "ACCESSIBLE",
             "https://www.pavconhecimento.pt", "Exploração científica interativa e oficinas para famílias no Parque das Nações.")
    add_item(3, "Uma Deriva Atlântica, Ângela Ferreira & Frida Orupabo", "exhibitions",
             "ccb", "10:00", "19:00", "10.00€", "ACCESSIBLE",
             "https://www.ccb.pt", "Exposições de arte moderna e contemporânea no MAC/CCB em Belém.")
    add_item(4, "Galerias de Arte, Lojas Independentes & Cultura Emergente", "community",
             "8 marvila", "12:00", "20:00", "Entrada Livre", "FREE",
             "https://www.8marvila.com", "Percurso expositivo, galerias e espaço cultural nos antigos armazéns do 8 Marvila.")

    if weekday != 0:  # Tuesday - Sunday
        add_item(5, "Délio Jasse: Entre a Pele e o Documento & Antologias da Memória", "exhibitions",
                 "mnac", "10:00", "18:00", "10.00€", "ACCESSIBLE",
                 "https://museuartecontemporanea.gov.pt", "Exposições temporárias de fotografia e arte contemporânea no MNAC - Museu do Chiado.")
        add_item(6, "Coleção Real de Viaturas de Gala & Modelismo de Coches", "exhibitions",
                 "museu nacional dos coches", "10:00", "18:00", "8.00€", "ACCESSIBLE",
                 "https://www.mncoches.gov.pt", "Exposição permanente e temporária no Museu Nacional dos Coches em Belém.")
        add_item(7, "Turn Around & Visitas à Central Tejo", "exhibitions",
                 "maat", "11:00", "19:00", "11.00€", "ACCESSIBLE",
                 "https://www.maat.pt", "Leitura ampla da arte contemporânea em Portugal no MAAT e Central Tejo (Belém).")
        add_item(8, "Japão: Festas e Rituais & Coleção Kwok On", "exhibitions",
                 "museu do oriente", "10:00", "18:00", "8.00€", "ACCESSIBLE",
                 "https://www.foriente.pt", "Exposição sobre festas e rituais tradicionais asiáticos no Museu do Oriente (Alcântara).")
        add_item(9, "Exposições de Arte Urbana & Edições de Artista", "exhibitions",
                 "underdogs gallery", "14:00", "19:00", "Entrada Livre", "FREE",
                 "https://www.under-dogs.net", "Galeria de arte contemporânea e arte urbana em Marvila.")

    if weekday in (1, 5):  # Tuesday & Saturday
        add_item(10, "Feira da Ladra — Mercado Histórico de Antiguidades e Vinil", "community",
                 "feira da ladra", "09:00", "17:00", "Entrada Livre", "FREE",
                 "https://www.agendalx.pt", "O mercado mais antigo de Lisboa no Campo de Santa Clara (terças e sábados).")

    if weekday in (2, 3, 4, 5):  # Wednesday - Saturday
        add_item(11, "Alexandre Estrela: RedSkyFalls (Réplica) — Exposição ZDB", "exhibitions",
                 "zdb", "18:00", "22:00", "Entrada Livre", "FREE",
                 "https://zedosbois.org/en/programa/redskyfalls-replica/", "Exposição de artes visuais de Alexandre Estrela na Galeria Zé dos Bois (18h–22h).")
        add_item(12, "Macbeth (enc. Pedro Penim) & Auto da Barca do Inferno (Raquel Castro)", "theatre",
                 "d. maria ii", "20:00", "22:00", "15.00€", "MID",
                 "https://www.tndm.pt", "Temporada teatral no Teatro Nacional D. Maria II.")
        add_item(13, "Em Silêncio — de Teresa Sobral", "theatre",
                 "sao luiz", "20:00", "22:00", "12.00€", "ACCESSIBLE",
                 "https://www.teatrosaoluiz.pt/espetaculo/em-silencio/", "Espetáculo de teatro contemporâneo em cena no São Luiz Teatro Municipal.")
        add_item(14, "Ópera-Pimba no Gelo! O Primeiro Musical no Gelo Derretido", "theatre",
                 "teatro da comuna", "20:10", "22:10", "12€ - 15€", "ACCESSIBLE",
                 "https://www.comunateatropesquisa.pt", "Comédia musical satírica na Sala Nova do Teatro da Comuna (Praça de Espanha).")
        add_item(15, "Clube dos Poetas Mortos — enc. Hélder Gamboa", "theatre",
                 "teatro da trindade", "21:00", "23:00", "16€ - 22€", "MID",
                 "https://teatrodatrindade.inatel.pt", "Peça de Tom Schulman em cena no Teatro da Trindade INATEL no Chiado.")
        add_item(16, "Pura Loucura — Temporada Teatro Maria Matos", "theatre",
                 "teatro maria matos", "21:00", "23:00", "21€ - 23€", "MID",
                 "https://teatromariamatos.pt/espetaculos/pura-loucura/", "Comédia teatral em cena no Teatro Maria Matos.")
        add_item(17, "Contos em Viagem — Goa", "theatre",
                 "teatro meridional", "21:00", "23:00", "12.00€", "ACCESSIBLE",
                 "https://teatromeridional.net", "Espetáculo teatral no Teatro Meridional em Marvila.")
        add_item(18, "Hércules - O Musical Heróico & Carmen Miranda - O Grande Musical", "theatre",
                 "teatro politeama", "21:00", "23:00", "15€ - 30€", "MID",
                 "https://filipelaferia.pt", "Grandes produções musicais de Filipe La Féria no Teatro Politeama.")

    return ongoing


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
    print(f"=== Keks Passa Scraper v2.2 — Operational Date: {date_str} ===")

    existing_events = []
    if os.path.exists("events.json"):
        try:
            with open("events.json", "r", encoding="utf-8") as f:
                old_payload = json.load(f)
            if old_payload.get("operational_date") == date_str:
                bad_venues = {"exit reality", "rasa", "mdlr", "66 chambers", "earworm"}
                existing_events = [
                    e for e in (old_payload.get("events") or [])
                    if str(e.get("venue", "")).lower().strip() not in bad_venues
                ]
        except Exception as e:
            print(f"[Main] Notice reading existing events.json: {e}")

    live_raw = []
    live_raw.extend(scrape_agendalx(target_date))
    live_raw.extend(scrape_nocartaz(target_date))
    live_raw.extend(scrape_cinemateca(target_date))
    live_raw.extend(scrape_nimas(target_date))
    live_raw.extend(scrape_agendadeconcertos(target_date))
    live_raw.extend(scrape_bota_anjos(target_date))
    live_raw.extend(scrape_resident_advisor(target_date))
    live_raw.extend(scrape_prior_velho_electronic(target_date))
    live_raw.extend(get_ongoing_cultural_events(target_date))

    all_events = deduplicate_events(existing_events + live_raw)

    # Ensure every event has clean text, endTime/endHour, and valid Lisbon coordinates
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
        lat = float(ev.get("lat", 38.7169))
        lng = float(ev.get("lng", -9.1399))
        if not (38.65 <= lat <= 38.82):
            lat = 38.7169
        if not (-9.25 <= lng <= -9.05):
            lng = -9.1399
        ev["lat"] = lat
        ev["lng"] = lng
        if not str(ev.get("url", "")).startswith("http"):
            ev["url"] = "https://www.agendalx.pt"
        validated.append(ev)

    # Sort chronologically along the 04:00 AM operational day
    def op_sort_key(e):
        t_parts = str(e.get("time", "21:00")).split(":")
        h = int(t_parts[0]) if t_parts and t_parts[0].isdigit() else int(e.get("hour", 21))
        m = int(t_parts[1]) if len(t_parts) > 1 and t_parts[1].isdigit() else 0
        op_h = h + 24 if h < 4 else h
        return (op_h * 60 + m, e.get("title", ""))

    validated.sort(key=op_sort_key)
    validated = apply_coordinate_jitter(validated)

    payload = {
        "generated_at": now_lx.isoformat(),
        "operational_date": date_str,
        "date_string": date_str,
        "total_events": len(validated),
        "events": validated,
    }

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"=== Saved {len(validated)} events to events.json for {date_str} ===")


if __name__ == "__main__":
    main()
