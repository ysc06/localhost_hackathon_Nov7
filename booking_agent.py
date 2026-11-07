"""
Discovery & Booking Agent: turns the WINNING plan into real-world places and search links.

Privacy: it only receives the winning public Plan + a city/date the user typed.
No friend data, votes, vetoes or memory ever reach Google.
Honesty: businesses come only from the Google Places API; without a key we return
plain Google Maps / Google Search URLs. Nothing is invented, nothing is booked.
"""
import os
from urllib.parse import quote_plus

import httpx
from dotenv import load_dotenv

load_dotenv()

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "places.displayName,places.formattedAddress,places.googleMapsUri,places.rating,places.websiteUri"


def _public_details(winner) -> tuple[str, str]:
    """Accept a Plan, a dict or a plain string; keep only public name + activity type."""
    if isinstance(winner, str):
        return winner, ""
    if isinstance(winner, dict):
        return winner.get("name", ""), winner.get("activity", "")
    return winner.name, getattr(winner, "activity", "")


def _google_search(q: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(q)}"


def _maps_search(q: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(q)}"


def _places_api(query: str, key: str, limit: int = 3) -> list[dict]:
    resp = httpx.post(
        PLACES_URL,
        headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS},
        json={"textQuery": query, "pageSize": limit},
        timeout=10,
    )
    resp.raise_for_status()
    return [
        {
            "name": p.get("displayName", {}).get("text", ""),
            "address": p.get("formattedAddress", ""),
            "rating": p.get("rating"),
            "maps_url": p.get("googleMapsUri", ""),
            "website": p.get("websiteUri", ""),
        }
        for p in resp.json().get("places", [])[:limit]
    ]


def discover_options(winner, city: str = "New York", date=None) -> dict:
    name, activity = _public_details(winner)
    city = (city or "New York").strip()
    when = f" {date}" if date else ""
    query = f"{name} in {city}"

    result = {
        "activity": name,
        "activity_type": activity,
        "location": city,
        "date": str(date) if date else None,
        "source": "search_links",
        "places": [],  # only filled from the real Places API
        "error": None,
        "links": {
            "places": _maps_search(query),
            "events": _google_search(f"{name} events tickets {city}{when}"),
            "booking": _google_search(f"book {name} reservation {city}{when}"),
        },
    }

    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if key:
        try:
            result["places"] = _places_api(query, key)
            result["source"] = "google_places_api"
        except Exception as e:  # bad key / quota / network -> links still work
            result["error"] = f"Google Places unavailable ({type(e).__name__}), showing search links."
    return result


if __name__ == "__main__":
    from models import load_activities

    acts = {a.id: a for a in load_activities()}
    for plan in (acts[6], acts[2], acts[7]):  # restaurant, karaoke, concert
        r = discover_options(plan, "New York", "2026-11-08")
        print(f"\n{r['activity']} ({r['activity_type']}) | source={r['source']} {r['error'] or ''}")
        for p in r["places"]:
            print("  •", p["name"], "|", p["address"], "|", p["maps_url"])
        for k, v in r["links"].items():
            print(f"  {k}: {v}")
