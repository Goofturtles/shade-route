# Shade Route — Build Brief

## 1. What we're building

A walking route planner that finds the shadiest path between two points, not the fastest.

Given an origin, a destination, and a date/time, it computes where building and tree shadows
fall at that moment, then routes to maximize time spent in shade — showing the trade-off
against the shortest route ("+4 min walk, 61% shaded instead of 12%").

## 2. Hard constraints — read these first

- This is a hackathon submission (OregonHacks, closes Aug 17, 8:00 AM PT). **Compressed to a
  single build day (~12 working hours).** Scope accordingly. Ruthlessly.
- All code must be written during the event. Do not scaffold from a pre-existing project.
  Third-party open-source libraries are fine and expected.
- AI assistance must be cited. Maintain `AI_USAGE.md` in the repo, updated as we go: what was
  generated, what the human wrote, what was changed together. Be accurate and specific — this
  is a rules requirement, not a formality.
- Deliverables: GitHub repo, a working demo, a README, and a 5-minute demo video. The code
  must run on a clean machine from the README instructions. Test that.
- No fabricated numbers. Every figure the UI displays must be computed from real data or
  clearly labelled as a modelled estimate with its assumption stated. See §7.

## 3. Target user — build for her specifically

Marisol, 71, Portland. Walks to the pharmacy and the bus stop three times a week. Takes a
diuretic, which impairs her body's ability to regulate heat. On a 32 °C afternoon her usual
900 m walk is genuinely dangerous, and the shortest route runs down an exposed arterial with
no benches.

She needs: a cooler route, a rest stop roughly every 300 m, no stairs, and a plain-text
description of the route she can read without interpreting a map.

**Every feature decision gets checked against Marisol. If it doesn't help her, it's out of scope.**

## 4. Tech stack — decided, don't relitigate

- **Backend**: Python 3.11+, FastAPI, uvicorn.
- **Geospatial**: OSMnx (street graph), NetworkX (routing), Shapely + GeoPandas (shadow
  geometry), pvlib (solar position).
- **Frontend**: One static `index.html`. Leaflet via CDN, vanilla JS, plain CSS. No npm, no
  bundler, no framework. A build step is 3 hours we don't have.
- **Data**: OpenStreetMap via the Overpass API (`https://overpass-api.de/api/interpreter`) and
  OSMnx. **No API keys anywhere in this project** — a deliberate constraint so judges can run it.
- **Optional**: Open-Meteo (`https://api.open-meteo.com`) for actual temperature. Free, no key.

**Version check before writing code**: OSMnx changed its API significantly between v1 and v2
(`graph_from_bbox` signature in particular), and pvlib's `get_solarposition` returns a
DataFrame whose exact column names must be confirmed rather than assumed. Pin versions in
`requirements.txt` and verify installed signatures against local docs before building on them.
Don't trust memory of these APIs — check. See `scripts/verify_env.py`.

## 5. The shade model — the technical core

Build in this order. Each step works before the next starts.

1. **Sun position.** For a lat/lon and datetime, get solar azimuth and apparent elevation from
   pvlib. If elevation ≤ 0, the sun is down — return a clear "no shadows, sun is below the
   horizon" state rather than garbage geometry.

2. **Building shadows.** Fetch building footprints from OSM. Estimate height: `building:height`
   if tagged, else `building:levels × 3.2 m`, else default 3 levels. Project each footprint away
   from the sun:

   ```
   shadow_length    = height / tan(solar_elevation)
   shadow_direction = solar_azimuth + 180°
   ```

   Translate the footprint by that vector and take the convex hull of the original plus the
   translated copy. Good-enough shadow projection — note the simplification in the README.

3. **Tree shadows.** Fetch `natural=tree` nodes and `landuse=forest` / `leisure=park` polygons.
   For point trees, buffer to a crown radius (`diameter_crown/2` if tagged, else 3.5 m default),
   estimate height (`height` tag, else 8 m), then project the same way. Park and forest polygons
   are treated as fully shaded — a defensible simplification, stated in the README.

4. **Work in metres, not degrees.** Reproject to a local UTM CRS before any buffering or
   translation. Doing this in EPSG:4326 produces wrong distances and it will not be obvious.

5. **Shade fraction per street segment.** Union all shadow polygons (`shapely.unary_union`),
   build a spatial index, and for each edge in the walking graph compute what fraction of its
   centreline length intersects the shadow union. This is the expensive step — use the spatial
   index, cache per (bbox, hour), and keep the demo bounding box small (~2 km × 2 km).

6. **Routing cost.**

   ```
   edge_cost = length × (1 + shade_aversion × (1 − shade_fraction))
   ```

   `shade_aversion` is a user-facing slider, 0 to 3: "how much detour will you accept for
   shade?" At 0 it returns the shortest path, which makes the comparison honest and gives a
   free A/B in the demo. Then `networkx.shortest_path(G, orig, dest, weight='shade_cost')`.

## 6. Milestones — stop and show after each

Original 40-hour plan, re-scoped for a one-day build:

