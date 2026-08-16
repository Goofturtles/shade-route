"""Shade Route — FastAPI application.

Serves the single-page frontend plus the routing API: `/api/route` returns the
shortest and the shadiest walk between two points, `/api/places` the named
destinations that populate the search box.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import platform
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import networkx as nx
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from app import config, graph, places, shade

app = FastAPI(
    title="Shade Route",
    description="Walking routes that maximise time spent in shade.",
    version="0.2.0",
)

# Guards the annotate-then-route section, which mutates the shared graph.
_routing_lock = threading.Lock()

# Packages whose versions we report, because the brief requires the project to
# run on a clean machine and version drift in the geo stack is the most likely
# way that breaks.
_REPORTED_PACKAGES = (
    "fastapi",
    "uvicorn",
    "osmnx",
    "networkx",
    "shapely",
    "geopandas",
    "pvlib",
    "pandas",
    "numpy",
)


def _installed_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in _REPORTED_PACKAGES:
        try:
            versions[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


@app.get("/health")
def health() -> dict:
    """Liveness check plus the exact dependency versions in use.

    Reports "degraded" rather than "ok" when part of the geo stack is missing.
    The server itself will happily start without OSMnx or pvlib installed, and
    an unqualified "ok" in that state would be a lie the frontend then repeats.
    """
    versions = _installed_versions()
    missing = sorted(name for name, value in versions.items() if value == "not installed")
    return {
        "status": "degraded" if missing else "ok",
        "missing": missing,
        "milestone": 2,
        "python": platform.python_version(),
        "versions": versions,
        # Lets the client warn that the first request will pause on a one-off
        # Overpass download rather than looking frozen.
        "graph_cached": graph.is_cached(),
    }


@app.get("/api/config")
def client_config() -> dict:
    """Single source of truth for values the frontend needs.

    The frontend never hardcodes the bounding box; it reads it from here so the
    map rectangle and the server's routing area can't disagree.
    """
    west, south, east, north = config.DEMO_BBOX
    return {
        "center": {"lat": config.DEMO_CENTER_LAT, "lon": config.DEMO_CENTER_LON},
        "bbox": {"west": west, "south": south, "east": east, "north": north},
        "timezone": config.TIMEZONE,
        "walking_speed_m_s": config.WALKING_SPEED_M_S,
        "area_label": "Inner Portland, Oregon",
    }


@app.get("/api/places")
def list_places() -> dict:
    """Named destinations inside the demo area.

    Exists so the interface can offer "Rite Aid Pharmacy" instead of asking for
    a latitude. Fetched from OSM once per process.
    """
    found = places.all_places()
    categories: dict[str, int] = {}
    for place in found:
        categories[place["category_label"]] = categories.get(place["category_label"], 0) + 1
    return {"count": len(found), "categories": categories, "places": found}


def _parse_when(raw: str | None) -> datetime:
    """Interpret the requested moment as Portland local time.

    A naive timestamp is what the interface sends ("2026-08-16T15:00"), and it
    means local time to the person typing it. pvlib will happily return a solar
    position that is wrong by hours if handed a naive value treated as UTC.
    """
    zone = ZoneInfo(config.TIMEZONE)
    if not raw:
        return datetime.now(zone)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read '{raw}' as a date and time. Expected ISO 8601, e.g. 2026-08-16T15:00.",
        )
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed


@app.get("/api/route")
def compute_route(
    orig_lat: float = Query(..., description="Origin latitude"),
    orig_lon: float = Query(..., description="Origin longitude"),
    dest_lat: float = Query(..., description="Destination latitude"),
    dest_lon: float = Query(..., description="Destination longitude"),
    when: str | None = Query(None, description="ISO 8601 local datetime; defaults to now"),
    shade_aversion: float = Query(
        1.5, ge=0.0, le=3.0,
        description="How much detour to accept for shade. 0 returns the shortest path.",
    ),
) -> dict:
    """Compute the shortest and the shadiest walking route between two points.

    Both routes come out of the same router over the same graph; the only thing
    that differs is the edge weight. At shade_aversion 0 the shade cost collapses
    to plain length, so the two routes become identical — which is what makes
    the comparison honest rather than two algorithms dressed up as a trade-off.
    """
    for label, lat, lon in (
        ("origin", orig_lat, orig_lon),
        ("destination", dest_lat, dest_lon),
    ):
        if not config.bbox_contains(lat, lon):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The {label} is outside the demo area. Street data has only "
                    "been downloaded for a 2 km by 2 km box of inner Portland."
                ),
            )

    walk_graph = graph.load_graph()
    orig_node = graph.nearest_node(walk_graph, orig_lat, orig_lon)
    dest_node = graph.nearest_node(walk_graph, dest_lat, dest_lon)

    if orig_node == dest_node:
        raise HTTPException(
            status_code=400,
            detail="Those two points snap to the same intersection. Move them further apart.",
        )

    moment = _parse_when(when)
    shade_field = shade.get_shade_field(moment)

    def build(route_id: str, label: str, weight: str) -> dict:
        node_path = graph.shortest_path(walk_graph, orig_node, dest_node, weight=weight)
        # `weight` is threaded through deliberately. Where two nodes are joined
        # by several parallel ways, the cheapest-by-length edge is not
        # necessarily the one the router took, and reading length, geometry or
        # shade off the wrong one misreports the headline metric.
        length_m = graph.route_length_m(walk_graph, node_path, weight)
        return {
            "id": route_id,
            "label": label,
            "coordinates": graph.route_coordinates(walk_graph, node_path, weight),
            "length_m": round(length_m, 1),
            "duration_s": round(length_m / config.WALKING_SPEED_M_S),
            "shade_fraction": round(
                shade.route_shade_fraction(walk_graph, node_path, weight), 4
            ),
            "_nodes": node_path,
        }

    # annotate_graph writes shade_cost onto the shared, process-wide graph, and
    # this is a sync endpoint so FastAPI runs it in a threadpool. Without this
    # lock, a second request at a different time or slider value could overwrite
    # those weights between our annotate and our Dijkstra, and we would return a
    # route computed against somebody else's settings. That is a wrong number
    # rather than a crash, which is precisely what the brief forbids.
    with _routing_lock:
        shade.annotate_graph(walk_graph, shade_field, shade_aversion)
        try:
            shortest = build("shortest", "Shortest route", "length")
            shadiest = build("shadiest", "Shadiest route", "shade_cost")
        except nx.NetworkXNoPath:
            raise HTTPException(
                status_code=422,
                detail="No walking route connects those two points inside the demo area.",
            )

    identical = shortest.pop("_nodes") == shadiest.pop("_nodes")
    sun_position = shade_field.sun

    return {
        "milestone": 2,
        "when": moment.isoformat(),
        "shade_aversion": shade_aversion,
        "sun": {
            "elevation_deg": round(sun_position.elevation_deg, 2),
            "azimuth_deg": round(sun_position.azimuth_deg, 2),
            "is_up": sun_position.sun_is_up,
            "casts_shadows": sun_position.casts_usable_shadows,
        },
        "routes": [shortest, shadiest],
        "comparison": {
            "identical": identical,
            "extra_distance_m": round(shadiest["length_m"] - shortest["length_m"], 1),
            "extra_duration_s": shadiest["duration_s"] - shortest["duration_s"],
            "shade_gain": round(shadiest["shade_fraction"] - shortest["shade_fraction"], 4),
        },
        "shade_sources": {
            "building_shadows": shade_field.building_count,
            "tree_shadows": shade_field.tree_count,
            "park_polygons": shade_field.park_count,
        },
        "assumptions": {
            "walking_speed_m_s": config.WALKING_SPEED_M_S,
            "walking_speed_note": (
                "Duration is computed from route length at a comfortable older-adult "
                "walking pace of 1.1 m/s. It is an assumption, not a measurement. "
                "Shade percentages are measured directly against modelled shadow "
                "geometry; no temperature difference is claimed."
            ),
        },
        "snapped": {
            "origin": [walk_graph.nodes[orig_node]["y"], walk_graph.nodes[orig_node]["x"]],
            "destination": [walk_graph.nodes[dest_node]["y"], walk_graph.nodes[dest_node]["x"]],
        },
    }


# Mounted last: a mount at "/" is greedy, so every real API route must be
# declared above it.
app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
