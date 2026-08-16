"""Shade Route — FastAPI application.

Milestone 0: health check, client configuration, and static hosting of the
single-page frontend. Routing arrives in Milestone 1, shade in Milestone 2.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import platform

import networkx as nx
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from app import config, graph

app = FastAPI(
    title="Shade Route",
    description="Walking routes that maximise time spent in shade.",
    version="0.1.0",
)

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
        "milestone": 1,
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


@app.get("/api/route")
def compute_route(
    orig_lat: float = Query(..., description="Origin latitude"),
    orig_lon: float = Query(..., description="Origin longitude"),
    dest_lat: float = Query(..., description="Destination latitude"),
    dest_lon: float = Query(..., description="Destination longitude"),
) -> dict:
    """Compute walking routes between two points.

    Milestone 1 returns only the shortest route. The response is already shaped
    as a *list* of routes so that M2 adds the shadiest one alongside it without
    the client having to change how it reads the payload.
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

    try:
        node_path = graph.shortest_path(walk_graph, orig_node, dest_node, weight="length")
    except nx.NetworkXNoPath:
        raise HTTPException(
            status_code=422,
            detail="No walking route connects those two points inside the demo area.",
        )

    length_m = graph.route_length_m(walk_graph, node_path)
    coordinates = graph.route_coordinates(walk_graph, node_path)

    return {
        "milestone": 1,
        "routes": [
            {
                "id": "shortest",
                "label": "Shortest route",
                "coordinates": coordinates,
                "length_m": round(length_m, 1),
                "duration_s": round(length_m / config.WALKING_SPEED_M_S),
                # Explicitly null rather than absent or zero: the shade model
                # does not exist yet, and a 0 here would read as "no shade".
                "shade_fraction": None,
            }
        ],
        "assumptions": {
            "walking_speed_m_s": config.WALKING_SPEED_M_S,
            "walking_speed_note": (
                "Duration is computed from route length at a comfortable older-adult "
                "walking pace. It is an assumption, not a measurement."
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
