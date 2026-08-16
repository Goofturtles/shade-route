# Shade Route

**A walking route planner that finds the shadiest path between two points, not the fastest.**

Give it an origin, a destination, and a date and time. It works out where building and tree
shadows fall at that moment, then routes to maximise the time you spend in shade — and shows
you honestly what that costs: *"+4 min walk, 61% shaded instead of 12%."*

> **Status: Milestone 5 of 5 — it works end to end.** Sun position, building and tree
> shadows, per-segment shade measurement, and shade-aware routing are all live. A mid-afternoon
> walk across downtown Portland comes out as **+4 min for 94% shade instead of 39%** — and 1 minute in direct sun instead of 15. See
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
| Benches, drinking fountains, steps | OSM `amenity=bench`, `amenity=drinking_water`, `highway=steps` | No |
| Air temperature — *considered and not used*, see Limitations | Open-Meteo | No |

Map data © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright).

### Interface assets

None of these carry an API key either, and none of them affect a computed number.

| What | Source | Licence | If it fails to load |
|---|---|---|---|
| `web/img/canopy.jpg` — the backdrop and hero photograph | [StockSnap.io](https://stocksnap.io) | CC0 (public domain) | The backdrop falls back to a procedurally painted canopy drawn on a `<canvas>`; nothing else changes |
| Fraunces (display type) | Google Fonts | SIL Open Font License 1.1 | Falls back to Georgia / system serif |
| Public Sans (body type) | Google Fonts | SIL Open Font License 1.1 | Falls back to the system UI sans stack |
| Leaflet 1.9.4 | unpkg CDN | BSD-2-Clause | The map does not render; the prose directions still do |

The photograph is committed to the repository rather than hotlinked, so it works
offline. The two typefaces load from Google Fonts with `font-display: swap` — the
same network bet already made on Leaflet and on the map tiles, and the page is
fully legible in the fallback faces if that bet loses.

**Public Sans** was chosen rather than defaulted to: it is the typeface drawn for
US federal public-service interfaces, where the legibility problem is the same
one this project has.

### The example route on first load

The page opens on a worked example — **Southwest 6th & Clay → Capsule Pharmacy**,
Marisol's actual errand — rather than an empty form. It is a real route computed
by the same endpoint any other query uses; nothing about it is hardcoded except
the two endpoints. It was selected by measuring 30 candidate pairs in the demo
area (see the shade-gain search in the commit history), so it is a favourable
example, not a typical one: the median pair in that sample gained closer to
35 percentage points of shade than 40. Any point you set replaces it.

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
- **Parks are treated as wholly shaded, and on this demo route that is nearly half the
  headline.** An open riverside lawn is not shaded at all. Rather than hide this, the interface
  decomposes every shade figure: the 94% route is **45.9% modelled building and tree shadows
  plus 47.7% park area assumed fully shaded**. The two numbers are never blended into one that
  looks measured.
- **Shade is sampled on the street centreline, not the sidewalk.** Marisol walks 5–7 m to one
  side. On a north–south street with a tall building on the west side, the centreline can read
  sunlit while the east sidewalk is fully shaded — a systematic under-count, and worst exactly
  where shade matters most. Not fixed; named.
- **Building heights are mostly inferred.** About 9% of footprints here carry a real `height`
  tag; the rest come from `levels × 3.2 m` or a 3-storey default.
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
| **M4** | Time-of-day controls, benches, stair avoidance | **Done** |
| **M5** | Prose turn-by-turn description, accessibility pass, polish | **Done** |
| M2v | Optional voxel 3D view of the shadow volumes | Cut — the shadow overlay does this job |

*(M3 from the original plan — building shadows — was merged into M2. The pipeline is identical
for trees and buildings; splitting them cost a checkpoint we didn't have in a one-day build.)*

---

## Where this sits in the literature

This is not a new idea, and pretending otherwise would be the wrong move in front of engineers.

- The shadow step is **SOLWEIG's** (Lindberg, Holmer & Thorsson, 2008, *Int. J. Biometeorology*)
  in vector form — geometric shade only, without the longwave and surface-temperature budget a
  real mean-radiant-temperature model carries.
- The routing formulation matches **CoolWalks** (Wolf, Vierø & Szell, *Scientific Reports* 15:14911,
  2025) — same OSM buildings, same shade-weighted cost.
- Their result is worth stating against ourselves: on a **regular grid with uniform building
  heights, shade routing yields little benefit**, because every detour is symmetric. Downtown
  Portland is a near-perfect grid. The gain here comes from what breaks that symmetry — the
  river frontage, the parks, and 737 mapped street trees — which is also precisely why the
  park assumption above carries so much of the number.
- Commercial prior art renders shadows well already (ShadeMap, Shadowmap). What none of them
  do is Marisol: benches, stairs, prose directions, and an accessibility-first interface.

**What this project claims:** percentage of route in shade (decomposed into modelled and
assumed), extra distance, extra time, minutes in direct sun, bench count, and the longest
stretch without a seat. **What it does not claim:** any temperature. Shade principally reduces
mean radiant temperature rather than air temperature, and computing that properly needs a
longwave budget this does not have.


## Accessibility

Accessibility isn't a polish pass on this project, it's the point of it. A route planner for
someone who can't safely take the fast route has to work for people who can't easily read a map
either.

**Working today:**

- **The route in words.** A numbered turn-by-turn description sits in the panel, not behind a
  disclosure, generated from the same graph the map draws - which way to turn, onto what street,
  how far, whether that stretch is in sun, and where the benches are. You can switch between
  describing the shadiest and the shortest route. A map alone is unusable for a screen-reader
  user; this is the route itself, in prose.
- **Rest stops.** 394 benches and 66 drinking fountains from OSM. Each route reports how many
  benches it passes and - the number that actually matters - **the longest stretch you would
  walk without being able to sit down.** The brief asks for a rest stop roughly every 300 m, and
  the interface says plainly when a route misses that.
- **Stairs are avoided.** Steps are priced out of the graph rather than merely discouraged, and
  if a route still contains them it says so.

- **Nobody has to know a latitude.** Start and destination are set by searching 245 real named
  places from OpenStreetMap — "Capsule Pharmacy", "Central Library", "Southwest 5th & Madison" —
  or by clicking the map, or by **Use my location**, or by typing coordinates in a collapsed
  advanced section. **Surprise me** picks a real pair for you. Every path is keyboard-operable.
- **Dark mode**, following your system preference with a manual override that persists. The map
  goes dark by filtering the tile layer only — no second tile provider, no API key — so route
  lines and pins keep their true colours.
- **Liquid Glass over foliage.** The interface floats on a soft, defocused canopy painted at
  runtime on a canvas — no image request, no key. The map is a card inside the layout rather
  than the page background, which is what allows the panels to be genuinely see-through: at a
  0.34 fill in light and 0.46 in dark you read the backdrop through them.
- **Contrast is verified against the pixels actually painted**, not against the tokens —
  the canopy is sampled at 280 points and the darkest and lightest taken, and Leaflet's own
  chrome is checked against the post-filter tile extremes. 110 text nodes per theme, zero
  failures. Decorative `aria-hidden` glyphs are excluded per WCAG 1.4.3 and the count of
  exclusions is reported, so the exemption is visible rather than silent.
- Secondary text is deliberately darker than Apple's own neutrals, because it sits on
  translucent glass rather than on a known page.

**Honest gaps:**

- The flow has **not** been driven with a real screen reader. The structure is verified —
  ordered list, labelled sections, no heading skips, no target under 44 px — but that is a
  different claim from "tested with NVDA".
- Below 860 px the map still captures touch drags meant to scroll the page.


## AI assistance

This project was built with AI assistance, disclosed in detail in
[AI_USAGE.md](AI_USAGE.md) as the event rules require.

---

## Licence

MIT.
