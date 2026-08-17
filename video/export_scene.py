"""Export the demo area as a static 3D scene for the launch film.

The film's centrepiece is a three.js model of a few blocks of downtown Portland
with the real route through it, lit by a directional light at the real solar
position. That is only worth doing if the geometry is the *same* geometry the
router runs on — a prettier, invented city would make the most convincing shot
in the film the least honest one.

So this reuses the app's own building fetch and its own height rule rather than
re-deriving either, and takes the route straight from the API. It runs once and
writes a static JSON; nothing here is imported at runtime, and the app keeps its
no-build-step guarantee.

    python video/export_scene.py          # needs the server on :8000

Writes video/scene3d.json:
    origin      lon/lat the local metric frame is centred on
    buildings   [{ p: [[east,north],...], h: height_m }]  metres from origin
    route       { shadiest: [[e,n],...], shortest: [...] }
    sun         { "07:00": {az, el}, ... }  from the app's own solar model
"""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

import geopandas as gpd  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

from app import config, shade, sun  # noqa: E402

BASE = "http://127.0.0.1:8000"
OUT = Path("video/scene3d.json")
OUT_JS = Path("video/scene3d.js")

# The demo journey the whole film is about.
ROUTE_PARAMS = {
    "orig_lat": 45.513604, "orig_lon": -122.681465,
    "dest_lat": 45.526229, "dest_lon": -122.683096,
    "when": "2026-08-16T15:00", "shade_aversion": 1.5, "avoid_stairs": "true",
}

# Wide enough to contain the whole 1.4 km journey with a margin. Framed tighter
# than this, the route ran off the edge of the model and the hero shot showed a
# walking line leaving the city into empty ground.
HALF_EXTENT_M = 820.0


def fetch_route() -> dict:
    query = urllib.parse.urlencode(ROUTE_PARAMS)
    with urllib.request.urlopen(f"{BASE}/api/route?{query}", timeout=300) as response:
        return json.load(response)


