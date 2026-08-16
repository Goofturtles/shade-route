"""Prove the installed geospatial APIs match what the code assumes.

The brief is explicit: OSMnx changed its API between v1 and v2, and pvlib's
solar-position frame has column names that are easy to misremember. Rather
than trusting memory, this script interrogates the *installed* packages and
prints what they actually expose.

Runs entirely offline — no Overpass calls, no downloads.

    python scripts/verify_env.py
"""

from __future__ import annotations

import inspect
import sys


def rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def main() -> int:
    import geopandas
    import networkx
    import numpy
    import osmnx as ox
    import pandas as pd
    import pvlib
    import shapely

    rule("Installed versions")
    for module in (ox, networkx, shapely, geopandas, pvlib, pd, numpy):
        print(f"  {module.__name__:<12} {module.__version__}")
    print(f"  {'python':<12} {sys.version.split()[0]}")

    rule("OSMnx signatures (the v1 -> v2 break)")
    for name, func in (
        ("graph_from_bbox", ox.graph_from_bbox),
        ("features_from_bbox", ox.features_from_bbox),
        ("project_graph", ox.projection.project_graph),
        ("project_gdf", ox.projection.project_gdf),
        ("nearest_nodes", ox.distance.nearest_nodes),
        ("graph_to_gdfs", ox.graph_to_gdfs),
    ):
        print(f"  {name}{inspect.signature(func)}")

    rule("Shapely spatial index")
    print(f"  shapely.STRtree present: {hasattr(shapely, 'STRtree')}")
    tree = shapely.STRtree([shapely.box(0, 0, 1, 1), shapely.box(5, 5, 6, 6)])
    print(f"  STRtree.query signature: {inspect.signature(tree.query)}")

    rule("pvlib solar position — actual column names")
    times = pd.DatetimeIndex(["2026-08-15 15:00:00"]).tz_localize("America/Los_Angeles")
    solpos = pvlib.solarposition.get_solarposition(times, 45.5220, -122.6750)
    print(f"  columns: {list(solpos.columns)}")
    row = solpos.iloc[0]
    for key in ("apparent_elevation", "elevation", "azimuth", "apparent_zenith", "zenith"):
        if key in solpos.columns:
            print(f"  {key:<20} {row[key]:.4f}")

    rule("Sanity: is that solar position plausible?")
    print(
        "  Portland, 15:00 local on 15 Aug. Expect the sun in the west-southwest\n"
        "  (azimuth roughly 230-250 deg) and fairly high (elevation roughly 40-50 deg)."
    )
    azimuth = float(row["azimuth"])
    elevation = float(row["apparent_elevation"])
    ok = 200.0 <= azimuth <= 270.0 and 30.0 <= elevation <= 60.0
    print(f"  azimuth={azimuth:.2f} elevation={elevation:.2f} -> {'PLAUSIBLE' if ok else 'SUSPICIOUS'}")

    rule("Result")
    if not ok:
        print("  FAIL — solar position is outside the expected envelope. Stop and investigate.")
        return 1
    print("  PASS — the stack imports, the signatures are known, the sun is where it should be.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
