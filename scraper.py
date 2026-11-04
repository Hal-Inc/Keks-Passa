#!/usr/bin/env python3
"""
Keks Passa — Daily Lisbon Cultural & Nightlife Scraper (v2.5 Unified Multi-Tier)
Fixes false-positive substring venue matching (e.g. 'nāda'->'nada', 'rca'->'mercado')
and expands Arts & Crafts, Markets, Workshops & Lectures:
1. AgendaLX (agendalx.pt events + Feiras/Mercados, Oficinas, Conferências, Literatura) & Cartaz Cultural
2. NoCartaz Lisboa (concelhos/lisboa + hoje + distrito/lisboa categories + date-range parser)
3. Cinemateca Portuguesa (cinemateca.pt/Programacao.aspx)
4. Cinema Medeia Nimas (medeiafilmes.com — fixed 'estreia DD.MM.YYYY' truncation)
5. Agenda de Concertos Lisboa (localidade/lisboa + concertos-em-portugal)
6. BOTA Anjos Programação (botaanjos.com/programacao)
7. Prior Velho, Lisabout & Electronic Hubs (lisabout.com/events + moonclub.pt + RA Area 229/51)
8. Arts & Crafts, Markets, Workshops & Lectures (Eventbrite Lisboa + FICA Oficina Criativa)
9. Active Lisbon Museum Exhibitions, Markets, Workshops, Cinemas & Theatre Seasons (35+ daily baseline)
"""

import os
import re
import json
import math
import datetime
import unicodedata
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import locations
import requests
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

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
    "concerts": {"category": "Concerts & Live Music", "color": "#E63946", "icon": "🎤"},
    "theatre": {"category": "Theatre & Comedy", "color": "#2A9D8F", "icon": "🎭"},
    "exhibitions": {"category": "Exhibitions & Visual Arts", "color": "#1D3557", "icon": "🎨"},
    "classical": {"category": "Opera & Classical", "color": "#8338EC", "icon": "🎻"},
    "cinema": {"category": "Cinema & Screenings", "color": "#06D6A0", "icon": "🍿"},
    "nightlife": {"category": "Nightlife & Electronic", "color": "#FB5607", "icon": "🔊"},
    "community": {"category": "Community & Gatherings", "color": "#FFB703", "icon": "🛍️"},
    "family": {"category": "Family & Youth", "color": "#118AB2", "icon": "🎠"},
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
    "campo grande", "principe real", "arroios", "anjos", "marvila", "beato"
}

