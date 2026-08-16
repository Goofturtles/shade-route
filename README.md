# Shade Route

**A walking route planner that finds the shadiest path between two points, not the fastest.**

Give it an origin, a destination, and a date and time. It works out where building and tree
shadows fall at that moment, then routes to maximise the time you spend in shade — and shows
you honestly what that costs: *"+4 min walk, 61% shaded instead of 12%."*

> **Status: Milestone 2 of 5 — the shade model works.** Sun position, building and tree
> shadows, per-segment shade measurement, and shade-aware routing are all live. A mid-afternoon
> walk across downtown Portland comes out as **+5 min for 94% shade instead of 29%**. See
> [Milestones](#milestones) for what is and isn't built yet.

---

## Why

Marisol is 71 and walks to the pharmacy and the bus stop three times a week. She takes a
diuretic, which impairs her body's ability to regulate heat. On a 32 °C afternoon her usual
900 m walk is genuinely dangerous — and every routing app she owns will send her down the
shortest path, which is an exposed arterial with no benches and no shade.

Nothing about that walk is hard to fix. The shade already exists; it's just that no router
knows about it. This one does.

Every feature in this project is checked against Marisol. Shade, rest stops roughly every
300 m, no stairs, and a plain-text description of the route she can read without interpreting
a map. Anything that doesn't help her is out of scope.

---

## Run it on a clean machine

Requires **Python 3.11 or newer** and nothing else. No API keys, no accounts, no npm, no build
step. That's deliberate — you should be able to clone this and have it running in two minutes.

```bash
git clone <this-repo> && cd shade-route
```

**macOS / Linux**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

**Windows (PowerShell)**

```powershell
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

Then open **http://127.0.0.1:8000**.

### Verify your install first (recommended)

The geospatial stack is the fragile part, and OSMnx changed its API in a way that fails
silently between v1 and v2. This script interrogates the packages you actually installed and
checks the solar-position maths against a known-good answer. It runs offline in about two
seconds.

```bash
python scripts/verify_env.py
```

A passing run ends with `PASS - the stack imports, the signatures are known, the sun is where it
should be.` (The script's output is deliberately pure ASCII — Windows consoles default to a
legacy code page and would mangle anything else.)

### Warm the street-network cache (recommended before a demo)

```bash
python scripts/warm_cache.py
```

This downloads and caches everything the app needs: the walking network, the 245 named places
that populate the search box, and the building and tree shadows. Afterwards a cold start takes
about a second and touches the network not at all.

That matters more than it sounds. Overpass is a shared public service, and during development it
went unreachable for roughly half an hour mid-build. The app degrades gracefully when that
happens — the place picker empties and you click the map instead — but you do not want to
discover it while recording a demo.

| Cached | Where | Cold | Warm |
|---|---|---|---|
| Walking network, 3,363 nodes / 10,408 edges | `cache/walk_graph.graphml` | ~11 s | 0.3 s |
| 245 named places | `cache/places.json` | ~8 s | 0.0 s |
| Raw building + tree geometry | `cache/osmnx/` | ~44 s | 0.6 s |

One thing is *not* on disk: the per-edge shade fractions. Those are recomputed in memory the
first time each quarter-hour is requested — about 1.2 s for all 10,408 edges — and cached for
the life of the process. So a restarted server pays roughly a second on its first route, and
nothing thereafter. It never touches the network for it.

This script also confirms *empirically* that the bounding-box tuple was interpreted in the order
the code assumes, by checking where the downloaded nodes actually landed. OSMnx types that
argument as `tuple[float, float, float, float]` and passing the wrong order doesn't raise — it
quietly returns a graph for somewhere else.

---

## How it works

```
   lat/lon + datetime
           |
           v
   [1] pvlib  ---------->  solar azimuth + apparent elevation
           |
           v
   [2] Overpass / OSMnx ->  building footprints, trees, parks
           |
           v
   [3] reproject to local UTM (metres, not degrees)
           |
           v
   [4] project each footprint away from the sun:
           shadow_length    = height / tan(elevation)
           shadow_direction = azimuth + 180 deg
           |
           v
   [5] unary_union of every shadow -> STRtree spatial index
           |
           v
   [6] per street edge: what fraction of its centreline is in shadow?
           |
           v
   [7] edge_cost = length x (1 + shade_aversion x (1 - shade_fraction))
           |
           v
   [8] networkx.shortest_path  ->  the shadiest route
```

Setting `shade_aversion` to 0 makes the cost function collapse to plain length, which returns
the ordinary shortest path. That's what makes the side-by-side comparison honest: both routes
come out of the same router, and the only thing that changed was the slider.

### Why metres, not degrees

Every buffer and translation happens in a local UTM projection. Doing this arithmetic in
EPSG:4326 (raw lat/lon degrees) silently produces wrong distances, because a degree of
longitude in Portland is about 70% the length of a degree of latitude. The bug wouldn't
crash anything — it would just quietly return bad routes.

---

## Data sources

| What | Source | Key needed |
|---|---|---|
| Street network (walking) | OpenStreetMap via OSMnx | No |
| Building footprints + heights | OpenStreetMap `building` tags | No |
| Trees, parks, forest | OSM `natural=tree`, `leisure=park`, `landuse=forest` | No |
| Named destinations for the search box | OSM `amenity`, `shop`, `highway=bus_stop`, `leisure=park` | No |
| Solar position | pvlib (computed locally, no network) | No |
| Benches, steps — *planned, M4, not yet used* | OSM `amenity=bench`, `highway=steps` | No |
| Air temperature — *considered and not used*, see Limitations | Open-Meteo | No |

Map data © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright).

---

## Limitations

Stated up front, because a model you can't describe the failure modes of isn't a model.

- **Flat terrain is assumed.** Portland has serious hills; a shadow cast downhill reaches
  further than this model says, and one cast uphill reaches less. No digital elevation model
  is used.
- **Shadow shape is approximated by a convex hull** of the footprint and its translated copy.
  For a concave building — an L-shape, or one with a courtyard — this fills in shade that
  isn't really there. It over-estimates rather than under-estimates.
- **Shadow length is clamped** (default 200 m). `height / tan(elevation)` diverges as the sun
  approaches the horizon: at 0.1° elevation a 10 m building would mathematically cast a 5.7 km
  shadow. The clamp keeps the geometry sane; it means near-sunrise and near-sunset results
  under-state shade at distance.
- **OSM tree coverage is incomplete and wildly uneven.** Some Portland neighbourhoods have
  every street tree mapped; others have none. A route through an unmapped area will look
  sunnier than it is. This is the largest source of error in the whole system.
- **No seasonal leaf-off modelling.** A bare February plane tree is treated exactly like a
  full July one.
- **Parks and forests are treated as fully shaded**, which is generous — an open lawn in the
  middle of a park is not shaded at all.
- **Building heights are frequently estimated**, not measured: `building:height` when tagged,
  else `building:levels × 3.2 m`, else a 3-storey default.
- **No temperature claim is displayed.** Shade principally reduces *mean radiant temperature*,
  not air temperature, so a "feels 8° cooler" figure would be a different quantity than the one
  a thermometer reports. Rather than dress a modelled number as a measured one, this project
  reports only what it actually computes: percentage of the route in shade, extra distance, and
  extra time.

---

## Milestones

| | Milestone | State |
|---|---|---|
| **M0** | Server skeleton, `/health`, Leaflet map, click/keyboard point selection | **Done** |
| **M1** | Walking graph cached to disk, shortest path rendered | **Done** |
| **M2** | Sun position, tree + building shadows, shade fraction, cost function, dual route comparison | **Done** |
| M2v | Optional voxel 3D view of the shadow volumes M2 computes | Not started |
| M4 | Time-of-day scrubber, benches, stair avoidance | Not started |
| M5 | Text route description, accessibility pass, polish | Not started |

*(M3 from the original plan — building shadows — was merged into M2. The pipeline is identical
for trees and buildings; splitting them cost a checkpoint we didn't have in a one-day build.)*

---

## Accessibility

Accessibility isn't a polish pass on this project, it's the point of it. A route planner for
someone who can't safely take the fast route has to work for people who can't easily read a map
either.

**Working today:**

- **Nobody has to know a latitude.** Start and destination are set by searching 245 real named
  places from OpenStreetMap — "Capsule Pharmacy", "Central Library", "Southwest 5th & Madison" —
  or by clicking the map, or by **Use my location**, or by typing coordinates in a collapsed
  advanced section. **Surprise me** picks a real pair for you. Every path is keyboard-operable.
- **Dark mode**, following your system preference with a manual override that persists. The map
  goes dark by filtering the tile layer only — no second tile provider, no API key — so route
  lines and pins keep their true colours.
- **Liquid Glass surfaces** on the header, the buttons, and the result cards: translucent fills
  with a backdrop blur, an inset edge highlight, an ambient shadow, and a specular gloss that
  tracks the pointer. Pill buttons, the system font stack, Apple's easing curves, hairline
  dividers, semibold as the heaviest weight.

  Three constraints were applied *over* the aesthetic, and each one changed the design:
  glass never sits behind the coordinate inputs or the status region, because contrast there
  must not depend on what happens to be underneath; the input cards are solid, which brought
  glass from 32% of the viewport down to 13% and avoided a sidebar of stacked glass panels; and
  the background wash was made much fainter after measurement showed it dragging 15px secondary
  text to 4.36:1.

  Contrast is verified with **alpha actually composited** — page surface, then the background
  wash, then the translucent fill, then the gloss — rather than read off the token value, which
  would report a translucent surface as if it were opaque. 65 text nodes per theme, zero
  failures in either.
- **Full keyboard operation** with visible focus rings, and Enter commits any field.
- **Okabe–Ito palette**, which stays distinguishable under protanopia, deuteranopia and
  tritanopia. Text contrast was swept against live computed styles; the map pins were checked
  separately by hand, since they don't exist in the DOM until a point is placed and an automated
  sweep therefore walks straight past them. That check is what caught the destination pin at
  3.87:1 — full-strength `#d55e00` under white bold text fails the 4.5:1 bar, so the pin uses a
  darkened vermillion at 6.07:1.
- **Nothing carries meaning by colour alone.** The two map pins are distinguished by letter
  (A / B) as well as hue; the two routes are distinguished by line pattern (dashed vs solid)
  with the pattern named in words on each result card; and the shade bar always has its
  percentage written out beside it.
- **Pin colours are deliberately not themed.** Pin labels are white on a white ring over map
  tiles, so their fill must clear 4.5:1 against *white* in either mode. An earlier dark-mode
  override darkened them to 4.07:1 — the opposite of the intended effect — and was removed.
- `prefers-reduced-motion` respected, including Leaflet's JS-driven inertia panning and zoom
  animations, which a CSS-only rule does not reach.
- **Nothing in the app's own interface is below 15 px**; body text is 17 px; interactive targets
  are at least 44 px, including the map's zoom controls, which are enlarged from Leaflet's
  26 px default. The one exception is Leaflet's attribution line — third-party chrome, raised
  from its 11 px default to 13 px but not to 15 px.
- Validation failures set `aria-invalid` and point the field at the error text, so tabbing back
  re-reads the reason instead of stranding it in a live region.
- Coordinate fields are `type="text"` with `inputmode="decimal"` rather than `type="number"`,
  because an arrow-key press on a number input silently turns 45.522 into 44.522 — a point
  110 km away.

**Scheduled, not yet built:**

- A **prose turn-by-turn description** alongside the map, with shade and rest-stop notes (M5).
- A keyboard-and-screen-reader pass over the complete flow (M5).

**Known gap:** below 860 px the page scrolls normally but the map still captures touch drags,
so a swipe starting on the map pans the map rather than the page. Scheduled for M5.

---

## AI assistance

This project was built with AI assistance, disclosed in detail in
[AI_USAGE.md](AI_USAGE.md) as the event rules require.

---

## Licence

MIT.
