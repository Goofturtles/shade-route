"""Shade Route — FastAPI application.

Milestone 0: health check, client configuration, and static hosting of the
single-page frontend. Routing arrives in Milestone 1, shade in Milestone 2.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import platform

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config

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
    """Liveness check plus the exact dependency versions in use."""
    return {
        "status": "ok",
        "milestone": 0,
        "python": platform.python_version(),
        "versions": _installed_versions(),
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


# Mounted last: a mount at "/" is greedy, so every real API route must be
# declared above it.
app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
