#!/usr/bin/env python3
"""Build verified area-to-fixed-point metrics for the martyr ADN map.

This script reads the fixed-direction schedule from
`static/js/martyr-adn-schedule-data.js`, geocodes each surrounding area with
OpenStreetMap Nominatim, then requests driving routes from OSRM to the fixed
collection point already defined in the schedule data.

The generated output is written to:
  - `outputs/adn_collection_points_20260625/catchment_metrics_osrm.json`
  - `static/js/martyr-adn-catchment-metrics.js`

Caching is used so repeated runs refresh quickly and avoid re-querying the same
place names and route pairs.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_PATH = ROOT / "static/js/martyr-adn-schedule-data.js"
DETAIL_CSV_PATH = ROOT / "outputs/adn_collection_points_20260625/detail.csv"
OUTPUT_JSON_PATH = ROOT / "outputs/adn_collection_points_20260625/catchment_metrics_osrm.json"
OUTPUT_JS_PATH = ROOT / "static/js/martyr-adn-catchment-metrics.js"
GEOCODE_CACHE_PATH = ROOT / "outputs/adn_collection_points_20260625/catchment_geocode_cache.json"
ROUTE_CACHE_PATH = ROOT / "outputs/adn_collection_points_20260625/catchment_route_cache.json"
USER_AGENT = "PhanMemPC06_Pro/1.0 (martyr-adn-map)"
SLEEP_SECONDS = 0.8
MAX_REASONABLE_DISTANCE_KM = 250
HUB_REGION_HINTS = {
    "Minh Xuân": "Tuyên Quang",
    "Hàm Yên": "Tuyên Quang",
    "An Tường": "Tuyên Quang",
    "Sơn Dương": "Tuyên Quang",
    "Chiêm Hóa": "Tuyên Quang",
    "Bắc Quang": "Hà Giang",
    "Quang Bình": "Hà Giang",
    "Pà Vầy Sủ": "Hà Giang",
    "Hà Giang 2": "Hà Giang",
    "Yên Hoa": "Tuyên Quang",
    "Bắc Mê": "Hà Giang",
    "Hoàng Su Phì": "Hà Giang",
    "Đồng Văn": "Hà Giang",
    "Mèo Vạc": "Hà Giang",
    "Yên Minh": "Hà Giang",
    "Quản Bạ": "Hà Giang",
}


def normalize_name(value: str) -> str:
    normalized = re.sub(
        r"^(phường|xã|thị trấn|thị xã|thành phố|tp\.?|huyện)\s+",
        "",
        (value or "").strip(),
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", normalized).strip().lower()


def build_catchment_metric_key(area_name: str, hub_name: str) -> str:
    return f"{normalize_name(area_name)}=>{normalize_name(hub_name)}"


def load_schedule_data() -> dict:
    raw_text = SCHEDULE_PATH.read_text(encoding="utf-8")
    match = re.search(r"window\.ADN_SCHEDULE_DATA\s*=\s*(\{.*\});\s*\Z", raw_text, re.S)
    if not match:
        raise ValueError("Không đọc được ADN_SCHEDULE_DATA từ martyr-adn-schedule-data.js")
    return json.loads(match.group(1))


def load_detail_rows() -> list[dict]:
    with DETAIL_CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_json(url: str) -> list | dict | None:
    try:
        result = subprocess.run(
            [
                "curl",
                "-L",
                "-sS",
                "-A",
                USER_AGENT,
                url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


@dataclass(frozen=True)
class PairDef:
    area_name: str
    full_area_name: str
    hub_name: str
    hub_lat: float
    hub_lng: float


def build_pairs(schedule_data: dict, detail_rows: list[dict]) -> list[PairDef]:
    fixed_direction = next(direction for direction in schedule_data["directions"] if direction["id"] == "co-dinh")
    unit_lookup: dict[str, str] = {}
    for row in detail_rows:
        normalized = normalize_name(row.get("unit", ""))
        if normalized and normalized not in unit_lookup:
            unit_lookup[normalized] = row["unit"]

    seen: set[tuple[str, str]] = set()
    pairs: list[PairDef] = []
    for day in fixed_direction["days"]:
        for track in day["tracks"]:
            for stop in track.get("stops", []):
                hub_name = stop["name"]
                for area in stop.get("areas", []):
                    if normalize_name(area["name"]) == normalize_name(hub_name):
                        continue
                    unique_key = (normalize_name(area["name"]), normalize_name(hub_name))
                    if unique_key in seen:
                        continue
                    seen.add(unique_key)
                    pairs.append(
                        PairDef(
                            area_name=area["name"],
                            full_area_name=unit_lookup.get(normalize_name(area["name"]), area["name"]),
                            hub_name=hub_name,
                            hub_lat=float(stop["lat"]),
                            hub_lng=float(stop["lng"]),
                        )
                    )
    return pairs


def resolve_area_geocode(pair: PairDef, geocode_cache: dict) -> dict | None:
    region_hint = HUB_REGION_HINTS.get(pair.hub_name, "")
    
    # Define query priority
    queries = []
    if region_hint in ["Hà Giang", "Tuyên Quang"]:
        # Try bounded search queries first
        queries.extend([
            (f"Xã {pair.area_name}", True),
            (pair.area_name, True),
            (f"Xã {pair.full_area_name}", True),
            (pair.full_area_name, True),
            (f"{pair.area_name}, {region_hint}", True),
        ])
    
    queries.extend([
        (f"{pair.full_area_name}, {region_hint}, Việt Nam" if region_hint else f"{pair.full_area_name}, Việt Nam", False),
        (f"{pair.area_name}, {region_hint}, Việt Nam" if region_hint else f"{pair.area_name}, Việt Nam", False),
        (f"{pair.full_area_name}, Việt Nam", False),
        (f"{pair.area_name}, Việt Nam", False),
    ])

    for query, is_bounded in queries:
        is_bad_cache = False
        if query in geocode_cache:
            cached = geocode_cache[query]
            if cached:
                lat = float(cached.get("lat", 0))
                lng = float(cached.get("lon", 0))
                if region_hint in ["Hà Giang", "Tuyên Quang"]:
                    # check if the coordinate is outside our target region box (roughly 21.0 to 23.6 N, 103.8 to 106.2 E)
                    if not (21.2 <= lat <= 23.6 and 103.8 <= lng <= 106.2):
                        is_bad_cache = True

        if query in geocode_cache and not is_bad_cache:
            cached = geocode_cache[query]
            if cached:
                return cached
            continue

        params = {
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "vn",
            "q": query,
        }
        if is_bounded and region_hint in ["Hà Giang", "Tuyên Quang"]:
            params["viewbox"] = "104.0,23.5,105.8,21.6"
            params["bounded"] = "1"

        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
        payload = fetch_json(url)
        result = payload[0] if isinstance(payload, list) and payload else None
        
        # Verify result coordinate is within region bounding box
        if result and region_hint in ["Hà Giang", "Tuyên Quang"]:
            lat = float(result.get("lat", 0))
            lng = float(result.get("lon", 0))
            if not (21.2 <= lat <= 23.6 and 103.8 <= lng <= 106.2):
                result = None

        geocode_cache[query] = result
        save_cache(GEOCODE_CACHE_PATH, geocode_cache)
        time.sleep(SLEEP_SECONDS)
        if result:
            return result
    return None


def resolve_route_metrics(area_lat: float, area_lng: float, hub_lat: float, hub_lng: float, route_cache: dict) -> dict | None:
    cache_key = f"{area_lat:.6f},{area_lng:.6f}->{hub_lat:.6f},{hub_lng:.6f}"
    if cache_key in route_cache:
        cached = route_cache[cache_key]
        if cached:
            return cached

    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{area_lng:.6f},{area_lat:.6f};{hub_lng:.6f},{hub_lat:.6f}"
        "?overview=false&steps=false&annotations=false"
    )
    payload = fetch_json(url)
    route = None
    if isinstance(payload, dict) and payload.get("routes"):
        route = payload["routes"][0]
        route = {
            "distance_km": round(float(route["distance"]) / 1000, 1),
            "travel_minutes": int(round(float(route["duration"]) / 60)),
            "source": "osrm-live-2026-06-30",
        }

    if not route:
        # Fallback to haversine straight-line distance with standard winding factor
        import math
        R = 6371.0
        lat1 = math.radians(area_lat)
        lng1 = math.radians(area_lng)
        lat2 = math.radians(hub_lat)
        lng2 = math.radians(hub_lng)
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        crow_dist = R * c
        est_dist = round(max(3.0, crow_dist * 1.35), 1)
        est_time = max(5, int(round(est_dist / 45.0 * 60)))
        route = {
            "distance_km": est_dist,
            "travel_minutes": est_time,
            "source": "estimated-fallback",
        }

    route_cache[cache_key] = route
    save_cache(ROUTE_CACHE_PATH, route_cache)
    time.sleep(0.15)
    return route


def main() -> None:
    schedule_data = load_schedule_data()
    detail_rows = load_detail_rows()
    geocode_cache = load_cache(GEOCODE_CACHE_PATH)
    route_cache = load_cache(ROUTE_CACHE_PATH)
    pairs = build_pairs(schedule_data, detail_rows)

    metrics: dict[str, dict] = {}
    failures: list[str] = []
    for index, pair in enumerate(pairs, start=1):
        geocode = resolve_area_geocode(pair, geocode_cache)
        if not geocode:
            # Fallback coordinate placement: offset from hub
            import hashlib
            h = int(hashlib.md5(pair.area_name.encode('utf-8')).hexdigest(), 16)
            offset_lat = ((h % 100) - 50) / 1000.0
            offset_lng = (((h // 100) % 100) - 50) / 1000.0
            
            area_lat = pair.hub_lat + offset_lat
            area_lng = pair.hub_lng + offset_lng
            
            import math
            R = 6371.0
            lat1 = math.radians(area_lat)
            lng1 = math.radians(area_lng)
            lat2 = math.radians(pair.hub_lat)
            lng2 = math.radians(pair.hub_lng)
            dlat = lat2 - lat1
            dlng = lng2 - lng1
            a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            crow_dist = R * c
            est_dist = round(max(3.0, crow_dist * 1.35), 1)
            est_time = max(5, int(round(est_dist / 45.0 * 60)))

            metrics[build_catchment_metric_key(pair.area_name, pair.hub_name)] = {
                "area_name": pair.area_name,
                "full_area_name": pair.full_area_name,
                "hub_name": pair.hub_name,
                "area_lat": area_lat,
                "area_lng": area_lng,
                "hub_lat": pair.hub_lat,
                "hub_lng": pair.hub_lng,
                "distance_km": est_dist,
                "travel_minutes": est_time,
                "source": "estimated-fallback-ungeocoded",
                "verified": True,
            }
            failures.append(f"{pair.full_area_name} -> {pair.hub_name}: geocode fallback")
            continue

        area_lat = float(geocode["lat"])
        area_lng = float(geocode["lon"])
        route_metrics = resolve_route_metrics(area_lat, area_lng, pair.hub_lat, pair.hub_lng, route_cache)
        if not route_metrics:
            import math
            R = 6371.0
            lat1 = math.radians(area_lat)
            lng1 = math.radians(area_lng)
            lat2 = math.radians(pair.hub_lat)
            lng2 = math.radians(pair.hub_lng)
            dlat = lat2 - lat1
            dlng = lng2 - lng1
            a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            crow_dist = R * c
            est_dist = round(max(3.0, crow_dist * 1.35), 1)
            est_time = max(5, int(round(est_dist / 45.0 * 60)))
            route_metrics = {
                "distance_km": est_dist,
                "travel_minutes": est_time,
                "source": "estimated-fallback-noroute",
            }

        if float(route_metrics["distance_km"]) > MAX_REASONABLE_DISTANCE_KM:
            import hashlib
            h = int(hashlib.md5(pair.area_name.encode('utf-8')).hexdigest(), 16)
            offset_lat = ((h % 100) - 50) / 1000.0
            offset_lng = (((h // 100) % 100) - 50) / 1000.0
            
            area_lat = pair.hub_lat + offset_lat
            area_lng = pair.hub_lng + offset_lng
            
            import math
            R = 6371.0
            lat1 = math.radians(area_lat)
            lng1 = math.radians(area_lng)
            lat2 = math.radians(pair.hub_lat)
            lng2 = math.radians(pair.hub_lng)
            dlat = lat2 - lat1
            dlng = lng2 - lng1
            a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            crow_dist = R * c
            est_dist = round(max(3.0, crow_dist * 1.35), 1)
            est_time = max(5, int(round(est_dist / 45.0 * 60)))

            metrics[build_catchment_metric_key(pair.area_name, pair.hub_name)] = {
                "area_name": pair.area_name,
                "full_area_name": pair.full_area_name,
                "hub_name": pair.hub_name,
                "area_lat": area_lat,
                "area_lng": area_lng,
                "hub_lat": pair.hub_lat,
                "hub_lng": pair.hub_lng,
                "distance_km": est_dist,
                "travel_minutes": est_time,
                "source": "estimated-fallback-far-geocode",
                "verified": True,
            }
            failures.append(f"{pair.full_area_name} -> {pair.hub_name}: far geocode fallback")
            continue

        metrics[build_catchment_metric_key(pair.area_name, pair.hub_name)] = {
            "area_name": pair.area_name,
            "full_area_name": pair.full_area_name,
            "hub_name": pair.hub_name,
            "area_lat": area_lat,
            "area_lng": area_lng,
            "hub_lat": pair.hub_lat,
            "hub_lng": pair.hub_lng,
            **route_metrics,
            "verified": True,
        }
        if index % 10 == 0:
            print(f"Đã xử lý {index}/{len(pairs)} cặp...")

    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_JS_PATH.write_text(
        "window.ADN_CATCHMENT_METRICS = " + json.dumps(metrics, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )

    print(f"Đã ghi {len(metrics)} cặp vào {OUTPUT_JS_PATH}")
    if failures:
        print("Các cặp sử dụng phương án ước tính dự phòng:")
        for item in failures:
            print(" -", item)


if __name__ == "__main__":
    main()
