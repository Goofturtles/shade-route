"""Static configuration for the Shade Route demo.

The bounding box is *derived* from a centre point and a half-extent in metres
rather than hand-typed, so the four corners cannot drift out of sync with each
other. Every magic number in this file carries the reason it exists.
"""

from __future__ import annotations

import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
CACHE_DIR = REPO_ROOT / "cache"

# Inner Portland, Oregon. Chosen because it is the city in the user story, and
# because it combines dense downtown buildings with unusually well-mapped
# street trees in OpenStreetMap.
DEMO_CENTER_LAT = 45.5220
DEMO_CENTER_LON = -122.6750

# Half-extent of the demo bounding box in metres, giving a ~2 km x 2 km area.
# The shade computation is O(edges x shadow polygons); a small box is what
# keeps it interactive.
DEMO_HALF_EXTENT_M = 1000.0

# Portland local time. pvlib needs timezone-aware datetimes or the solar
# position will be silently wrong by up to 8 hours.
TIMEZONE = "America/Los_Angeles"

# Walking speed used to convert route length into a duration.
# 1.1 m/s is a comfortable pace for an older adult on level ground. It is an
# assumption, not a measurement, and the UI labels it as such.
WALKING_SPEED_M_S = 1.1

_M_PER_DEG_LAT = 111_320.0


def _derive_bbox() -> tuple[float, float, float, float]:
    """Return (west, south, east, north) in EPSG:4326 degrees."""
    d_lat = DEMO_HALF_EXTENT_M / _M_PER_DEG_LAT
    d_lon = DEMO_HALF_EXTENT_M / (
        _M_PER_DEG_LAT * math.cos(math.radians(DEMO_CENTER_LAT))
    )
    return (
        DEMO_CENTER_LON - d_lon,
        DEMO_CENTER_LAT - d_lat,
        DEMO_CENTER_LON + d_lon,
        DEMO_CENTER_LAT + d_lat,
    )


# (west, south, east, north) — this is the ordering OSMnx v2 expects for its
# `bbox` argument. Verified against the installed version by
# scripts/verify_env.py rather than assumed.
DEMO_BBOX = _derive_bbox()


def bbox_contains(lat: float, lon: float) -> bool:
    west, south, east, north = DEMO_BBOX
    return south <= lat <= north and west <= lon <= east
