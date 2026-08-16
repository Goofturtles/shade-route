"""Download and cache the walking network before running the app.

Optional, but recommended before a demo: the first route request otherwise
triggers a one-off Overpass download that can take a minute, and Overpass is a
public service that is sometimes slow or rate-limited. Doing it ahead of time
means the demo never waits on someone else's server.

    python scripts/warm_cache.py

Also confirms, empirically, that the bounding box tuple was interpreted in the
order this project assumes - see app/graph.verify_bbox_orientation.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from app import config, graph  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    west, south, east, north = config.DEMO_BBOX
    print("Shade Route - warming the street network cache")
    print(f"  area   : {config.DEMO_CENTER_LAT}, {config.DEMO_CENTER_LON} "
          f"(+/- {config.DEMO_HALF_EXTENT_M:.0f} m)")
    print(f"  bbox   : west={west:.6f} south={south:.6f} east={east:.6f} north={north:.6f}")
    print(f"  cache  : {graph.GRAPH_FILE}")
    print(f"  cached : {'yes, will load from disk' if graph.GRAPH_FILE.exists() else 'no, will download'}")
    print()

    started = time.perf_counter()
    try:
        g = graph.load_graph()
    except Exception as exc:  # noqa: BLE001 - the diagnosis is the whole point
        print(f"FAILED - {type(exc).__name__}: {exc}")
        print("\nIf this is a network error, Overpass may be busy. Wait and retry.")
        return 1
    elapsed = time.perf_counter() - started

    print(f"Graph ready in {elapsed:.1f}s")

    stats = graph.verify_bbox_orientation(g)
    print(f"  nodes  : {stats['node_count']:,}")
    print(f"  edges  : {stats['edge_count']:,}")
    print(f"  extent : lat {stats['lat_min']:.5f}..{stats['lat_max']:.5f}, "
          f"lon {stats['lon_min']:.5f}..{stats['lon_max']:.5f}")
    print()
    print("  bbox tuple order VERIFIED empirically: the downloaded nodes lie")
    print("  inside the requested box, so (west, south, east, north) is correct")
    print("  for this OSMnx version. This was the last unverified assumption.")

    # Prove the graph can actually answer a routing question end to end.
    orig = graph.nearest_node(g, config.DEMO_CENTER_LAT - 0.004, config.DEMO_CENTER_LON - 0.005)
    dest = graph.nearest_node(g, config.DEMO_CENTER_LAT + 0.004, config.DEMO_CENTER_LON + 0.005)
    route = graph.shortest_path(g, orig, dest)
    metres = graph.route_length_m(g, route)
    coords = graph.route_coordinates(g, route)
    print()
    print(f"Smoke test route: {len(route)} nodes, {len(coords)} polyline points, {metres:,.0f} m")
    print(f"  ~{metres / config.WALKING_SPEED_M_S / 60:.0f} min at {config.WALKING_SPEED_M_S} m/s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