| Milestone | Original | One-day | Notes |
|---|---|---|---|
| **M0** Skeleton | 2 h | 1.0 h | + dependency de-risk up front |
| **M1** Plain routing | 3 h | 1.5 h | graph cached to `.graphml`, never re-downloaded |
| **M2** Shade engine | 6 h | 4.0 h | **merged with M3** — trees first, then buildings |
| **M3** Building shadows | 6 h | — | folded into M2 |
| **M2v** Voxel 3D view | — | 1.5 h | **added mid-build**, see below |
| **M4** Marisol's features | 5 h | 1.5 h | benches, no stairs, time scrubber; **fountains cut** |
| **M5** Polish + a11y + README | 5 h | 1.5 h | text route description is not cuttable |
| Video + submit | 4 h | 1.0 h | |

### M2v — voxel 3D view (added 15 Aug, mid-build)

An optional 3D voxel view of the demo area, in the spirit of the ghostbus voxel map, rendering
the building shadow volumes M2 already computes. Decisions made when it was added:

- **It is an additive panel, not a replacement.** The Leaflet map and the prose route description
  remain the primary path. A WebGL canvas has no accessible equivalent, and accessibility is 20%
  of the score and the reason this project exists — the 3D view must never become the only way to
  read a route.
- **It reuses M2's geometry.** The extruded shadow polygons are already computed for the shade
  fraction; the voxel view extrudes and renders those rather than building a second pipeline.
  This is why it is sequenced *after* M2 — built before it, there would be nothing to draw.
- **No build step.** Three.js as an ES module from a CDN, consistent with §4. No npm, no bundler.
- **Coverage stays 2 km × 2 km.** Expanding to the Greater Toronto Area was considered and
  rejected: ~7,100 km² is roughly 1,780× the demo area, Overpass will not serve a building query
  at that scale, routing degrades to minutes per request, and it would move the demo off
  Marisol's Portland. §9's "stop me if I ask for multi-city support" applied.
- **Paid for by cutting drinking fountains** from M4, and by trimming M5 and the video block.

**M0** — FastAPI app, `/health`, `index.html` with a Leaflet map centred on Portland,
click-to-set origin and destination. Commit.

**M1** — OSMnx downloads the walking graph for a hardcoded bbox once and caches to `.graphml`
on disk. Shortest path renders on the map. Do not re-download on every request. Commit.

**M2** — Sun position + tree shadows + building shadows + shade fraction per edge + cost
function + slider. Two routes render simultaneously: shortest in one colour, shadiest in
another, with a comparison panel. **Minimum viable submission** — commit and tag after the
tree-shade half works, before adding buildings.

**M4** — Time-of-day scrubber. Bench locations (`amenity=bench`) along the route with
distance-to-next-rest-stop. Avoid stairs (`highway=steps`). Drinking fountains
(`amenity=drinking_water`) if in the data. Commit.

**M5** — Polish, README, accessibility pass. See §8. Commit.

Then stop coding. The last block is for the video. Non-negotiable.

## 7. Honesty requirements

The judging panel includes working engineers. They will ask where a number came from.

- **Display** % of route in shade — directly computed, defensible, the headline metric.
- **Display** extra distance and extra time versus the shortest route — directly computed.
- **Do not** display a temperature difference as if it were measured. A thermal claim must be
  presented as a modelled estimate with the assumption visible in the UI and sourced in the
  README (shade primarily reduces mean radiant temperature, not air temperature — cite the
  literature properly or leave it out).
- **README needs a "Limitations" section**: flat-terrain assumption, no seasonal leaf-off
  modelling, incomplete and uneven OSM tree coverage, convex-hull shadow approximation,
  shadow-length clamping at low sun elevation.

## 8. Accessibility — 20% of the score, and the point of the project

- A **text route description** alongside the map. Turn-by-turn, in prose, with shade and
  rest-stop notes. A map alone is unusable for a screen-reader user, and this is the cheapest
  way to earn that 20%.
- Full keyboard navigation with visible focus rings. Origin and destination settable by
  address/coordinate entry, not just by clicking the map.
- **Never encode information by colour alone** — route lines get distinct patterns and labels
  as well as distinct colours.
- Colourblind-safe palette (Okabe–Ito), WCAG AA contrast minimum, respect
  `prefers-reduced-motion`.
- Proper ARIA labels on map controls. Test one full flow with keyboard only before calling it
  done.

## 9. Explicitly out of scope

Do not build: user accounts, a database, cycling or driving modes, multi-city support, a mobile
app, real-time updates, saved routes, social sharing, a machine learning model of any kind. Any
one of these costs us the project.

## 10. Working agreement

- Commit after every milestone with a real message. The commit history is evidence the code was
  written during the event — keep it clean and frequent.
- Stop and ask before adding a dependency not listed in §4, changing the shade model's
  approach, or starting a milestone early.
- If something is going to take more than 90 minutes, stop and say so. Cut scope rather than
  run over.
- When a milestone finishes, say what to click to verify it, and what you're least confident about.