def main() -> int:
    print("route...")
    payload = fetch_route()
    routes = {r["id"]: r for r in payload["routes"]}
    shadiest = routes["shadiest"]["coordinates"]
    shortest = routes["shortest"]["coordinates"]

    # Centre the local frame on the middle of the shadiest route, so the model is
    # built around the thing the film is actually following.
    mid = shadiest[len(shadiest) // 2]
    origin_lat, origin_lon = float(mid[0]), float(mid[1])
    print(f"  origin {origin_lat:.6f}, {origin_lon:.6f}")

    config.configure_osmnx()
    print("buildings... (uses the committed OSM cache)")
    buildings = shade._fetch("buildings", {"building": True})
    if buildings.empty:
        print("  no buildings returned")
        return 1
    print(f"  {len(buildings):,} in the demo box")

    # Work in the app's projected CRS so distances are metres, then express
    # everything relative to the origin. three.js wants a small local frame, not
    # six-figure UTM eastings.
    crs = buildings.estimate_utm_crs()
    projected = buildings.to_crs(crs)
    origin_pt = (
        gpd.GeoSeries([Point(origin_lon, origin_lat)], crs="EPSG:4326")
        .to_crs(crs)
        .iloc[0]
    )
    ox, oy = origin_pt.x, origin_pt.y

    clip = box(ox - HALF_EXTENT_M, oy - HALF_EXTENT_M,
               ox + HALF_EXTENT_M, oy + HALF_EXTENT_M)
    near = projected[projected.intersects(clip)]
    print(f"  {len(near):,} within {HALF_EXTENT_M:.0f} m of the route centre")

    out_buildings = []
    for _, row in near.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        # Multipart footprints become separate prisms; a single ring is all the
        # extruder needs and holes are not worth the geometry at this distance.
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        height = shade.building_height(row)
        for part in parts:
            if part.geom_type != "Polygon":
                continue
            ring = list(part.exterior.coords)
            if len(ring) < 4:
                continue
            # 0.6 m is well below anything visible at the camera distances used,
            # and it roughly halves the vertex count.
            simple = part.simplify(0.6, preserve_topology=True)
            ring = list(simple.exterior.coords) if simple.geom_type == "Polygon" else ring
            pts = [[round(x - ox, 2), round(y - oy, 2)] for x, y in ring[:-1]]
            if len(pts) < 3:
                continue
            out_buildings.append({"p": pts, "h": round(height, 1)})

    print(f"  {len(out_buildings):,} prisms, "
          f"{sum(len(b['p']) for b in out_buildings):,} vertices")

    def to_local(coords):
        series = gpd.GeoSeries([Point(lon, lat) for lat, lon in coords], crs="EPSG:4326")
        return [[round(p.x - ox, 2), round(p.y - oy, 2)] for p in series.to_crs(crs)]

    print("route -> local metres...")
    local_routes = {"shadiest": to_local(shadiest), "shortest": to_local(shortest)}

    print("sun...")
    day = datetime.fromisoformat(ROUTE_PARAMS["when"])
    sun_table = {}
    # Every ten minutes, so the film can sweep the sun across the day and the
    # shadows move continuously. Interpolating between hourly samples would be
    # close enough to look right and would stop being the real solar track,
    # which is the only thing that makes the shot worth filming.
    track = []
    for minute in range(5 * 60, 21 * 60 + 1, 10):
        pos = sun.solar_position(datetime(day.year, day.month, day.day,
                                          minute // 60, minute % 60))
        track.append({
            "t": f"{minute // 60:02d}:{minute % 60:02d}",
            "m": minute,
            "az": round(pos.azimuth_deg, 2),
            "el": round(pos.elevation_deg, 2),
        })
    peak = max(track, key=lambda e: e["el"])
    print(f"  {len(track)} samples, 05:00-21:00 every 10 min")
    print(f"  peak {peak['el']:.2f} deg at {peak['t']}")

    for hour in (7, 9, 12, 15, 17, 19):
        pos = sun.solar_position(datetime(day.year, day.month, day.day, hour, 0))
        sun_table[f"{hour:02d}:00"] = {
            "az": round(pos.azimuth_deg, 2),
            "el": round(pos.elevation_deg, 2),
            "up": bool(pos.sun_is_up),
        }
        print(f"  {hour:02d}:00  elevation {pos.elevation_deg:5.2f}  "
              f"azimuth {pos.azimuth_deg:6.2f}")

    xs = [p[0] for b in out_buildings for p in b["p"]]
    ys = [p[1] for b in out_buildings for p in b["p"]]
    data = {
        "note": "Generated by video/export_scene.py from the same OSM footprints and "
                "the same height rule the router uses. Metres, east/north, from origin.",
        "origin": {"lat": origin_lat, "lon": origin_lon},
        "crs": str(crs),
        "extent_m": HALF_EXTENT_M,
        "bounds": {"minx": min(xs), "maxx": max(xs), "miny": min(ys), "maxy": max(ys)},
        "buildings": out_buildings,
        "route": local_routes,
        "sun": sun_table,
        "sun_track": track,
        "sun_peak": peak,
        "tallest_m": max(b["h"] for b in out_buildings),
    }
    blob = json.dumps(data, separators=(",", ":"))
    OUT.write_text(blob, encoding="utf-8")
    # Also emit it as a script that assigns a global. The renderer loads the
    # film over file://, where fetch() is blocked by CORS, and a <script src>
    # is the one way in that works on every protocol without loosening the
    # browser's security flags for the whole capture.
    OUT_JS.write_text("window.SCENE3D = " + blob + ";\n", encoding="utf-8")
    print(f"\nwrote {OUT}  {OUT.stat().st_size / 1024:.0f} KB")
    print(f"wrote {OUT_JS}  {OUT_JS.stat().st_size / 1024:.0f} KB  "
          f"tallest building {data['tallest_m']:.0f} m")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
