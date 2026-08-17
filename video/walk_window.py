"""Find a stretch of the route with genuine open ground around it.

The film's walking shot kept putting the camera inside a building. The model has
no streets carved out of it - the prisms are solid OSM footprints - so the route
polyline runs along and sometimes through them, and any camera placed near the
walker landed in a wall.

An earlier attempt scored clearance by distance to the nearest building VERTEX,
which is the wrong measure: a point can be far from every vertex of a large
footprint and still be sitting inside it. This uses real polygon geometry -
`Polygon.distance` for the gap and `Polygon.contains` for the inside test - so
"clear" means clear.

Reads video/scene3d.json, writes the chosen window back into scene3d.js as
`walk_window`. No API call: the buildings and the route are already in that file
in the same local metric frame.

    python video/walk_window.py
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
SRC = HERE / "scene3d.json"
JS = HERE / "scene3d.js"

# The camera sits behind and above the walker; this is the radius it needs.
CAMERA_REACH_M = 22.0
# How much of the route the shot should cover, as a fraction of its length.
WINDOW = 0.055


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))

    polys = []
    for b in data["buildings"]:
        try:
            poly = Polygon(b["p"])
            if poly.is_valid and not poly.is_empty:
                polys.append(poly)
        except Exception:  # noqa: BLE001
            continue
    print(f"{len(polys):,} building footprints")

    tree = STRtree(polys)
    route = LineString([(e, n) for e, n in data["route"]["shadiest"]])
    print(f"route {route.length:,.0f} m")

    # Walk the route and measure the true clearance at each sample.
    SAMPLES = 400
    clearance = []
    for i in range(SAMPLES + 1):
        u = i / SAMPLES
        pt = route.interpolate(u, normalized=True)
        idx = tree.query(pt.buffer(90.0))
        gap = 90.0
        inside = False
        for j in idx:
            poly = polys[j]
            if poly.contains(pt):
                inside = True
                break
            d = poly.distance(pt)
            if d < gap:
                gap = d
        clearance.append(0.0 if inside else gap)

    inside_count = sum(1 for c in clearance if c == 0.0)
    print(f"{inside_count} of {SAMPLES + 1} samples sit inside a footprint")

    # Find the window whose WORST sample is best - the shot is only as good as
    # its tightest moment, so maximising the mean would pick a stretch that
    # clips a wall halfway through.
    span = max(2, int(WINDOW * SAMPLES))
    best_start, best_worst = 0, -1.0
    for start in range(0, SAMPLES + 1 - span):
        worst = min(clearance[start:start + span])
        if worst > best_worst:
            best_worst, best_start = worst, start

    u0 = best_start / SAMPLES
    u1 = (best_start + span) / SAMPLES
    print(f"\nbest window  u {u0:.3f} -> {u1:.3f}   "
          f"worst clearance {best_worst:.1f} m")

    if best_worst < CAMERA_REACH_M:
        print(f"  ! the tightest point is under the {CAMERA_REACH_M:.0f} m the camera needs.")
        print("  ! the walking shot cannot be framed cleanly on this route.")
    else:
        print(f"  the camera needs {CAMERA_REACH_M:.0f} m and has {best_worst:.1f} m.")

    window = {
        "u0": round(u0, 4),
        "u1": round(u1, 4),
        "clearance_m": round(best_worst, 1),
        "usable": bool(best_worst >= CAMERA_REACH_M),
    }
    data["walk_window"] = window
    SRC.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    JS.write_text("window.SCENE3D = " + json.dumps(data, separators=(",", ":")) + ";\n",
                  encoding="utf-8")
    print(f"\nwrote walk_window to {SRC.name} and {JS.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
