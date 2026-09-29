"""One-time OSM address extraction. Cache responses; no random/synthetic coordinates."""

import json
import csv
import re
import os
import sys
import hashlib
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def query_overpass(query):
    request = urllib.request.Request(
        os.getenv("OVERPASS_URL", "https://overpass.kumi.systems/api/interpreter"),
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "EngineerRoutingPrototype/1.0 (one-time hackathon address preparation)"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def main():
    target = ROOT / "data" / "geo"
    target.mkdir(parents=True, exist_ok=True)
    streets = {}
    for path in (ROOT / "data" / "raw").glob("*Синтетические*.csv"):
        for row in csv.DictReader(path.read_text(encoding="cp1251").splitlines(), delimiter=";"):
            address = row.get("Адрес") or (
                row.get("Тип заявки BK") if row.get("Заявка", "").lower() == "адрес офиса" else ""
            )
            if not address:
                continue
            street, _ = address_parts(address)
            if "Кашира" in address:
                bbox = "54.80,38.10,54.90,38.30"
            elif "Ступино" in address:
                bbox = "54.85,38.02,54.96,38.17"
            elif "Домодедово" in address:
                bbox = "55.37,37.69,55.49,37.85"
            else:
                district = row.get("Район", "")
                centers = {
                    "Таганский": (55.743, 37.670),
                    "Текстильщики": (55.706, 37.734),
                    "Кузьминки": (55.697, 37.779),
                    "Рязанский": (55.718, 37.784),
                    "Нижегородский": (55.728, 37.721),
                    "Выхино": (55.711, 37.817),
                    "Лефортово": (55.759, 37.704),
                    "Басманный": (55.772, 37.689),
                    "Южнопортовый": (55.712, 37.678),
                    "Академический": (55.687, 37.579),
                    "Нагатинский Затон": (55.676, 37.704),
                    "Даниловский": (55.708, 37.639),
                    "Зюзино": (55.657, 37.591),
                    "Хамовники": (55.732, 37.579),
                    "Котловка": (55.677, 37.603),
                    "Нагатино - Садовники": (55.679, 37.639),
                    "Замоскворечье": (55.729, 37.627),
                    "Нагорный": (55.667, 37.615),
                    "GPON Даниловский": (55.708, 37.639),
                    "Донской": (55.707, 37.603),
                    "Гагаринский": (55.694, 37.550),
                    "Царицыно": (55.635, 37.670),
                    "Зябликово": (55.615, 37.744),
                    "Бирюлево Восточное": (55.591, 37.679),
                    "Орехово Борисово Северное": (55.614, 37.708),
                    "Орехово Борисово Южное": (55.597, 37.733),
                    "Братеево": (55.632, 37.760),
                    "Бирюлево Западное": (55.586, 37.645),
                    "Москворечье - Сабурово": (55.642, 37.688),
                }
                lat, lon = centers.get(district, (55.68, 37.68))
                bbox = f"{lat - 0.035},{lon - 0.055},{lat + 0.035},{lon + 0.055}"
            streets[street] = bbox
            words = street.split()
            if words and words[0] in {
                "улица",
                "проезд",
                "переулок",
                "бульвар",
                "проспект",
                "набережная",
                "шоссе",
            }:
                streets[" ".join(words[1:] + words[:1])] = bbox
    names = sorted(streets)
    for index, name in enumerate(names):
        path = target / f"osm-street-{hashlib.md5((name + streets[name]).encode()).hexdigest()[:12]}.json"
        if path.exists():
            print(f"Cached {path.name}", flush=True)
            continue
        query = f'[out:json][timeout:25];nwr["addr:street"={json.dumps(name, ensure_ascii=False)}]["addr:housenumber"]({streets[name]});out center tags;'
        try:
            result = query_overpass(query)
        except Exception as error:
            print(f"Unavailable {name}: {error}", flush=True)
            continue
        if "remark" in result:
            print(f"Incomplete {name}: {result['remark']}", flush=True)
            continue
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        print(f"{index + 1}/{len(names)} {name}: {len(result['elements'])} objects", flush=True)
        time.sleep(1.1)


def address_parts(address):
    text = re.sub(r"^.*?(?:Москва|Домодедово|Кашира|Ступино)[,\s]*", "", address, flags=re.I)
    chunks = re.split(r"\b(?:дом|д\.?)\s*(?=\d)", text, maxsplit=1, flags=re.I)
    street = chunks[0].strip(" ,.")
    house = chunks[1].strip(" ,.").split(",")[0] if len(chunks) > 1 else ""
    for short, long in [
        ("пр-кт.", "проспект "),
        ("пр-зд.", "проезд "),
        ("ул.", "улица "),
        ("пер.", "переулок "),
        ("наб.", "набережная "),
        ("б-р.", "бульвар "),
        ("ш.", "шоссе "),
        ("проезд.", "проезд "),
    ]:
        street = street.replace(short, long)
    street = re.sub(r"\bул\b", "улица", street)
    words = street.split()
    if words and words[-1] in {"улица", "проезд", "переулок", "бульвар", "проспект", "набережная", "шоссе"}:
        words = words[-1:] + words[:-1]
    street = " ".join(words)
    return street, house


if __name__ == "__main__":
    if "--probe" in sys.argv:
        print(
            json.dumps(
                query_overpass(
                    '[out:json][timeout:20];nwr["addr:street"="улица Юных Ленинцев"]["addr:housenumber"](55.65,37.7,55.75,37.85);out center tags;'
                ),
                ensure_ascii=False,
            )
        )
    else:
        main()
