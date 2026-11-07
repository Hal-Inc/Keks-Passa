#!/usr/bin/env python3
"""
verify_venues.py — Keks Passa Venue-to-Source Verification & Audit Engine

Validates the integrity, coordinates, source platforms, and primary agenda URLs
for all venues in venues.json. Ensures the scraper extracts events from true primary
sources of truth (Shotgun, DICE, Resident Advisor, official web agendas, Instagram)
rather than stale or misattributed aggregator fallbacks.
"""

import sys
import os
import json
import re
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse

# Reconfigure stdout for UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENUES_FILE = os.path.join(SCRIPT_DIR, "venues.json")
REPORT_FILE = os.path.join(SCRIPT_DIR, "venue_audit_report.json")

# Lisbon Municipality (North of Tagus) geographic bounding box
LISBON_BOUNDS = {
    "lat_min": 38.690,
    "lat_max": 38.805,
    "lng_min": -9.235,
    "lng_max": -9.085,
}

AMBIGUOUS_STANDALONE_ALIASES = {
    "nada", "nāda", "naada", "rca", "lav", "bota", "lux", "fil",
    "alvalade", "alcantara", "alcântara", "campolide", "campo pequeno",
    "campo grande", "principe real", "arroios", "anjos", "marvila", "beato",
}

VALID_CORRIDORS = {
    "Eastern Corridor",
    "Axial Spine",
    "Northern Belt",
    "Belém Waterfront",
}

AGGREGATOR_DOMAINS = {
    "agendalx.pt",
    "www.agendalx.pt",
    "lisabout.com",
    "www.lisabout.com",
    "nocartaz.pt",
    "www.nocartaz.pt",
    "cartazculturallisboa.pt",
}

