"""Walking street network: download once, cache to disk, route across it.

The brief is emphatic that the graph must not be re-downloaded per request. It
is fetched once for the demo bounding box, written to `.graphml`, and then held
in module memory for the life of the process.
"""

from __future__ import annotations

import logging
import math
import threading

import networkx as nx
import numpy as np
import osmnx as ox

from app import config

log = logging.getLogger("shade_route.graph")

def graph_file(area=None) -> "Path":
    """Where this area's street graph lives on disk.

    Portland keeps the original unsuffixed name so the graph committed to the
    repository is still found — that file is the reason a fresh clone answers
    its first request without calling Overpass.
    """
    area = area or config.current_area()
    if area.id == "portland":
        return config.CACHE_DIR / "walk_graph.graphml"
    safe = area.id.replace(",", "_").replace(".", "p").replace("-", "m")
    return config.CACHE_DIR / f"walk_graph_{safe}.graphml"


# Kept as a module attribute for the scripts that import it by name.
GRAPH_FILE = config.CACHE_DIR / "walk_graph.graphml"

# One graph per area, not one graph. Switching city and back is then free,
# and Portland stays resident once loaded.
_graphs: dict[str, nx.MultiDiGraph] = {}
# Two simultaneous first-requests would otherwise both start a download.
_graph_lock = threading.Lock()


def _configure_osmnx() -> None:
    config.configure_osmnx()


def verify_bbox_orientation(graph: nx.MultiDiGraph) -> dict:
    """Confirm empirically that DEMO_BBOX was interpreted as we intended.

    OSMnx 2.x types the argument as `tuple[float, float, float, float]` and the
    signature reveals nothing about element order. Passing the wrong order does
    not raise — it quietly returns a graph for a different patch of the planet,
    or an empty one. So rather than trust a docstring, look at where the nodes
    actually landed.
    """
    west, south, east, north = config.DEMO_BBOX
    lats = [data["y"] for _, data in graph.nodes(data=True)]
    lons = [data["x"] for _, data in graph.nodes(data=True)]

    if not lats:
        raise RuntimeError(
            "The downloaded walking graph has no nodes. The bbox was almost "
            f"certainly interpreted in an unexpected order. Passed: {config.DEMO_BBOX}"
        )

    observed = {
        "lat_min": min(lats), "lat_max": max(lats),
        "lon_min": min(lons), "lon_max": max(lons),
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
    }

    # A small tolerance: `truncate_by_edge` is off, but nodes can still sit a
    # little outside the requested box depending on how ways are cut.
    pad = 0.01
    inside = (
        south - pad <= observed["lat_min"] and observed["lat_max"] <= north + pad
        and west - pad <= observed["lon_min"] and observed["lon_max"] <= east + pad
    )
    if not inside:
        raise RuntimeError(
            "The downloaded graph does not lie inside the requested bounding box, "
            "which means the bbox tuple order is wrong.\n"
            f"  requested (west, south, east, north): {config.DEMO_BBOX}\n"
            f"  observed lat {observed['lat_min']:.5f}..{observed['lat_max']:.5f}, "
            f"lon {observed['lon_min']:.5f}..{observed['lon_max']:.5f}"
        )

    observed["orientation_verified"] = True
    return observed


def _download_graph() -> nx.MultiDiGraph:
    log.info("Downloading walking network for %s ...", config.DEMO_BBOX)
    graph = ox.graph_from_bbox(config.DEMO_BBOX, network_type="walk")
    verify_bbox_orientation(graph)
    GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(graph, graph_file())
    log.info("Cached walking network to %s", GRAPH_FILE)
    return graph


def load_graph() -> nx.MultiDiGraph:
    """Return the walking graph for the current area, downloading only if new."""
    area = config.current_area()
    cached = _graphs.get(area.id)
    if cached is not None:
        return cached

    with _graph_lock:
        cached = _graphs.get(area.id)
        if cached is not None:  # another thread won the race
            return cached
        _configure_osmnx()
        path = graph_file(area)
        if path.exists():
            log.info("Loading cached walking network from %s", path)
            graph = ox.load_graphml(path)
        else:
            graph = _download_graph()
        _graphs[area.id] = graph
    return graph