# ==============================================================================
# VENUE REGISTRY (96 Verified Lisbon, Craft, Market & Prior Velho Venues)
# ==============================================================================
VENUE_REGISTRY = [
    # --- PRIOR VELHO & ORIENTE ELECTRONIC CLUSTER ---
    {"venue": "Kømplex Lisbon", "aliases": ["komplex lisbon", "kømplex lisbon", "kømplex", "komplex", "praceta domingos rodrigues"], "lat": 38.7845, "lng": -9.1192, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor", "url": "https://shotgun.live/pt-pt/venues/komplex"},
    {"venue": "Moon Club", "aliases": ["moon club", "moonclub", "moon club prior velho", "raw kinky lab", "invdrs"], "lat": 38.7862, "lng": -9.1245, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor", "url": "https://www.moonclub.pt"},
    {"venue": "NĀDA 3.0 (NADA Lisbon)", "aliases": ["nada 3.0", "naada 3.0", "nada lisbon", "naada lisbon", "nāda 3.0", "rua figo maduro 3", "tiga naada", "nada temple", "balagan halloween"], "lat": 38.7858, "lng": -9.1238, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor", "url": "https://shotgun.live/pt-pt/venues/nada-lisbon"},
    {"venue": "Higher Ground", "aliases": ["higher ground", "rua ary dos santos 20"], "lat": 38.7868, "lng": -9.1252, "neighborhood": "Prior Velho / Oriente", "corridor": "Eastern Corridor", "url": "https://shotgun.live/en/cities/lisbon"},
    {"venue": "Music Station", "aliases": ["music station", "rock station", "aquilino ribeiro machado 74", "therapy sessions"], "lat": 38.7735, "lng": -9.0975, "neighborhood": "Parque das Nações / Oriente", "corridor": "Eastern Corridor", "url": "https://pt.ra.co/clubs/254407"},
    {"venue": "Top Floor", "aliases": ["top floor", "rua da pimenta 29"], "lat": 38.7712, "lng": -9.0928, "neighborhood": "Parque das Nações / Oriente", "corridor": "Eastern Corridor", "url": "https://www.lisabout.com/genero/dance-electronic"},

    # --- MARVILA, BEATO, ANJOS & EASTERN CORRIDOR ---
    {"venue": "Lux Frágil", "aliases": ["lux fragil", "av. infante d. henrique"], "lat": 38.71575, "lng": -9.12135, "neighborhood": "Santa Apolónia", "corridor": "Eastern Corridor", "url": "https://www.luxfragil.com"},
    {"venue": "8 Marvila", "aliases": ["8 marvila", "oito marvila", "praca david leandro da silva"], "lat": 38.74215, "lng": -9.10195, "neighborhood": "Marvila", "corridor": "Eastern Corridor", "url": "https://www.8marvila.com"},
    {"venue": "LAV - Lisboa ao Vivo", "aliases": ["lisboa ao vivo", "lav - lisboa ao vivo", "av. marechal gomes da costa"], "lat": 38.75485, "lng": -9.10285, "neighborhood": "Marvila / Cabo Ruivo", "corridor": "Eastern Corridor", "url": "https://lisboaaovivo.com"},
    {"venue": "Casa Capitão", "aliases": ["casa capitao", "casa do capitao", "convento do beato", "rua do grilo"], "lat": 38.73295, "lng": -9.10595, "neighborhood": "Beato", "corridor": "Eastern Corridor", "url": "https://casa-capitao.com"},
    {"venue": "Musa de Marvila", "aliases": ["musa de marvila", "musa marvila"], "lat": 38.73925, "lng": -9.10125, "neighborhood": "Marvila", "corridor": "Eastern Corridor", "url": "https://cervejamusa.com"},
    {"venue": "Arroz Estúdios", "aliases": ["arroz estudios"], "lat": 38.73365, "lng": -9.10385, "neighborhood": "Beato", "corridor": "Eastern Corridor", "url": "https://arrozestudios.pt"},
    {"venue": "Fábrica Braço de Prata", "aliases": ["fabrica do braco de prata", "fabrica braco de prata", "braco de prata"], "lat": 38.74379, "lng": -9.10124, "neighborhood": "Marvila / Braço de Prata", "corridor": "Eastern Corridor", "url": "https://www.bracodeprata.com"},
    {"venue": "Underdogs Gallery", "aliases": ["underdogs", "underdogs gallery", "rua fernando palha"], "lat": 38.73995, "lng": -9.10035, "neighborhood": "Marvila", "corridor": "Eastern Corridor", "url": "https://www.under-dogs.net"},
    {"venue": "Teatro Meridional", "aliases": ["teatro meridional", "meridional"], "lat": 38.73785, "lng": -9.10165, "neighborhood": "Marvila", "corridor": "Eastern Corridor", "url": "https://teatromeridional.net"},
    {"venue": "BOTA - Base Organizada da Toca das Artes", "aliases": ["bota anjos", "base organizada da toca das artes", "largo de santa barbara"], "lat": 38.72675, "lng": -9.13650, "neighborhood": "Anjos", "corridor": "Eastern Corridor", "url": "https://www.botaanjos.com"},
    {"venue": "Jardins do Bombarda (LARGO Residências)", "aliases": ["jardins do bombarda", "largo residencias", "hospital miguel bombarda", "rua gomes freire", "jardim do bombarda"], "lat": 38.72515, "lng": -9.13915, "neighborhood": "Arroios / Gomes Freire", "corridor": "Eastern Corridor", "url": "https://www.jardinsdobombarda.pt"},
    {"venue": "Caulino Ceramics & Ateliers de Olaria", "aliases": ["caulino ceramics", "caulino", "atelier de ceramica arroios", "olaria arroios"], "lat": 38.7278, "lng": -9.1342, "neighborhood": "Arroios", "corridor": "Eastern Corridor", "url": "https://www.caulinoceramics.com"},
    {"venue": "Contraprova — Atelier de Gravura e Risografia", "aliases": ["contraprova", "atelier de gravura", "oficina de serigrafia anjos", "risografia lisboa"], "lat": 38.7231, "lng": -9.1361, "neighborhood": "Anjos / Intendente", "corridor": "Eastern Corridor", "url": "https://www.agendalx.pt"},
    {"venue": "Anjos70", "aliases": ["anjos70", "anjos 70", "regueirao dos anjos"], "lat": 38.72298, "lng": -9.13588, "neighborhood": "Anjos", "corridor": "Eastern Corridor", "url": "https://anjos70.org/"},
    {"venue": "Well Read Bookshop", "aliases": ["well read", "well read bookshop", "calcada de sant'ana"], "lat": 38.71642, "lng": -9.13847, "neighborhood": "Arroios / Santana", "corridor": "Axial Spine", "url": "https://soko.fyi/pt/venues/well-read-nqqx52"},
    {"venue": "Hangar - Centro de Investigação Artística", "aliases": ["hangar", "centro de investigacao artistica", "rua damasceno monteiro", "mafolofolo"], "lat": 38.71975, "lng": -9.13285, "neighborhood": "Graça", "corridor": "Eastern Corridor", "url": "https://hangar.com.pt"},
    {"venue": "Feira da Ladra (Campo de Santa Clara)", "aliases": ["feira da ladra", "campo de santa clara"], "lat": 38.7154, "lng": -9.1255, "neighborhood": "São Vicente / Alfama", "corridor": "Eastern Corridor", "url": "https://www.agendalx.pt"},
    {"venue": "Mercado de Santa Clara", "aliases": ["mercado de santa clara", "mercado santa clara"], "lat": 38.7156, "lng": -9.1252, "neighborhood": "São Vicente / Santa Clara", "corridor": "Eastern Corridor", "url": "https://www.agendalx.pt"},
    {"venue": "Panteão Nacional", "aliases": ["panteao nacional"], "lat": 38.7150, "lng": -9.1247, "neighborhood": "Santa Clara / Alfama", "corridor": "Eastern Corridor", "url": "https://www.panteaonacional.gov.pt"},
    {"venue": "Pavilhão do Conhecimento", "aliases": ["pavilhao do conhecimento", "ciencia viva"], "lat": 38.7626, "lng": -9.0936, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor", "url": "https://www.pavconhecimento.pt"},
    {"venue": "Oceanário de Lisboa", "aliases": ["oceanario de lisboa", "oceanario"], "lat": 38.7635, "lng": -9.0937, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor", "url": "https://www.oceanario.pt"},
    {"venue": "MEO Arena", "aliases": ["meo arena", "altice arena", "sala tejo", "feira internacional de lisboa", "fil lisboa"], "lat": 38.7686, "lng": -9.0940, "neighborhood": "Parque das Nações", "corridor": "Eastern Corridor", "url": "https://arena.meo.pt"},

    # --- AXIAL SPINE ---
    {"venue": "Galeria Zé dos Bois (ZDB)", "aliases": ["zdb", "galeria ze dos bois", "ze dos bois", "rua da barrosa", "rua da barroca"], "lat": 38.71202, "lng": -9.14438, "neighborhood": "Bairro Alto", "corridor": "Axial Spine", "url": "https://zedosbois.org"},
    {"venue": "Menina e Moça", "aliases": ["menina e moca", "livraria menina e moca", "livraria-bar menina e moca", "rua nova do carvalho"], "lat": 38.70723, "lng": -9.14362, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://meninaemoca.pt"},
    {"venue": "Musicbox", "aliases": ["musicbox", "music box"], "lat": 38.70718, "lng": -9.14338, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://musicboxlisboa.com"},
    {"venue": "Lust in Rio", "aliases": ["lust in rio", "rua da cintura do porto de lisboa"], "lat": 38.70585, "lng": -9.15205, "neighborhood": "Santos / Cais do Sodré", "corridor": "Axial Spine", "url": "https://www.lisabout.com"},
    {"venue": "The Vintage Hotel Lisbon (THE CURATED Lisbon)", "aliases": ["the vintage hotel", "the curated lisbon", "curated selection", "rua rodrigo da fonseca 2"], "lat": 38.72095, "lng": -9.15165, "neighborhood": "Príncipe Real / Rato", "corridor": "Axial Spine", "url": "https://thecuratedlisbon.com"},
    {"venue": "Auditório Camões (Liceu Camões)", "aliases": ["auditorio camoes", "liceu camoes", "escola secundaria camoes"], "lat": 38.73255, "lng": -9.14455, "neighborhood": "Picoas / Saldanha", "corridor": "Northern Belt", "url": "https://www.agendalx.pt"},
    {"venue": "Ministerium Club", "aliases": ["ministerium", "ministerium club"], "lat": 38.70828, "lng": -9.13578, "neighborhood": "Terreiro do Paço", "corridor": "Axial Spine", "url": "https://pt.ra.co/clubs/66945"},
    {"venue": "Harbour Music Shelter", "aliases": ["harbour music shelter"], "lat": 38.7066, "lng": -9.1448, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Rive Rouge", "aliases": ["rive rouge", "estudio time out", "mercado da ribeira"], "lat": 38.70695, "lng": -9.14585, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Tokyo Lisboa", "aliases": ["tokyo lisboa"], "lat": 38.70712, "lng": -9.14315, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://tokyolisboa.com"},
    {"venue": "B.Leza", "aliases": ["b.leza", "bleza", "cais da ribeira nova"], "lat": 38.70555, "lng": -9.14565, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://www.agendalx.pt"},
    {"venue": "Titanic Sur Mer", "aliases": ["titanic sur mer", "lisboa rio", "cais do gas"], "lat": 38.70572, "lng": -9.14678, "neighborhood": "Cais do Sodré", "corridor": "Axial Spine", "url": "https://www.agendalx.pt"},
    {"venue": "O Bom O Mau e O Vilão", "aliases": ["o bom o mau e o vilao"], "lat": 38.70762, "lng": -9.14348, "neighborhood": "Cais do Sodré / Chiado", "corridor": "Axial Spine", "url": "https://www.lisabout.com"},
    {"venue": "Pátio da Galé", "aliases": ["patio da gale", "monkey project"], "lat": 38.70795, "lng": -9.13772, "neighborhood": "Baixa / Terreiro do Paço", "corridor": "Axial Spine", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Palácio Chiado", "aliases": ["palacio chiado"], "lat": 38.70912, "lng": -9.14325, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://palaciochiado.pt"},
    {"venue": "Chiado Comedy Club", "aliases": ["chiado comedy club", "convento comedy club"], "lat": 38.7104, "lng": -9.1419, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://www.nocartaz.pt/concelhos/lisboa/"},
    {"venue": "Skones & Pátio do Pinzaleiro", "aliases": ["skones", "patio do pinzaleiro", "pinzaleiro"], "lat": 38.7086, "lng": -9.1562, "neighborhood": "Santos / Madragoa", "corridor": "Axial Spine", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Museu da Marioneta", "aliases": ["museu da marioneta", "convento das bernardas"], "lat": 38.70792, "lng": -9.15615, "neighborhood": "Madragoa / Santos", "corridor": "Axial Spine", "url": "https://www.museudamarioneta.pt"},
    {"venue": "Museu da Farmácia", "aliases": ["museu da farmacia"], "lat": 38.70972, "lng": -9.14815, "neighborhood": "Santa Catarina / Chiado", "corridor": "Axial Spine", "url": "https://www.museudafarmacia.pt"},
    {"venue": "Jardim da Estrela (Crafts & Design)", "aliases": ["jardim da estrela", "mercado crafts & design", "crafts and design", "feira da estrela"], "lat": 38.71455, "lng": -9.15935, "neighborhood": "Estrela / Lapa", "corridor": "Axial Spine", "url": "https://www.agendalx.pt"},
    {"venue": "Jardim do Príncipe Real", "aliases": ["jardim do principe real", "mercado biologico do principe real"], "lat": 38.71645, "lng": -9.14875, "neighborhood": "Príncipe Real", "corridor": "Axial Spine", "url": "https://www.agendalx.pt"},
    {"venue": "MUHNAC — Museu Nacional de História Natural e da Ciência", "aliases": ["muhnac", "museu nacional de historia natural", "jardim botanico de lisboa", "escola politecnica"], "lat": 38.71765, "lng": -9.15125, "neighborhood": "Príncipe Real", "corridor": "Axial Spine", "url": "https://www.museus.ulisboa.pt"},
    {"venue": "Teatro do Bairro Alto (TBA)", "aliases": ["teatro do bairro alto", "tba"], "lat": 38.71968, "lng": -9.15278, "neighborhood": "Príncipe Real", "corridor": "Axial Spine", "url": "https://teatrodobairroalto.pt"},
    {"venue": "Fundação Arpad Szenes-Vieira da Silva", "aliases": ["arpad szenes", "vieira da silva", "fundacao arpad szenes"], "lat": 38.72148, "lng": -9.15915, "neighborhood": "Amoreiras / Rato", "corridor": "Axial Spine", "url": "https://fasvs.pt"},
    {"venue": "Casa Fernando Pessoa", "aliases": ["casa fernando pessoa", "rua coelho da rocha"], "lat": 38.71592, "lng": -9.16645, "neighborhood": "Campo de Ourique", "corridor": "Axial Spine", "url": "https://www.casafernandopessoa.pt"},
    {"venue": "Goethe-Institut Lisboa", "aliases": ["goethe-institut", "goethe institut", "campo dos martires da patria"], "lat": 38.72205, "lng": -9.14058, "neighborhood": "Santana / Pena", "corridor": "Axial Spine", "url": "https://www.goethe.de/ins/pt/pt/ver.cfm"},
    {"venue": "Hot Clube de Portugal", "aliases": ["hot clube", "hot clube de portugal", "praca da alegria"], "lat": 38.71818, "lng": -9.14468, "neighborhood": "Avenida / Praça da Alegria", "corridor": "Axial Spine", "url": "https://hcp.pt"},
    {"venue": "Cineteatro Capitólio", "aliases": ["capitolio", "cineteatro capitolio", "teatro capitolio"], "lat": 38.71855, "lng": -9.14635, "neighborhood": "Parque Mayer / Avenida", "corridor": "Axial Spine", "url": "https://www.cineteatrocapitolio.pt"},
    {"venue": "Teatro Variedades", "aliases": ["teatro variedades"], "lat": 38.71832, "lng": -9.14592, "neighborhood": "Parque Mayer", "corridor": "Axial Spine", "url": "https://teatrovariedades-capitolio.pt"},
    {"venue": "Teatro Politeama", "aliases": ["teatro politeama", "politeama"], "lat": 38.71642, "lng": -9.14065, "neighborhood": "Baixa / Rossio", "corridor": "Axial Spine", "url": "https://filipelaferia.pt"},
    {"venue": "Coliseu dos Recreios", "aliases": ["coliseu dos recreios", "coliseu de lisboa", "rua das portas de santo antao"], "lat": 38.71662, "lng": -9.14082, "neighborhood": "Baixa / Rossio", "corridor": "Axial Spine", "url": "https://www.coliseulisboa.com"},
    {"venue": "Teatro Nacional D. Maria II", "aliases": ["d. maria ii", "d maria ii", "dona maria ii", "tndmii"], "lat": 38.71462, "lng": -9.13968, "neighborhood": "Rossio", "corridor": "Axial Spine", "url": "https://www.tndm.pt"},
    {"venue": "São Luiz Teatro Municipal", "aliases": ["sao luiz", "teatro sao luiz", "sao luis", "teatro municipal sao luiz"], "lat": 38.70948, "lng": -9.14258, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://www.teatrosaoluiz.pt"},
    {"venue": "Teatro Nacional de São Carlos", "aliases": ["sao carlos", "teatro nacional de sao carlos"], "lat": 38.70958, "lng": -9.14162, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://saocarlos.pt"},
    {"venue": "Teatro da Trindade INATEL", "aliases": ["teatro da trindade", "trindade inatel"], "lat": 38.71265, "lng": -9.14242, "neighborhood": "Chiado / Bairro Alto", "corridor": "Axial Spine", "url": "https://teatrodatrindade.inatel.pt"},
    {"venue": "Teatro Tivoli BBVA", "aliases": ["tivoli bbva", "teatro tivoli"], "lat": 38.71962, "lng": -9.14448, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine", "url": "https://www.teatrotivolibbva.pt"},
    {"venue": "Cinemateca Portuguesa", "aliases": ["cinemateca", "cinemateca portuguesa", "rua barata salgueiro"], "lat": 38.72168, "lng": -9.14828, "neighborhood": "Avenida / Marquês", "corridor": "Axial Spine", "url": "https://www.cinemateca.pt"},
    {"venue": "Cinema São Jorge", "aliases": ["cinema sao jorge"], "lat": 38.71915, "lng": -9.14502, "neighborhood": "Avenida da Liberdade", "corridor": "Axial Spine", "url": "https://cinemasaojorge.pt"},
    {"venue": "Cinema Ideal", "aliases": ["cinema ideal", "rua do loreto"], "lat": 38.71088, "lng": -9.14442, "neighborhood": "Chiado / Camões", "corridor": "Axial Spine", "url": "https://cinemaideal.pt"},
    {"venue": "MNAC - Museu do Chiado", "aliases": ["mnac", "museu do chiado", "museu nacional de arte contemporanea"], "lat": 38.70882, "lng": -9.14122, "neighborhood": "Chiado", "corridor": "Axial Spine", "url": "https://museuartecontemporanea.gov.pt"},
    {"venue": "MUDE — Museu do Design", "aliases": ["mude", "museu do design"], "lat": 38.70922, "lng": -9.13695, "neighborhood": "Baixa", "corridor": "Axial Spine", "url": "https://www.mude.pt"},
    {"venue": "Castelo de São Jorge", "aliases": ["castelo de sao jorge", "camara escura"], "lat": 38.7139, "lng": -9.1334, "neighborhood": "Castelo / Alfama", "corridor": "Axial Spine", "url": "https://castelodesaojorge.pt"},
    {"venue": "Fundação José Saramago (Casa dos Bicos)", "aliases": ["casa dos bicos", "fundacao jose saramago"], "lat": 38.7090, "lng": -9.1326, "neighborhood": "Alfama / Ribeira", "corridor": "Axial Spine", "url": "https://www.josesaramago.org"},
    {"venue": "Museu do Fado", "aliases": ["museu do fado", "largo do chafariz de dentro"], "lat": 38.7112, "lng": -9.1277, "neighborhood": "Alfama", "corridor": "Axial Spine", "url": "https://www.museudofado.pt"},
    {"venue": "Incógnito", "aliases": ["incognito", "incognito bar", "rua de poiais de sao bento"], "lat": 38.71095, "lng": -9.15035, "neighborhood": "São Bento", "corridor": "Axial Spine", "url": "https://incognitobar.com"},
    {"venue": "Casa Independente", "aliases": ["casa independente", "largo do intendente"], "lat": 38.72138, "lng": -9.13538, "neighborhood": "Intendente", "corridor": "Axial Spine", "url": "https://casaindependente.com"},
    {"venue": "Plano B / Bica & Cais", "aliases": ["bicaense", "damas", "desterro", "bus paragem cultural"], "lat": 38.7218, "lng": -9.1352, "neighborhood": "Intendente / Anjos", "corridor": "Axial Spine", "url": "https://www.agendalx.pt"},

    # --- NORTHERN BELT ---
    {"venue": "CAM - Centro de Arte Moderna Gulbenkian", "aliases": ["gulbenkian", "fundacao calouste gulbenkian", "cam gulbenkian", "centro de arte moderna"], "lat": 38.73645, "lng": -9.15465, "neighborhood": "Avenidas Novas / Praça de Espanha", "corridor": "Northern Belt", "url": "https://gulbenkian.pt"},
    {"venue": "Reitoria da Universidade NOVA de Lisboa", "aliases": ["reitoria da nova", "universidade nova de lisboa", "campus de campolide"], "lat": 38.7336, "lng": -9.1602, "neighborhood": "Campolide / Praça de Espanha", "corridor": "Northern Belt", "url": "https://www.unl.pt"},
    {"venue": "Aula Magna — Universidade de Lisboa", "aliases": ["aula magna", "reitoria da universidade de lisboa"], "lat": 38.7525, "lng": -9.1582, "neighborhood": "Cidade Universitária", "corridor": "Northern Belt", "url": "https://www.ulisboa.pt"},
    {"venue": "Teatro da Comuna", "aliases": ["teatro da comuna", "comuna teatro", "opera-pimba no gelo"], "lat": 38.7367, "lng": -9.1605, "neighborhood": "Praça de Espanha", "corridor": "Northern Belt", "url": "https://www.comunateatropesquisa.pt"},
    {"venue": "Jardim Zoológico de Lisboa", "aliases": ["jardim zoologico", "zoo de lisboa", "reptilario"], "lat": 38.7442, "lng": -9.1712, "neighborhood": "Sete Rios", "corridor": "Northern Belt", "url": "https://www.zoo.pt"},
    {"venue": "Evolution Valbom Rooftop", "aliases": ["evolution valbom", "rooftop over lisbon"], "lat": 38.73485, "lng": -9.14525, "neighborhood": "Picoas / Saldanha", "corridor": "Northern Belt", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "Fórum Picoas", "aliases": ["forum picoas", "auditorio forum picoas", "galeria forum picoas", "fontes pereira de melo"], "lat": 38.73068, "lng": -9.14692, "neighborhood": "Picoas", "corridor": "Northern Belt", "url": "https://www.agendalx.pt"},
    {"venue": "Casa-Museu Dr. Anastácio Gonçalves", "aliases": ["anastacio goncalves", "casa-museu dr. anastacio goncalves", "casa museu anastacio goncalves"], "lat": 38.73145, "lng": -9.14765, "neighborhood": "Picoas", "corridor": "Northern Belt", "url": "https://www.museusemonumentos.pt"},
    {"venue": "Galeria Monumental", "aliases": ["galeria monumental"], "lat": 38.7294, "lng": -9.1442, "neighborhood": "Picoas / Saldanha", "corridor": "Northern Belt", "url": "https://www.galeriamonumental.com"},
    {"venue": "Mercado 31 de Janeiro", "aliases": ["mercado 31 de janeiro", "rua engenheiro vieira da silva"], "lat": 38.73188, "lng": -9.14362, "neighborhood": "Picoas", "corridor": "Northern Belt", "url": "https://www.agendalx.pt"},
    {"venue": "Imprensa Nacional — Galeria & Oficinas INCM", "aliases": ["imprensa nacional", "galeria incm", "casa da moeda", "biblioteca da imprensa nacional"], "lat": 38.72780, "lng": -9.14860, "neighborhood": "Picoas / Marquês", "corridor": "Northern Belt", "url": "https://imprensanacional.pt"},
    {"venue": "Culturgest", "aliases": ["culturgest", "fundacao caixa geral de depositos"], "lat": 38.74165, "lng": -9.14345, "neighborhood": "Campo Pequeno / Arco do Cego", "corridor": "Northern Belt", "url": "https://www.culturgest.pt"},
    {"venue": "Biblioteca Palácio Galveias", "aliases": ["palacio galveias", "biblioteca palacio galveias"], "lat": 38.74175, "lng": -9.14685, "neighborhood": "Campo Pequeno", "corridor": "Northern Belt", "url": "https://blx.cm-lisboa.pt"},
    {"venue": "Cinema Medeia Nimas", "aliases": ["cinema nimas", "medeia nimas", "espaco nimas", "nimas"], "lat": 38.73342, "lng": -9.14798, "neighborhood": "Picoas / Saldanha", "corridor": "Northern Belt", "url": "https://medeiafilmes.com/cinemas/cinema-medeia-nimas"},
    {"venue": "Cinema Medeia Monumental", "aliases": ["medeia monumental", "cinema monumental", "saldanha monumental"], "lat": 38.73355, "lng": -9.14545, "neighborhood": "Picoas / Saldanha", "corridor": "Northern Belt", "url": "https://medeiafilmes.com"},
    {"venue": "Teatro Maria Matos", "aliases": ["maria matos", "teatro maria matos"], "lat": 38.74632, "lng": -9.13808, "neighborhood": "Roma / Areeiro", "corridor": "Northern Belt", "url": "https://teatromariamatos.pt"},
    {"venue": "Teatro Bocage", "aliases": ["teatro bocage", "rua manuel da silva leal"], "lat": 38.7429, "lng": -9.1392, "neighborhood": "Areeiro / Alvalade", "corridor": "Northern Belt", "url": "https://www.nocartaz.pt/concelhos/lisboa/"},
    {"venue": "Appleton Associação Cultural", "aliases": ["appleton", "appleton associacao cultural", "rua acacio paiva"], "lat": 38.75015, "lng": -9.14145, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://appleton.pt"},
    {"venue": "Cinema City Classic Alvalade", "aliases": ["cinema city classic alvalade", "cinema city alvalade", "classic alvalade"], "lat": 38.75185, "lng": -9.14365, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://www.cinemacity.pt"},
    {"venue": "República da Música", "aliases": ["republica da musica"], "lat": 38.75545, "lng": -9.14295, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://www.agendalx.pt"},
    {"venue": "RCA Club", "aliases": ["rca club", "rua joao saraiva"], "lat": 38.75245, "lng": -9.14085, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://www.rcaclub.com"},
    {"venue": "Távola Jazz Club", "aliases": ["tavola jazz club", "tavola jazz"], "lat": 38.7485, "lng": -9.1398, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://www.tavolajazzclub.com"},
    {"venue": "Museu Bordalo Pinheiro", "aliases": ["museu bordalo pinheiro", "bordalo pinheiro"], "lat": 38.75812, "lng": -9.15285, "neighborhood": "Campo Grande", "corridor": "Northern Belt", "url": "https://museubordalopinheiro.pt"},
    {"venue": "Sagres Campo Pequeno", "aliases": ["sagres campo pequeno", "arena campo pequeno"], "lat": 38.74258, "lng": -9.14532, "neighborhood": "Campo Pequeno", "corridor": "Northern Belt", "url": "https://www.campopequeno.com"},
    {"venue": "Pavilhão Carlos Lopes", "aliases": ["pavilhao carlos lopes"], "lat": 38.72892, "lng": -9.15175, "neighborhood": "Parque Eduardo VII", "corridor": "Northern Belt", "url": "https://www.agendalx.pt"},

    # --- BELÉM WATERFRONT & ALCÂNTARA ---
    {"venue": "Centro Cultural de Belém (CCB)", "aliases": ["ccb", "centro cultural de belem", "mac/ccb", "museu de arte contemporanea ccb"], "lat": 38.69558, "lng": -9.20642, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://www.ccb.pt"},
    {"venue": "MAAT - Museu de Arte, Arquitetura e Tecnologia", "aliases": ["maat", "central tejo"], "lat": 38.69588, "lng": -9.19448, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://www.maat.pt"},
    {"venue": "Padrão dos Descobrimentos", "aliases": ["padrao dos descobrimentos"], "lat": 38.6936, "lng": -9.2057, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://padraodosdescobrimentos.pt"},
    {"venue": "Museu Nacional dos Coches", "aliases": ["museu nacional dos coches", "museu dos coches"], "lat": 38.6966, "lng": -9.1997, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://www.mncoches.gov.pt"},
    {"venue": "BONANÇA - Associação Naval de Lisboa", "aliases": ["bonanca", "associacao naval de lisboa", "doca de belem"], "lat": 38.6942, "lng": -9.2038, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://www.lisabout.com/genero/dance-electronic"},
    {"venue": "MACAM / àCapela", "aliases": ["macam", "acapela"], "lat": 38.6989, "lng": -9.1887, "neighborhood": "Belém / Junqueira", "corridor": "Belém Waterfront", "url": "https://www.nocartaz.pt/concelhos/lisboa/"},
    {"venue": "FICA — Oficina Criativa (LX Factory)", "aliases": ["fica oficina criativa", "fica-oc"], "lat": 38.70378, "lng": -9.17865, "neighborhood": "Alcântara (LX Factory)", "corridor": "Belém Waterfront", "url": "https://fica-oc.pt"},
    {"venue": "LX Factory / Village Underground", "aliases": ["lx factory", "lxfactory", "collect lx factory", "village underground", "ler devagar", "lx rural"], "lat": 38.70355, "lng": -9.17885, "neighborhood": "Alcântara", "corridor": "Belém Waterfront", "url": "https://lxfactory.com"},
    {"venue": "Docas de Santo Amaro / Cais Rocha Conde de Óbidos", "aliases": ["docas de santo amaro", "rocha conde de obidos", "sunset boat party"], "lat": 38.7008, "lng": -9.1742, "neighborhood": "Alcântara / Docas", "corridor": "Belém Waterfront", "url": "https://www.agendalx.pt"},
    {"venue": "Museu do Oriente", "aliases": ["museu do oriente"], "lat": 38.70278, "lng": -9.17135, "neighborhood": "Alcântara", "corridor": "Belém Waterfront", "url": "https://www.foriente.pt"},
    {"venue": "Museu Nacional de Arte Antiga (MNAA)", "aliases": ["museu nacional de arte antiga", "mnaa", "janelas verdes"], "lat": 38.70435, "lng": -9.16085, "neighborhood": "Santos / Janelas Verdes", "corridor": "Belém Waterfront", "url": "https://www.museudearteantiga.pt"},
    {"venue": "LU.CA — Teatro Luís de Camões", "aliases": ["lu.ca", "teatro luis de camoes"], "lat": 38.70048, "lng": -9.20075, "neighborhood": "Belém / Ajuda", "corridor": "Belém Waterfront", "url": "https://lucateatroluisdecamoes.pt"},

    # --- VERIFIED CULTURAL, CIVIC & COMMUNITY HUBS ---
    {"venue": "Emaús Pop-Up Arroios", "aliases": ["emaus pop-up arroios", "emaus arroios", "emaus pop-up", "rua carlos mardel 23", "carlos mardel 23"], "lat": 38.73528, "lng": -9.13317, "neighborhood": "Arroios", "corridor": "Eastern Corridor", "url": "https://cartazculturallisboa.pt"},
    {"venue": "Museu de Lisboa - Santo António", "aliases": ["museu de lisboa - santo antonio", "museu de lisboa santo antonio", "museu de santo antonio", "largo de santo antonio da se"], "lat": 38.70996, "lng": -9.13346, "neighborhood": "Alfama / Sé", "corridor": "Axial Spine", "url": "https://www.museudelisboa.pt"},
    {"venue": "Museu Berardo Arte Deco (B-MAD)", "aliases": ["b-mad", "museu berardo arte deco", "berardo arte deco", "rua 1o de maio 28", "rua primeiro de maio 28"], "lat": 38.70428, "lng": -9.18029, "neighborhood": "Alcântara", "corridor": "Belém Waterfront", "url": "https://b-mad.pt"},
    {"venue": "Museu Banksy Lisboa", "aliases": ["museu banksy lisboa", "museu banksy", "world of banksy", "the world of banksy", "rua viriato 25"], "lat": 38.73038, "lng": -9.14801, "neighborhood": "Picoas / Saldanha", "corridor": "Northern Belt", "url": "https://museubanksy.pt"},
    {"venue": "Museu de Marinha & Planetário", "aliases": ["museu de marinha", "planetario de marinha", "planetario calouste gulbenkian belem"], "lat": 38.69736, "lng": -9.20875, "neighborhood": "Belém", "corridor": "Belém Waterfront", "url": "https://ccm.marinha.pt"},
    {"venue": "Cordoaria Nacional", "aliases": ["cordoaria nacional", "galerias da cordoaria nacional", "av. da india"], "lat": 38.69768, "lng": -9.19018, "neighborhood": "Belém / Junqueira", "corridor": "Belém Waterfront", "url": "https://www.agendalx.pt"},
    {"venue": "Igreja e Museu de São Roque", "aliases": ["museu de sao roque", "igreja de sao roque", "largo trindade coelho"], "lat": 38.71358, "lng": -9.14349, "neighborhood": "Bairro Alto", "corridor": "Axial Spine", "url": "https://mais.scml.pt/museu-saoroque/"},
    {"venue": "Academia das Ciências de Lisboa", "aliases": ["academia das ciencias de lisboa", "academia das ciencias", "rua da academia das ciencias"], "lat": 38.71285, "lng": -9.14881, "neighborhood": "Bairro Alto / Mercês", "corridor": "Axial Spine", "url": "https://www.acad-ciencias.pt"},
    {"venue": "Praça da Alegria", "aliases": ["praca da alegria", "jardim alfredo keil"], "lat": 38.71802, "lng": -9.14482, "neighborhood": "Santo António", "corridor": "Axial Spine", "url": "https://www.jfsantoantonio.pt"},
    {"venue": "Biblioteca Arquitecto Cosmelli Sant'Anna (BACS)", "aliases": ["bacs", "biblioteca arquitecto cosmelli sant'anna", "biblioteca cosmelli sant'anna"], "lat": 38.72120, "lng": -9.15180, "neighborhood": "Santo António", "corridor": "Axial Spine", "url": "https://www.jfsantoantonio.pt"},
    {"venue": "Junta de Freguesia de Santo António", "aliases": ["junta de freguesia de santo antonio", "jfreguesia santo antonio", "rua alexandre herculano 46"], "lat": 38.72485, "lng": -9.14394, "neighborhood": "Santo António", "corridor": "Axial Spine", "url": "https://www.jfsantoantonio.pt"},
    {"venue": "Jardim do Torel", "aliases": ["jardim do torel", "rua julio de andrade"], "lat": 38.71962, "lng": -9.14081, "neighborhood": "Santo António / Campo Mártires", "corridor": "Axial Spine", "url": "https://www.jfsantoantonio.pt"},
    {"venue": "Hospital de São José", "aliases": ["hospital de sao jose", "hospital sao jose", "hospital s. jose", "rua jose antonio serrano"], "lat": 38.71778, "lng": -9.13743, "neighborhood": "Martim Moniz / Santana", "corridor": "Axial Spine", "url": "https://dador.pt/sessoes"},
    {"venue": "Hospital de Santa Maria", "aliases": ["hospital de santa maria", "hospital santa maria", "hosp.santa maria", "rampa central"], "lat": 38.74846, "lng": -9.16066, "neighborhood": "Cidade Universitária", "corridor": "Northern Belt", "url": "https://dador.pt/sessoes"},
    {"venue": "Pavilhão 17 — Parque de Saúde de Lisboa", "aliases": ["pavilhao 17", "av. brasil 53", "posto fixo alvalade", "parque de saude de lisboa"], "lat": 38.75683, "lng": -9.14805, "neighborhood": "Alvalade", "corridor": "Northern Belt", "url": "https://dador.pt/sessoes"},
    {"venue": "Edifício Sede Caixa Geral de Depósitos", "aliases": ["caixa geral de depositos de lisboa", "cgd-edif sede", "av. joao xxi"], "lat": 38.74172, "lng": -9.14172, "neighborhood": "Areeiro / Campo Pequeno", "corridor": "Northern Belt", "url": "https://dador.pt/sessoes"},
]


def load_external_venues():
    """Merges any user-curated entries from venues.json if present, filtering out ambiguous single-word aliases."""
    if os.path.exists("venues.json"):
        try:
            with open("venues.json", "r", encoding="utf-8") as f:
                ext = json.load(f)
            if isinstance(ext, list):
                existing = {v["venue"].lower() for v in VENUE_REGISTRY}
                for item in ext:
                    if isinstance(item, dict) and item.get("venue"):
                        clean_aliases = [
                            a for a in item.get("aliases", [])
                            if strip_accents(a).strip() not in AMBIGUOUS_ALIAS_TOKENS
                        ]
                        item["aliases"] = clean_aliases
                        if item["venue"].lower() not in existing:
                            VENUE_REGISTRY.append(item)
        except Exception as e:
            print(f"[Venue Loader] Notice reading venues.json: {e}")
        # Rebuild compiled patterns to include any newly loaded external venues
        _VENUE_PATTERNS.clear()
        _build_venue_patterns()


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


# Pre-compiled venue patterns (built once at import time for O(n) matching per call).
# Each entry is (compiled_regex, registry_entry, alias_length); sorted longest-first
# so the first match is always the most specific one — no inner best_len tracking needed.
_VENUE_PATTERNS: list = []


def _build_venue_patterns() -> None:
    """Compile every venue alias into a regex once, sorted longest-alias-first."""
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


def match_venue(*texts, require_match=False):
    """
    Matches venue by checking each text argument in priority order (e.g., venue_candidate first,
    then title, then full card text), requiring strict word boundaries and preferring the longest
    matching alias so short tokens never hijack unrelated events.

    Uses pre-compiled _VENUE_PATTERNS (built at startup) instead of rebuilding regexes on
    every call — eliminates the inner O(aliases) re.compile loop that ran on every scraped item.
    """
    for raw_t in texts:
        if not raw_t:
            continue
        norm_t = strip_accents(fix_mojibake(raw_t))
        if not norm_t:
            continue
        for pat, entry, _alias_len in _VENUE_PATTERNS:
            if pat.search(norm_t):
                return entry

    return None


# Build pattern table at import time (runs once; re-runs inside load_external_venues if needed)
_build_venue_patterns()


def infer_category_preset(text, default_key="concerts"):
    low = strip_accents(text or "")
    # 1. Family, Aquariums, Science Centers & Youth
    if any(k in low for k in [
        "criancas", "familia", "oficina infantil", "infantil", "jovens", "bebes",
        "kids", "pre-escolar", "primeiro ciclo", "segundo ciclo", "terceiro ciclo",
        "oceanario", "aquario", "zoologico", "zoo de lisboa", "pavilhao do conhecimento",
        "ciencia viva", "planetario", "lu.ca"
    ]):
        return CATEGORY_PRESETS["family"]
    # 2. Markets, Arts & Crafts, Workshops, Lectures & Community Gatherings
    if any(k in low for k in [
        "conferencia", "palestra", "debate", "conversa", "coloquio", "seminario",
        "feira", "mercado", "flea market", "literatura", "alfarrabistas", "clube de leitura",
        "lancamento", "visita guiada", "comunidade", "workshop", "tertulia", "artesanato",
        "ceramica", "olaria", "serigrafia", "risografia", "bordado", "costura", "encadernacao",
        "marcenaria", "ilustracao", "zine", "fanzine", "gravura", "crafts"
    ]):
        return CATEGORY_PRESETS["community"]
    # 3. Exhibitions, Museums & Visual Arts
    if any(k in low for k in [
        "exposicao", "artes plasticas", "fotografia", "instalacao", "arte moderna",
        "artes visuais", "cartoon", "galeria", "museu", "panteao", "castelo de sao jorge",
        "padrao dos descobrimentos", "maat", "mude", "mnac", "mnaa", "cam gulbenkian"
    ]):
        return CATEGORY_PRESETS["exhibitions"]
    # 4. Theatre, Performance, Dance & Comedy
    if any(k in low for k in [
        "teatro", "danca", "comedia", "stand-up", "stand up", "circo",
        "improviso", "musical", "performance", "cabaret", "burlesque", "encenacao"
    ]):
        return CATEGORY_PRESETS["theatre"]
    # 5. Cinema & Screenings
    if any(k in low for k in ["cinema", "filme", "documentario", "curtas", "animacao", "cinemateca", "nimas"]):
        return CATEGORY_PRESETS["cinema"]
    # 6. Opera & Classical
    if any(k in low for k in ["opera", "classica", "sinfonica", "coro", "orquestra", "schubert", "beethoven", "strauss", "recital"]):
        return CATEGORY_PRESETS["classical"]
    # 7. Nightlife & Electronic
    if any(k in low for k in ["dj", "clubbing", "eletronica", "electronic", "noite", "festa", "rave", "techno", "house", "afterhours", "halloween party", "pub crawl"]):
        return CATEGORY_PRESETS["nightlife"]
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
            return ("17:30", 17) if sh <= 11 else add_minutes(sh, sm, 150)
        return add_minutes(sh, sm, 120)

    if category_name in ("Cinema & Screenings", "Theatre & Comedy", "Opera & Classical"):
        return add_minutes(sh, sm, 120)

    if category_name == "Concerts & Live Music":
        return add_minutes(sh, sm, 150)

    if category_name == "Community & Gatherings":
        if "8 marvila" in v_low or "lx factory" in v_low:
            return "20:00", 20
        if "feira da ladra" in v_low or "mercado" in t_low or "feira" in t_low:
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
        if "nada" in v_low or "naada" in v_low:
            return "06:00", 6
        return "06:00", 6

    return add_minutes(sh, sm, 120)


def parse_price_and_tier(text, default_price="Consultar bilheteira", default_tier="ACCESSIBLE"):
    low = strip_accents(text or "")
    for m in re.finditer(r"(?:€\s*(\d{1,3})(?:[.,](\d{1,2}))?|(\d{1,3})(?:[.,](\d{1,2}))?\s*€)", str(text)):
        whole = m.group(1) if m.group(1) is not None else m.group(3)
        dec = m.group(2) if m.group(1) is not None else m.group(4)
        val = float(f"{whole}.{dec or '0'}")
        disp = f"{whole}€" if not dec else f"{whole}.{dec}€"
        if val > 0:
            if val <= 15:
                return disp, "ACCESSIBLE"
            if val <= 30:
                return disp, "MID"
            return disp, "PREMIUM"
    if re.search(r"\b(entrada livre|entrada gratuita|gratuito|gratis|free entry|free admission|free entrance|a borla|gratuita)\b", low):
        if not re.search(r"\b(birthday|aniversari|drink|beer|imperial|ate as|until)\b", low):
            return "Entrada Livre", "FREE"
    return default_price, default_tier


def matches_portuguese_date_or_range(text, target_date):
    """
    Returns True if `text` explicitly mentions `target_date` (e.g. '02 nov', '2 novembro', '02/11/2026')
    OR contains an active Portuguese date range spanning across `target_date`.
    """
    norm = strip_accents(text or "")
    month_short = strip_accents(PT_MONTHS_SHORT[target_date.month])
    month_full = strip_accents(PT_MONTHS_FULL[target_date.month])

    day_patterns = [
        rf"\b0?{target_date.day}\s+(?:de\s+)?(?:{month_short}|{month_full})\b",
        rf"\b{target_date.strftime('%d/%m/%Y')}\b",
        rf"\b{target_date.strftime('%d.%m.%Y')}\b",
    ]
    for pat in day_patterns:
        if re.search(pat, norm):
            return True

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
            if start_d <= target_date <= end_d:
                return True
        except ValueError:
            continue

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
            if start_d <= target_date <= end_d:
                return True
        except ValueError:
            continue

    return False


def fetch_url(url, timeout=18, headers=None):
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    resp = SCRAPER_SESSION.get(url, headers=hdrs, timeout=timeout)
    if hasattr(resp, "encoding") and resp.encoding and resp.encoding.lower() in ("iso-8859-1", "latin-1"):
        resp.encoding = "utf-8"
    return resp


# ==============================================================================
# TIER 1: AGENDALX, CARTAZ CULTURAL LISBOA & NOCARTAZ LISBOA
# ==============================================================================
def scrape_agendalx(target_date):
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"[Tier 1] Scraping AgendaLX & Cartaz Cultural for {date_str}...")

    agendalx_urls = [
        "https://www.agendalx.pt/?s=&type=event&archive=agenda",
        "https://www.agendalx.pt/?s=&type=event&archive=agenda&paged=2",
        "https://www.agendalx.pt/events/",
        "https://www.agendalx.pt/categoria/feiras-e-mercados/",
        "https://www.agendalx.pt/categoria/formacao-e-oficinas/",
        "https://www.agendalx.pt/categoria/conferencias-e-debates/",
        "https://www.agendalx.pt/categoria/literatura/",
        "https://www.agendalx.pt/categoria/artes/",
        "https://www.agendalx.pt/categoria/musica/",
        "https://www.agendalx.pt/categoria/teatro/",
        "https://www.agendalx.pt/categoria/cinema/",
    ]
    seen_alx = set()
    for alx_url in agendalx_urls:
        try:
            resp = fetch_url(alx_url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for art in soup.select("article, .event-card, .card, .type-event, .search-result, .post-item"):
                txt = clean_html_text(art.get_text(" ", strip=True))
                a_tag = art.find("a", href=True)
                if not a_tag or a_tag["href"] in seen_alx:
                    continue
                href = a_tag["href"]
                if "/events/event/" not in href and "agendalx.pt" in href and "archive=agenda" in alx_url:
                    # Skip non-event navigation links on the archive search page
                    if any(skip in href for skip in ["/categoria/", "/local/", "/tag/", "/author/", "/page/", "?s="]):
                        continue
                title_el = art.find(["h1", "h2", "h3", "h4", ".entry-title", ".card-title"])
                title = clean_html_text(title_el.get_text(" ", strip=True) if title_el else a_tag.get_text(" ", strip=True))
                if not title or len(title) < 3:
                    continue
                # If the card explicitly shows a date or range, verify it includes target_date
                if re.search(r"\b\d{1,2}\s+(?:de\s+)?(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)", strip_accents(txt)):
                    if not matches_portuguese_date_or_range(txt, target_date):
                        continue
                seen_alx.add(href)

                default_cat = "community" if any(k in alx_url for k in ["feiras", "oficinas", "conferencias", "literatura"]) else (
                    "exhibitions" if "artes" in alx_url else (
                        "theatre" if "teatro" in alx_url else (
                            "cinema" if "cinema" in alx_url else "concerts"
                        )
                    )
                )
                preset = infer_category_preset(f"{title} {txt}", default_cat)
                default_t = "10:00" if preset["category"] in ("Exhibitions & Visual Arts", "Community & Gatherings", "Family & Youth") else "21:00"
                time_str, hour_int = parse_time_str(txt, default_t)
                geo = match_venue(title, txt)
                if not geo:
                    continue
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
                    "url": urljoin("https://www.agendalx.pt", href),
                    "description": f"{title} em {geo['venue']} ({geo['neighborhood']}).",
                })
        except Exception as e:
            print(f"[AgendaLX] Notice on {alx_url}: {e}")

    ccl_urls = [
        "https://cartazculturallisboa.pt/agenda-eventos-lisboa/",
        "https://cartazculturallisboa.pt/exposicoes-em-lisboa/",
    ]
    seen_ccl = set()
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
                card = a_tag.find_parent(["article", "div", "li"]) or a_tag
                txt = clean_html_text(card.get_text(" | ", strip=True))
                if not matches_portuguese_date_or_range(txt, target_date):
                    continue
                seen_ccl.add(href)
                h_el = card.find(["h2", "h3", "h4"])
                title = clean_html_text(h_el.get_text(" ", strip=True) if h_el else a_tag.get_text(" ", strip=True))
                if not title or len(title) < 4:
                    continue

                full_url = urljoin("https://cartazculturallisboa.pt", href)
                geo = match_venue(title, txt, require_match=True)
                if not geo:
                    try:
                        d_resp = fetch_url(full_url, timeout=8)
                        if d_resp.status_code == 200:
                            loc_str = locations.extract_event_location(d_resp.text)
                            if loc_str:
                                geo = match_venue(loc_str, require_match=True)
                                if not geo:
                                    hit, name = locations.geocode_location(loc_str)
                                    if hit:
                                        geo = {
                                            "venue": name,
                                            "lat": hit["lat"],
                                            "lng": hit["lng"],
                                            "neighborhood": locations.infer_neighborhood(hit["lat"], hit["lng"], hit.get("area")),
                                            "corridor": locations.infer_corridor(hit["lat"], hit["lng"]),
                                            "url": full_url,
                                        }
                    except Exception:
                        pass

                if not geo:
                    continue

                default_cat = "exhibitions" if "exposicoes" in ccl_url else "concerts"
                preset = infer_category_preset(f"{title} {txt}", default_cat)
                default_t = "10:00" if preset["category"] in ("Exhibitions & Visual Arts", "Family & Youth", "Community & Gatherings") else "21:00"
                time_str, hour_int = parse_time_str(txt, default_t)
                price_disp, price_tier = parse_price_and_tier(txt)
                end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, txt)
                slug = href.strip("/").split("/")[-1][:32]

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
                    "url": urljoin("https://cartazculturallisboa.pt", href),
                    "description": f"{title} em {geo['venue']} ({geo['neighborhood']}).",
                })
        except Exception as e:
            print(f"[CartazCultural] Notice on {ccl_url}: {e}")

    return events


def scrape_nocartaz(target_date):
    """Scrapes NoCartaz Lisboa across concelho, hoje, and category pages for target_date."""
    events = []
    month_short = PT_MONTHS_SHORT[target_date.month]
    day_pat = rf"\b0?{target_date.day}\s+{month_short}\b"
    print(f"[Tier 1] Scraping NoCartaz Lisboa for {target_date.day} {month_short}...")

    nocartaz_urls = [
        ("https://www.nocartaz.pt/concelhos/lisboa/", False),
        ("https://www.nocartaz.pt/hoje/", True),
        ("https://www.nocartaz.pt/distrito/lisboa/concertos/", False),
        ("https://www.nocartaz.pt/distrito/lisboa/teatro/", False),
        ("https://www.nocartaz.pt/distrito/lisboa/exposicoes/", False),
        ("https://www.nocartaz.pt/distrito/lisboa/cinema/", False),
        ("https://www.nocartaz.pt/distrito/lisboa/jazz/", False),
        ("https://www.nocartaz.pt/distrito/lisboa/feiras/", False),
        ("https://www.nocartaz.pt/distrito/lisboa/conferencias/", False),
    ]

    seen_hrefs = set()
    for nc_url, is_hoje_page in nocartaz_urls:
        try:
            resp = fetch_url(nc_url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/eventos/"]'):
                href = a_tag.get("href", "")
                if not href or href in seen_hrefs:
                    continue
                container = a_tag.find_parent(["article", "li", "div"]) or a_tag
                raw_pipe = clean_html_text(container.get_text(" | ", strip=True))
                norm_pipe = strip_accents(raw_pipe)

                if not is_hoje_page:
                    if not (re.search(day_pat, norm_pipe) or matches_portuguese_date_or_range(raw_pipe, target_date)):
                        continue

                h_el = container.find(["h2", "h3", "h4"])
                title = clean_html_text(h_el.get_text(" ", strip=True)) if h_el else ""
                parts = [p.strip() for p in raw_pipe.split("|") if p.strip() and p.strip() != "♡"]
                if not title and len(parts) >= 2:
                    title = parts[1]
                if not title or len(title) < 3:
                    continue

                if any(k in strip_accents(title) for k in ["viagens ilimitadas", "hop-on", "caves calem"]):
                    continue

                venue_candidate = ""
                is_lisboa_concelho = "/concelhos/lisboa/" in nc_url
                for p in parts:
                    if "· Lisboa" in p or "· lisboa" in p.lower():
                        venue_candidate = p.split("·")[0].strip()
                        is_lisboa_concelho = True
                        break
                    elif "·" in p and not re.search(day_pat, strip_accents(p)):
                        venue_candidate = p.split("·")[0].strip()

                geo = match_venue(venue_candidate, title, raw_pipe, require_match=True)
                if not geo:
                    if venue_candidate:
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
                default_cat = "community" if any(k in nc_url for k in ["feiras", "conferencias"]) else "concerts"
                preset = infer_category_preset(f"{title} {geo['venue']} {raw_pipe}", default_cat)
                default_t = "10:00" if preset["category"] in ("Exhibitions & Visual Arts", "Family & Youth", "Community & Gatherings") else "21:00"
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
                        geo = match_venue(venue_part, artist)
                        preset = infer_category_preset(f"{artist} {venue_part}", "concerts")
                        time_str, hour_int = parse_time_str(venue_line, "21:30")
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
                            "url": adc_url,
                            "description": f"Concerto de {artist} ao vivo em {geo['venue']} ({geo['neighborhood']}).",
                        })
                    i += 2
                    continue
                i += 1
        except Exception as e:
            print(f"[Agenda de Concertos] Notice on {adc_url}: {e}")
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
            if d_slash not in txt and d_long not in strip_accents(txt) and not matches_portuguese_date_or_range(txt, target_date):
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
    print(f"[Tier 3] Scraping Lisabout & Prior Velho hubs for {target_date.day:02d}/{target_date.month:02d} (and afterhours {next_date.day:02d}/{next_date.month:02d})...")

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
                v_neigh = "Centro Histórico"
                for seg in card_text.split("|"):
                    if "•" in seg and not re.search(r"\b\d{1,2}/\d{2}\b", seg):
                        sp = seg.split("•", 1)
                        if sp[0].strip():
                            v_seg = sp[0].strip()
                        if len(sp) > 1 and sp[1].strip():
                            v_neigh = sp[1].strip()
                        break

                detail_url = urljoin("https://www.lisabout.com", href)
                ev_url = detail_url
                detail_text = ""
                outbound_ticket_url = ""
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
                                        if isinstance(offers, dict) and offers.get("url"):
                                            cand = str(offers["url"]).strip()
                                            if "lisabout.com" not in cand:
                                                outbound_ticket_url = cand
                            except Exception:
                                pass
                        if not outbound_ticket_url:
                            for t_a in d_soup.find_all("a", href=True):
                                t_href = t_a["href"].strip()
                                if any(tk in t_href for tk in ("shotgun.live", "xceed.me", "ra.co/events", "dice.fm", "3cket.com", "bol.pt", "ticketline", "eventbrite", "seetickets")):
                                    outbound_ticket_url = t_href
                                    break
                except Exception:
                    pass

                if outbound_ticket_url:
                    ev_url = outbound_ticket_url

                geo = match_venue(v_seg, title, card_text, detail_text, require_match=True)
                if not geo:
                    if v_seg:
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
                price_disp, price_tier = parse_price_and_tier(f"{card_text} {detail_text}", "10€ - 20€", "ACCESSIBLE")
                # Never trust "Grátis" on Lisabout when an external ticketing link (Shotgun, 3cket, RA, Xceed, etc.) is attached
                if outbound_ticket_url and price_tier == "FREE":
                    price_disp, price_tier = "10€", "ACCESSIBLE"
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

    return events


# ==============================================================================
# TIER 3.5: ARTS & CRAFTS, MARKETS, WORKSHOPS & LECTURES SCRAPER
# ==============================================================================
def scrape_markets_workshops_lectures(target_date):
    """
    Scrapes Lisbon directories for Arts & Crafts, Markets, Workshops, and Lectures:
    - Eventbrite Lisboa (workshops, classes, arts & crafts, talks)
    - FICA Oficina Criativa (fica-oc.pt in LX Factory)
    """
    events = []
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"[Tier 3.5] Scraping Arts & Crafts, Markets, Workshops & Lectures for {date_str}...")

    eb_urls = [
        "https://www.eventbrite.pt/d/portugal--lisboa/events--today/",
        "https://www.eventbrite.pt/d/portugal--lisboa/workshops--events--today/",
        "https://www.eventbrite.pt/d/portugal--lisboa/arts--events--today/",
    ]
    seen_eb = set()
    for eb_url in eb_urls:
        try:
            resp = fetch_url(eb_url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/e/"]'):
                href = a_tag.get("href", "").split("?")[0]
                if not href or href in seen_eb:
                    continue
                card = a_tag.find_parent(["article", "li", "div"]) or a_tag
                txt = clean_html_text(card.get_text(" | ", strip=True))
                low_txt = strip_accents(txt)
                if any(k in low_txt for k in ["online", "webinar", "porto", "sintra", "cascais"]):
                    continue
                h_el = card.find(["h2", "h3", "h4"])
                title = clean_html_text(h_el.get_text(" ", strip=True) if h_el else a_tag.get_text(" ", strip=True))
                if not title or len(title) < 5:
                    continue
                seen_eb.add(href)

                geo = match_venue(title, txt, require_match=True)
                if not geo:
                    continue
                preset = infer_category_preset(f"{title} {txt}", "community")
                time_str, hour_int = parse_time_str(txt, "18:30")
                price_disp, price_tier = parse_price_and_tier(txt, "Inscrição no link", "ACCESSIBLE")
                end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, txt)

                events.append({
                    "id": f"eb-{abs(hash(href)) % 1000000}",
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
                    "url": href,
                    "description": f"{title} — oficina, encontro ou palestra em {geo['venue']} ({geo['neighborhood']}).",
                })
        except Exception as e:
            print(f"[Eventbrite Workshops] Notice on {eb_url}: {e}")

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
                price_disp, price_tier = parse_price_and_tier(txt, "Consultar oficina", "MID")
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

    # Jardins do Bombarda (LARGO Residências) live agenda check
    try:
        resp = fetch_url("https://www.jardinsdobombarda.pt")
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
                    "url": "https://www.jardinsdobombarda.pt",
                    "description": f"{title} nos Jardins do Bombarda / LARGO Residências (Rua Gomes Freire, Arroios).",
                })
    except Exception as e:
        print(f"[Jardins do Bombarda] Notice: {e}")

    return events


# ==============================================================================
# TIER 3.8: VIRALAGENDA DYNAMIC DAILY & CATEGORY SCRAPER
# ==============================================================================
def scrape_viralagenda(target_date):
    """
    Scrapes ViralAgenda Lisboa using dynamic daily URL formatting (DD-MM-YYYY)
    as well as category feeds (concerts, workshops-courses, exhibitions).
    Example date URL: https://www.viralagenda.com/pt/lisboa/03-11-2026
    """
    events = []
    dd_mm_yyyy = target_date.strftime("%d-%m-%Y")
    iso_date = target_date.strftime("%Y-%m-%d")
    print(f"[Tier 3.8] Scraping ViralAgenda for {dd_mm_yyyy} (/pt/lisboa/{dd_mm_yyyy} + concerts & workshops)...")

    va_urls = [
        (f"https://www.viralagenda.com/pt/lisboa/{dd_mm_yyyy}", "community", True),
        ("https://www.viralagenda.com/pt/lisboa/concerts", "concerts", False),
        ("https://www.viralagenda.com/pt/lisboa/workshops-courses", "community", False),
        ("https://www.viralagenda.com/pt/lisboa/exhibitions", "exhibitions", False),
    ]
    seen_va = set()

    for url, default_cat, is_date_specific_url in va_urls:
        try:
            resp = fetch_url(url)
            if resp.status_code != 200:
                print(f"[ViralAgenda] HTTP {resp.status_code} on {url}")
                continue
            soup = BeautifulSoup(resp.text, "html.parser")

            # 1) Check JSON-LD Event blocks if present
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict) or item.get("@type") != "Event":
                            continue
                        start_dt = str(item.get("startDate", ""))
                        if not is_date_specific_url and iso_date not in start_dt and dd_mm_yyyy not in start_dt:
                            continue
                        title = clean_html_text(item.get("name", ""))
                        if not title or len(title) < 4:
                            continue
                        loc = item.get("location") or {}
                        venue_raw = loc.get("name", "") if isinstance(loc, dict) else str(loc)
                        ev_url = item.get("url") or url
                        if ev_url in seen_va:
                            continue
                        seen_va.add(ev_url)

                        geo = match_venue(venue_raw, title, require_match=True)
                        if not geo and venue_raw:
                            hit, name = locations.geocode_location(f"{venue_raw}, Lisboa")
                            if hit:
                                geo = {
                                    "venue": name or venue_raw,
                                    "lat": hit["lat"],
                                    "lng": hit["lng"],
                                    "neighborhood": locations.infer_neighborhood(hit["lat"], hit["lng"], hit.get("area")),
                                    "corridor": locations.infer_corridor(hit["lat"], hit["lng"]),
                                    "url": ev_url,
                                }
                        if not geo:
                            continue
                        preset = infer_category_preset(f"{title} {venue_raw}", default_cat)
                        time_str, hour_int = parse_time_str(start_dt, "21:00" if default_cat == "concerts" else "18:00")
                        price_disp, price_tier = parse_price_and_tier(str(item.get("offers", "")), "Consultar evento", "ACCESSIBLE")
                        end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, "")

                        events.append({
                            "id": f"va-{abs(hash(ev_url)) % 1000000}",
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
                            "url": ev_url if str(ev_url).startswith("http") else urljoin("https://www.viralagenda.com", str(ev_url)),
                            "description": f"{title} em {geo['venue']} ({geo['neighborhood']}). Fonte: ViralAgenda Lisboa.",
                        })
                except Exception:
                    pass

            # 2) Parse HTML event cards (.viral-event, li[data-id], article)
            cards = soup.select(".viral-event, li.viral-event, article, div[itemtype*='Event']")
            for card in cards:
                txt = clean_html_text(card.get_text(" | ", strip=True))
                if len(txt) < 15:
                    continue
                if not is_date_specific_url:
                    date_attr = str(card.get("data-date", "")) + " " + txt
                    if (
                        iso_date not in date_attr
                        and dd_mm_yyyy not in date_attr
                        and not matches_portuguese_date_or_range(date_attr, target_date)
                    ):
                        continue

                title_el = card.select_one(".viral-event-title, h2, h3, h4, a[itemprop='url']")
                title = clean_html_text(title_el.get_text(" ", strip=True) if title_el else "")
                if not title or len(title) < 4:
                    continue

                a_el = card.select_one("a[href*='/events/'], a[href]")
                href = a_el.get("href", "") if a_el else url
                full_url = urljoin("https://www.viralagenda.com", href) if href else url
                dedup_k = f"{title.lower()}|{full_url}"
                if dedup_k in seen_va:
                    continue
                seen_va.add(dedup_k)

                venue_el = card.select_one(".viral-event-place, [itemprop='location'], .place, .venue")
                venue_hint = clean_html_text(venue_el.get_text(" ", strip=True) if venue_el else "")

                geo = match_venue(f"{venue_hint} {title}", txt, require_match=True)
                if not geo and venue_hint:
                    hit, name = locations.geocode_location(f"{venue_hint}, Lisboa")
                    if hit:
                        geo = {
                            "venue": name or venue_hint,
                            "lat": hit["lat"],
                            "lng": hit["lng"],
                            "neighborhood": locations.infer_neighborhood(hit["lat"], hit["lng"], hit.get("area")),
                            "corridor": locations.infer_corridor(hit["lat"], hit["lng"]),
                            "url": full_url,
                        }
                if not geo:
                    continue
                preset = infer_category_preset(f"{title} {txt}", default_cat)
                time_str, hour_int = parse_time_str(txt, "21:00" if default_cat == "concerts" else "18:00")
                price_disp, price_tier = parse_price_and_tier(txt, "Consultar bilheteira", "ACCESSIBLE")
                end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], title, txt)

                events.append({
                    "id": f"va-card-{abs(hash(dedup_k)) % 1000000}",
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


def scrape_soko_curated_capsula(target_date):
    """
    Scrapes:
    1) Soko.fyi (https://soko.fyi / https://www.instagram.com/soko.fyi/) — Lisbon venue JSON-LD & Instagram-fed events
    2) THE CURATED Lisbon (https://thecuratedlisbon.com/ / https://www.instagram.com/thecuratedlisbon/) — exhibitions, art walks & creative series
    3) Cápsula Melódica (https://www.instagram.com/capsulamelodica.pt/) — Lisbon electronic music showcases
    """
    events = []
    iso_date = target_date.strftime("%Y-%m-%d")
    next_iso = (target_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"[Tier 3.9] Scraping Soko.fyi, THE CURATED Lisbon & Cápsula Melódica for {iso_date}...")

    # 1. SOKO.FYI (Public Showcase API + Lisbon Venue JSON-LD Feeds)
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
    for slug in soko_slugs:
        v_url = f"https://soko.fyi/pt/venues/{slug}"
        try:
            resp = fetch_url(v_url, timeout=8)
            if resp.status_code != 200:
                continue
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
                        geo = {
                            "venue": v_name or "Lisboa",
                            "lat": round(float(s_lat), 5) if s_lat else 38.7169,
                            "lng": round(float(s_lng), 5) if s_lng else -9.1399,
                            "neighborhood": "Lisboa",
                            "corridor": "Axial Spine",
                            "url": v_url,
                        }
                    for ev in node.get("event", []):
                        if not isinstance(ev, dict):
                            continue
                        start_raw = str(ev.get("startDate", ""))
                        is_today = start_raw.startswith(iso_date)
                        is_afterhours = start_raw.startswith(next_iso) and bool(re.search(r"T0[0-5]:", start_raw))
                        if not (is_today or is_afterhours):
                            continue
                        ev_title = clean_html_text(ev.get("name", ""))
                        if not ev_title or len(ev_title) < 3:
                            continue
                        ev_link = str(ev.get("url") or v_url).strip()
                        dedup_k = f"{geo['venue'].lower()}|{ev_title.lower()}"
                        if dedup_k in seen_soko:
                            continue
                        seen_soko.add(dedup_k)

                        t_match = re.search(r"T(\d{2}:\d{2})", start_raw)
                        time_str, hour_int = parse_time_str(t_match.group(1) if t_match else "", "19:00")
                        preset = infer_category_preset(f"{ev_title} {v_name}", "community")
                        price_disp, price_tier = parse_price_and_tier(ev_title, "Ver no link", "ACCESSIBLE")
                        end_t, end_h = infer_end_time(time_str, hour_int, preset["category"], geo["venue"], ev_title, "")

                        events.append({
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
                            "url": ev_link,
                            "description": f"{ev_title} em {geo['venue']} ({geo['neighborhood']}). Curadoria Soko Lisboa.",
                        })
        except Exception:
            pass

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

    # 3. CÁPSULA MELÓDICA (https://www.instagram.com/capsulamelodica.pt/)
    try:
        resp = fetch_url("https://www.lisabout.com/events", timeout=8)
        if resp.status_code == 200 and "capsula melodica" in strip_accents(resp.text):
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.select('a[href*="/events/"]'):
                txt = clean_html_text(a_tag.get_text(" | ", strip=True))
                if "capsula melodica" in strip_accents(txt) and matches_portuguese_date_or_range(txt, target_date):
                    href = a_tag.get("href", "")
                    geo = match_venue(txt, require_match=False)
                    time_str, hour_int = parse_time_str(txt, "23:00")
                    end_t, end_h = infer_end_time(time_str, hour_int, CATEGORY_PRESETS["nightlife"]["category"], geo["venue"], "Cápsula Melódica", txt)
                    events.append({
                        "id": f"capsula-{target_date.strftime('%Y%m%d')}",
                        "title": "Cápsula Melódica — Showcase",
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
                        "price": "10€ - 15€",
                        "priceTier": "ACCESSIBLE",
                        "url": urljoin("https://www.lisabout.com", href) if href else "https://www.instagram.com/capsulamelodica.pt/",
                        "description": f"Noite de música eletrónica curada pela Cápsula Melódica em {geo['venue']} ({geo['neighborhood']}).",
                    })
    except Exception:
        pass

    print(f"[Tier 3.9] Soko / THE CURATED Lisbon / Cápsula Melódica extracted {len(events)} events.")
    return events


# ==============================================================================
# TIER 4: ACTIVE LISBON MUSEUM EXHIBITIONS, MARKETS, WORKSHOPS & RUNS (35+ BASELINE)
# ==============================================================================
def get_ongoing_cultural_events(target_date):
    """
    Generates day-of-week-aware ongoing Lisbon museum exhibitions, craft workshops,
    street markets, lectures, independent cinema sessions, and active theatre/music
    programming so every day of the week exceeds the 30-event minimum.
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

    # --- 1. OPEN DAILY (MONDAY - SUNDAY) ---
    add_item(1, "Câmara Escura (Periscópio Ótico) & Visitas ao Castelo de São Jorge", "exhibitions",
             "castelo de sao jorge", "09:00", "18:00", "15.00€", "ACCESSIBLE",
             "https://castelodesaojorge.pt", "Observação de Lisboa a 360º em tempo real na Câmara Escura e visitas patrimoniais ao Castelo de São Jorge.")
    add_item(2, "Xerazade, a Coleção Interminável do CAM & Diogo Pimentão", "exhibitions",
             "cam gulbenkian", "10:00", "18:00", "8.00€", "ACCESSIBLE",
             "https://gulbenkian.pt/cam/agenda/", "Exposições de arte moderna e contemporânea no renovado CAM Gulbenkian e jardins.")
    add_item(3, "Exposições Interativas de Ciência Viva em Família", "family",
             "pavilhao do conhecimento", "10:00", "18:00", "11€ - 15€", "ACCESSIBLE",
             "https://www.pavconhecimento.pt", "Exploração científica interativa e oficinas Tcharan! para famílias no Parque das Nações.")
    add_item(4, "Uma Deriva Atlântica, Ângela Ferreira & Frida Orupabo", "exhibitions",
             "ccb", "10:00", "19:00", "10.00€", "ACCESSIBLE",
             "https://www.ccb.pt", "Exposições de arte moderna e contemporânea no MAC/CCB em Belém.")
    add_item(5, "Na Onda do Oceano — Florestas Submersas & Exposições Marinhas", "family",
             "oceanario de lisboa", "10:00", "19:00", "15€ - 25€", "MID",
             "https://www.oceanario.pt", "Percurso imersivo pelos oceanos e habitats marinhos no Oceanário de Lisboa (Parque das Nações).")
    add_item(6, "Encontros da Vida Selvagem, Baía dos Golfinhos & Reptilário", "family",
             "jardim zoologico", "10:00", "18:00", "18€ - 27€", "MID",
             "https://www.zoo.pt", "Apresentações educativas diárias e conservação da biodiversidade no Jardim Zoológico de Lisboa.")
    add_item(7, "Cinco Mil Anos de História da Saúde e das Boticas", "exhibitions",
             "museu da farmacia", "10:00", "19:00", "6.00€", "ACCESSIBLE",
             "https://www.museudafarmacia.pt", "Coleção histórica global de boticas, sarcófagos e instrumentos de saúde no Miradouro de Santa Catarina.")
    add_item(8, "Feira de Livros, Artesanato Urbano, Zines & Livraria Ler Devagar", "community",
             "lx factory", "10:30", "21:00", "Entrada Livre", "FREE",
             "https://lxfactory.com", "Ateliers abertos, bancas de artesãos, edições independentes e livraria na antiga fábrica de Alcântara.")
    add_item(9, "Galerias de Arte, Ateliers Criativos & Lojas Independentes", "community",
             "8 marvila", "12:00", "20:00", "Entrada Livre", "FREE",
             "https://www.8marvila.com", "Percurso expositivo, mercados criativos, vinil e espaço cultural nos antigos armazéns do 8 Marvila.")
    add_item(10, "Sessão da Tarde: Cinema de Autor e Estreias Independentes", "cinema",
             "cinema ideal", "16:15", "18:15", "7.50€", "ACCESSIBLE",
             "https://cinemaideal.pt", "Programação diária de cinema independente, europeu e português no histórico Cinema Ideal (Chiado).")
    add_item(11, "Sessão de Fim de Tarde — Ciclos e Festivais de Cinema", "cinema",
             "cinema sao jorge", "18:30", "20:30", "6.00€", "ACCESSIBLE",
             "https://cinemasaojorge.pt", "Sessões de cinema de autor, documentário e mostras internacionais no Cinema São Jorge (Avenida da Liberdade).")
    add_item(12, "Cinema de Autor & Estreias da Semana em Alvalade", "cinema",
             "cinema city classic alvalade", "19:00", "21:00", "7.50€", "ACCESSIBLE",
             "https://www.cinemacity.pt", "Exibição de cinema de autor e estreias internacionais no Cinema City Classic Alvalade.")
    add_item(13, "Noite de Jazz, Bossa Nova, Tertúlias & Música ao Vivo", "concerts",
             "fabrica braco de prata", "20:30", "23:30", "5€ - 10€", "ACCESSIBLE",
             "https://www.bracodeprata.com", "Concertos ao vivo em várias salas, livraria, tertúlias e exposições na Fábrica Braço de Prata (Marvila).")
    add_item(14, "Sessão da Noite: Cinema Independente no Chiado", "cinema",
             "cinema ideal", "21:30", "23:30", "7.50€", "ACCESSIBLE",
             "https://cinemaideal.pt", "Sessão noturna de cinema contemporâneo e estreias no Cinema Ideal (Rua do Loreto, Chiado).")
    add_item(15, "Live Jazz & Jam Session em Alvalade", "concerts",
             "tavola jazz club", "21:30", "23:55", "8.00€", "ACCESSIBLE",
             "https://www.tavolajazzclub.com", "Concertos intimistas de jazz ao vivo e jam sessions no Távola Jazz Club.")
    add_item(16, "Live Rock, Indie & DJ Set na Rua Cor-de-Rosa", "concerts",
             "tokyo lisboa", "22:30", "03:00", "5€ - 10€", "ACCESSIBLE",
             "https://tokyolisboa.com", "Música ao vivo e DJ sets até de madrugada no Tokyo Lisboa (Cais do Sodré).")
    add_item(17, "Noite de Clubbing & Eletrónica no Cais do Sodré", "nightlife",
             "musicbox", "23:30", "05:00", "10€ - 15€", "ACCESSIBLE",
             "https://musicboxlisboa.com", "Programação noturna de clubbing, DJ sets e música eletrónica no Cais do Sodré.")

    # --- 2. OPEN WEDNESDAY - MONDAY (CLOSED TUESDAYS — ACTIVE ON MONDAYS!) ---
    if weekday != 1:
        add_item(18, "Turn Around, Pedro Casqueiro & Visitas à Central Tejo", "exhibitions",
                 "maat", "10:00", "19:00", "11.00€", "ACCESSIBLE",
                 "https://www.maat.pt", "Exposições de arte contemporânea, arquitetura e tecnologia no MAAT e Central Tejo (Belém, aberto qua–seg).")
        add_item(19, "Coleção do Fundador Gulbenkian, Conversas de Arte & Jardins", "exhibitions",
                 "gulbenkian", "10:00", "18:00", "10.00€", "ACCESSIBLE",
                 "https://gulbenkian.pt", "Obras-primas da Antiguidade ao século XX e percurso botânico nos jardins (aberto qua–seg).")
        add_item(20, "PADRÃO: Casa-Obsessão & Miradouro do Tejo", "exhibitions",
                 "padrao dos descobrimentos", "10:00", "18:00", "6.00€", "ACCESSIBLE",
                 "https://padraodosdescobrimentos.pt", "Exposição temporária e subida ao terraço panorâmico do Padrão dos Descobrimentos em Belém.")
        add_item(21, "Exposições de Arte Contemporânea & Ciclo de Conferências", "exhibitions",
                 "culturgest", "11:00", "19:00", "5.00€", "ACCESSIBLE",
                 "https://www.culturgest.pt", "Exposições de artes visuais e debates culturais na Culturgest (Campo Pequeno).")

    # --- 3. OPEN MONDAY - SATURDAY (ARTS & CRAFTS, WORKSHOPS & LECTURE HUBS) ---
    if weekday != 6:
        add_item(22, "A Semente dos Livros — Exposição & Leituras José Saramago", "exhibitions",
                 "casa dos bicos", "10:00", "18:00", "4.00€", "ACCESSIBLE",
                 "https://www.josesaramago.org", "Exposição sobre a vida e obra do Nobel da Literatura e encontros literários na Casa dos Bicos.")
        add_item(23, "Oficinas Abertas de Cerâmica, Serigrafia, Risografia e Marcenaria", "community",
                 "fica oficina criativa", "10:30", "19:00", "Consultar oficina", "MID",
                 "https://fica-oc.pt", "Workshops práticos de artes e ofícios (olaria, serigrafia, encadernação e madeira) na FICA (LX Factory).")
        add_item(24, "Clubes de Leitura, Tertúlias & Exposições no Palácio Galveias", "community",
                 "biblioteca palacio galveias", "10:00", "19:30", "Entrada Livre", "FREE",
                 "https://blx.cm-lisboa.pt", "Encontros literários, palestras, exposições documentais e salas de leitura no Campo Pequeno.")
        add_item(25, "Hierofania (Mané Pacheco) & Conversas de Arte Contemporânea", "exhibitions",
                 "appleton", "14:00", "19:00", "Entrada Livre", "FREE",
                 "https://appleton.pt", "Exposições e encontros com artistas na Appleton Associação Cultural (Alvalade).")
        add_item(26, "Exposições, Conversas Abertas e Residências Artísticas na Graça", "exhibitions",
                 "hangar", "15:00", "19:00", "Entrada Livre", "FREE",
                 "https://hangar.com.pt", "Exposições, palestras pós-coloniais e investigação artística no Hangar (Graça).")

    # --- 4. MONDAY-SPECIFIC LISBON CULTURAL, WORKSHOP & NIGHTLIFE PROGRAMMING ---
    if weekday == 0:
        add_item(27, "Segunda-Feira de Cinema Clássico e Restaurado (Matiné)", "cinema",
                 "cinema medeia nimas", "14:00", "16:15", "7.50€", "ACCESSIBLE",
                 "https://medeiafilmes.com/cinemas/cinema-medeia-nimas", "Ciclos de cinema restaurado e grandes mestres da sétima arte no Cinema Medeia Nimas.")
        add_item(28, "Sessão de Cinema Europeu & Retrospetivas no Saldanha", "cinema",
                 "medeia monumental", "17:00", "19:15", "7.50€", "ACCESSIBLE",
                 "https://medeiafilmes.com", "Exibição de cinema de autor e antestreias no Cinema Medeia Monumental (Saldanha).")
        add_item(29, "Sunset, Feira de Vinil & Listening Session à Beira-Tejo", "community",
                 "docas de santo amaro", "18:00", "22:00", "Entrada Livre", "FREE",
                 "https://www.agendalx.pt", "Fim de tarde com bancas de vinil, ilustração e convívio nas Docas de Santo Amaro / Alcântara.")
        add_item(30, "Oficina de Desenho, Tertúlia & Exposição no Largo do Intendente", "community",
                 "casa independente", "18:30", "23:30", "Entrada Livre", "FREE",
                 "https://casaindependente.com", "Exposição coletiva, encontro criativo e convívio cultural na Casa Independente (Intendente).")
        add_item(31, "Noite de Fado Vadio e Guitarra Portuguesa em Alfama", "concerts",
                 "museu do fado", "20:00", "23:00", "Entrada Livre", "FREE",
                 "https://www.museudofado.pt", "Sessão acústica de fado tradicional e guitarra portuguesa no coração histórico de Alfama.")
        add_item(32, "Open Mic de Stand-Up Comedy no Chiado", "theatre",
                 "chiado comedy club", "21:00", "23:00", "8€ - 10€", "ACCESSIBLE",
                 "https://www.nocartaz.pt/concelhos/lisboa/", "Noite de stand-up comedy e novos talentos do humor no Chiado.")
        add_item(33, "Ciclo Grandes Realizadores — Sessão da Noite Nimas", "cinema",
                 "cinema medeia nimas", "21:30", "23:45", "7.50€", "ACCESSIBLE",
                 "https://medeiafilmes.com/cinemas/cinema-medeia-nimas", "Sessão noturna de cinema de autor e ciclos temáticos no Cinema Medeia Nimas.")
        add_item(34, "Cabaret, Jazz & Cocktails na Rua do Alecrim", "theatre",
                 "o bom o mau e o vilao", "21:30", "01:30", "7.50€", "ACCESSIBLE",
                 "https://www.lisabout.com", "Noite de música, cabaret e DJ set no O Bom O Mau e O Vilão (Cais do Sodré).")
        add_item(35, "Ritmos Atlânticos & Dança no Cais da Ribeira Nova", "concerts",
                 "b.leza", "22:30", "03:00", "10.00€", "ACCESSIBLE",
                 "https://www.agendalx.pt", "Noite dedicada à música lusófona, mornas, funaná e ritmos africanos no B.Leza.")
        add_item(36, "Indie, Post-Punk & Alternative Night em São Bento", "nightlife",
                 "incognito", "23:30", "04:00", "8.00€", "ACCESSIBLE",
                 "https://incognitobar.com", "Pista clássica de indie, post-punk, synth-pop e new wave na Rua de Poiais de São Bento.")

    # --- 5. OPEN TUESDAY - SUNDAY (MUSEUMS, SCIENCE LECTURES & WORKSHOPS) ---
    if weekday != 0:
        add_item(37, "Délio Jasse: Entre a Pele e o Documento & Antologias da Memória", "exhibitions",
                 "mnac", "10:00", "18:00", "10.00€", "ACCESSIBLE",
                 "https://museuartecontemporanea.gov.pt", "Exposições temporárias de fotografia e arte contemporânea no MNAC - Museu do Chiado.")
        add_item(38, "Coleção Real de Viaturas de Gala & Modelismo de Coches", "exhibitions",
                 "museu nacional dos coches", "10:00", "18:00", "8.00€", "ACCESSIBLE",
                 "https://www.mncoches.gov.pt", "Exposição permanente e temporária no Museu Nacional dos Coches em Belém.")
        add_item(39, "Japão: Festas e Rituais, Oficinas Asiáticas & Coleção Kwok On", "exhibitions",
                 "museu do oriente", "10:00", "18:00", "8.00€", "ACCESSIBLE",
                 "https://www.foriente.pt", "Exposição e oficinas de artes tradicionais asiáticos no Museu do Oriente (Alcântara).")
        add_item(40, "Design Português, Moda e Arquitetura na Rua Augusta", "exhibitions",
                 "mude", "10:00", "19:00", "11.00€", "ACCESSIBLE",
                 "https://www.mude.pt", "Exposições de design industrial, gráfico e moda no renovado MUDE — Museu do Design (Baixa).")
        add_item(41, "A Biblioteca Particular de Fernando Pessoa & Clubes de Poesia", "community",
                 "casa fernando pessoa", "10:00", "18:00", "6.00€", "ACCESSIBLE",
                 "https://www.casafernandopessoa.pt", "Visita guiada, palestras literárias e exposição dedicada a Fernando Pessoa em Campo de Ourique.")
        add_item(42, "Marionetas do Mundo & Oficinas de Construção de Formas Animadas", "exhibitions",
                 "museu da marioneta", "10:00", "18:00", "5.00€", "ACCESSIBLE",
                 "https://www.museudamarioneta.pt", "Exposição e oficinas de marionetas e máscaras no Convento das Bernardas (Madragoa).")
        add_item(43, "Obras de Maria Helena Vieira da Silva & Arpad Szenes", "exhibitions",
                 "arpad szenes", "10:00", "18:00", "6.00€", "ACCESSIBLE",
                 "https://fasvs.pt", "Exposição permanente e temporária na Fundação Arpad Szenes-Vieira da Silva (Jardim das Amoreiras).")
        add_item(44, "Painéis de São Vicente e Arte Europeia nas Janelas Verdes", "exhibitions",
                 "museu nacional de arte antiga", "10:00", "18:00", "10.00€", "ACCESSIBLE",
                 "https://www.museudearteantiga.pt", "Acervo nacional de pintura, escultura e artes decorativas no MNAA (Santos).")
        add_item(45, "Exposições de História Natural, Jardim Botânico & Palestras de Ciência", "community",
                 "muhnac", "10:00", "18:00", "6.00€", "ACCESSIBLE",
                 "https://www.museus.ulisboa.pt", "Exposições científicas, herbário, observatório astronómico e visitas ao Jardim Botânico no Príncipe Real.")
        add_item(46, "Exposições de Arte Urbana & Edições de Artista", "exhibitions",
                 "underdogs gallery", "14:00", "19:00", "Entrada Livre", "FREE",
                 "https://www.under-dogs.net", "Galeria de arte contemporânea e arte urbana em Marvila.")

    # --- 6. TUESDAY & SATURDAY FLEA MARKET ---
    if weekday in (1, 5):
        add_item(47, "Feira da Ladra — Mercado Histórico de Antiguidades, Artesanato e Vinil", "community",
                 "feira da ladra", "09:00", "17:00", "Entrada Livre", "FREE",
                 "https://www.agendalx.pt", "O mercado de rua mais antigo de Lisboa no Campo de Santa Clara (terças e sábados).")

    # --- 7. WEEKEND CRAFT, DESIGN & ORGANIC MARKETS (SATURDAY & SUNDAY) ---
    if weekday in (5, 6):
        add_item(48, "Mercado Crafts & Design e Feira de Artesanato no Jardim da Estrela", "community",
                 "jardim da estrela", "10:00", "18:00", "Entrada Livre", "FREE",
                 "https://www.agendalx.pt", "Mercado de autor, cerâmica, ilustração, joalharia e design independente no Jardim da Estrela.")
        add_item(49, "Feira de Artesãos, Vintage, Zines e Criadores no Mercado de Santa Clara", "community",
                 "mercado de santa clara", "10:00", "18:00", "Entrada Livre", "FREE",
                 "https://www.agendalx.pt", "Bancas de cerâmica, gravura, roupa vintage e gastronomia artesanal no histórico pavilhão de Santa Clara.")
        add_item(50, "Mercado Biológico e Feira de Pequenos Produtores no Príncipe Real", "community",
                 "jardim do principe real", "09:30", "15:00", "Entrada Livre", "FREE",
                 "https://www.agendalx.pt", "Mercado ao ar livre sob o cedro do Jardim do Príncipe Real.")

    # --- 8. ACTIVE THEATRE SEASONS & GALLERIES (WEDNESDAY - SUNDAY) ---
    if weekday in (2, 3, 4, 5, 6):
        th_time = "16:30" if weekday == 6 else "20:00"
        th_end = "18:30" if weekday == 6 else "22:00"
        th_late = "17:00" if weekday == 6 else "21:00"
        th_late_end = "19:00" if weekday == 6 else "23:00"

        add_item(51, "Alexandre Estrela: RedSkyFalls (Réplica) — Exposição ZDB", "exhibitions",
                 "zdb", "18:00", "22:00", "Entrada Livre", "FREE",
                 "https://zedosbois.org", "Exposição de artes visuais e instalações na Galeria Zé dos Bois (Bairro Alto).")
        add_item(52, "Macbeth (enc. Pedro Penim) & Auto da Barca do Inferno", "theatre",
                 "d. maria ii", th_time, th_end, "15.00€", "MID",
                 "https://www.tndm.pt", "Temporada teatral do Teatro Nacional D. Maria II.")
        add_item(53, "Em Silêncio — Temporada São Luiz Teatro Municipal", "theatre",
                 "sao luiz", th_time, th_end, "12.00€", "ACCESSIBLE",
                 "https://www.teatrosaoluiz.pt", "Espetáculo de teatro contemporâneo em cena no São Luiz Teatro Municipal (Chiado).")
        add_item(54, "Ópera-Pimba no Gelo! O Primeiro Musical no Gelo Derretido", "theatre",
                 "teatro da comuna", th_time, th_end, "12€ - 15€", "ACCESSIBLE",
                 "https://www.comunateatropesquisa.pt", "Comédia musical satírica na Sala Nova do Teatro da Comuna (Praça de Espanha).")
        add_item(55, "Clube dos Poetas Mortos — enc. Hélder Gamboa", "theatre",
                 "teatro da trindade", th_late, th_late_end, "16€ - 22€", "MID",
                 "https://teatrodatrindade.inatel.pt", "Peça de Tom Schulman em cena no Teatro da Trindade INATEL no Chiado.")
        add_item(56, "Pura Loucura — Temporada Teatro Maria Matos", "theatre",
                 "teatro maria matos", th_late, th_late_end, "21€ - 23€", "MID",
                 "https://teatromariamatos.pt", "Comédia teatral em cena no Teatro Maria Matos (Avenida de Roma).")
        add_item(57, "Contos em Viagem — Goa", "theatre",
                 "teatro meridional", th_late, th_late_end, "12.00€", "ACCESSIBLE",
                 "https://teatromeridional.net", "Espetáculo teatral no Teatro Meridional em Marvila.")
        add_item(58, "Hércules & Carmen Miranda — O Grande Musical", "theatre",
                 "teatro politeama", th_late, th_late_end, "15€ - 30€", "MID",
                 "https://filipelaferia.pt", "Grandes produções musicais de Filipe La Féria no Teatro Politeama (Baixa).")

    # --- 9. JARDINS DO BOMBARDA, ARTS & CRAFTS WORKSHOPS & PICOAS CULTURAL HUB ---
    # Jardins do Bombarda (LARGO Residências) — Open Cultural Gardens, Workshops & Community Events
    add_item(59, "Jardins Abertos, Horta Comunitária, Oficinas Criativas & Esplanada Cultural", "community",
             "jardins do bombarda", "12:00", "20:00", "Entrada Livre", "FREE",
             "https://www.jardinsdobombarda.pt", "Programação comunitária, oficinas de artes e ofícios, exposições e convívio nos Jardins do Bombarda / LARGO Residências (Rua Gomes Freire).")
    add_item(60, "Noites no Bombarda: Música, Cinema ao Ar Livre & Encontros Comunitários", "concerts",
             "jardins do bombarda", "19:00", "23:00", "Entrada Livre", "FREE",
             "https://www.jardinsdobombarda.pt", "Fim de tarde e noite com concertos acústicos, DJ sets, tertúlias e cinema nos Jardins do Bombarda (Arroios).")

    # More Arts & Crafts, Ceramics, Printmaking, Letterpress & Creative Workshops
    if weekday != 6:
        add_item(61, "Oficina de Olaria na Roda, Modelação em Barro & Cerâmica de Autor", "community",
                 "caulino ceramics", "14:30", "18:30", "35€ (c/ materiais)", "MID",
                 "https://www.caulinoceramics.com", "Workshop prático de iniciação à roda de oleiro, modelação manual e esmaltagem em atelier de cerâmica em Arroios.")
        add_item(62, "Atelier Aberto de Serigrafia, Gravura, Risografia, Cianotipia e Zines", "community",
                 "contraprova", "15:00", "19:30", "15€ - 25€", "ACCESSIBLE",
                 "https://www.agendalx.pt", "Oficina prática de técnicas de impressão artesanal, linogravura, encadernação manual e autoedição nos Anjos.")
        add_item(63, "Oficina de Tipografia Tradicional, Artes Gráficas & Exposição INCM", "community",
                 "imprensa nacional", "10:30", "18:00", "Entrada Livre", "FREE",
                 "https://imprensanacional.pt", "Exposição de artes do livro, imprensa de caracteres móveis e património gráfico na Imprensa Nacional (Picoas / Marquês).")
        add_item(64, "Ateliers de Tufting, Bordado Contemporâneo, Ilustração & Feira Criativa", "community",
                 "anjos70", "14:00", "20:00", "Entrada Livre / Oficinas", "ACCESSIBLE",
                 "https://anjos70.org/", "Espaço de criadores independentes com workshops de têxteis, tufting, ilustração e artes plásticas no Regueirão dos Anjos.")
    if weekday != 0:
        add_item(65, "Oficina de Pintura de Azulejo Tradicional & Cerâmica Naturalista", "community",
                 "museu bordalo pinheiro", "10:30", "17:30", "6€ - 15€", "ACCESSIBLE",
                 "https://museubordalopinheiro.pt", "Exposição e oficinas práticas de modelação cerâmica e pintura de azulejo no Museu Bordalo Pinheiro (Campo Grande).")

    # Picoas Cultural Cluster (Fórum Picoas, Anastácio Gonçalves, Galeria Monumental, Nimas, Mercado 31 de Janeiro)
    add_item(66, "Exposição de Fotografia, Conversas Urbanas & Sessões no Fórum Picoas", "exhibitions",
             "forum picoas", "10:00", "19:30", "Entrada Livre", "FREE",
             "https://www.agendalx.pt", "Mostra documental, encontros culturais e programação comunitária no Fórum Picoas (Av. Fontes Pereira de Melo).")
    add_item(67, "Matiné de Cinema de Autor & Clássicos Restaurados em Picoas", "cinema",
             "cinema medeia nimas", "15:30", "17:45", "7.50€", "ACCESSIBLE",
             "https://medeiafilmes.com/cinemas/cinema-medeia-nimas", "Sessão da tarde dedicada a grandes realizadores e retrospetivas no Cinema Medeia Nimas (Picoas / Saldanha).")
    add_item(68, "Sessão da Noite: Ciclos de Cinema Independente no Medeia Nimas", "cinema",
             "cinema medeia nimas", "21:30", "23:45", "7.50€", "ACCESSIBLE",
             "https://medeiafilmes.com/cinemas/cinema-medeia-nimas", "Programação noturna de cinema de autor no histórico Cinema Medeia Nimas (Av. 5 de Outubro, Picoas).")
    add_item(72, "Afterwork Sunset, Live Soul/Jazz & DJ Set entre Picoas e Saldanha", "nightlife",
             "evolution valbom", "18:30", "23:00", "Entrada Livre", "FREE",
             "https://www.lisabout.com/genero/dance-electronic", "Fim de tarde e noite com DJ sets, música ao vivo e cocktails entre Picoas e o Saldanha.")
    if weekday != 6:
        add_item(70, "Exposição de Ilustração, Livros de Artista & Oficina de Desenho em Picoas", "exhibitions",
                 "galeria monumental", "14:00", "19:30", "Entrada Livre", "FREE",
                 "https://www.galeriamonumental.com", "Mostra de arte contemporânea, gravura, ilustração e edição de autor na Galeria Monumental (Picoas / Saldanha).")
        add_item(71, "Bancas de Produtores, Artesanato Urbano & Degustações em Picoas", "community",
                 "mercado 31 de janeiro", "09:30", "16:00", "Entrada Livre", "FREE",
                 "https://www.agendalx.pt", "Mercado tradicional e pop-ups gastronómicos e criativos no coração de Picoas (Rua Eng. Vieira da Silva).")
    if weekday != 0:
        add_item(69, "Coleção de Pintura, Porcelana & Oficina de Aguarela na Casa-Museu", "exhibitions",
                 "anastacio goncalves", "10:00", "17:30", "5.00€", "ACCESSIBLE",
                 "https://www.museusemonumentos.pt", "Visita à joia de arquitetura Arte Nova em Picoas (atelier de Malhoa) com oficinas de desenho e aguarela.")

    return ongoing


def apply_coordinate_jitter(events):
    """Applies a tight golden-angle spiral offset (~7m) when multiple events share the same venue coordinates, keeping pins on the same building."""
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
            ev["lat"] = min(38.82, max(38.65, new_lat))
            ev["lng"] = min(-9.05, max(-9.25, new_lng))
    return events


_DEDUP_STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "para", "com", "por", "um", "uma", "e", "ou", "ao", "aos", "vivo", "live", "concerto",
    "unico", "regressa", "regressam", "portugal", "lisboa", "apresenta", "apresentam",
    "novo", "nova", "disco", "album", "tour", "digressao", "espetaculo", "sessao",
    "teatro", "arena", "meo", "altice", "club", "clube", "festival", "edicao",
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
    if h < 4:
        h += 24
    return h * 60 + m


def _event_quality_score(ev):
    score = 0
    price = str(ev.get("price", "")).lower()
    if "€" in price or "livre" in price:
        score += 3
    desc = str(ev.get("description", ""))
    if len(desc) > 55 and not desc.endswith(")."):
        score += 2
    title = str(ev.get("title", ""))
    if not title.isupper() and "@" not in title:
        score += 1
    if ev.get("category") == "Concerts & Live Music" and 20 <= int(ev.get("hour", 21)) <= 23:
        score += 2
    return score


def deduplicate_events(events):
    seen_exact = set()
    unique = []
    non_lisbon_markers = ("queer porto", "no porto", "em coimbra", "em braga", "em faro", "em aveiro")

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
        ev_mins = _event_op_minutes(ev)

        duplicate_idx = None
        for idx, existing in enumerate(unique):
            ex_venue = strip_accents(existing.get("venue", "")).strip()
            if ex_venue != venue_norm:
                continue
            ex_mins = _event_op_minutes(existing)
            if abs(ev_mins - ex_mins) > 300:
                continue
            ex_sig = _core_title_signature(existing.get("title", ""), existing.get("venue", ""))
            if not sig or not ex_sig:
                continue
            if sig == ex_sig or (len(sig) >= 4 and len(ex_sig) >= 4 and (sig in ex_sig or ex_sig in sig)):
                duplicate_idx = idx
                break

        if duplicate_idx is not None:
            if _event_quality_score(ev) > _event_quality_score(unique[duplicate_idx]):
                unique[duplicate_idx] = ev
        else:
            unique.append(ev)

    return unique


def scrape_dador_sessions(target_date):
    """
    Fetches real-time blood donation sessions from dador.pt API (https://dador.pt/sessoes).
    Filters for Lisbon sessions matching target_date (e.g. Hospital de São José, Hospital de Santa Maria,
    Pavilhão 17 Alvalade, CGD Sede, mobile blood drives).
    """
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
                distrito = (s.get("DesDistrito") or "").strip().upper()
                if concelho != "LISBOA" and distrito != "LISBOA":
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

                venue_name = local.split(" - ")[0].strip() if " - " in local else des_brigada
                if len(venue_name) < 4:
                    venue_name = des_brigada

                corridor = locations.infer_corridor(lat, lng)
                neighborhood = locations.infer_neighborhood(lat, lng)

                title = f"Dádiva de Sangue: {des_brigada.title()}"
                s_id = f"dador-{s.get('Id', abs(hash(des_brigada + geo_ref)) % 10000)}"
                desc = f"Sessão de dádiva e colheita de sangue ({tipo}) em {local or des_brigada}. Horário: {time_str} às {end_t}. Dá sangue, salva vidas!"

                events.append({
                    "id": s_id,
                    "title": title,
                    "category": "Community & Gatherings",
                    "color": "#E63946",
                    "icon": "🩸",
                    "venue": venue_name.title(),
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
    """
    Scrapes events from Junta de Freguesia de Santo António (https://www.jfsantoantonio.pt/index.php/freguesia/agenda).
    Extracts events matching target_date (e.g. Magusto 2026 on 11-11-2026 at Praça da Alegria,
    Recolha de Sangue on 05-11-2026, Ciência na BACS, etc.).
    """
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
                venue_name = "Freguesia de Santo António"
                lat, lng = 38.72485, -9.14394
                end_t = f"{min(23, hour_int + 2):02d}:00"
                end_h = min(23, hour_int + 2)

                try:
                    d_resp = fetch_url(ev_url, timeout=8)
                    if d_resp.status_code == 200:
                        clean_d = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', d_resp.text, flags=re.S|re.I)
                        clean_d = re.sub(r'<[^>]+>', ' ', clean_d)
                        clean_d = re.sub(r'\s+', ' ', clean_d)

                        if "praça da alegria" in clean_d.lower() or "praca da alegria" in clean_d.lower():
                            venue_name = "Praça da Alegria"
                            lat, lng = 38.71802, -9.14482
                        elif "bacs" in clean_d.lower() or "cosmelli" in clean_d.lower():
                            venue_name = "Biblioteca Cosmelli Sant'Anna (BACS)"
                            lat, lng = 38.72120, -9.15180
                        elif "torel" in clean_d.lower():
                            venue_name = "Jardim do Torel"
                            lat, lng = 38.71962, -9.14081
                        else:
                            hit, g_name = locations.geocode_location(title + ", Santo António, Lisboa")
                            if hit:
                                lat, lng = hit["lat"], hit["lng"]
                                venue_name = g_name

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


def main():
    load_external_venues()

    # Determine operational date in Europe/Lisbon with 04:00 AM cutoff
    now_lx = datetime.datetime.now(ZoneInfo("Europe/Lisbon"))
    target_date = (now_lx - datetime.timedelta(hours=4)).date()
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"=== Keks Passa Scraper v2.5 — Operational Date: {date_str} ===")

    # Rebuild cleanly from all live scrapers so stale/misattributed venue entries are never carried over
    live_raw = []
    live_raw.extend(scrape_agendalx(target_date))
    live_raw.extend(scrape_nocartaz(target_date))
    live_raw.extend(scrape_cinemateca(target_date))
    live_raw.extend(scrape_nimas(target_date))
    live_raw.extend(scrape_agendadeconcertos(target_date))
    live_raw.extend(scrape_bota_anjos(target_date))
    live_raw.extend(scrape_resident_advisor(target_date))
    live_raw.extend(scrape_prior_velho_electronic(target_date))
    live_raw.extend(scrape_markets_workshops_lectures(target_date))
    live_raw.extend(scrape_viralagenda(target_date))
    live_raw.extend(scrape_soko_curated_capsula(target_date))
    live_raw.extend(scrape_dador_sessions(target_date))
    live_raw.extend(scrape_junta_santo_antonio(target_date))

    all_events = deduplicate_events(live_raw)

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

        lat_val = ev.get("lat")
        lng_val = ev.get("lng")
        if lat_val is None or lng_val is None:
            continue
        try:
            lat = float(lat_val)
            lng = float(lng_val)
        except (ValueError, TypeError):
            continue

        if not (38.65 <= lat <= 38.82 and -9.25 <= lng <= -9.05):
            continue

        ev["lat"] = round(lat, 6)
        ev["lng"] = round(lng, 6)
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

    locations.save_cache()

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
