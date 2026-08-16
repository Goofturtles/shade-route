"""The shade model.

Fetch buildings and trees from OpenStreetMap, project each one away from the
sun to get the ground it shades, then measure what fraction of every street
segment falls inside that shade.

Everything geometric happens in a projected CRS with metres as its unit. Doing
this arithmetic in raw lat/lon degrees does not crash — it just silently
produces wrong distances, because a degree of longitude in Portland is about
70% the length of a degree of latitude.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import osmnx as ox
import shapely
from shapely import affinity
from shapely.ops import unary_union

from app import config, sun as sun_module

log = logging.getLogger("shade_route.shade")

# --- Height estimation -------------------------------------------------------
# OSM height tags are patchy. These fallbacks are stated in the README because
# they are assumptions, not measurements.
DEFAULT_BUILDING_LEVELS = 3.0
METRES_PER_LEVEL = 3.2
DEFAULT_TREE_HEIGHT_M = 8.0
DEFAULT_TREE_CROWN_RADIUS_M = 3.5

_cache: dict[tuple, "ShadeField"] = {}
_features_cache: dict[str, gpd.GeoDataFrame] = {}
_lock = threading.Lock()


def _parse_number(value) -> float | None:
    """Pull a number out of an OSM tag value like '12', '12 m', '12.5'."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value) if np.isfinite(value) else None
    except TypeError:
        return None
    text = str(value).strip().lower().replace("m", "").replace("metres", "").strip()
    try:
        number = float(text.split()[0]) if text else None
    except (ValueError, IndexError):
        return None
    return number if number is not None and number > 0 else None


def building_height(row) -> float:
    """height tag, else levels x 3.2 m, else a 3-storey default."""
    for key in ("building:height", "height"):
        value = _parse_number(row.get(key))
        if value:
            return value
    for key in ("building:levels", "levels"):
        levels = _parse_number(row.get(key))
        if levels:
            return levels * METRES_PER_LEVEL
    return DEFAULT_BUILDING_LEVELS * METRES_PER_LEVEL


def tree_height(row) -> float:
    return _parse_number(row.get("height")) or DEFAULT_TREE_HEIGHT_M


def tree_crown_radius(row) -> float:
    diameter = _parse_number(row.get("diameter_crown"))
    if diameter:
        return diameter / 2.0
    return DEFAULT_TREE_CROWN_RADIUS_M


# --- Feature fetching --------------------------------------------------------

def _fetch(name: str, tags: dict) -> gpd.GeoDataFrame:
    """Fetch OSM features for the demo bbox, memoised for the process lifetime."""
    if name in _features_cache:
        return _features_cache[name]
    # Must happen before the first Overpass call from *this* module. Without it
    # the cache folder depends on which module ran first: check_shade.py reached
    # here before anything configured OSMnx and wrote to ./cache instead of
    # ./cache/osmnx, so three responses were downloaded and stored twice.
    config.configure_osmnx()
    log.info("Fetching %s from OpenStreetMap ...", name)
    try:
        gdf = ox.features_from_bbox(config.DEMO_BBOX, tags)
    except Exception as exc:  # noqa: BLE001 - an empty layer is survivable, a crash is not
        log.warning("Could not fetch %s: %s", name, exc)
        gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    _features_cache[name] = gdf
    return gdf


def _project(gdf: gpd.GeoDataFrame, crs) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf.set_crs("EPSG:4326", allow_override=True).to_crs(crs)
    return gdf.to_crs(crs)


# --- Shadow projection -------------------------------------------------------

def _project_footprint(geom, dx: float, dy: float):
    """The ground shaded by an object, as its footprint swept along the shadow.

    Per the brief: convex hull of the footprint plus its translated copy. This
    over-estimates for concave shapes — an L-shaped building's inner corner and
    a courtyard both get filled in with shade that isn't really there. It errs
    generous rather than stingy, and the README says so.
    """
    if geom is None or geom.is_empty:
        return None
    moved = affinity.translate(geom, xoff=dx, yoff=dy)
    return unary_union([geom, moved]).convex_hull


@dataclass
class ShadeField:
    """Every shadow on the ground at one instant, plus a spatial index."""

    polygons: list = field(default_factory=list)
    tree: shapely.STRtree | None = None
    crs: object = None
    sun: sun_module.SolarPosition | None = None
    building_count: int = 0
    tree_count: int = 0
    park_count: int = 0

    def shade_fraction(self, line) -> float:
        """What fraction of a line's length lies in shadow."""
        if self.tree is None or line.is_empty or line.length <= 0:
            return 0.0
        candidates = self.tree.query(line, predicate="intersects")
        if len(candidates) == 0:
            return 0.0
        # Union only the handful of shadows that actually touch this segment,
        # rather than intersecting against one giant union of the whole city.
        local = unary_union([self.polygons[int(i)] for i in candidates])
        shaded = line.intersection(local).length
        return float(min(max(shaded / line.length, 0.0), 1.0))


