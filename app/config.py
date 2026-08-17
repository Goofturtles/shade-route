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


# (west, south, east, north) — the ordering OSMnx v2 expects for its `bbox`
# argument, i.e. (left, bottom, right, top). Verified empirically in M1 from the
# coordinates of the downloaded nodes, because a type annotation says nothing
# about element order and getting it wrong returns a graph for the wrong place
# rather than raising.
DEMO_BBOX = _derive_bbox()


# --------------------------------------------------------------------------
# Areas
#
# The brief scoped this to one hardcoded 2 km box and listed multi-city as out
# of scope. That was the right call for a one-day build, and it is being
# overridden deliberately: "Use my location" is unusable if the only place the
# app accepts is a city the visitor is probably not in.
#
# An Area is a 2 km box around a point, with its own timezone. Every cache in
# the app keys on `area.id`, so switching away and back is free, and Portland
# stays pre-warmed on disk as the default.
#
# The box stays 2 km for the reason §5 gives: shade is O(edges x polygons) and a
# bigger box stops being interactive. This makes the box *movable*, not bigger.
# --------------------------------------------------------------------------

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Area:
    id: str
    label: str
    center_lat: float
    center_lon: float
    bbox: tuple[float, float, float, float]
    timezone: str


def _bbox_around(lat: float, lon: float, half_m: float = DEMO_HALF_EXTENT_M):
    d_lat = half_m / _M_PER_DEG_LAT
    # cos(lat) guards the poles, where a degree of longitude collapses to zero
    # and the box would otherwise become infinitely wide.
    d_lon = half_m / max(_M_PER_DEG_LAT * math.cos(math.radians(lat)), 1.0)
    return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)


DEFAULT_AREA = Area(
    id="portland",
    label="Inner Portland, Oregon",
    center_lat=DEMO_CENTER_LAT,
    center_lon=DEMO_CENTER_LON,
    bbox=DEMO_BBOX,
    timezone=TIMEZONE,
)

_areas: dict[str, Area] = {DEFAULT_AREA.id: DEFAULT_AREA}
_current: Area = DEFAULT_AREA
area_lock = threading.RLock()


def make_area(lat: float, lon: float, timezone: str, label: str | None = None) -> Area:
    """An Area centred on a point, snapped so nearby points share a cache.

    Snapping to ~500 m means two visitors on the same street get the same area
    id and therefore the same cached graph, rather than each paying a fresh
    Overpass download for a box a few metres apart.
    """
    # Anyone standing inside the pre-built demo box gets the pre-built demo box.
    # Without this, "Use my location" in Portland minted a near-identical area a
    # few hundred metres off centre, whose caches did not exist -- so the one
    # place guaranteed to be instant became a cold Overpass download.
    dw, ds, de, dn = DEFAULT_AREA.bbox
    if ds <= lat <= dn and dw <= lon <= de:
        return DEFAULT_AREA

    snap = 0.005
    slat = round(lat / snap) * snap
    slon = round(lon / snap) * snap
    aid = f"{slat:.3f},{slon:.3f}"
    if aid in _areas:
        return _areas[aid]
    area = Area(
        id=aid,
        label=label or f"{slat:.3f}, {slon:.3f}",
        center_lat=slat,
        center_lon=slon,
        bbox=_bbox_around(slat, slon),
        timezone=timezone,
    )
    _areas[aid] = area
    return area


def current_area() -> Area:
    return _current


def set_current_area(area: Area) -> None:
    """Point the module-level globals at `area`.

    Every other module reads these as `config.NAME` at call time rather than
    importing the value, so reassigning here redirects the whole app. Callers
    MUST hold `area_lock` for as long as they depend on the result — the
    globals are process-wide, so an unlocked switch mid-request would compute
    one city's shade against another's street graph.
    """
    global _current, DEMO_BBOX, DEMO_CENTER_LAT, DEMO_CENTER_LON, TIMEZONE
    _current = area
    DEMO_BBOX = area.bbox
    DEMO_CENTER_LAT = area.center_lat
    DEMO_CENTER_LON = area.center_lon
    TIMEZONE = area.timezone


def bbox_contains(lat: float, lon: float) -> bool:
    west, south, east, north = DEMO_BBOX
    return south <= lat <= north and west <= lon <= east


_osmnx_configured = False


def configure_osmnx() -> None:
    """Point OSMnx at our on-disk HTTP cache.

    Must run before *any* Overpass call, from whichever module gets there
    first. Overpass is a shared public service that rate-limits, and without
    this every process restart re-downloads and eventually gets refused.
    """
    global _osmnx_configured
    if _osmnx_configured:
        return
    import osmnx as ox

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(CACHE_DIR / "osmnx")
    ox.settings.log_console = False

    # OSMnx defaults to a 180-second request timeout. When Overpass refuses
    # connections -- which it does, and which it did twice during this build --
    # that turns a dead upstream into a three-minute hang with no explanation.
    # Twelve seconds across three mirrors bounds the whole attempt at about a
    # minute, and a healthy Overpass answers a 2 km query well inside it.
    ox.settings.requests_timeout = 12
    _osmnx_configured = True


