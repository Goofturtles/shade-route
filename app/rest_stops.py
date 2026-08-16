"""Benches and drinking fountains — the places Marisol can stop.

Separate from `places.py`, which handles *named destinations* you search for.
These are unnamed street furniture: you never look one up, you only ever ask
"is there somewhere to sit between here and there?"

Same two lessons as places.py: one combined Overpass query, and a disk cache so
a shared public service is asked at most once.
"""

from __future__ import annotations

import json
import logging
import threading

import osmnx as ox

from app import config

log = logging.getLogger("shade_route.rest_stops")

REST_STOPS_FILE = config.CACHE_DIR / "rest_stops.json"

TAGS: dict[str, list[str]] = {"amenity": ["bench", "drinking_water"]}

_cache: list[dict] | None = None
_lock = threading.Lock()


def _download() -> list[dict]:
    config.configure_osmnx()
    log.info("Fetching benches and drinking fountains from OpenStreetMap ...")
    try:
        gdf = ox.features_from_bbox(config.DEMO_BBOX, TAGS)
    except Exception as exc:  # noqa: BLE001 - the route still works without these
        log.warning("Could not fetch rest stops: %s", exc)
        return []

    if gdf.empty:
        return []

    found: list[dict] = []
    amenities = gdf["amenity"] if "amenity" in gdf.columns else None
    if amenities is None:
        return []

    for position, (_, row) in enumerate(gdf.iterrows()):
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        point = geom if geom.geom_type == "Point" else geom.centroid
        lat, lon = float(point.y), float(point.x)
        if not config.bbox_contains(lat, lon):
            continue
        kind = amenities.iloc[position]
        if kind not in ("bench", "drinking_water"):
            continue
        found.append({"kind": kind, "lat": round(lat, 6), "lon": round(lon, 6)})

    seen: set[tuple] = set()
    unique: list[dict] = []
    for stop in found:
        key = (stop["kind"], round(stop["lat"], 5), round(stop["lon"], 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append(stop)
    return unique


def all_rest_stops(refresh: bool = False) -> list[dict]:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    with _lock:
        if _cache is not None and not refresh:
            return _cache
        if REST_STOPS_FILE.exists() and not refresh:
            try:
                _cache = json.loads(REST_STOPS_FILE.read_text(encoding="utf-8"))
                log.info("Loaded %d rest stops from %s", len(_cache), REST_STOPS_FILE)
                return _cache
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Rest-stop cache unreadable (%s); refetching.", exc)
        stops = _download()
        if stops:
            REST_STOPS_FILE.parent.mkdir(parents=True, exist_ok=True)
            REST_STOPS_FILE.write_text(json.dumps(stops, indent=1), encoding="utf-8")
            log.info("Cached %d rest stops to %s", len(stops), REST_STOPS_FILE)
        _cache = stops
    return _cache


def is_loaded() -> bool:
    return _cache is not None or REST_STOPS_FILE.exists()
