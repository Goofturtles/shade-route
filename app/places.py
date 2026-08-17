"""Named places inside the demo area, so nobody has to type coordinates.

Marisol walks to the pharmacy and the bus stop. Those are real objects in
OpenStreetMap with real names, and offering them by name is both kinder than a
latitude box and a better demonstration of what the project is for.

Two deliberate choices here, both learned the hard way:

* **One Overpass query, not one per category.** An earlier version issued eight
  separate requests and was rate-limited into connection timeouts. OSMnx ORs a
  multi-key tag dict into a single query.
* **Cached to disk, not just to memory.** Overpass is a shared public service.
  Refetching on every process start is rude, slow, and a live demo risk.
"""

from __future__ import annotations

import json
import logging
import threading

import osmnx as ox

from app import config

log = logging.getLogger("shade_route.places")

def places_file(area=None):
    """Per-area cache file. Portland keeps the committed unsuffixed name."""
    area = area or config.current_area()
    if area.id == "portland":
        return config.CACHE_DIR / "places.json"
    safe = area.id.replace(",", "_").replace(".", "p").replace("-", "m")
    return config.CACHE_DIR / f"places_{safe}.json"


PLACES_FILE = config.CACHE_DIR / "places.json"

# One combined query. OSMnx turns a multi-key dict into a single Overpass
# request with the clauses OR'd together.
COMBINED_TAGS: dict[str, list[str]] = {
    "amenity": ["pharmacy", "clinic", "doctors", "hospital", "library", "cafe", "post_office"],
    "shop": ["supermarket", "convenience"],
    "highway": ["bus_stop"],
    "leisure": ["park"],
}

# (tag key, tag value) -> (category key, human label). Ordered by relevance to
# the user story: the pharmacy and the bus stop come first.
CATEGORY_OF: dict[tuple[str, str], tuple[str, str]] = {
    ("amenity", "pharmacy"): ("pharmacy", "Pharmacy"),
    ("highway", "bus_stop"): ("bus_stop", "Bus stop"),
    ("shop", "supermarket"): ("supermarket", "Groceries"),
    ("shop", "convenience"): ("supermarket", "Groceries"),
    ("amenity", "clinic"): ("healthcare", "Healthcare"),
    ("amenity", "doctors"): ("healthcare", "Healthcare"),
    ("amenity", "hospital"): ("healthcare", "Healthcare"),
    ("amenity", "library"): ("library", "Library"),
    ("leisure", "park"): ("park", "Park"),
    ("amenity", "cafe"): ("cafe", "Cafe"),
    ("amenity", "post_office"): ("post_office", "Post office"),
}

CATEGORY_ORDER = [
    "Pharmacy", "Bus stop", "Groceries", "Healthcare",
    "Library", "Park", "Cafe", "Post office",
]

_cache: dict[str, list[dict]] = {}
_lock = threading.Lock()


def _centroid(geom) -> tuple[float, float] | None:
    if geom is None or geom.is_empty:
        return None
    point = geom if geom.geom_type == "Point" else geom.centroid
    return (float(point.y), float(point.x))


def _classify(row) -> tuple[str, str] | None:
    for tag_key in COMBINED_TAGS:
        value = row.get(tag_key)
        if isinstance(value, str):
            found = CATEGORY_OF.get((tag_key, value))
            if found:
                return found
    return None


def _download() -> list[dict]:
    config.configure_osmnx()
    log.info("Fetching named places from OpenStreetMap (single combined query) ...")
    try:
        gdf = config.with_overpass_fallback(
            lambda: ox.features_from_bbox(config.DEMO_BBOX, COMBINED_TAGS)
        )
    except Exception as exc:  # noqa: BLE001 - the app must still work without this
        log.warning("Could not fetch places: %s", exc)
        return []

    if gdf.empty:
        return []

    found: list[dict] = []
    names = gdf["name"] if "name" in gdf.columns else None

    for position, (_, row) in enumerate(gdf.iterrows()):
        coords = _centroid(row.geometry)
        if coords is None:
            continue
        lat, lon = coords
        if not config.bbox_contains(lat, lon):
            continue
        classified = _classify(row)
        if classified is None:
            continue
        category_key, category_label = classified

        name = None
        if names is not None:
            raw = names.iloc[position]
            if isinstance(raw, str) and raw.strip():
                name = raw.strip()
        if name is None:
            # An unnamed pharmacy is useless in a picker, but an unnamed bus
            # stop is still somewhere you can walk to.
            if category_key != "bus_stop":
                continue
            name = "Bus stop"

        found.append({
            "name": name,
            "category": category_key,
            "category_label": category_label,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
        })

    # OSM often carries the same feature as both a node and a way.
    seen: set[tuple] = set()
    unique: list[dict] = []
    for place in found:
        key = (place["name"], place["category"], round(place["lat"], 4), round(place["lon"], 4))
        if key in seen:
            continue
        seen.add(key)
        unique.append(place)

    order = {label: index for index, label in enumerate(CATEGORY_ORDER)}
    unique.sort(key=lambda p: (order.get(p["category_label"], 99), p["name"]))
    return unique


def all_places(refresh: bool = False) -> list[dict]:
    """Every named place in the demo area. Disk-cached; fetched at most once."""
    aid = config.current_area().id
    hit = _cache.get(aid)
    if hit is not None and not refresh:
        return hit

    with _lock:
        hit = _cache.get(aid)
        if hit is not None and not refresh:
            return hit

        path = places_file()
        if path.exists() and not refresh:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                log.info("Loaded %d places from %s", len(loaded), path)
                _cache[aid] = loaded
                return loaded
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Places cache unreadable (%s); refetching.", exc)

        places = _download()
        if places:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(places, indent=1), encoding="utf-8")
            log.info("Cached %d places to %s", len(places), path)
        _cache[aid] = places
    return places


def is_loaded() -> bool:
    return config.current_area().id in _cache or places_file().exists()