# Overpass mirroring was tried here and REMOVED. OSMnx keys its on-disk HTTP
# cache by request URL, so pointing at a mirror makes every cached response a
# miss -- which turned the committed Portland cache, the whole reason a fresh
# clone works without Overpass, into a two-minute pile of retries against a
# dead upstream. The tightened requests_timeout above is kept: it was the part
# that actually helped, bounding a dead upstream at 12s instead of 180s.


def bbox_contains(lat: float, lon: float) -> bool:
    west, south, east, north = DEMO_BBOX
    return south <= lat <= north and west <= lon <= east


_osmnx_configured = False


def configure_osmnx() -> None:
    """Point OSMnx at our on-disk HTTP cache.

    Must run before *any* Overpass call, from whichever module gets there
    first. Overpass is a shared public service that rate-limits, and without
    this every process restart re-downloads and eventually gets refused.
    """
    global _osmnx_configured
    if _osmnx_configured:
        return
    import osmnx as ox

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(CACHE_DIR / "osmnx")
    ox.settings.log_console = False

    # OSMnx defaults to a 180-second request timeout. When Overpass refuses
    # connections -- which it does, and which it did twice during this build --
    # that turns a dead upstream into a three-minute hang with no explanation.
    # Twelve seconds across three mirrors bounds the whole attempt at about a
    # minute, and a healthy Overpass answers a 2 km query well inside it.
    ox.settings.requests_timeout = 12
    _osmnx_configured = True


# Overpass mirrors, tried in order, ONLY after the default has failed.
#
# The default must be tried first and must be tried unchanged: OSMnx keys its
# on-disk HTTP cache by request URL, so pointing at a mirror makes every cached
# response a miss. That is not theoretical -- doing it turned a 0.6s cached
# shade field into a two-minute pile of retries against a dead upstream, and
# the committed Portland cache is the whole reason a fresh clone works offline.
OVERPASS_MIRRORS = (
    "https://overpass-api.de/api",       # default: the cache was built against this
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
)


def with_overpass_fallback(fetch):
    """Run `fetch`, moving to another mirror only if the default is unreachable.

    All three are public instances of the same API over the same OSM data, so
    which one answers changes nothing about the result -- only whether there is
    one. None needs a key, which keeps §4's "no API keys anywhere" intact.
    """
    import osmnx as ox

    configure_osmnx()
    last = None
    for url in OVERPASS_MIRRORS:
        ox.settings.overpass_url = url
        try:
            return fetch()
        except Exception as exc:  # noqa: BLE001 - any transport failure is a miss
            last = exc
            continue
    # Always leave the default in place, so the next call can hit the cache.
    ox.settings.overpass_url = OVERPASS_MIRRORS[0]
    raise last if last else RuntimeError("No Overpass mirror was reachable.")


def bbox_contains(lat: float, lon: float) -> bool:
    west, south, east, north = DEMO_BBOX
    return south <= lat <= north and west <= lon <= east


_osmnx_configured = False


def configure_osmnx() -> None:
    """Point OSMnx at our on-disk HTTP cache.

    Must run before *any* Overpass call, from whichever module gets there
    first. Overpass is a shared public service that rate-limits, and without
    this every process restart re-downloads and eventually gets refused.
    """
    global _osmnx_configured
    if _osmnx_configured:
        return
    import osmnx as ox

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(CACHE_DIR / "osmnx")
    ox.settings.log_console = False

    # OSMnx defaults to a 180-second request timeout. When Overpass refuses
    # connections -- which it does, and which it did twice during this build --
    # that turns a dead upstream into a three-minute hang with no explanation.
    # Twelve seconds across three mirrors bounds the whole attempt at about a
    # minute, and a healthy Overpass answers a 2 km query well inside it.
    ox.settings.requests_timeout = 12
    _osmnx_configured = True


# Overpass mirrors, tried in order. All three are public instances of the same
# API serving the same OSM data, so which one answers changes nothing about the
# result -- only whether there is one. No key is needed for any of them, which
# keeps §4's "no API keys anywhere" intact.
OVERPASS_MIRRORS = (
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
)


def with_overpass_fallback(fetch):
    """Run `fetch`, moving to the next mirror if one is unreachable.

    Returns the first successful result. If every mirror fails, the LAST error
    is raised, because by then the interesting fact is that they are all down
    rather than what the first one said.
    """
    import osmnx as ox

    configure_osmnx()
    last = None
    for url in OVERPASS_MIRRORS:
        ox.settings.overpass_url = url
        try:
            return fetch()
        except Exception as exc:  # noqa: BLE001 - any transport failure is a miss
            last = exc
            continue
    ox.settings.overpass_url = OVERPASS_MIRRORS[0]
    raise last if last else RuntimeError("No Overpass mirror was reachable.")
