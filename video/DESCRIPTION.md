# Video description

Three versions, longest first. All figures are real outputs of the app for the
route the film follows, and `video/check_claims.py` fails the build if any of
them stops matching the API.

---

## Long — Devpost, project page, LinkedIn

**Shade Route — a walking planner that optimises for shadow, not speed.**

Every map you own routes you the fastest way. For most people that's fine. For
Marisol — 71, in Portland, on a diuretic that impairs her body's ability to shed
heat — the fastest way is an exposed arterial in full sun with nowhere to sit
down, and on a hot afternoon that isn't an inconvenience. It's a risk.

Shade Route computes where building and tree shadows actually fall at a given
moment, then routes to stay in them.

On her walk from the bus stop at SW 6th & Clay to Capsule Pharmacy at 3:00 PM:

- **85% of the shade-weighted route is in shadow**, against **44%** on the fastest one
- The swap costs **+148 m** and **+2 minutes**
- Time in direct sun drops from **15 minutes to 4**
- **17 benches** along the way — and it tells her the longest stretch without one
  is **780 m**, more than the 300 m she needs

Nothing here is a heat map or a guess. Solar position comes from pvlib. Building
footprints and heights come from OpenStreetMap; each one is projected away from
the sun by `height / tan(elevation)` along the solar azimuth, and the shade
fraction of every street segment is measured against the union of those shadows.
The film's 3D sequences are that same geometry — 1,186 building shadows and 737
tree shadows, lit from the sun's real position — so the shadows you see falling
across those streets are the shadows the routing decision was made from.

It also answers the question she actually asks: *when should I go?* Thirteen
departure times, each fully routed, ranked by time in direct sun rather than by
percentage — minutes of exposure are what cause harm.

**What it does not know**, and says so on screen: building heights are estimated
from floor counts wherever OSM has no height; tree coverage is only as complete
as the map, so an untagged street looks sunnier than it is; shadows are convex
hulls and the ground is assumed flat. Shade changes radiant temperature, not air
temperature — so nothing in this project is ever quoted in degrees.

Runs on open data with no API keys. Clone it and it runs.

Built for OregonHacks 2026 · Python · FastAPI · OSMnx · NetworkX · Shapely ·
pvlib · OpenStreetMap · three.js

Repo: https://github.com/Goofturtles/shade-route

---

## Short — YouTube

A walking route planner that finds the shadiest path, not the fastest.

Built for Marisol, 71, who takes a diuretic and can't regulate heat well. On her
walk to the pharmacy: **85% shaded instead of 44%**, for **+148 m** and **+2
minutes** — and time in direct sun falls from **15 minutes to 4**.

Shadows are computed, not guessed: solar position from pvlib, building
footprints from OpenStreetMap, each projected away from the sun and intersected
with the street network. 1,186 building shadows and 737 tree shadows at 3:00 PM.

Open data. No API keys. Clone it and it runs.
https://github.com/Goofturtles/shade-route

---

## One line

A walking route planner that optimises for shadow instead of speed — 85% shaded
instead of 44%, for two extra minutes.

---

## Notes on writing more of these

Two rules this project holds itself to, and they apply to copy as much as to the
interface:

1. **Every figure must be a computed output**, not a rounded-up impression. The
   numbers above come from one API call for one route at one moment, and the
   build gate checks them.
2. **No temperature claim in any form.** Shade reduces mean radiant temperature
   rather than air temperature, and this project does not model that — so any
   headline offering a difference in degrees is unavailable, however tempting.
