"""Apply explicitly documented address variants, never a silent nearest-point substitution."""

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from geocode_sources import norm

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "data" / "geocodes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    reviews = json.loads((ROOT / "data" / "address-review.json").read_text(encoding="utf-8"))
    for review in reviews:
        keys = [key for key in data if review["contains"] in key and data[key].get("location") is None]
        if not keys:
            continue
        query = review["query"]
        cache = (
            ROOT / "data" / "geo" / "nominatim" / f"{hashlib.sha256(query.encode()).hexdigest()[:20]}.json"
        )
        if cache.exists():
            hits = json.loads(cache.read_text(encoding="utf-8"))
        else:
            params = urllib.parse.urlencode(
                {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 5, "countrycodes": "ru"}
            )
            request = urllib.request.Request(
                "https://nominatim.openstreetmap.org/search?" + params,
                headers={
                    "User-Agent": "EngineerRoutingHackathon/1.0 (one-time prepared dataset)",
                    "Accept-Language": "ru",
                },
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                hits = json.load(response)
            cache.write_text(json.dumps(hits, ensure_ascii=False), encoding="utf-8")
            time.sleep(1.1)
        matched = [
            h for h in hits if norm(h.get("address", {}).get("house_number", "")) == norm(review["house"])
        ]
        print(
            query, [(h.get("address", {}).get("house_number"), h["lat"], h["lon"]) for h in hits], flush=True
        )
        if matched:
            hit = matched[0]
            for key in keys:
                data[key] = {
                    "location": {"latitude": float(hit["lat"]), "longitude": float(hit["lon"])},
                    "quality": review["quality"],
                    "query": query,
                    "source": "Nominatim / OpenStreetMap",
                    "matched_address": hit["display_name"],
                    "osm_type": hit.get("osm_type"),
                    "osm_id": hit.get("osm_id"),
                    "note": review["note"],
                }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
