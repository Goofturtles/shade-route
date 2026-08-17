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

# The camera sits directly behind the walker at 7 m, plus a little margin for
# the near plane. The first version of this asked for 22 m, which is what a
# lateral tracking shot would need - and since no stretch of the route has that,
# it declared the shot impossible. The shot is behind her, so 9 m is plenty.
CAMERA_REACH_M = 8.5

# The shot covers exactly as much ground as Marisol can actually walk in it.
# 1.1 m/s is the one constant the whole film derives from - it is what makes
# 15 min, 4 min and +2 min all true of the same journey, and it is stated on
# screen two shots later. The first version covered 105 m in 8 seconds, which
# is 13 m/s: she crossed four blocks at running pace under a caption saying
# she walks at 1.1. Deriving the window from the speed makes that impossible.
WALK_SPEED_M_S = 1.1
SHOT_SECONDS = 8.0

# The look the shot wants: a street, not a plaza. Facades about this far away
# read as a corridor and lay shadow across the pavement she is walking on.
STREET_WIDTH_M = 12.0


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))

    polys, skipped = [], 0
    for b in data["buildings"]:
        try:
            poly = Polygon(b["p"])
            if poly.is_valid and not poly.is_empty:
                polys.append(poly)
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
    print(f"{len(polys):,} building footprints"
          + (f"  ({skipped} unusable and skipped)" if skipped else ""))
    if skipped:
        # A dropped footprint makes the clearance look better than it is, which
        # is the direction that puts a camera in a wall.
        print("  ! skipped footprints are not counted as obstacles")

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
    # clips a wall halfway through. The slice is inclusive of the final sample:
    # scoring [start:start+span] left the shot's last instant unmeasured, which
    # is precisely the moment the guarantee is about.
    walk_m = WALK_SPEED_M_S * SHOT_SECONDS
    window_u = walk_m / route.length
    span = max(2, round(window_u * SAMPLES))
    print(f"shot covers {walk_m:.1f} m at {WALK_SPEED_M_S} m/s "
          f"({window_u:.5f} of the route, {span} samples)")
    best_start, best_score, best_worst = -1, -1e9, 0.0
    for start in range(0, SAMPLES + 1 - span):
        worst = min(clearance[start:start + span + 1])
        if worst < CAMERA_REACH_M:
            continue                      # the camera would be inside a wall
        score = -abs(worst - STREET_WIDTH_M)
        if score > best_score:
            best_score, best_start, best_worst = score, start, worst
    if best_start < 0:
        # Nothing clears the camera. Fall back to the most open stretch and let
        # the usable flag below tell the film not to run the shot.
        best_start = max(range(0, SAMPLES + 1 - span),
                         key=lambda i: min(clearance[i:i + span + 1]))
        best_worst = min(clearance[best_start:best_start + span + 1])

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