def is_cached() -> bool:
    area = config.current_area()
    return area.id in _graphs or graph_file(area).exists()


# Keyed by id(graph), not by area: the index describes one specific graph
# object, and tying it to the object it was built from makes it impossible to
# hand another area's node coordinates back by mistake. That was a live risk
# once the graph stopped being a singleton.
_node_index: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def _node_arrays(graph: nx.MultiDiGraph) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    hit = _node_index.get(id(graph))
    if hit is not None:
        return hit
    ids, lats, lons = [], [], []
    for node_id, data in graph.nodes(data=True):
        ids.append(node_id)
        lats.append(data["y"])
        lons.append(data["x"])
    built = (
        np.asarray(ids, dtype=np.int64),
        np.asarray(lats, dtype=np.float64),
        np.asarray(lons, dtype=np.float64),
    )
    _node_index[id(graph)] = built
    return built


def nearest_node(graph: nx.MultiDiGraph, lat: float, lon: float) -> int:
    """Find the graph node closest to a lat/lon.

    Deliberately not `ox.distance.nearest_nodes`: on an unprojected graph that
    requires scikit-learn, which is a large dependency to add — and one the
    brief says to ask before adding — for a single nearest-neighbour lookup.

    Over ~3,400 nodes a vectorised scan is exact and takes microseconds. The
    longitude term is scaled by cos(latitude) so a degree of longitude is
    weighted correctly against a degree of latitude; without it the "nearest"
    node would be biased east-west. Only the argmin matters, so an
    equirectangular approximation is more than adequate across a 2 km box.
    """
    ids, node_lat, node_lon = _node_arrays(graph)
    lon_scale = math.cos(math.radians(lat))
    d_lat = node_lat - lat
    d_lon = (node_lon - lon) * lon_scale
    return int(ids[int(np.argmin(d_lat * d_lat + d_lon * d_lon))])


def _shortest_parallel_edge(graph: nx.MultiDiGraph, u: int, v: int, weight: str) -> dict:
    """Pick the cheapest edge between two nodes.

    This is a MultiDiGraph: a pair of nodes can be joined by several ways, and
    `shortest_path` returns only the node sequence, so the edge has to be
    recovered by weight.
    """
    return min(graph[u][v].values(), key=lambda data: data.get(weight, data["length"]))


def route_coordinates(
    graph: nx.MultiDiGraph, route: list[int], weight: str = "length"
) -> list[list[float]]:
    """Build a [lat, lon] polyline that follows the real street centrelines.

    Using node positions alone would cut the corners off every curved street,
    and M2 measures shade against these same centrelines, so it needs to be the
    true geometry rather than a chord.

    `weight` must match the weight the router used. Where two nodes are joined
    by several ways, the cheapest-by-length edge is not necessarily the one a
    shade-weighted Dijkstra chose, and drawing the wrong one would show a line
    the walker was never routed along.
    """
    coords: list[list[float]] = []
    for u, v in zip(route[:-1], route[1:]):
        data = _shortest_parallel_edge(graph, u, v, weight)
        geometry = data.get("geometry")
        if geometry is not None:
            segment = [[lat, lon] for lon, lat in geometry.coords]
            # Stored geometry is not guaranteed to run u -> v.
            start = (graph.nodes[u]["y"], graph.nodes[u]["x"])
            if _distance_sq(segment[0], start) > _distance_sq(segment[-1], start):
                segment.reverse()
        else:
            segment = [
                [graph.nodes[u]["y"], graph.nodes[u]["x"]],
                [graph.nodes[v]["y"], graph.nodes[v]["x"]],
            ]
        if coords and coords[-1] == segment[0]:
            segment = segment[1:]
        coords.extend(segment)
    return coords


def _distance_sq(a: list[float] | tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def route_length_m(graph: nx.MultiDiGraph, route: list[int], weight: str = "length") -> float:
    return sum(
        _shortest_parallel_edge(graph, u, v, weight)["length"]
        for u, v in zip(route[:-1], route[1:])
    )


def shortest_path(graph: nx.MultiDiGraph, orig: int, dest: int, weight: str = "length") -> list[int]:
    return nx.shortest_path(graph, orig, dest, weight=weight)
