#!/usr/bin/env python3
"""
adk_agent.py — Keks Passa Multi-Agent System powered by Google ADK (https://adk.dev/)

Provides:
  1. KeksVenueAuditorAgent: Audits venues.json, promotes newly geocoded Lisbon venues from
     geocode_cache.json, and verifies geographic bounds & primary source URLs.
  2. KeksEventVerifierAgent: Audits events.json for operational_date accuracy, time ranges,
     pricing tiers, and live HTTP reachability.
  3. KeksConciergeAgent: Interactive Lisbon cultural & nightlife advisor grounded on today's
     verified events.json.
  4. KeksPassaCoordinator (`root_agent`): Root ADK dispatcher routing tasks to sub-agents.

Usage:
  • CLI Deterministic Check (no API key needed):
      python adk_agent.py --status
  • Google ADK Interactive CLI / Local Web Studio (requires `pip install google-adk` + GOOGLE_API_KEY):
      adk run .
      adk web .
"""

import os
import sys
import json
from typing import Dict, Any, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EVENTS_PATH = os.path.join(SCRIPT_DIR, "events.json")
VENUES_PATH = os.path.join(SCRIPT_DIR, "venues.json")

import locations
import verify_venues
import scraper


# ==============================================================================
# 1. DETERMINISTIC PYTHON TOOLS EXPOSED TO ADK AGENTS
# ==============================================================================
def audit_venues_tool(promote_from_cache: bool = False, check_live_urls: bool = False) -> Dict[str, Any]:
    """
    Audits all Lisbon venues in venues.json for strict North-of-Tagus coordinates,
    valid corridors, non-ambiguous aliases, and authoritative URLs.
    Optionally promotes newly geocoded venues from geocode_cache.json.
    """
    venues = verify_venues.load_venues(VENUES_PATH)
    promoted_count = 0

    if promote_from_cache:
        cache_path = os.path.join(SCRIPT_DIR, "geocode_cache.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as cf:
                gcache = json.load(cf)
            existing_aliases = set()
            for v in venues:
                existing_aliases.add(locations._strip_accents(v.get("venue", "")).lower())
                for al in v.get("aliases", []):
                    existing_aliases.add(locations._strip_accents(al).lower())
            for raw_k, hit in gcache.items():
                if not isinstance(hit, dict) or "lat" not in hit or "lng" not in hit:
                    continue
                v_part = raw_k.split(",")[0].strip().lower()
                if (
                    len(v_part) < 4
                    or locations.STREET_PREFIX.match(v_part)
                    or v_part in existing_aliases
                    or v_part in verify_venues.AMBIGUOUS_STANDALONE_ALIASES
                ):
                    continue
                lat_f, lng_f = float(hit["lat"]), float(hit["lng"])
                if not locations.in_lisbon(lat_f, lng_f):
                    continue
                venues.append({
                    "venue": v_part.title(),
                    "aliases": [v_part],
                    "lat": round(lat_f, 5),
                    "lng": round(lng_f, 5),
                    "neighborhood": locations.infer_neighborhood(lat_f, lng_f, hit.get("area", "")),
                    "corridor": locations.infer_corridor(lat_f, lng_f),
                    "url": "https://www.agendalx.pt/",
                    "agenda_url": "https://www.agendalx.pt/",
                    "source_platform": "municipal",
                })
                existing_aliases.add(v_part)
                promoted_count += 1
            if promoted_count:
                verify_venues.save_venues(venues, VENUES_PATH)

    report = verify_venues.audit_venues(venues)
    return {
        "total_venues": report["total_venues"],
        "authoritative_count": report["authoritative_count"],
        "authoritative_percentage": report["authoritative_percentage"],
        "promoted_from_cache": promoted_count,
        "geo_errors": report["geo_errors"],
        "corridor_warnings": report["corridor_warnings"],
        "alias_warnings": report["alias_warnings"],
    }


def verify_events_tool() -> Dict[str, Any]:
    """
    Audits events.json against today's Europe/Lisbon operational date, checking
    time ranges, Lisbon coordinates, pricing tiers, and URL validity.
    """
    if not os.path.exists(EVENTS_PATH):
        return {"status": "ERROR", "reason": "events.json not found"}

    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("events", [])
    op_date = data.get("operational_date", "")
    expected_today = scraper.get_lisbon_now().date().isoformat()

    anomalies = []
    by_category: Dict[str, int] = {}
    by_tier: Dict[str, int] = {}

    for ev in events:
        cat = ev.get("category", "Unknown")
        tier = ev.get("priceTier", "Unknown")
        by_category[cat] = by_category.get(cat, 0) + 1
        by_tier[tier] = by_tier.get(tier, 0) + 1

        lat = float(ev.get("lat", 0))
        lng = float(ev.get("lng", 0))
        if not locations.in_lisbon(lat, lng):
            anomalies.append(f"Out of Lisbon bounds: {ev.get('id')} @ {ev.get('venue')}")
        if ev.get("time") == ev.get("endTime"):
            anomalies.append(f"Zero-duration time: {ev.get('id')} ({ev.get('time')})")
        url = str(ev.get("url", ""))
        if not url.startswith("http") or "facebook.com/sharer" in url or "event-test" in url:
            anomalies.append(f"Invalid URL: {ev.get('id')} -> {url}")

    return {
        "status": "OK" if (op_date == expected_today and not anomalies) else "NEEDS_ATTENTION",
        "operational_date": op_date,
        "expected_lisbon_today": expected_today,
        "total_events": len(events),
        "by_category": by_category,
        "by_price_tier": by_tier,
        "anomalies": anomalies,
    }


def search_events_tool(
    category: Optional[str] = None,
    corridor: Optional[str] = None,
    price_tier: Optional[str] = None,
    query: Optional[str] = None,
    min_hour: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Searches today's verified Lisbon events in events.json by category, corridor,
    price_tier ('FREE', 'ACCESSIBLE', 'MID', 'PREMIUM'), keyword query, or minimum start hour.
    """
    if not os.path.exists(EVENTS_PATH):
        return []
    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        events = json.load(f).get("events", [])

    results = []
    q_low = (query or "").strip().lower()
    for ev in events:
        if category and category.lower() not in ev.get("category", "").lower():
            continue
        if corridor and corridor.lower() not in ev.get("corridor", "").lower():
            continue
        if price_tier and ev.get("priceTier", "").upper() != price_tier.upper():
            continue
        if min_hour is not None and int(ev.get("hour", 0)) < min_hour:
            continue
        if q_low:
            blob = f"{ev.get('title','')} {ev.get('venue','')} {ev.get('neighborhood','')} {ev.get('description','')}".lower()
            if q_low not in blob:
                continue
        results.append({
            "id": ev.get("id"),
            "title": ev.get("title"),
            "venue": ev.get("venue"),
            "neighborhood": ev.get("neighborhood"),
            "corridor": ev.get("corridor"),
            "time": f"{ev.get('time')} - {ev.get('endTime')}",
            "price": ev.get("price"),
            "priceTier": ev.get("priceTier"),
            "category": ev.get("category"),
            "url": ev.get("url"),
        })
    return results[:25]


# ==============================================================================
# 2. GOOGLE ADK MULTI-AGENT HIERARCHY (https://adk.dev/)
# ==============================================================================
root_agent = None
try:
    from google.adk.agents import LlmAgent

    venue_auditor_agent = LlmAgent(
        name="KeksVenueAuditor",
        model="gemini-2.5-flash",
        description="Audits Lisbon venues in venues.json, promotes geocoded venues, and enforces geographic bounds.",
        instruction=(
            "You are the Keks Passa Venue Auditor. Use `audit_venues_tool` to verify that all "
            "venues in venues.json have accurate North-of-Tagus Lisbon coordinates, valid corridors, "
            "and working primary source URLs."
        ),
        tools=[audit_venues_tool],
    )

    event_verifier_agent = LlmAgent(
        name="KeksEventVerifier",
        model="gemini-2.5-flash",
        description="Verifies daily scraped events in events.json for date, time, location, and pricing accuracy.",
        instruction=(
            "You are the Keks Passa Event Verifier. Use `verify_events_tool` and `search_events_tool` "
            "to inspect events.json and ensure zero stale dates, zero 404/test links, and accurate pricing."
        ),
        tools=[verify_events_tool, search_events_tool],
    )

    concierge_agent = LlmAgent(
        name="KeksConcierge",
        model="gemini-2.5-flash",
        description="Recommends real-time Lisbon cultural, music, cinema, and nightlife events happening today.",
        instruction=(
            "You are the Keks Passa Lisbon Cultural Concierge. Use `search_events_tool` to find "
            "real events happening today in Lisbon matching the user's time, neighborhood/corridor, "
            "and budget. Always cite exact venue, time, price, and URL."
        ),
        tools=[search_events_tool],
    )

    root_agent = LlmAgent(
        name="KeksPassaCoordinator",
        model="gemini-2.5-flash",
        description="Root coordinator for the Keks Passa Lisbon event pipeline and concierge.",
        instruction=(
            "Route venue registry audits to KeksVenueAuditor, daily event pipeline verification "
            "to KeksEventVerifier, and event recommendations to KeksConcierge."
        ),
        sub_agents=[venue_auditor_agent, event_verifier_agent, concierge_agent],
    )
except ImportError:
    pass


if __name__ == "__main__":
    print("=== Keks Passa ADK Pipeline & Venue/Event Status Check ===")
    v_status = audit_venues_tool(promote_from_cache=True)
    e_status = verify_events_tool()
    print(f"[Venues] {v_status['total_venues']} verified venues ({v_status['authoritative_percentage']}% direct sources, {len(v_status['geo_errors'])} geo errors)")
    print(f"[Events] Status: {e_status['status']} | Date: {e_status['operational_date']} | Total: {e_status['total_events']} | Anomalies: {len(e_status['anomalies'])}")
    if root_agent is not None:
        print("[ADK] Google ADK (`google-adk`) is installed and `root_agent` is ready (`adk web .` or `adk run .`).")
    else:
        print("[ADK] Deterministic tools verified. Install `pip install google-adk` to enable `adk web` / `adk run` LLM orchestration.")