def build_shade_field(when, graph_crs=None) -> ShadeField:
    """Compute every shadow polygon for a given moment."""
    position = sun_module.solar_position(when)

    buildings = _fetch("buildings", {"building": True})
    trees = _fetch("trees", {"natural": "tree"})
    parks = _fetch("parks", {"leisure": "park", "landuse": "forest"})

    # Work out the local UTM zone from the data itself rather than hardcoding it.
    reference = buildings if not buildings.empty else parks
    if reference.empty:
        log.warning("No building or park data available; shade field will be empty.")
        return ShadeField(sun=position, crs=graph_crs)
    projected_reference = ox.projection.project_gdf(reference)
    crs = projected_reference.crs

    field_obj = ShadeField(crs=crs, sun=position)

    if not position.casts_usable_shadows:
        # Sun down, or so low that height/tan(elevation) is meaningless. Return
        # an explicitly empty field rather than nonsense geometry.
        log.info("Sun elevation %.2f deg — no usable shadows.", position.elevation_deg)
        field_obj.tree = shapely.STRtree([])
        return field_obj

    polygons: list = []

    # Buildings ---------------------------------------------------------------
    b = projected_reference if not buildings.empty else None
    if b is not None:
        for _, row in b.iterrows():
            geom = row.geometry
            if geom is None or geom.geom_type not in ("Polygon", "MultiPolygon"):
                continue
            height = building_height(row)
            dx, dy = position.shadow_offset_m(height)
            shadow = _project_footprint(geom, dx, dy)
            if shadow is not None and not shadow.is_empty:
                polygons.append(shadow)
        field_obj.building_count = len(polygons)

    # Trees -------------------------------------------------------------------
    if not trees.empty:
        projected_trees = _project(trees, crs)
        before = len(polygons)
        for _, row in projected_trees.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            point = geom.centroid if geom.geom_type != "Point" else geom
            crown = point.buffer(tree_crown_radius(row))
            dx, dy = position.shadow_offset_m(tree_height(row))
            shadow = _project_footprint(crown, dx, dy)
            if shadow is not None and not shadow.is_empty:
                polygons.append(shadow)
        field_obj.tree_count = len(polygons) - before

    # Parks and forest --------------------------------------------------------
    # Treated as wholly shaded. Generous — an open lawn in the middle of a park
    # is not shaded at all — and flagged as a limitation in the README.
    if not parks.empty:
        projected_parks = _project(parks, crs)
        before = len(polygons)
        for geom in projected_parks.geometry:
            if geom is not None and geom.geom_type in ("Polygon", "MultiPolygon"):
                polygons.append(geom)
        field_obj.park_count = len(polygons) - before

    field_obj.polygons = polygons
    field_obj.tree = shapely.STRtree(polygons) if polygons else shapely.STRtree([])
    log.info(
        "Shade field: %d building, %d tree, %d park polygons at elevation %.1f deg",
        field_obj.building_count, field_obj.tree_count, field_obj.park_count,
        position.elevation_deg,
    )
    return field_obj


def cache_key(when) -> tuple:
    """Shade is cached per quarter-hour: shadows do not move meaningfully faster."""
    return (when.date().isoformat(), when.hour, when.minute // 15)


def get_shade_field(when) -> ShadeField:
    key = cache_key(when)
    if key in _cache:
        return _cache[key]
    with _lock:
        if key in _cache:
            return _cache[key]
        _cache[key] = build_shade_field(when)
    return _cache[key]


# --- Applying shade to the street graph --------------------------------------

def annotate_graph(graph, field_obj: ShadeField, shade_aversion: float) -> str:
    """Write a `shade_cost` onto every edge, and return the weight attribute name.

    edge_cost = length x (1 + shade_aversion x (1 - shade_fraction))

    At shade_aversion 0 this collapses to plain length, so the "shortest" and
    "shadiest" routes come out of the same router with the same code path. That
    is what makes the comparison in the UI honest rather than two different
    algorithms dressed up as a trade-off.
    """
    fractions = edge_shade_fractions(graph, field_obj)
    for u, v, k, data in graph.edges(keys=True, data=True):
        fraction = fractions.get((u, v, k), 0.0)
        data["shade_fraction"] = fraction
        data["shade_cost"] = data["length"] * (1.0 + shade_aversion * (1.0 - fraction))
    return "shade_cost"


_edge_fraction_cache: dict[tuple, dict] = {}


def edge_shade_fractions(graph, field_obj: ShadeField) -> dict:
    """Shade fraction for every edge, cached per (moment, graph size).

    This is the expensive step the brief warns about, so it is computed once per
    quarter-hour and reused across every routing request in that window.
    """
    if field_obj.sun is None:
        return {}
    key = (cache_key(field_obj.sun.when), graph.number_of_edges())
    if key in _edge_fraction_cache:
        return _edge_fraction_cache[key]

    if not field_obj.polygons:
        result = {}
        _edge_fraction_cache[key] = result
        return result

    edges = ox.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True)
    edges = edges.to_crs(field_obj.crs)

    fractions: dict = {}
    for edge_id, geom in zip(edges.index, edges.geometry):
        fractions[edge_id] = field_obj.shade_fraction(geom)

    _edge_fraction_cache[key] = fractions
    return fractions


def route_shade_fraction(graph, route: list[int], weight: str = "length") -> float:
    """Length-weighted shade fraction across a whole route.

    Weighted by length, not a plain mean over edges: a 5 m alley and a 200 m
    boulevard should not count equally toward "61% shaded".

    `weight` must be the weight the router used. Reading shade off the
    cheapest-by-length parallel edge while the router actually took the
    cheapest-by-shade-cost one systematically under-reports the headline
    number — the one figure the whole project is judged on.
    """
    total = 0.0
    shaded = 0.0
    for u, v in zip(route[:-1], route[1:]):
        data = min(graph[u][v].values(), key=lambda d: d.get(weight, d["length"]))
        length = data["length"]
        total += length
        shaded += length * data.get("shade_fraction", 0.0)
    return (shaded / total) if total > 0 else 0.0
