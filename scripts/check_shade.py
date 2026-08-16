"""Verify the shade model produces geometry that is actually correct.

The shade model is the technical core of this project, so it gets checked
rather than assumed. Every assertion here is something that would be wrong in a
plausible-looking way if the maths were subtly off - a shadow pointing the
wrong direction still renders as a nice picture.

    python scripts/check_shade.py
"""

from __future__ import annotations

import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from app import config, graph, shade, sun  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" - {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def compass(azimuth: float) -> str:
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[int((azimuth % 360) / 22.5 + 0.5) % 16]


def main() -> int:
    rule("1. Solar position through one day")
    for hour, expect in ((9, "east-ish"), (12, "south-ish"), (15, "west-ish"), (23, "below horizon")):
        pos = sun.solar_position(datetime(2026, 8, 16, hour, 0))
        print(f"  {hour:02d}:00  elevation {pos.elevation_deg:7.2f} deg  "
              f"azimuth {pos.azimuth_deg:6.2f} deg ({compass(pos.azimuth_deg)})  "
              f"sun_up={pos.sun_is_up}  expected {expect}")

    morning = sun.solar_position(datetime(2026, 8, 16, 9, 0))
    noon = sun.solar_position(datetime(2026, 8, 16, 12, 0))
    afternoon = sun.solar_position(datetime(2026, 8, 16, 15, 0))
    night = sun.solar_position(datetime(2026, 8, 16, 23, 0))

    check("morning sun is in the east", 60 < morning.azimuth_deg < 130,
          f"azimuth {morning.azimuth_deg:.1f}")
    check("afternoon sun is in the west", 200 < afternoon.azimuth_deg < 300,
          f"azimuth {afternoon.azimuth_deg:.1f}")

    # Solar noon is NOT 12:00 clock time. Portland sits about 17.7 degrees west
    # of the -105 central meridian of its timezone, which pushes solar noon
    # roughly 71 minutes later, and the equation of time shifts it a few minutes
    # further. Finding the actual maximum and checking the sun is due south
    # *there* tests the timezone and equation-of-time handling, whereas asserting
    # "south at 12:00" would just have been wrong.
    samples = [
        sun.solar_position(datetime(2026, 8, 16, 11 + step // 4, 15 * (step % 4)))
        for step in range(4 * 4)
    ]
    peak = max(samples, key=lambda p: p.elevation_deg)
    print(f"  solar noon found at {peak.when:%H:%M} local: elevation "
          f"{peak.elevation_deg:.2f} deg, azimuth {peak.azimuth_deg:.2f} deg "
          f"({compass(peak.azimuth_deg)})")
    check("the sun is due south at solar noon", 170 < peak.azimuth_deg < 190,
          f"azimuth {peak.azimuth_deg:.1f}")
    check("solar noon lands after 13:00, as Portland's longitude requires",
          peak.when.hour >= 13, f"{peak.when:%H:%M}")
    check("solar noon is the day's highest sun",
          peak.elevation_deg >= max(morning.elevation_deg, afternoon.elevation_deg))
    check("sun is below the horizon at 23:00", not night.sun_is_up,
          f"elevation {night.elevation_deg:.1f}")
    check("night casts no usable shadows", not night.casts_usable_shadows)

    rule("2. Shadows fall away from the sun")
    # Morning sun in the east -> shadows point west (negative dx).
    dx_am, dy_am = morning.shadow_offset_m(10.0)
    # Afternoon sun in the west -> shadows point east (positive dx).
    dx_pm, dy_pm = afternoon.shadow_offset_m(10.0)
    print(f"  09:00  10 m object -> shadow offset dx={dx_am:+7.2f} m  dy={dy_am:+7.2f} m")
    print(f"  15:00  10 m object -> shadow offset dx={dx_pm:+7.2f} m  dy={dy_pm:+7.2f} m")
    check("morning shadow points west", dx_am < 0, f"dx={dx_am:+.2f}")
    check("afternoon shadow points east", dx_pm > 0, f"dx={dx_pm:+.2f}")
    check("both shadows point away from the equator-side sun (northward)",
          dy_am > 0 and dy_pm > 0, f"dy={dy_am:+.2f}, {dy_pm:+.2f}")

    length_noon = noon.shadow_length_m(10.0)
    length_pm = afternoon.shadow_length_m(10.0)
    check("a lower sun casts a longer shadow", length_pm > length_noon,
          f"noon {length_noon:.1f} m vs 15:00 {length_pm:.1f} m")

    rule("3. Shadow length is clamped near the horizon")
    grazing = sun.SolarPosition(elevation_deg=0.1, azimuth_deg=270.0,
                                when=datetime(2026, 8, 16, 20, 30))
    unclamped = 10.0 / math.tan(math.radians(0.1))
    print(f"  a 10 m object at 0.1 deg elevation would mathematically cast {unclamped:,.0f} m")
    check("below the usable-elevation floor, no shadow is emitted at all",
          grazing.shadow_length_m(10.0) == 0.0)

    # Just above the floor, where shadows *are* emitted, the clamp must bite.
    low = sun.SolarPosition(elevation_deg=3.5, azimuth_deg=270.0,
                            when=datetime(2026, 8, 16, 20, 0))
    raw = 20.0 / math.tan(math.radians(3.5))
    clamped = low.shadow_length_m(20.0)
    print(f"  a 20 m object at 3.5 deg would be {raw:,.0f} m, clamped to {clamped:,.0f} m")
    check("the clamp actually bites above the floor",
          clamped == sun.MAX_SHADOW_LENGTH_M and raw > sun.MAX_SHADOW_LENGTH_M,
          f"{clamped:.0f} m")
    check("a short object below the clamp is left untouched",
          abs(low.shadow_length_m(5.0) - 5.0 / math.tan(math.radians(3.5))) < 1e-6)

    rule("4. Building the shade field (fetches OSM data on first run)")
    started = time.perf_counter()
    field = shade.get_shade_field(datetime(2026, 8, 16, 15, 0))
    print(f"  built in {time.perf_counter() - started:.1f}s")
    print(f"  building shadows : {field.building_count:,}")
    print(f"  tree shadows     : {field.tree_count:,}")
    print(f"  park polygons    : {field.park_count:,}")
    print(f"  projected CRS    : {field.crs}")
    check("buildings produced shadows", field.building_count > 0)
    check("CRS is projected, not lat/lon degrees",
          field.crs is not None and not field.crs.is_geographic, str(field.crs))

    rule("5. Shade fractions across the street network")
    started = time.perf_counter()
    g = graph.load_graph()
    fractions = shade.edge_shade_fractions(g, field)
    elapsed = time.perf_counter() - started
    values = list(fractions.values())
    shaded = [v for v in values if v > 0.01]
    fully = [v for v in values if v > 0.99]
    print(f"  computed {len(values):,} edge fractions in {elapsed:.1f}s")
    print(f"  edges with any shade : {len(shaded):,} ({100 * len(shaded) / max(len(values), 1):.0f}%)")
    print(f"  edges fully shaded   : {len(fully):,}")
    print(f"  mean fraction        : {sum(values) / max(len(values), 1):.3f}")
    check("every fraction is within 0..1", all(0.0 <= v <= 1.0 for v in values))
    check("some edges are shaded", len(shaded) > 0)
    check("not every edge is fully shaded", len(fully) < len(values))
    check("the expensive step is fast enough to be interactive", elapsed < 60,
          f"{elapsed:.1f}s")

    rule("6. Shade routing actually differs from shortest routing")
    orig = graph.nearest_node(g, 45.5180, -122.6800)
    dest = graph.nearest_node(g, 45.5260, -122.6700)

    shade.annotate_graph(g, field, shade_aversion=0.0)
    plain = graph.shortest_path(g, orig, dest, weight="shade_cost")
    plain_len = graph.route_length_m(g, plain)
    plain_shade = shade.route_shade_fraction(g, plain)

    by_length = graph.shortest_path(g, orig, dest, weight="length")
    check("aversion 0 reproduces the shortest path exactly", plain == by_length,
          f"{len(plain)} vs {len(by_length)} nodes")

    shade.annotate_graph(g, field, shade_aversion=2.0)
    shady = graph.shortest_path(g, orig, dest, weight="shade_cost")
    shady_len = graph.route_length_m(g, shady)
    shady_shade = shade.route_shade_fraction(g, shady)

    print(f"  shortest : {plain_len:7.0f} m, {100 * plain_shade:5.1f}% shaded")
    print(f"  shadiest : {shady_len:7.0f} m, {100 * shady_shade:5.1f}% shaded")
    print(f"  trade    : {shady_len - plain_len:+.0f} m for "
          f"{100 * (shady_shade - plain_shade):+.1f} percentage points of shade")
    check("the shadier route is at least as shaded", shady_shade >= plain_shade - 1e-9)
    check("the shadier route is never shorter than the shortest route",
          shady_len >= plain_len - 1e-6)

    rule("Result")
    if failures:
        print(f"  FAIL - {len(failures)} check(s) failed:")
        for name in failures:
            print(f"    - {name}")
        return 1
    print("  PASS - the shade model behaves correctly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