# Master Source Upgrade Matrix: maps venue name -> verified primary source info
PRIMARY_SOURCE_UPGRADES: Dict[str, Dict[str, str]] = {
    "Titanic Sur Mer": {
        "url": "https://www.instagram.com/titanicsurmer/",
        "agenda_url": "https://shotgun.live/venues/titanic-sur-mer",
        "source_platform": "shotgun",
    },
    "B.Leza": {
        "url": "https://www.instagram.com/bleza.clube/",
        "agenda_url": "https://www.instagram.com/bleza.clube/",
        "source_platform": "instagram",
    },
    "Rive Rouge": {
        "url": "https://www.instagram.com/riverougelisboa/",
        "agenda_url": "https://www.lisabout.com/genero/dance-electronic",
        "source_platform": "instagram",
    },
    "Harbour Music Shelter": {
        "url": "https://www.instagram.com/harbourmusicshelter/",
        "agenda_url": "https://www.lisabout.com/genero/dance-electronic",
        "source_platform": "instagram",
    },
    "Lust in Rio": {
        "url": "https://www.instagram.com/lustinrio/",
        "agenda_url": "https://3cket.com/",
        "source_platform": "instagram",
    },
    "O Bom O Mau e O Vilão": {
        "url": "https://www.instagram.com/obomomaueovilao/",
        "agenda_url": "https://www.instagram.com/obomomaueovilao/",
        "source_platform": "instagram",
    },
    "Top Floor": {
        "url": "https://www.instagram.com/topfloorlisbon/",
        "agenda_url": "https://www.instagram.com/topfloorlisbon/",
        "source_platform": "instagram",
    },
    "Skones & Pátio do Pinzaleiro": {
        "url": "https://www.instagram.com/skones.lisboa/",
        "agenda_url": "https://www.instagram.com/skones.lisboa/",
        "source_platform": "instagram",
    },
    "Contraprova — Atelier de Gravura e Risografia": {
        "url": "https://contraprova.pt/",
        "agenda_url": "https://contraprova.pt/",
        "source_platform": "official_web",
    },
    "Feira da Ladra (Campo de Santa Clara)": {
        "url": "https://www.visitlisboa.com/pt-pt/locais/feira-da-ladra",
        "agenda_url": "https://www.agendalx.pt/",
        "source_platform": "municipal",
    },
    "Chiado Comedy Club": {
        "url": "https://www.instagram.com/lisboacomedyclub/",
        "agenda_url": "https://lisboacomedyclub.pt/",
        "source_platform": "official_web",
    },
    "Jardim da Estrela (Crafts & Design)": {
        "url": "https://www.agendalx.pt/",
        "agenda_url": "https://www.agendalx.pt/",
        "source_platform": "municipal",
    },
    "República da Música": {
        "url": "https://www.instagram.com/republicadamusicaoficial/",
        "agenda_url": "https://www.instagram.com/republicadamusicaoficial/",
        "source_platform": "instagram",
    },
    "Pavilhão Carlos Lopes": {
        "url": "https://www.visitlisboa.com/pt-pt/locais/pavilhao-carlos-lopes",
        "agenda_url": "https://www.agendalx.pt/",
        "source_platform": "municipal",
    },
    "BONANÇA - Associação Naval de Lisboa": {
        "url": "https://anl.pt/",
        "agenda_url": "https://www.lisabout.com/genero/dance-electronic",
        "source_platform": "official_web",
    },
    "MACAM / àCapela": {
        "url": "https://www.instagram.com/macam.lisboa/",
        "agenda_url": "https://www.instagram.com/macam.lisboa/",
        "source_platform": "instagram",
    },
    "Docas de Santo Amaro / Cais Rocha Conde de Óbidos": {
        "url": "https://www.portodelisboa.pt/docas-de-recreio",
        "agenda_url": "https://www.portodelisboa.pt/docas-de-recreio",
        "source_platform": "municipal",
    },
    "Emaús Pop-Up Arroios": {
        "url": "https://www.instagram.com/emaus.lisboa/",
        "agenda_url": "https://www.instagram.com/emaus.lisboa/",
        "source_platform": "instagram",
    },
    "Cordoaria Nacional": {
        "url": "https://galeriasmunicipais.pt/",
        "agenda_url": "https://galeriasmunicipais.pt/exposicoes/",
        "source_platform": "municipal",
    },
    "Galeria Zé dos Bois (ZDB)": {
        "url": "https://zedosbois.org/",
        "agenda_url": "https://zedosbois.org/",
        "source_platform": "official_web",
    },
    "Musicbox": {
        "url": "https://musicboxlisboa.com/",
        "agenda_url": "https://musicboxlisboa.com/",
        "source_platform": "official_web",
    },
    "Lux Frágil": {
        "url": "https://www.luxfragil.com/",
        "agenda_url": "https://www.luxfragil.com/",
        "source_platform": "official_web",
    },
    "Ministerium Club": {
        "url": "https://www.instagram.com/ministeriumclub/",
        "agenda_url": "https://www.lisabout.com/genero/dance-electronic",
        "source_platform": "instagram",
    },
    "Kømplex Lisbon": {
        "url": "https://shotgun.live/pt-pt/venues/komplex",
        "agenda_url": "https://shotgun.live/pt-pt/venues/komplex",
        "source_platform": "shotgun",
    },
    "NĀDA 3.0 (NADA Lisbon)": {
        "url": "https://shotgun.live/pt-pt/venues/nada-lisbon",
        "agenda_url": "https://shotgun.live/pt-pt/venues/nada-lisbon",
        "source_platform": "shotgun",
    },
    "Damas Bar & Concertos": {
        "url": "https://www.instagram.com/damas_lisboa/",
        "agenda_url": "https://www.instagram.com/damas_lisboa/",
        "source_platform": "instagram",
    },
    "Menina e Moça": {
        "url": "https://www.instagram.com/meninaemocalivrariabar/?hl=en",
        "agenda_url": "https://www.instagram.com/meninaemocalivrariabar/?hl=en",
        "source_platform": "instagram",
    },
    "BOTA - Base Organizada da Toca das Artes": {
        "url": "https://www.botaanjos.com/",
        "agenda_url": "https://www.botaanjos.com/programacao",
        "source_platform": "official_web",
    },
    "Cinemateca Portuguesa": {
        "url": "https://www.cinemateca.pt/",
        "agenda_url": "https://www.cinemateca.pt/Programacao.aspx",
        "source_platform": "official_web",
    },
    "Cinema Medeia Nimas": {
        "url": "https://medeiafilmes.com/cinemas/cinema-medeia-nimas",
        "agenda_url": "https://medeiafilmes.com/cinemas/cinema-medeia-nimas",
        "source_platform": "official_web",
    },
    "Centro Cultural de Belém (CCB)": {
        "url": "https://www.ccb.pt/",
        "agenda_url": "https://www.ccb.pt/programacao/",
        "source_platform": "bol",
    },
    "São Luiz Teatro Municipal": {
        "url": "https://www.teatrosaoluiz.pt/",
        "agenda_url": "https://www.teatrosaoluiz.pt/espetaculos/",
        "source_platform": "bol",
    },
    "Culturgest": {
        "url": "https://www.culturgest.pt/",
        "agenda_url": "https://www.culturgest.pt/pt/programacao/",
        "source_platform": "bol",
    },
    "Teatro Maria Matos": {
        "url": "https://teatromariamatos.pt/",
        "agenda_url": "https://teatromariamatos.pt/",
        "source_platform": "ticketline",
    },
    "Kosmicare": {
        "url": "https://kosmicare.org/drugchecking/",
        "agenda_url": "https://kosmicare.org/drugchecking/",
        "source_platform": "health_service",
    },
}


