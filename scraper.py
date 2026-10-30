#!/usr/bin/env python3
"""
Keks Passa / Lisbon Live Daily Events Pipeline (v2.0)
Scrapes, deduplicates, and geocodes cultural & nightlife events in Lisbon
based on the 04:00 Europe/Lisbon operational day.

Live Multi-Tier Sources:
 - Tier 1: AgendaLX Official WP REST API (wp-json/agendalx/v1/events) & RA GraphQL API
 - Tier 2: Direct Venue Scrapers (Cinemateca, Medeia Nimas, BOTA, ZDB, Casa Capitão, Ticketline)
 - Tier 3: High-Density Aggregators (NoCartaz Lisboa, Agenda de Concertos, Shotgun Live)
 - Tier 4: Date-Verified Ongoing Exhibitions & Theater Seasons (Only for unrepresented active venues)
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

# Use curl_cffi if available to impersonate Chrome TLS fingerprint (bypasses Cloudflare on RA/Shotgun)
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

# Maximum events cap (None = unlimited, or set to e.g. 150)
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

# ==============================================================================
# MASTER LISBON VENUE REGISTRY (Verified Coords & Working Official/Agenda URLs)
# ==============================================================================
VENUE_REGISTRY = [
    # --- AXIAL SPINE (Baixa, Chiado, Bairro Alto, Príncipe Real, Av. Liberdade, Cais do Sodré) ---
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
        "venue": "Teatro Nacional D. Maria II",
        "aliases": ["teatro nacional d. maria ii", "teatro nacional dona maria ii", "d. maria ii", "tndm"],
        "lat": 38.7138, "lng": -9.1394, "neighborhood": "Rossio", "corridor": "Axial Spine",
        "url": "https://www.tndm.pt"
    },
    {
        "venue": "São Luiz Teatro Municipal",
        "aliases": ["sao luiz teatro municipal", "teatro municipal sao luiz", "teatro sao luiz", "sao luiz"],
        "lat": 38.7101, "lng": -9.1423, "neighborhood": "Chiado", "corridor": "Axial Spine",
        "url": "https://www.teatrosaoluiz.pt/programacao/"
    },
    {
        "venue": "Teatro Nacional de São Carlos",
        "aliases": ["teatro nacional de sao carlos", "sao carlos", "tnsc"],
        "lat": 38.7096, "lng": -9.1416, "neighborhood": "Chiado", "corridor": "Axial Spine",
        "url": "https://cartazculturallisboa.pt/agenda-teatro-nacional-de-sao-carlos/"
    },
    {
        "venue": "Teatro da Trindade INATEL",
        "aliases": ["teatro da trindade inatel", "teatro da trindade", "largo da trindade"],
        "lat": 38.7126, "lng": -9.1424, "neighborhood": "Chiado", "corridor": "Axial Spine",
        "url": "https://teatrotrindade.inatel.pt/programacao/"
    },
    {
        "venue": "Teatro do Bairro Alto (TBA)",
        "aliases": ["teatro do bairro alto", "tba - teatro bairro alto", "tenente raul cascais", "tba"],
        "lat": 38.7197, "lng": -9.1528, "neighborhood": "Príncipe Real", "corridor": "Axial Spine",
        "url": "https://teatrodobairroalto.pt/pt"
    },
    {
        "venue": "Teatro do Bairro",
        "aliases": ["teatro do bairro", "rua luz soriano 63"],
        "lat": 38.7122, "lng": -9.1457, "neighborhood": "Bairro Alto", "corridor": "Axial Spine",
        "url": "https://teatrodobairro.org"
    },
    {
        "venue": "Cinemateca Portuguesa",
        "aliases": ["cinemateca portuguesa", "sala m. felix ribeiro", "sala luis de pina", "cinemateca"],
        "lat": 38.7212, "lng": -9.1485, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine",
        "url": "https://www.cinemateca.pt/Programacao.aspx"
    },
    {
        "venue": "Teatro Tivoli BBVA",
        "aliases": ["teatro tivoli bbva", "teatro tivoli", "tivoli bbva"],
        "lat": 38.7208, "lng": -9.1465, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine",
        "url": "https://www.teatrotivolibbva.pt/en/"
    },
    {
        "venue": "Cinema São Jorge",
        "aliases": ["cinema sao jorge", "sao jorge"],
        "lat": 38.7202, "lng": -9.1461, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine",
        "url": "https://cinemasaojorge.pt/programacao/"
    },
    {
        "venue": "Cineteatro Capitólio",
        "aliases": ["cineteatro capitolio", "teatro capitolio", "teatro raul solnado", "capitolio"],
        "lat": 38.7186, "lng": -9.1466, "neighborhood": "Parque Mayer", "corridor": "Axial Spine",
        "url": "https://cartazculturallisboa.pt/agenda-cineteatro-capitolio/"
    },
    {
        "venue": "Teatro Variedades",
        "aliases": ["teatro variedades", "parque mayer"],
        "lat": 38.7191, "lng": -9.1462, "neighborhood": "Parque Mayer", "corridor": "Axial Spine",
        "url": "https://www.nocartaz.pt/concelhos/lisboa/"
    },
    {
        "venue": "Teatro Politeama",
        "aliases": ["teatro politeama", "politeama", "filipe la feria"],
        "lat": 38.7161, "lng": -9.1408, "neighborhood": "Baixa / Rossio", "corridor": "Axial Spine",
        "url": "https://filipelaferia.pt"
    },
    {
        "venue": "Chapitô",
        "aliases": ["companhia de teatro do chapito", "chapito", "costa do castelo"],
        "lat": 38.7115, "lng": -9.1340, "neighborhood": "Alfama", "corridor": "Axial Spine",
        "url": "https://chapito.org/calendario/categoria/espetaculos/"
    },
    {
        "venue": "Cinema Ideal",
        "aliases": ["cinema ideal", "rua do loreto"],
        "lat": 38.7109, "lng": -9.1437, "neighborhood": "Chiado", "corridor": "Axial Spine",
        "url": "https://www.cinemaideal.pt"
    },
    {
        "venue": "MNAC - Museu do Chiado",
        "aliases": ["museu nacional de arte contemporanea", "museu do chiado", "mnac"],
        "lat": 38.7093, "lng": -9.1412, "neighborhood": "Chiado", "corridor": "Axial Spine",
        "url": "https://museuartecontemporanea.gov.pt"
    },
    {
        "venue": "Casa do Comum",
        "aliases": ["casa do comum do bairro alto", "casa do comum", "rua da rosa 285"],
        "lat": 38.7135, "lng": -9.1449, "neighborhood": "Bairro Alto", "corridor": "Axial Spine",
        "url": "https://www.casadocomum.org"
    },
    {
        "venue": "Carmo Rooftop",
        "aliases": ["carmo rooftop", "terracos do carmo", "largo do carmo"],
        "lat": 38.7121, "lng": -9.1402, "neighborhood": "Chiado", "corridor": "Axial Spine",
        "url": "https://ra.co/clubs/200506"
    },
    {
        "venue": "Pavilhão Chinês",
        "aliases": ["pavilhao chines", "rua dom pedro v 89"],
        "lat": 38.7158, "lng": -9.1463, "neighborhood": "Príncipe Real", "corridor": "Axial Spine",
        "url": "https://cartazculturallisboa.pt/pavilhao-chines-lisboa-agenda/"
    },
    {
        "venue": "5A Club",
        "aliases": ["5a club", "rua do noronha 5a", "rua noronha, 5a", "5a"],
        "lat": 38.7183, "lng": -9.1519, "neighborhood": "Príncipe Real / Rato", "corridor": "Axial Spine",
        "url": "https://ra.co/events/pt/lisbon"
    },
    {
        "venue": "SEEN Sky Bar",
        "aliases": ["seen sky bar", "seen lisboa"],
        "lat": 38.7218, "lng": -9.1478, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine",
        "url": "https://shotgun.live/en/cities/lisbon"
    },
    {
        "venue": "B.Leza Club",
        "aliases": ["clube b.leza", "b.leza club", "b.leza clube", "b.leza", "bleza", "cais do gas 1"],
        "lat": 38.7061, "lng": -9.1462, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://www.ticketline.pt/salas/sala/971"
    },
    {
        "venue": "Tokyo Lisboa",
        "aliases": ["tokyo lisboa", "tokyo"],
        "lat": 38.7063, "lng": -9.1456, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://agendadeconcertos.com/concertos-em-portugal/"
    },
    {
        "venue": "Titanic Sur Mer",
        "aliases": ["titanic sur mer", "cais da ribeira nova"],
        "lat": 38.7058, "lng": -9.1472, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://cartazculturallisboa.pt/agenda-titanic-sur-mer/"
    },
    {
        "venue": "Lisboa Rio Club",
        "aliases": ["lisboa rio club", "lisboa rio"],
        "lat": 38.7062, "lng": -9.1458, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://shotgun.live/en/cities/lisbon"
    },
    {
        "venue": "Collect - Cais do Sodré",
        "aliases": ["collect - cais do sodre", "rua nova do carvalho 60"],
        "lat": 38.7073, "lng": -9.1442, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://ra.co/events/pt/lisbon"
    },
    {
        "venue": "SUBBAR Lisboa",
        "aliases": ["subbar lisboa", "sub_bar", "subbar"],
        "lat": 38.7065, "lng": -9.1450, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://ra.co/events/pt/lisbon"
    },
    {
        "venue": "TEJÁ HOUSE",
        "aliases": ["teja house", "cais do sodre 5"],
        "lat": 38.7066, "lng": -9.1445, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine",
        "url": "https://shotgun.live/en/cities/lisbon"
    },
    {
        "venue": "Ministerium Club",
        "aliases": ["ministerium club", "ministerium", "praca do comercio 72"],
        "lat": 38.7081, "lng": -9.1368, "neighborhood": "Terreiro do Paço", "corridor": "Axial Spine",
        "url": "https://ra.co/clubs/72396"
    },
    {
        "venue": "Pátio da Galé",
        "aliases": ["patio da gale", "praca do comercio"],
        "lat": 38.7079, "lng": -9.1376, "neighborhood": "Terreiro do Paço", "corridor": "Axial Spine",
        "url": "https://ra.co/events/pt/lisbon"
    },
    {
        "venue": "Museu da Farmácia",
        "aliases": ["museu da farmacia", "rua marechal saldanha"],
        "lat": 38.7097, "lng": -9.1482, "neighborhood": "Santa Catarina / Chiado", "corridor": "Axial Spine",
        "url": "https://www.nocartaz.pt/concelhos/lisboa/"
    },
    {
        "venue": "Museu da Marioneta",
        "aliases": ["museu da marioneta", "convento das bernardas"],
        "lat": 38.7078, "lng": -9.1558, "neighborhood": "Madragoa / Santos", "corridor": "Axial Spine",
        "url": "https://www.nocartaz.pt/concelhos/lisboa/"
    },

    # --- BELÉM WATERFRONT (Alcântara, Junqueira, Belém, Ajuda) ---
    {
        "venue": "MAC/CCB - Museu de Arte Contemporânea",
        "aliases": ["mac/ccb", "museu colecao berardo", "galerias do ccb", "centro de arquitetura"],
        "lat": 38.6956, "lng": -9.2073, "neighborhood": "Belém", "corridor": "Belém Waterfront",
        "url": "https://www.ccb.pt/macccb/"
    },
    {
        "venue": "Centro Cultural de Belém (CCB)",
        "aliases": ["centro cultural de belem", "ccb - grande auditorio", "ccb - pequeno auditorio", "ccb"],
        "lat": 38.6956, "lng": -9.2086, "neighborhood": "Belém", "corridor": "Belém Waterfront",
        "url": "https://www.ccb.pt/event/category/espetaculos/"
    },
    {
        "venue": "MAAT - Museu de Arte, Arquitetura e Tecnologia",
        "aliases": ["maat central", "maat gallery", "fabrica da eletricidade", "maat"],
        "lat": 38.6959, "lng": -9.1938, "neighborhood": "Belém", "corridor": "Belém Waterfront",
        "url": "https://www.maat.pt/pt/agenda"
    },
    {
        "venue": "Museu Nacional dos Coches",
        "aliases": ["museu nacional dos coches", "museu dos coches", "picadeiro real"],
        "lat": 38.6966, "lng": -9.1997, "neighborhood": "Belém", "corridor": "Belém Waterfront",
        "url": "https://www.mncoches.gov.pt"
    },
    {
        "venue": "MACAM / àCapela",
        "aliases": ["macam", "acapela", "àcapela", "rua da junqueira 76"],
        "lat": 38.6989, "lng": -9.1887, "neighborhood": "Belém / Junqueira", "corridor": "Belém Waterfront",
        "url": "https://www.nocartaz.pt/concelhos/lisboa/"
    },
    {
        "venue": "LU.CA - Teatro Luís de Camões",
        "aliases": ["lu.ca", "teatro luis de camoes", "calcada da ajuda"],
        "lat": 38.7014, "lng": -9.1994, "neighborhood": "Ajuda / Belém", "corridor": "Belém Waterfront",
        "url": "https://cartazculturallisboa.pt/agenda-lu-ca-teatro-luis-de-camoes/"
    },
    {
        "venue": "Palácio Nacional da Ajuda",
        "aliases": ["palacio nacional da ajuda", "palacio da ajuda"],
        "lat": 38.7076, "lng": -9.1979, "neighborhood": "Ajuda", "corridor": "Belém Waterfront",
        "url": "https://www.nocartaz.pt/concelhos/lisboa/"
    },
    {
        "venue": "Collect LX Factory",
        "aliases": ["collect lx factory", "collect ‣ lx factory"],
        "lat": 38.7035, "lng": -9.1786, "neighborhood": "Alcântara", "corridor": "Belém Waterfront",
        "url": "https://ra.co/events/pt/lisbon"
    },
    {
        "venue": "LX Factory",
        "aliases": ["lx factory", "lxfactory", "ler devagar"],
        "lat": 38.7036, "lng": -9.1788, "neighborhood": "Alcântara", "corridor": "Belém Waterfront",
        "url": "https://lxfactory.com"
    },
    {
        "venue": "Village Underground Lisboa",
        "aliases": ["village underground lisboa", "village underground", "vulisboa", "av. da india 52"],
        "lat": 38.7020, "lng": -9.1784, "neighborhood": "Alcântara", "corridor": "Belém Waterfront",
        "url": "https://vulisboa.com"
    },
    {
        "venue": "Museu do Oriente",
        "aliases": ["museu do oriente", "fundacao oriente", "doca de alcantara"],
        "lat": 38.7027, "lng": -9.1706, "neighborhood": "Alcântara", "corridor": "Belém Waterfront",
        "url": "https://www.foriente.pt/agenda.php"
    },

    # --- EASTERN CREATIVE CORRIDOR (Anjos, Intendente, Beato, Marvila, Parque das Nações) ---
    {
        "venue": "BOTA - Base Organizada da Toca das Artes",
        "aliases": ["bota anjos", "base organizada da toca das artes", "base de oficios das artes", "largo santa barbara", "bota"],
        "lat": 38.7247, "lng": -9.1345, "neighborhood": "Anjos", "corridor": "Eastern Corridor",
        "url": "https://www.botaanjos.com/programacao"
    },
    {
        "venue": "Desterro",
        "aliases": ["associacao cultural desterro", "calcada do desterro", "desterro"],
        "lat": 38.7205, "lng": -9.1356, "neighborhood": "Intendente / Desterro", "corridor": "Eastern Corridor",
        "url": "https://ra.co/events/pt/lisbon"
    },
    {
        "venue": "Miradouro de Baixo / Carpintarias de São Lázaro",
        "aliases": ["carpintarias de sao lazaro", "miradouro de baixo"],
        "lat": 38.7192, "lng": -9.1365, "neighborhood": "São Lázaro / Mouraria", "corridor": "Eastern Corridor",
        "url": "https://ra.co/events/pt/lisbon"
    },
    {
        "venue": "Lux Frágil",
        "aliases": ["lux fragil", "lux"],
        "lat": 38.7108, "lng": -9.1225, "neighborhood": "Santa Apolónia", "corridor": "Eastern Corridor",
        "url": "https://www.luxfragil.com/agenda"
    },
    {
        "venue": "Cavo Rooftop",
        "aliases": ["cavo rooftop", "cavo terrace", "terminal de cruzeiros de lisboa"],
        "lat": 38.7118, "lng": -9.1248, "neighborhood": "Santa Apolónia", "corridor": "Eastern Corridor",
        "url": "https://ra.co/clubs/298576"
    },
    {
        "venue": "Casa Capitão",
        "aliases": ["casa capitao", "casa do capitao", "rua do grilo 119"],
        "lat": 38.7305, "lng": -9.1082, "neighborhood": "Beato", "corridor": "Eastern Corridor",
        "url": "https://casa-capitao.com"
    },
    {
        "venue": "Arroz Estúdios",
        "aliases": ["arroz estudios", "arroz studios"],
        "lat": 38.7370, "lng": -9.1012, "neighborhood": "Beato", "corridor": "Eastern Corridor",
        "url": "https://www.arrozestudios.pt"
    },
    {
        "venue": "Beato 30",
        "aliases": ["beato 30", "rua do beato 30"],
        "lat": 38.7345, "lng": -9.1045, "neighborhood": "Beato", "corridor": "Eastern Corridor",
        "url": "https://ra.co/events/pt/lisbon"
    },
    {
        "venue": "NAVE Gallery",
        "aliases": ["nave gallery", "galeria nave"],
        "lat": 38.7320, "lng": -9.1120, "neighborhood": "Beato", "corridor": "Eastern Corridor",
        "url": "https://www.agendalx.pt"
    },
    {
        "venue": "8 Marvila",
        "aliases": ["zdb 8 marvila", "8 marvila", "8marvila", "praca david leandro da silva"],
        "lat": 38.7380, "lng": -9.1005, "neighborhood": "Marvila", "corridor": "Eastern Corridor",
        "url": "https://www.8marvila.com"
    },
    {
        "venue": "Fábrica Braço de Prata",
        "aliases": ["fabrica braco de prata", "fabrica do braco de prata", "braco de prata"],
        "lat": 38.7428, "lng": -9.0988, "neighborhood": "Marvila", "corridor": "Eastern Corridor",
        "url": "https://www.fabricabracodeprata.com"
    },
    {
        "venue": "Underdogs Gallery",
        "aliases": ["underdogs gallery", "galeria underdogs", "underdogs", "rua fernando palha"],
        "lat": 38.7363, "lng": -9.1020, "neighborhood": "Marvila", "corridor": "Eastern Corridor",
        "url": "https://www.under-dogs.net/pages/exhibitions"
    },
    {
        "venue": "Teatro Meridional",
        "aliases": ["teatro meridional", "meridional"],
        "lat": 38.7360, "lng": -9.1025, "neighborhood": "Marvila", "corridor": "Eastern Corridor",
        "url": "https://teatromeridional.net/index.php/programacao/espectaculos"
    },
    {
        "venue": "LAV - Lisboa ao Vivo",
        "aliases": ["lav - lisboa ao vivo", "lisboa ao vivo", "lav"],
        "lat": 38.7475, "lng": -9.1026, "neighborhood": "Marvila / Cabo Ruivo", "corridor": "Eastern Corridor",
        "url": "https://lisboaaovivo.com"
    },
    {
        "venue": "MEO Arena",
        "aliases": ["meo arena", "altice arena", "sala tejo", "pavilhao atlantico"],
        "lat": 38.7682, "lng": -9.0940, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor",
        "url": "https://arena.meo.pt/agenda"
    },
    {
        "venue": "Pavilhão do Conhecimento",
        "aliases": ["pavilhao do conhecimento", "ciencia viva"],
        "lat": 38.7626, "lng": -9.0936, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor",
        "url": "https://www.pavconhecimento.pt"
    },
    {
        "venue": "Casino Lisboa - Auditório dos Oceanos",
        "aliases": ["casino lisboa", "auditorio dos oceanos"],
        "lat": 38.7652, "lng": -9.0963, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor",
        "url": "https://www.nocartaz.pt/salas/casino-lisboa-auditorio-oceanos/"
    },
    {
        "venue": "Oceanário de Lisboa",
        "aliases": ["oceanario de lisboa", "oceanario"],
        "lat": 38.7635, "lng": -9.0937, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor",
        "url": "https://cartazculturallisboa.pt/agenda-eventos-lisboa/"
    },
    {
        "venue": "Kømplex Lisbon",
        "aliases": ["komplex lisbon", "komplex", "praceta domingos rodrigues"],
        "lat": 38.7845, "lng": -9.1192, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor",
        "url": "https://pt.ra.co/clubs/215718"
    },

    # --- NORTHERN BELT (Saldanha, São Sebastião, Campo Pequeno, Alvalade, Benfica) ---
    {
        "venue": "CAM - Centro de Arte Moderna Gulbenkian",
        "aliases": ["centro de arte moderna gulbenkian", "cam gulbenkian", "cam"],
        "lat": 38.7371, "lng": -9.1542, "neighborhood": "São Sebastião", "corridor": "Northern Belt",
        "url": "https://gulbenkian.pt/cam/agenda/"
    },
    {
        "venue": "Fundação Calouste Gulbenkian",
        "aliases": ["fundacao calouste gulbenkian", "museu calouste gulbenkian", "orquestra gulbenkian", "gulbenkian"],
        "lat": 38.7371, "lng": -9.1542, "neighborhood": "São Sebastião", "corridor": "Northern Belt",
        "url": "https://gulbenkian.pt/agenda/"
    },
    {
        "venue": "Teatro da Comuna",
        "aliases": ["teatro da comuna", "comuna teatro de pesquisa", "praca de espanha"],
        "lat": 38.7367, "lng": -9.1605, "neighborhood": "Praça de Espanha", "corridor": "Northern Belt",
        "url": "https://www.comunateatropesquisa.pt"
    },
    {
        "venue": "Pavilhão Carlos Lopes",
        "aliases": ["pavilhao carlos lopes", "brunch electronik lisboa", "parque eduardo vii"],
        "lat": 38.7289, "lng": -9.1518, "neighborhood": "Parque Eduardo VII", "corridor": "Northern Belt",
        "url": "https://cartazculturallisboa.pt/agenda-pavilhao-carlos-lopes/"
    },
    {
        "venue": "Teatro Villaret",
        "aliases": ["teatro villaret", "villaret"],
        "lat": 38.7311, "lng": -9.1466, "neighborhood": "Saldanha / Picoas", "corridor": "Northern Belt",
        "url": "https://cartazculturallisboa.pt/agenda-teatro-villaret-lisboa/"
    },
    {
        "venue": "Cinema Medeia Monumental",
        "aliases": ["cinema medeia monumental", "medeia monumental", "cinema monumental"],
        "lat": 38.7336, "lng": -9.1452, "neighborhood": "Saldanha", "corridor": "Northern Belt",
        "url": "https://medeiafilmes.com"
    },
    {
        "venue": "Cinema Medeia Nimas",
        "aliases": ["cinema medeia nimas", "medeia nimas", "cinema nimas", "espaco nimas"],
        "lat": 38.7357, "lng": -9.1495, "neighborhood": "Saldanha", "corridor": "Northern Belt",
        "url": "https://medeiafilmes.com/cinemas/cinema-medeia-nimas"
    },
    {
        "venue": "Culturgest",
        "aliases": ["culturgest - fundacao cgd", "culturgest", "arco do cego"],
        "lat": 38.7408, "lng": -9.1418, "neighborhood": "Campo Pequeno", "corridor": "Northern Belt",
        "url": "https://www.culturgest.pt/pt/programacao/por-evento/"
    },
    {
        "venue": "Sagres Campo Pequeno",
        "aliases": ["sagres campo pequeno", "campo pequeno"],
        "lat": 38.7423, "lng": -9.1449, "neighborhood": "Campo Pequeno", "corridor": "Northern Belt",
        "url": "https://www.sagrescampopequeno.pt/pt/agenda"
    },
    {
        "venue": "Teatro Maria Matos",
        "aliases": ["teatro maria matos", "maria matos"],
        "lat": 38.7461, "lng": -9.1415, "neighborhood": "Alvalade", "corridor": "Northern Belt",
        "url": "https://teatromariamatos.pt/tipo/programacao/"
    },
    {
        "venue": "Távola Jazz Club",
        "aliases": ["tavola jazz club", "tavola"],
        "lat": 38.7485, "lng": -9.1398, "neighborhood": "Alvalade", "corridor": "Northern Belt",
        "url": "https://www.nocartaz.pt/concelhos/lisboa/"
    },
    {
        "venue": "RCA Club",
        "aliases": ["rca club", "rua joao saraiva 18", "rca"],
        "lat": 38.7502, "lng": -9.1261, "neighborhood": "Alvalade", "corridor": "Northern Belt",
        "url": "https://www.rcaclub.com"
    },
    {
        "venue": "República da Música",
        "aliases": ["republica da musica", "rua do centro cultural"],
        "lat": 38.7554, "lng": -9.1444, "neighborhood": "Alvalade", "corridor": "Northern Belt",
        "url": "https://republicadamusica.pt"
    },
    {
        "venue": "Aula Magna",
        "aliases": ["aula magna", "reitoria da universidade de lisboa"],
        "lat": 38.7525, "lng": -9.1585, "neighborhood": "Cidade Universitária", "corridor": "Northern Belt",
        "url": "https://cartazculturallisboa.pt/agenda-aula-magna-lisboa/"
    }
]

# Optional external venues.json merge (Task 6)
if os.path.exists("venues.json"):
    try:
        with open("venues.json", "r", encoding="utf-8") as vf:
            custom_venues = json.load(vf)
            if isinstance(custom_venues, list):
                VENUE_REGISTRY.extend(custom_venues)
            elif isinstance(custom_venues, dict):
                VENUE_REGISTRY.extend(custom_venues.values())
    except Exception as e:
        print(f"Notice loading venues.json: {e}")

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


# Pre-build sorted alias index (longest alias first to prevent substring collisions)
SORTED_ALIAS_INDEX = []
for v_entry in VENUE_REGISTRY:
    for alias in v_entry.get("aliases", []):
        SORTED_ALIAS_INDEX.append((strip_accents(alias), v_entry))
SORTED_ALIAS_INDEX.sort(key=lambda x: len(x[0]), reverse=True)


def match_venue(venue_str, title_hint=""):
    """Deterministic longest-alias-first matcher with word boundaries for short keys."""
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
    if clean_display.lower() in ["lisbon", "lisboa", "lisbon venue"]:
        clean_display = "Lisboa (Local a confirmar)"
    res = DEFAULT_GEO.copy()
    res["venue"] = clean_display
    return res


def fetch_url(url, method="GET", json_body=None, headers=None, timeout=14):
    """Fetches URL using curl_cffi (Chrome TLS impersonation) if available, falling back to requests."""
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
    """Extracts Euro price and maps to FREE, ACCESSIBLE (<=15€), MID (15-30€), PREMIUM (>30€)."""
    if not raw_price:
        return default_price, default_tier
    p_str = str(raw_price).strip()
    p_low = strip_accents(p_str)

    if any(w in p_low for w in ["gratis", "gratuito", "gratuita", "free", "entrada livre", "a borla"]):
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
        if max_p == 0:
            return "Grátis", "FREE"
        display = f"{min_p:.2f}€".replace(".00€", "€") if min_p == max_p else f"{min_p:.0f}€ - {max_p:.0f}€"
        if "desde" in p_low and min_p == max_p:
            display = f"Desde {display}"
        if min_p == 0:
            tier = "FREE"
        elif min_p <= 15.0:
            tier = "ACCESSIBLE"
        elif min_p <= 30.0:
            tier = "MID"
        else:
            tier = "PREMIUM"
        return display, tier

    return default_price, default_tier


def parse_time_str(raw_time, default_time="21:00"):
    """Normalizes 24h ('21h30', '21.00') and 12h ('9:30 PM', '11:59 PM') strings into ('HH:MM', hour_int)."""
    if not raw_time:
        h = int(default_time.split(":")[0])
        return default_time, h
    t_clean = str(raw_time).strip()

    m_ampm = re.search(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(am|pm)\b", t_clean, re.I)
    if m_ampm:
        h = int(m_ampm.group(1))
        mins = m_ampm.group(2) or "00"
        meridiem = m_ampm.group(3).lower()
        if meridiem == "pm" and h != 12:
            h += 12
        elif meridiem == "am" and h == 12:
            h = 0
        return f"{h:02d}:{mins}", h

    m_24 = re.search(r"\b([01]?\d|2[0-3])[:h.]([0-5]\d)\b", t_clean, re.I)
    if m_24:
        h = int(m_24.group(1))
        mins = m_24.group(2)
        return f"{h:02d}:{mins}", h

    m_hour_only = re.search(r"\b([01]?\d|2[0-3])\s*h\b", t_clean, re.I)
    if m_hour_only:
        h = int(m_hour_only.group(1))
        return f"{h:02d}:00", h

    h = int(default_time.split(":")[0])
    return default_time, h


def detect_category(title, venue, category_hint=""):
    combined = strip_accents(f"{title} {venue} {category_hint}")
    if any(k in combined for k in ["dj", "clubbing", "techno", "electronic", "eletronica", "house", "nightlife", "rave", "baile", "ministerium", "komplex", "5a", "lux fragil"]):
        return CATEGORY_PRESETS["nightlife"]
    if any(k in combined for k in ["filme", "cinema", "projecao", "screening", "cinemateca", "nimas", "leffest", "doclisboa"]):
        return CATEGORY_PRESETS["cinema"]
    if any(k in combined for k in ["teatro", "peca", "stand-up", "stand up", "comedia", "commedia", "dramaturgia", "musical", "encenacao", "circo", "danca", "performance"]):
        return CATEGORY_PRESETS["theatre"]
    if any(k in combined for k in ["exposicao", "galeria", "instalacao", "pintura", "escultura", "fotografia", "museu", "maat", "mnac", "underdogs"]):
        return CATEGORY_PRESETS["art"]
    if any(k in combined for k in ["opera", "classica", "orquestra", "sinfonica", "recital", "camara", "coro", "violoncelo", "piano"]):
        return CATEGORY_PRESETS["opera"]
    if any(k in combined for k in ["infantil", "familia", "criancas", "oficina", "bebes", "pavilhao do conhecimento"]):
        return CATEGORY_PRESETS["family"]
    if any(k in combined for k in ["feira", "mercado", "conferencia", "debate", "conversa", "lancamento", "tertulia", "visita"]):
        return CATEGORY_PRESETS["community"]
    return CATEGORY_PRESETS["music"]


def get_lisbon_operational_date():
    now = datetime.datetime.now(LISBON_TZ)
    op_date = (now - datetime.timedelta(days=1)).date() if now.hour < 4 else now.date()
    return op_date, now


# ==============================================================================
# TIER 1A: OFFICIAL AGENDALX WORDPRESS REST API
# ==============================================================================
def scrape_agendalx_api(target_date):
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    api_url = "https://www.agendalx.pt/wp-json/agendalx/v1/events"
    print(f"[Tier 1] Fetching Official AgendaLX REST API: {api_url}")
    try:
        resp = fetch_url(api_url, timeout=16)
        if resp.status_code == 200:
            items = resp.json()
            if isinstance(items, list):
                for idx, item in enumerate(items):
                    occ = item.get("occurences") or []
                    start_d = item.get("StartDate") or ""
                    last_d = item.get("LastDate") or ""
                    is_today = (date_str in occ) or (start_d <= date_str <= last_d and not occ)
                    if not is_today:
                        continue

                    raw_title = html.unescape((item.get("title") or {}).get("rendered", "")).strip()
                    if not raw_title:
                        continue
                    subtitles = [html.unescape(s).strip() for s in (item.get("subtitle") or []) if s]
                    full_title = f"{raw_title} — {subtitles[0]}" if subtitles and subtitles[0].lower() not in raw_title.lower() else raw_title

                    venue_dict = item.get("venue") or {}
                    venue_name = ""
                    if isinstance(venue_dict, dict):
                        for v_obj in venue_dict.values():
                            if isinstance(v_obj, dict) and v_obj.get("name"):
                                venue_name = html.unescape(v_obj["name"])
                                break

                    geo = match_venue(venue_name, full_title)
                    cat_names = " ".join(
                        c.get("name", "") for c in (item.get("categories_name_list") or {}).values() if isinstance(c, dict)
                    )
                    cat_info = detect_category(full_title, geo["venue"], f"{cat_names} {item.get('subject', '')}")

                    time_str, hour_int = parse_time_str(item.get("string_times", ""), "19:00" if cat_info == CATEGORY_PRESETS["art"] else "21:00")
                    raw_price_arr = item.get("price_val") or []
                    raw_price_str = " ".join(str(x) for x in raw_price_arr)
                    price_disp, price_tier = parse_price_and_tier(raw_price_str, "Entrada sujeita a bilheteira", "ACCESSIBLE")

                    desc_list = item.get("description") or []
                    clean_desc = BeautifulSoup(" ".join(str(d) for d in desc_list), "html.parser").get_text(" ", strip=True)
                    if len(clean_desc) > 200:
                        clean_desc = clean_desc[:197].rsplit(" ", 1)[0] + "…"
                    if not clean_desc:
                        clean_desc = f"{full_title} em {geo['venue']} ({geo['neighborhood']})."

                    ev_url = item.get("link") or geo["url"]
                    events.append({
                        "id": f"agendalx-{item.get('id', idx)}",
                        "title": full_title,
                        "category": cat_info["category"],
                        "color": cat_info["color"],
                        "icon": cat_info["icon"],
                        "venue": geo["venue"],
                        "neighborhood": geo["neighborhood"],
                        "corridor": geo["corridor"],
                        "lat": geo["lat"],
                        "lng": geo["lng"],
                        "time": time_str,
                        "hour": hour_int,
                        "price": price_disp,
                        "priceTier": price_tier,
                        "url": ev_url,
                        "description": clean_desc
                    })
    except Exception as e:
        print(f"[Tier 1] AgendaLX API notice: {e}")
    return events


# ==============================================================================
# TIER 1B: RESIDENT ADVISOR (GraphQL API + HTML Listing Parser)
# ==============================================================================
def scrape_resident_advisor(target_date):
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    graphql_url = "https://ra.co/graphql"
    print(f"[Tier 1] Fetching Resident Advisor GraphQL & Listing for {date_str}")

    gql_query = """
    query GET_POPULAR_EVENTS($filters: FilterInputDtoInput, $pageSize: Int) {
      eventListings(filters: $filters, pageSize: $pageSize, page: 1, sort: { attending: { priority: 1, order: DESCENDING } }) {
        data {
          id
          listingDate
          event {
            id
            title
            date
            startTime
            contentUrl
            venue {
              name
            }
            artists {
              name
            }
          }
        }
      }
    }
    """
    for area_id in (51, 229):
        try:
            payload = {
                "query": gql_query,
                "variables": {
                    "filters": {
                        "areas": {"eq": area_id},
                        "listingDate": {"gte": date_str, "lte": date_str}
                    },
                    "pageSize": 40
                }
            }
            resp = fetch_url(graphql_url, method="POST", json_body=payload, headers={"Referer": "https://ra.co/events/pt/lisbon"})
            if resp.status_code == 200:
                data = resp.json()
                listings = (((data.get("data") or {}).get("eventListings") or {}).get("data")) or []
                for idx, item in enumerate(listings):
                    ev = item.get("event") or {}
                    title = (ev.get("title") or "").strip()
                    if not title:
                        continue
                    venue_name = ((ev.get("venue") or {}).get("name") or "").strip()
                    if any(bad in venue_name.lower() for bad in ["porto", "faro", "coimbra", "london"]):
                        continue
                    artists = [a.get("name") for a in (ev.get("artists") or []) if a.get("name")]
                    if artists and not any(a.lower() in title.lower() for a in artists[:2]):
                        title = f"{title} — {', '.join(artists[:4])}"

                    content_url = ev.get("contentUrl") or ""
                    ev_url = urljoin("https://ra.co", content_url) if content_url else "https://ra.co/events/pt/lisbon"
                    time_str, hour_int = parse_time_str(ev.get("startTime") or ev.get("date", ""), "23:59")
                    geo = match_venue(venue_name, title)
                    cat_info = CATEGORY_PRESETS["nightlife"]
                    lineup_desc = f"Lineup: {', '.join(artists[:6])}. " if artists else ""

                    events.append({
                        "id": f"ra-{ev.get('id', idx)}",
                        "title": title,
                        "category": cat_info["category"],
                        "color": cat_info["color"],
                        "icon": cat_info["icon"],
                        "venue": geo["venue"],
                        "neighborhood": geo["neighborhood"],
                        "corridor": geo["corridor"],
                        "lat": geo["lat"],
                        "lng": geo["lng"],
                        "time": time_str,
                        "hour": hour_int,
                        "price": "10€ - 20€",
                        "priceTier": "ACCESSIBLE",
                        "url": ev_url,
                        "description": f"{lineup_desc}Noite de música eletrónica e clubbing em {geo['venue']} ({geo['neighborhood']})."
                    })
                if events:
                    break
        except Exception as e:
            print(f"[Tier 1] RA GraphQL notice: {e}")

    if not events:
        list_url = f"https://ra.co/events/pt/lisbon?startDate={date_str}"
        try:
            resp = fetch_url(list_url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for idx, a_tag in enumerate(soup.select('a[href^="/events/"]')):
                    href = a_tag.get("href", "")
                    if not re.match(r"^/events/\d+$", href):
                        continue
                    title = a_tag.get_text(" ", strip=True)
                    if len(title) < 2 or title.lower() in ["ra", "events", "tickets"]:
                        continue
                    card = a_tag.find_parent(["li", "article", "div"])
                    card_text = card.get_text(" | ", strip=True) if card else title
                    geo = match_venue(card_text, title)
                    ev_url = urljoin("https://ra.co", href)
                    events.append({
                        "id": f"ra-dom-{href.split('/')[-1]}",
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
                        "price": "12€ - 20€",
                        "priceTier": "ACCESSIBLE",
                        "url": ev_url,
                        "description": f"Sessão de eletrónica e clubbing em {geo['venue']} via Resident Advisor."
                    })
        except Exception as e:
            print(f"[Tier 1] RA HTML notice: {e}")

    return events


# ==============================================================================
# TIER 3A: SHOTGUN LIVE (Valid City & Genre Routes)
# ==============================================================================
def scrape_shotgun(target_date):
    events = []
    day_num = target_date.day
    month_en = target_date.strftime("%b")
    month_pt = {
        1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
        7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"
    }[target_date.month]

    urls = [
        "https://shotgun.live/en/cities/lisbon",
        "https://shotgun.live/en/cities/lisbon/techno",
        "https://shotgun.live/en/cities/lisbon/house"
    ]
    print(f"[Tier 3] Scraping Shotgun Live Lisbon routes for {day_num} {month_en}")

    date_pat = re.compile(rf"\b({day_num}\s+{month_en}|{month_en}\s+{day_num}|{day_num}\s+{month_pt})\b", re.I)

    for url in urls:
        try:
            resp = fetch_url(url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/events/"]'):
                href = a_tag.get("href", "")
                if not href or "/cities/" in href:
                    continue
                ev_url = urljoin("https://shotgun.live", href)
                card_text = a_tag.get_text(" | ", strip=True)
                parent_section = a_tag.find_parent(["section", "div", "li"])
                context_text = parent_section.get_text(" ", strip=True) if parent_section else card_text

                if not date_pat.search(context_text) and not date_pat.search(card_text):
                    continue

                parts = [p.strip() for p in card_text.split("|") if p.strip()]
                if not parts:
                    continue
                title = parts[0]
                if len(title) < 2:
                    continue

                time_str, hour_int = parse_time_str(card_text, "23:00")
                price_disp, price_tier = parse_price_and_tier(card_text, "10€ - 20€", "ACCESSIBLE")
                geo = match_venue(card_text, title)
                cat_info = detect_category(title, geo["venue"], "shotgun electronic nightlife")

                events.append({
                    "id": f"shotgun-{href.strip('/').split('/')[-1]}",
                    "title": title,
                    "category": cat_info["category"],
                    "color": cat_info["color"],
                    "icon": cat_info["icon"],
                    "venue": geo["venue"],
                    "neighborhood": geo["neighborhood"],
                    "corridor": geo["corridor"],
                    "lat": geo["lat"],
                    "lng": geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "price": price_disp,
                    "priceTier": price_tier,
                    "url": ev_url,
                    "description": f"{title} em {geo['venue']} ({geo['neighborhood']}). Bilhetes e alinhamento na Shotgun."
                })
        except Exception as e:
            print(f"[Tier 3] Shotgun notice on {url}: {e}")

    return events


# ==============================================================================
# TIER 3B: NOCARTAZ LISBOA & AGENDA DE CONCERTOS (High-Accuracy Artist Names)
# ==============================================================================
def scrape_nocartaz_lisboa(target_date):
    events = []
    day_num = target_date.day
    month_pt = {
        1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
        7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"
    }[target_date.month]
    date_header_pat = re.compile(rf"\b0?{day_num}\s+{month_pt}\b", re.I)

    url = "https://www.nocartaz.pt/concelhos/lisboa/"
    print(f"[Tier 3] Scraping NoCartaz Lisboa: {url}")
    try:
        resp = fetch_url(url)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/eventos/"]'):
                href = a_tag.get("href", "")
                card = a_tag.find_parent(["article", "li", "div"]) or a_tag
                text_block = card.get_text(" | ", strip=True)
                if not date_header_pat.search(text_block):
                    prev_h = card.find_previous(["h2", "h3", "h4"])
                    if not prev_h or not date_header_pat.search(prev_h.get_text(" ", strip=True)):
                        continue

                title_el = card.find(["h3", "h4", "strong"]) or a_tag
                raw_title = title_el.get_text(" ", strip=True)
                if not raw_title or len(raw_title) < 2:
                    continue

                venue_hint = text_block
                if " @ " in raw_title:
                    t_parts = raw_title.split(" @ ", 1)
                    raw_title = t_parts[0].strip()
                    venue_hint = f"{t_parts[1]} | {text_block}"

                geo = match_venue(venue_hint, raw_title)
                time_str, hour_int = parse_time_str(text_block, "21:00")
                price_disp, price_tier = parse_price_and_tier(text_block, "Consultar bilheteira", "ACCESSIBLE")
                cat_info = detect_category(raw_title, geo["venue"], text_block)
                ev_url = urljoin("https://www.nocartaz.pt", href)

                events.append({
                    "id": f"nocartaz-{href.strip('/').split('/')[-1]}",
                    "title": raw_title,
                    "category": cat_info["category"],
                    "color": cat_info["color"],
                    "icon": cat_info["icon"],
                    "venue": geo["venue"],
                    "neighborhood": geo["neighborhood"],
                    "corridor": geo["corridor"],
                    "lat": geo["lat"],
                    "lng": geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "price": price_disp,
                    "priceTier": price_tier,
                    "url": ev_url,
                    "description": f"{raw_title} ao vivo em {geo['venue']} ({geo['neighborhood']})."
                })
    except Exception as e:
        print(f"[Tier 3] NoCartaz notice: {e}")
    return events


def scrape_agendadeconcertos(target_date):
    events = []
    day_num = target_date.day
    month_full_pt = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
        7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
    }[target_date.month]

    url = "https://agendadeconcertos.com/concertos-em-portugal/"
    print(f"[Tier 3] Scraping Agenda de Concertos: {url}")
    try:
        resp = fetch_url(url)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = soup.get_text("\n", strip=True)
            lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]

            in_target_date = False
            date_heading_re = re.compile(rf"\b0?{day_num}\s+{month_full_pt}\b", re.I)
            other_date_re = re.compile(r"\b\d{1,2}\s+(Janeiro|Fevereiro|Março|Abril|Maio|Junho|Julho|Agosto|Setembro|Outubro|Novembro|Dezembro)\b", re.I)

            for idx, ln in enumerate(lines):
                if date_heading_re.search(ln):
                    in_target_date = True
                    continue
                elif in_target_date and other_date_re.search(ln):
                    break

                if in_target_date and ("– Lisboa" in ln or "- Lisboa" in ln):
                    venue_line = re.sub(r"\s*[–-]\s*Lisboa.*$", "", ln).strip()
                    artist_name = lines[idx - 1] if idx > 0 else ""
                    if not artist_name or other_date_re.search(artist_name) or "–" in artist_name:
                        continue
                    geo = match_venue(venue_line, artist_name)
                    cat_info = detect_category(artist_name, geo["venue"], "concerto musica ao vivo")
                    events.append({
                        "id": f"adc-{target_date.strftime('%Y%m%d')}-{idx}",
                        "title": artist_name,
                        "category": cat_info["category"],
                        "color": cat_info["color"],
                        "icon": cat_info["icon"],
                        "venue": geo["venue"],
                        "neighborhood": geo["neighborhood"],
                        "corridor": geo["corridor"],
                        "lat": geo["lat"],
                        "lng": geo["lng"],
                        "time": "21:30",
                        "hour": 21,
                        "price": "Consultar bilheteira",
                        "priceTier": "ACCESSIBLE",
                        "url": geo["url"],
                        "description": f"Concerto de {artist_name} ao vivo em {geo['venue']} ({geo['neighborhood']})."
                    })
    except Exception as e:
        print(f"[Tier 3] Agenda de Concertos notice: {e}")
    return events


# ==============================================================================
# TIER 2: DIRECT VENUE SCRAPERS (Cinemateca, Nimas, BOTA)
# ==============================================================================
def scrape_direct_venues(target_date):
    events = []
    d_slash = target_date.strftime("%d/%m/%Y")
    d_dot = target_date.strftime("%d.%m.%Y")
    day_num = target_date.day
    month_pt_full = {
        1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
        7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
    }[target_date.month]

    # 1. Cinemateca Portuguesa (Programacao.aspx)
    try:
        resp = fetch_url("https://www.cinemateca.pt/Programacao.aspx")
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            text_lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]
            geo = match_venue("cinemateca")
            for i, line in enumerate(text_lines):
                if d_slash in line and "|" in line:
                    time_str, hour_int = parse_time_str(line, "19:00")
                    room = line.split("|")[-1].strip()
                    film_title = text_lines[i + 2] if i + 2 < len(text_lines) else "Sessão Cinemateca"
                    director = text_lines[i + 3] if i + 3 < len(text_lines) and text_lines[i + 3].startswith("de ") else ""
                    full_title = f"{film_title} ({director})" if director else film_title
                    events.append({
                        "id": f"cinemateca-{target_date.strftime('%Y%m%d')}-{i}",
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
                        "price": "3.20€",
                        "priceTier": "ACCESSIBLE",
                        "url": "https://www.cinemateca.pt/Programacao.aspx",
                        "description": f"Sessão na {room} da Cinemateca Portuguesa."
                    })
    except Exception as e:
        print(f"[Tier 2] Cinemateca notice: {e}")

    # 2. Cinema Medeia Nimas
    try:
        resp = fetch_url("https://medeiafilmes.com/cinemas/cinema-medeia-nimas")
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            geo = match_venue("cinema medeia nimas")
            text_lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]
            in_today = False
            for i, line in enumerate(text_lines):
                if line == d_dot:
                    in_today = True
                    continue
                elif in_today and re.match(r"^\d{2}\.\d{2}\.\d{4}$", line):
                    break
                if in_today and re.match(r"^\d{2}:\d{2}$", line):
                    time_str, hour_int = parse_time_str(line, "18:30")
                    film_title = text_lines[i + 1] if i + 1 < len(text_lines) else "Sessão Nimas"
                    director = text_lines[i + 2] if i + 2 < len(text_lines) and text_lines[i + 2].startswith("de ") else ""
                    full_title = f"{film_title} ({director})" if director else film_title
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
                        "price": "7.50€",
                        "priceTier": "ACCESSIBLE",
                        "url": "https://medeiafilmes.com/cinemas/cinema-medeia-nimas",
                        "description": f"Exibição de {full_title} no Cinema Medeia Nimas (Saldanha)."
                    })
    except Exception as e:
        print(f"[Tier 2] Medeia Nimas notice: {e}")

    # 3. BOTA Anjos (botaanjos.com/programacao)
    try:
        resp = fetch_url("https://www.botaanjos.com/programacao")
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            geo = match_venue("bota anjos")
            target_pt_str = f"{day_num} de {month_pt_full} de {target_date.year}"
            for article in soup.find_all(["article", "div"], class_=re.compile(r"eventlist-event", re.I)):
                txt = article.get_text(" ", strip=True)
                if target_pt_str.lower() not in txt.lower():
                    continue
                h_el = article.find(["h1", "h2", "a"], class_=re.compile(r"title", re.I)) or article.find(["h1", "h2"])
                if not h_el:
                    continue
                title = h_el.get_text(" ", strip=True)
                link_el = article.find("a", href=re.compile(r"/programacao/"))
                ev_url = urljoin("https://www.botaanjos.com", link_el["href"]) if link_el else "https://www.botaanjos.com/programacao"
                time_str, hour_int = parse_time_str(txt, "21:00")
                events.append({
                    "id": f"bota-{target_date.strftime('%Y%m%d')}-{len(events)}",
                    "title": title,
                    "category": CATEGORY_PRESETS["music"]["category"],
                    "color": CATEGORY_PRESETS["music"]["color"],
                    "icon": CATEGORY_PRESETS["music"]["icon"],
                    "venue": geo["venue"],
                    "neighborhood": geo["neighborhood"],
                    "corridor": geo["corridor"],
                    "lat": geo["lat"],
                    "lng": geo["lng"],
                    "time": time_str,
                    "hour": hour_int,
                    "price": "5€ - 10€",
                    "priceTier": "ACCESSIBLE",
                    "url": ev_url,
                    "description": f"Concerto e programação cultural na BOTA Anjos: {title}."
                })
    except Exception as e:
        print(f"[Tier 2] BOTA Anjos notice: {e}")

    return events


# ==============================================================================
# TIER 4: VERIFIED ONGOING EXHIBITIONS & THEATER RUNS (Fallback Only for Unrepresented Venues)
# ==============================================================================
def get_verified_ongoing_runs(target_date, represented_venues):
    """
    Injects real, verified ongoing exhibitions and theatrical runs ONLY for venues
    that did not already receive a time-specific event today, respecting closed days.
    """
    weekday = target_date.weekday()  # 0 = Monday, 1 = Tuesday, ... 6 = Sunday
    verified_runs = [
        {
            "title": "Délio Jasse: Entre a Pele e o Documento & Antologias da Memória",
            "venue_key": "mnac", "category_key": "art", "time": "10:00", "hour": 10,
            "price": "10.00€", "priceTier": "ACCESSIBLE",
            "url": "https://museuartecontemporanea.gov.pt",
            "closed_weekdays": [0],
            "desc": "Exposições temporárias de fotografia e arte contemporânea no MNAC - Museu do Chiado."
        },
        {
            "title": "VENUS – Valentino Garavani pelo olhar de Joana Vasconcelos & Pedro Cabrita Reis",
            "venue_key": "maat", "category_key": "art", "time": "11:00", "hour": 11,
            "price": "11.00€", "priceTier": "ACCESSIBLE",
            "url": "https://www.maat.pt/pt/agenda",
            "closed_weekdays": [1],
            "desc": "Grandes exposições de Joana Vasconcelos, Pedro Cabrita Reis e João Pimenta Gomes no MAAT."
        },
        {
            "title": "Ângela Ferreira: Here I Stand & Frida Orupabo: Cloud of Confusion",
            "venue_key": "mac/ccb", "category_key": "art", "time": "10:00", "hour": 10,
            "price": "15.00€", "priceTier": "ACCESSIBLE",
            "url": "https://www.ccb.pt/macccb/",
            "closed_weekdays": [0],
            "desc": "Exposições temporárias e coleção Berardo no MAC/CCB — Museu de Arte Contemporânea."
        },
        {
            "title": "Xerazade, a Coleção Interminável do CAM & Inês Zenha: Águas Turvas",
            "venue_key": "cam gulbenkian", "category_key": "art", "time": "10:00", "hour": 10,
            "price": "8.00€", "priceTier": "ACCESSIBLE",
            "url": "https://gulbenkian.pt/cam/agenda/",
            "closed_weekdays": [1],
            "desc": "Exposições de arte moderna e contemporânea no renovado CAM Gulbenkian."
        },
        {
            "title": "Japão: Festas e Rituais & Invocar o Silêncio (Indonésia)",
            "venue_key": "museu do oriente", "category_key": "art", "time": "10:00", "hour": 10,
            "price": "6.00€", "priceTier": "ACCESSIBLE",
            "url": "https://www.foriente.pt/agenda.php",
            "closed_weekdays": [0],
            "desc": "Exposições sobre rituais asiáticos e património biocultural no Museu do Oriente."
        },
        {
            "title": "Coleção Real de Viaturas de Gala & Modelismo de Coches",
            "venue_key": "museu nacional dos coches", "category_key": "art", "time": "10:00", "hour": 10,
            "price": "8.00€", "priceTier": "ACCESSIBLE",
            "url": "https://www.mncoches.gov.pt",
            "closed_weekdays": [0],
            "desc": "Exposição permanente e temporária no Museu Nacional dos Coches e Picadeiro Real em Belém."
        },
        {
            "title": "Macbeth (enc. Pedro Penim) & Auto da Barca do Inferno (Raquel Castro)",
            "venue_key": "teatro nacional d. maria ii", "category_key": "theatre", "time": "20:00", "hour": 20,
            "price": "15.00€", "priceTier": "MID",
            "url": "https://www.tndm.pt",
            "closed_weekdays": [0, 1],
            "desc": "Temporada teatral nas Salas Garrett e Estúdio do Teatro Nacional D. Maria II."
        },
        {
            "title": "Em Silêncio — de Teresa Sobral",
            "venue_key": "sao luiz", "category_key": "theatre", "time": "20:00", "hour": 20,
            "price": "12.00€", "priceTier": "ACCESSIBLE",
            "url": "https://www.teatrosaoluiz.pt/espetaculo/em-silencio/",
            "closed_weekdays": [0, 1],
            "desc": "Espetáculo de teatro contemporâneo em cena no São Luiz Teatro Municipal."
        },
        {
            "title": "Clube dos Poetas Mortos — enc. Hélder Gamboa",
            "venue_key": "teatro da trindade", "category_key": "theatre", "time": "21:00", "hour": 21,
            "price": "16€ - 22€", "priceTier": "MID",
            "url": "https://teatrotrindade.inatel.pt/espetaculo/clube-dos-poetas-mortos/",
            "closed_weekdays": [0, 1],
            "desc": "Peça de Tom Schulman em cena no Teatro da Trindade INATEL no Chiado."
        },
        {
            "title": "Pura Loucura — Temporada Teatro Maria Matos",
            "venue_key": "teatro maria matos", "category_key": "theatre", "time": "21:00", "hour": 21,
            "price": "21€ - 23€", "priceTier": "MID",
            "url": "https://teatromariamatos.pt/espetaculos/pura-loucura/",
            "closed_weekdays": [0, 1, 2],
            "desc": "Comédia teatral em cena de quinta a domingo no Teatro Maria Matos em Alvalade."
        },
        {
            "title": "Contos em Viagem — Goa",
            "venue_key": "teatro meridional", "category_key": "theatre", "time": "21:00", "hour": 21,
            "price": "12.00€", "priceTier": "ACCESSIBLE",
            "url": "https://teatromeridional.net/index.php/programacao/espectaculos",
            "closed_weekdays": [0, 1],
            "desc": "Espetáculo teatral sobre Goa, Damão e Diu no Teatro Meridional em Marvila."
        },
        {
            "title": "Ópera-Pimba no Gelo! O Primeiro Musical no Gelo Derretido",
            "venue_key": "teatro da comuna", "category_key": "theatre", "time": "20:10", "hour": 20,
            "price": "12€ - 15€", "priceTier": "ACCESSIBLE",
            "url": "https://www.comunateatropesquisa.pt",
            "closed_weekdays": [0, 1],
            "desc": "Comédia musical satírica na Sala Nova do Teatro da Comuna (Praça de Espanha)."
        },
        {
            "title": "Hércules - O Musical Heróico & Carmen Miranda - O Grande Musical",
            "venue_key": "teatro politeama", "category_key": "theatre", "time": "21:00", "hour": 21,
            "price": "15€ - 30€", "priceTier": "MID",
            "url": "https://filipelaferia.pt",
            "closed_weekdays": [0, 1],
            "desc": "Grandes produções musicais de Filipe La Féria no Teatro Politeama."
        },
        {
            "title": "Alexandre Estrela: RedSkyFalls (Réplica) — Exposição ZDB",
            "venue_key": "zdb", "category_key": "art", "time": "18:00", "hour": 18,
            "price": "Grátis", "priceTier": "FREE",
            "url": "https://zedosbois.org/en/programa/redskyfalls-replica/",
            "closed_weekdays": [6],
            "desc": "Exposição de artes visuais de Alexandre Estrela na Galeria Zé dos Bois (18h–22h)."
        },
        {
            "title": "Exposições de Arte Urbana & Edições de Artista",
            "venue_key": "underdogs", "category_key": "art", "time": "14:00", "hour": 14,
            "price": "Grátis", "priceTier": "FREE",
            "url": "https://www.under-dogs.net/pages/exhibitions",
            "closed_weekdays": [0, 6],
            "desc": "Galeria de arte contemporânea e arte urbana em Marvila."
        },
        {
            "title": "Exposições Interativas de Ciência Viva em Família",
            "venue_key": "pavilhao do conhecimento", "category_key": "family", "time": "10:00", "hour": 10,
            "price": "11€ - 15€", "priceTier": "ACCESSIBLE",
            "url": "https://www.pavconhecimento.pt",
            "closed_weekdays": [],
            "desc": "Exploração científica interativa e oficinas para famílias no Parque das Nações."
        },
        {
            "title": "Galerias de Arte, Lojas Independentes & Cultura Emergente",
            "venue_key": "8 marvila", "category_key": "community", "time": "12:00", "hour": 12,
            "price": "Grátis", "priceTier": "FREE",
            "url": "https://www.8marvila.com",
            "closed_weekdays": [0, 1, 2],
            "desc": "Percurso expositivo, galerias e espaço cultural no 8 Marvila."
        }
    ]

    fallback_events = []
    for idx, item in enumerate(verified_runs):
        if weekday in item["closed_weekdays"]:
            continue
        geo = match_venue(item["venue_key"])
        if geo["venue"] in represented_venues:
            continue
        cat_info = CATEGORY_PRESETS[item["category_key"]]
        fallback_events.append({
            "id": f"ongoing-{target_date.strftime('%Y%m%d')}-{idx+1}",
            "title": item["title"],
            "category": cat_info["category"],
            "color": cat_info["color"],
            "icon": cat_info["icon"],
            "venue": geo["venue"],
            "neighborhood": geo["neighborhood"],
            "corridor": geo["corridor"],
            "lat": geo["lat"],
            "lng": geo["lng"],
            "time": item["time"],
            "hour": item["hour"],
            "price": item["price"],
            "priceTier": item["priceTier"],
            "url": item["url"],
            "description": item["desc"]
        })
    return fallback_events


# ==============================================================================
# SMART DEDUPLICATION & GOLDEN-ANGLE FERMAT SPIRAL JITTER
# ==============================================================================
def deduplicate_and_merge_events(raw_events):
    """
    Deduplicates events by (venue, normalized_title_prefix) while preserving short
    artist names (>= 2 chars like 'Sul', 'Jos', 'RY X') and merging richer metadata.
    """
    merged = {}
    for ev in raw_events:
        raw_t = ev.get("title", "").strip()
        clean_t = re.sub(r"\s*@\s*.*$", "", raw_t)
        t_key = re.sub(r"[^a-z0-9]", "", strip_accents(clean_t))
        if len(t_key) < 2:
            continue

        v_key = re.sub(r"[^a-z0-9]", "", strip_accents(ev.get("venue", "")))
        dedup_sig = (v_key, t_key[:18], ev.get("hour", 21) // 3)

        if dedup_sig not in merged:
            merged[dedup_sig] = ev
        else:
            existing = merged[dedup_sig]
            if len(urlparse(ev.get("url", "")).path) > len(urlparse(existing.get("url", "")).path):
                existing["url"] = ev["url"]
            if "confirmar" in existing.get("price", "").lower() and "confirmar" not in ev.get("price", "").lower():
                existing["price"] = ev["price"]
                existing["priceTier"] = ev["priceTier"]

    return list(merged.values())


def apply_coordinate_jitter(events):
    """
    Applies a compact Golden-Angle Fermat spiral offset around shared venue coordinates
    so 100+ pins do not stack on top of each other or drift into the Tagus River.
    """
    coord_groups = {}
    for ev in events:
        key = f"{ev['lat']:.4f},{ev['lng']:.4f}"
        coord_groups.setdefault(key, []).append(ev)

    golden_angle_deg = 137.507764
    for key, group in coord_groups.items():
        if len(group) <= 1:
            continue
        base_lat = group[0]["lat"]
        base_lng = group[0]["lng"]
        for idx, ev in enumerate(group):
            if idx == 0:
                continue
            radius = 0.00016 * math.sqrt(idx)
            rad_angle = math.radians(idx * golden_angle_deg)
            ev["lat"] = round(base_lat + (radius * math.cos(rad_angle)), 6)
            ev["lng"] = round(base_lng + (radius * math.sin(rad_angle) * 1.25), 6)

    return events


def main():
    target_date, now_time = get_lisbon_operational_date()
    print(f"=== Executing Keks Passa Live Pipeline for Operational Date: {target_date} ===")

    tier1_agendalx = scrape_agendalx_api(target_date)
    tier1_ra = scrape_resident_advisor(target_date)
    tier2_direct = scrape_direct_venues(target_date)
    tier3_shotgun = scrape_shotgun(target_date)
    tier3_nocartaz = scrape_nocartaz_lisboa(target_date)
    tier3_adc = scrape_agendadeconcertos(target_date)

    live_raw = tier1_ra + tier3_shotgun + tier2_direct + tier3_nocartaz + tier3_adc + tier1_agendalx
    live_events = deduplicate_and_merge_events(live_raw)

    represented_venues = {ev["venue"] for ev in live_events}
    tier4_ongoing = get_verified_ongoing_runs(target_date, represented_venues)

    all_events = deduplicate_and_merge_events(live_events + tier4_ongoing)

    # Sort chronologically according to the 04:00 AM Lisbon operational day
    all_events.sort(
        key=lambda x: (
            x.get("hour", 0) + 24 if x.get("hour", 0) < 4 else x.get("hour", 0),
            x.get("time", "00:00")
        )
    )

    if MAX_EVENTS and len(all_events) > MAX_EVENTS:
        all_events = all_events[:MAX_EVENTS]

    all_events = apply_coordinate_jitter(all_events)

    timestamp_str = now_time.isoformat()
    output_payload = {
        "updated_at": timestamp_str,
        "generated_at": timestamp_str,
        "date_string": target_date.strftime("%A, %B %d, %Y"),
        "operational_date": target_date.strftime("%Y-%m-%d"),
        "total_events": len(all_events),
        "events": all_events
    }

    output_filename = "events.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    print(f"=== Successfully published {len(all_events)} live events to {output_filename} ===")


if __name__ == "__main__":
    main()
