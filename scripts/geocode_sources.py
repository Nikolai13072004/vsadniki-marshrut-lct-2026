"""One-time, single-machine preparation only; no runtime calls or autocomplete.

Nominatim policy: https://operations.osmfoundation.org/policies/nominatim/
At most one request per 1.1 sec, one thread; every response including misses cached.
Only building addresses from supplied synthetic data, never apartment numbers/names.
"""

import csv
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.importer import normalize_address  # noqa: E402
from prepare_geodata import address_parts  # noqa: E402


def norm(value):
    return re.sub(
        r"[^а-яa-z0-9/]",
        "",
        value.lower()
        .replace("ё", "е")
        .replace("корпус", "к")
        .replace("строение", "с")
        .replace("стр.", "с")
        .replace("стр", "с"),
    )


def main():
    cache_dir = ROOT / "data" / "geo" / "nominatim"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = ROOT / "data" / "geocodes.json"
    result = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    addresses = []
    for path in sorted((ROOT / "data" / "raw").glob("*Синтетические*.csv")):
        for row in csv.DictReader(path.read_text(encoding="cp1251").splitlines(), delimiter=";"):
            address = row.get("Адрес") or (
                row.get("Тип заявки BK") if row.get("Заявка", "").lower() == "адрес офиса" else ""
            )
            if address and normalize_address(address) not in addresses:
                addresses.append(normalize_address(address))
    for i, address in enumerate(addresses):
        if result.get(address, {}).get("location"):
            continue
        street, house = address_parts(address)
        words = street.split()
        if (
            "--retry" in sys.argv
            and words
            and words[0] in {"улица", "проезд", "бульвар", "проспект", "набережная", "переулок", "шоссе"}
        ):
            street = " ".join(words[1:] + words[:1])
        if "--retry" in sys.argv:
            house = norm(house)
        city = next((city for city in ("Домодедово", "Кашира", "Ступино") if city in address), "Москва")
        query = f"{city}, {street}, {house}"
        key = hashlib.sha256(query.encode()).hexdigest()[:20]
        path = cache_dir / f"{key}.json"
        if path.exists():
            hits = json.loads(path.read_text(encoding="utf-8"))
        else:
            params = urllib.parse.urlencode(
                {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 5, "countrycodes": "ru"}
            )
            request = urllib.request.Request(
                "https://nominatim.openstreetmap.org/search?" + params,
                headers={
                    "User-Agent": "EngineerRoutingHackathon/1.0 (one-time synthetic building-address preparation)",
                    "Accept-Language": "ru",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    hits = json.load(response)
                path.write_text(json.dumps(hits, ensure_ascii=False), encoding="utf-8")
            except Exception as error:
                print(f"FAILED {query}: {error}", flush=True)
                time.sleep(1.1)
                continue
            time.sleep(1.1)
        matched = [
            h
            for h in hits
            if 54.6 < float(h["lat"]) < 56
            and 37.2 < float(h["lon"]) < 38.6
            and norm(h.get("address", {}).get("house_number", "")) == norm(house)
        ]
        if matched:
            hit = matched[0]
            result[address] = {
                "location": {"latitude": float(hit["lat"]), "longitude": float(hit["lon"])},
                "quality": "house",
                "source": "Nominatim / OpenStreetMap",
                "query": query,
                "matched_address": hit["display_name"],
                "osm_type": hit.get("osm_type"),
                "osm_id": hit.get("osm_id"),
                "checked": "house number and region bounds",
            }
        else:
            result[address] = {"location": None, "quality": "missing", "query": query, "candidates": hits[:2]}
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{i + 1}/{len(addresses)} {'OK' if matched else 'MISSING'} {query}", flush=True)


if __name__ == "__main__":
    main()