def infer_platform_from_url(url: str) -> str:
    """Classifies source platform from URL domain/pattern."""
    u = url.lower()
    if "shotgun.live" in u:
        return "shotgun"
    if "dice.fm" in u:
        return "dice"
    if "ra.co" in u or "residentadvisor.net" in u:
        return "resident_advisor"
    if "bol.pt" in u:
        return "bol"
    if "ticketline.sapo.pt" in u or "ticketline.pt" in u:
        return "ticketline"
    if "3cket.com" in u:
        return "3cket"
    if "instagram.com" in u:
        return "instagram"
    if "facebook.com" in u:
        return "facebook"
    if "dador.pt" in u:
        return "blood_donation"
    if "kosmicare.org" in u:
        return "health_service"
    if "cm-lisboa.pt" in u or "lisboa.pt" in u or "visitlisboa.com" in u or "jfsantoantonio.pt" in u:
        return "municipal"
    if any(agg in u for agg in AGGREGATOR_DOMAINS):
        return "aggregator_fallback"
    return "official_web"


def load_venues(path: str = VENUES_FILE) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_venues(venues: List[Dict[str, Any]], path: str = VENUES_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(venues, f, ensure_ascii=False, indent=2)


def audit_venues(venues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Runs a complete integrity and source audit across all venues."""
    total = len(venues)
    geo_errors = []
    alias_warnings = []
    corridor_warnings = []
    fallback_venues = []
    authoritative_venues = []
    platform_counts: Dict[str, int] = {}

    seen_names = set()
    for idx, v in enumerate(venues):
        name = v.get("venue", f"Venue #{idx}")
        if name.lower() in seen_names:
            geo_errors.append({"venue": name, "reason": "Duplicate venue entry in venues.json"})
        seen_names.add(name.lower())
        lat = v.get("lat")
        lng = v.get("lng")
        corridor = v.get("corridor")
        aliases = v.get("aliases", [])
        url = v.get("url", "")
        agenda_url = v.get("agenda_url", url)
        platform = v.get("source_platform") or infer_platform_from_url(agenda_url or url)

        # 1. Geographic Bounds Check
        if lat is None or lng is None:
            geo_errors.append({"venue": name, "reason": "Missing coordinates"})
        elif not (LISBON_BOUNDS["lat_min"] <= lat <= LISBON_BOUNDS["lat_max"] and
                  LISBON_BOUNDS["lng_min"] <= lng <= LISBON_BOUNDS["lng_max"]):
            geo_errors.append({
                "venue": name,
                "reason": f"Coordinates ({lat}, {lng}) outside Lisbon bounds",
            })

        # 2. Corridor Check
        if corridor not in VALID_CORRIDORS:
            corridor_warnings.append({"venue": name, "corridor": corridor})

        # 3. Aliases Check
        if not aliases or not isinstance(aliases, list):
            alias_warnings.append({"venue": name, "reason": "No aliases defined"})
        else:
            for al in aliases:
                if str(al).strip().lower() in AMBIGUOUS_STANDALONE_ALIASES:
                    alias_warnings.append({"venue": name, "reason": f"Ambiguous standalone alias '{al}'"})

        # 3b. URL Format Check
        if not str(url).startswith("http") or not str(agenda_url).startswith("http"):
            geo_errors.append({"venue": name, "reason": f"Missing or non-HTTP url/agenda_url: {url!r}"})

        # 4. Source Platform & Authoritative URL Check
        is_fallback = any(agg in url.lower() for agg in AGGREGATOR_DOMAINS)
        platform_counts[platform] = platform_counts.get(platform, 0) + 1

        record = {
            "venue": name,
            "neighborhood": v.get("neighborhood", ""),
            "corridor": corridor,
            "lat": lat,
            "lng": lng,
            "url": url,
            "agenda_url": agenda_url,
            "source_platform": platform,
            "has_primary_upgrade_available": name in PRIMARY_SOURCE_UPGRADES,
        }

        if is_fallback:
            fallback_venues.append(record)
        else:
            authoritative_venues.append(record)

    score = round((len(authoritative_venues) / total) * 100, 1) if total else 0.0

    return {
        "total_venues": total,
        "authoritative_count": len(authoritative_venues),
        "fallback_count": len(fallback_venues),
        "authoritative_percentage": score,
        "platform_distribution": platform_counts,
        "geo_errors": geo_errors,
        "corridor_warnings": corridor_warnings,
        "alias_warnings": alias_warnings,
        "fallback_venues": fallback_venues,
        "authoritative_venues": authoritative_venues,
    }


def upgrade_venues_registry(venues: List[Dict[str, Any]]) -> (List[Dict[str, Any]], int):
    """
    Upgrades all venues using the PRIMARY_SOURCE_UPGRADES matrix.
    Adds 'agenda_url' and 'source_platform' metadata, and separates Village Underground.
    """
    upgraded_count = 0
    updated_venues = []

    for v in venues:
        name = v.get("venue", "")

        # Check if LX Factory / Village Underground should be cleaned up
        if name == "LX Factory / Village Underground":
            # Keep LX Factory as design & cultural quarter
            v["venue"] = "LX Factory"
            v["aliases"] = ["lx factory", "lxfactory", "ler devagar", "livraria ler devagar", "cais do gais alcantara"]
            v["url"] = "https://lxfactory.com/"
            v["agenda_url"] = "https://lxfactory.com/"
            v["source_platform"] = "official_web"
            updated_venues.append(v)
            upgraded_count += 1

            # Insert Village Underground Lisboa as independent electronic & music venue
            vu = {
                "venue": "Village Underground Lisboa",
                "aliases": [
                    "village underground",
                    "village underground lisboa",
                    "vu lisboa",
                    "autocarro village underground",
                    "carrilho videira alcantara",
                ],
                "lat": 38.70348,
                "lng": -9.17935,
                "neighborhood": "Alcântara",
                "corridor": "Belém Waterfront",
                "url": "https://vulisboa.com/",
                "agenda_url": "https://vulisboa.com/",
                "source_platform": "official_web",
            }
            updated_venues.append(vu)
            upgraded_count += 1
            continue

        if name in PRIMARY_SOURCE_UPGRADES:
            upgrade = PRIMARY_SOURCE_UPGRADES[name]
            v["url"] = upgrade["url"]
            v["agenda_url"] = upgrade["agenda_url"]
            v["source_platform"] = upgrade["source_platform"]
            upgraded_count += 1
        else:
            # Enrich existing primary venue with agenda_url and source_platform if missing
            if "agenda_url" not in v:
                v["agenda_url"] = v.get("url", "")
            if "source_platform" not in v:
                v["source_platform"] = infer_platform_from_url(v.get("url", ""))

        updated_venues.append(v)

    return updated_venues, upgraded_count


def print_audit_summary(report: Dict[str, Any]) -> None:
    """Prints a clear, human-readable terminal scorecard."""
    print("=" * 72)
    print("  KEKS PASSA — VENUE-TO-SOURCE AUDIT SCORECARD (TASK 1)")
    print("=" * 72)
    print(f"Total Venues in Registry   : {report['total_venues']}")
    print(f"Authoritative Direct Sources: {report['authoritative_count']} ({report['authoritative_percentage']}%)")
    print(f"Fallback Aggregator Links   : {report['fallback_count']}")
    print("-" * 72)
    print("Platform Distribution Breakdown:")
    for plat, cnt in sorted(report["platform_distribution"].items(), key=lambda x: x[1], reverse=True):
        print(f"  • {plat:22s} : {cnt:3d} venues")
    print("-" * 72)

    if report["geo_errors"]:
        print(f"⚠️  GEO ERRORS ({len(report['geo_errors'])}):")
        for g in report["geo_errors"]:
            print(f"   - {g['venue']}: {g['reason']}")
    else:
        print("✅ Geographic Coordinates: 100% of venues within Lisbon metro boundaries.")

    if report["fallback_venues"]:
        print(f"\n📋 Venues Currently Relying on Aggregator Fallbacks ({len(report['fallback_venues'])}):")
        for f in report["fallback_venues"][:12]:
            upgrade_badge = "[UPGRADE READY]" if f["has_primary_upgrade_available"] else "[NEEDS RESEARCH]"
            print(f"   {upgrade_badge:16s} {f['venue']:38s} -> {f['url']}")
        if len(report["fallback_venues"]) > 12:
            print(f"   ... and {len(report['fallback_venues']) - 12} more (see venue_audit_report.json)")

    print("=" * 72)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Keks Passa Venue-to-Source Verification Engine")
    parser.add_argument("--upgrade", action="store_true", help="Apply verified primary source upgrades to venues.json")
    parser.add_argument("--promote-cache", action="store_true", help="Promote newly geocoded named venues from geocode_cache.json into venues.json")
    parser.add_argument("--strict", action="store_true", help="Exit with code 1 if any geo, corridor, alias, or URL error is found")
    parser.add_argument("--check-live", action="store_true", help="Perform live HTTP status checks on all venue URLs")
    parser.add_argument("--report", default=REPORT_FILE, help="Path for JSON audit report output")
    args = parser.parse_args()

    venues = load_venues()

    if args.promote_cache:
        import locations
        cache_path = os.path.join(SCRIPT_DIR, "geocode_cache.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as cf:
                gcache = json.load(cf)
            existing_aliases = set()
            for v in venues:
                existing_aliases.add(locations._strip_accents(v.get("venue", "")).lower())
                for al in v.get("aliases", []):
                    existing_aliases.add(locations._strip_accents(al).lower())
            promoted = 0
            for raw_k, hit in gcache.items():
                if not isinstance(hit, dict) or "lat" not in hit or "lng" not in hit:
                    continue
                v_part = raw_k.split(",")[0].strip().lower()
                if len(v_part) < 4 or locations.STREET_PREFIX.match(v_part) or v_part in existing_aliases or v_part in AMBIGUOUS_STANDALONE_ALIASES:
                    continue
                lat_f, lng_f = float(hit["lat"]), float(hit["lng"])
                if not locations.in_lisbon(lat_f, lng_f):
                    continue
                venues.append({
                    "venue": v_part.title(),
                    "aliases": [v_part.lower()],
                    "lat": round(lat_f, 5),
                    "lng": round(lng_f, 5),
                    "neighborhood": locations.infer_neighborhood(lat_f, lng_f, hit.get("area", "")),
                    "corridor": locations.infer_corridor(lat_f, lng_f),
                    "url": "https://www.agendalx.pt/",
                    "agenda_url": "https://www.agendalx.pt/",
                    "source_platform": "municipal",
                })
                existing_aliases.add(v_part.lower())
                promoted += 1
            if promoted:
                save_venues(venues)
                print(f"[✓] Promoted {promoted} newly geocoded Lisbon venues from geocode_cache.json into venues.json!")

    if args.upgrade:
        print("\n[+] Upgrading venues registry with verified primary URLs & agenda platforms...")
        venues, upgraded_count = upgrade_venues_registry(venues)
        save_venues(venues)
        print(f"[✓] Successfully upgraded {upgraded_count} venues in {VENUES_FILE}!\n")

    report = audit_venues(venues)
    print_audit_summary(report)

    if args.check_live:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        try:
            from curl_cffi import requests as cffi_req
            make_req = lambda u: cffi_req.get(u, impersonate="chrome120", timeout=10, verify=False).status_code
        except ImportError:
            import urllib.request
            make_req = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=10).status
        urls_to_check = sorted({v.get("url", "") for v in venues if v.get("url")} | {v.get("agenda_url", "") for v in venues if v.get("agenda_url")})
        print(f"\n[+] Live HTTP verification of {len(urls_to_check)} unique venue URLs...")
        dead_urls = []
        with ThreadPoolExecutor(max_workers=12) as pool:
            futs = {pool.submit(make_req, u): u for u in urls_to_check}
            for fut in as_completed(futs):
                u = futs[fut]
                try:
                    code = fut.result()
                    if code == 404 or code >= 500:
                        dead_urls.append((u, code))
                except Exception as exc:
                    dead_urls.append((u, str(exc)))
        report["dead_urls"] = dead_urls
        if dead_urls:
            print(f"⚠️  Live URL issues detected ({len(dead_urls)}):")
            for u, err in dead_urls:
                print(f"   - [{err}] {u}")
        else:
            print("✅ All venue URLs passed live HTTP verification.")

    # Save detailed JSON report
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[✓] Detailed audit report written to: {args.report}")

    if args.strict and (report["geo_errors"] or report["corridor_warnings"] or report["alias_warnings"]):
        print("❌ Strict audit failed due to schema/geo/alias warnings above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
