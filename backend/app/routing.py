import hashlib
import json
import math
import os

import httpx


def distance_m(a, b, factor=1.0):
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(6371000 * 2 * math.asin(min(1, math.sqrt(h))) * factor)


class Matrix:
    def __init__(self, locations, settings, storage=None):
        self.locations = locations
        self.settings = settings
        self.method = "estimate"
        self.notice = "Оценка по прямому расстоянию × дорожный коэффициент. Линии на карте не являются дорожной навигацией."
        key = hashlib.sha256(
            json.dumps(
                {
                    "locations": [p.model_dump() for p in locations],
                    "settings": settings.model_dump(
                        include={"routing_provider", "speeds_kmh", "road_factor"}
                    ),
                    "osrm": os.getenv("OSRM_URL", ""),
                    "v": 1,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cached = storage.matrix(key) if storage else None
        self.distances = [[distance_m(a, b, settings.road_factor) for b in locations] for a in locations]
        self.times = {
            mode: [[math.ceil(d / (speed * 1000 / 60)) for d in row] for row in self.distances]
            for mode, speed in settings.speeds_kmh.items()
        }
        if cached:
            self.distances = cached["distances"]
            self.car_distances = cached.get("car_distances", self.distances)
            self.times = cached["times"]
            self.method = cached["method"]
            self.notice = cached["notice"]
            return
        if settings.routing_provider == "osrm":
            try:
                base = os.environ.get("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
                coords = ";".join(f"{p.longitude},{p.latitude}" for p in locations)
                response = httpx.get(
                    f"{base}/table/v1/driving/{coords}",
                    params={"annotations": "duration,distance"},
                    timeout=3,
                )
                response.raise_for_status()
                body = response.json()
                size = len(locations)

                def valid_matrix(value):
                    return (
                        isinstance(value, list)
                        and len(value) == size
                        and all(
                            isinstance(row, list)
                            and len(row) == size
                            and all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in row)
                            for row in value
                        )
                    )

                if (
                    body.get("code") != "Ok"
                    or not valid_matrix(body.get("distances"))
                    or not valid_matrix(body.get("durations"))
                ):
                    raise ValueError("Недоступные дорожные сегменты")
                # Road distances apply to cars only; other modes retain their declared approximation.
                self.car_distances = [[round(d) for d in row] for row in body["distances"]]
                self.times["car"] = [[math.ceil(s / 60) for s in row] for row in body["durations"]]
                self.method = "osrm+estimate"
                self.notice = "Автомобиль: OSRM. Остальные виды транспорта: расчётная оценка. На карте - последовательность остановок."
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                self.notice = (
                    "OSRM недоступен. Использован резервный расчёт по расстоянию и скорости транспорта."
                )
        self.car_distances = getattr(self, "car_distances", self.distances)
        if storage and (settings.routing_provider != "osrm" or self.method != "estimate"):
            storage.save_matrix(
                key,
                {
                    "distances": self.distances,
                    "car_distances": self.car_distances,
                    "times": self.times,
                    "method": self.method,
                    "notice": self.notice,
                },
            )

    def meters(self, mode, a, b):
        return getattr(self, "car_distances", self.distances)[a][b] if mode == "car" else self.distances[a][b]

    def minutes(self, mode, a, b):
        return self.times[mode][a][b]
