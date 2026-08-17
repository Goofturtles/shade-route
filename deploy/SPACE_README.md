---
title: Shade Route
emoji: 🌳
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: Walking routes that stay in the shade, not routes that are fastest.
---

# Shade Route

A walking route planner that finds the **shadiest** path between two points, not
the fastest.

It computes where building and tree shadows actually fall at a given moment —
from OpenStreetMap footprints and the sun's real position — then routes to
maximise time spent out of the sun, and shows you what the detour costs.

**Try it:** the page opens on a worked example — a bus stop to a pharmacy in
inner Portland at 3pm. 85% of that walk stays in shade against 44% on the
fastest route, for 148 m and about 2 minutes more walking. Drag the shade
slider to 0 and it collapses to the plain shortest path, which is how you can
tell the comparison is honest.

Built for OregonHacks 2026. Source, method and limitations:
**https://github.com/Goofturtles/shade-route**

## What the numbers mean

Shade percentages are computed from modelled building and tree shadow geometry,
and are reported separately from park areas that are *assumed* fully shaded —
because only the first is geometry we computed. No temperature difference is
claimed anywhere: shade cuts radiant heat, not air temperature.

## Note on first load

This Space sleeps when idle. The first request after a sleep rebuilds the shade
field and can take a few seconds; every request after that is fast. The street
network and OSM data are baked into the image, so nothing here waits on the
Overpass API.
