"""Turn-by-turn directions in plain prose.

This is the part of the project that makes it usable without a map. Marisol
should be able to read the route out, or have it read to her, and walk it —
knowing which way to turn, how far, whether that stretch is in sun, and where
she can sit down.

The brief is explicit that a map alone is unusable for a screen-reader user, so
nothing here is a caption on the map: it is the route, in words, generated from
the same graph the map draws.
"""

from __future__ import annotations

import math

from app import config

# Turn thresholds in degrees of bearing change. Deliberately coarse — "bear
# left" versus "turn left" is a distinction a walker can act on; five
# gradations is not.
SLIGHT = 22.0
NORMAL = 55.0
SHARP = 130.0

# How close a bench has to be to count as "on" this route.
BENCH_NEAR_M = 28.0

# The brief asks for a rest stop roughly every 300 m.
REST_TARGET_M = 300.0

_COMPASS = ["north", "north-east", "east", "south-east",
            "south", "south-west", "west", "north-west"]


def compass_name(bearing: float) -> str:
    return _COMPASS[int((bearing % 360) / 45.0 + 0.5) % 8]


def bearing_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from one point to another, degrees clockwise from north."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def turn_phrase(previous: float, current: float) -> str:
    delta = (current - previous + 540.0) % 360.0 - 180.0   # -180..180
    magnitude = abs(delta)
    side = "right" if delta > 0 else "left"
    if magnitude < SLIGHT:
        return "Continue"
    if magnitude < NORMAL:
        return f"Bear {side}"
    if magnitude < SHARP:
        return f"Turn {side}"
    return f"Turn sharply {side}"


def describe_shade(fraction: float) -> str:
    """Plain words for a measured shade fraction."""
    if fraction >= 0.85:
        return "almost entirely in shade"
    if fraction >= 0.6:
        return "mostly in shade"
    if fraction >= 0.35:
        return "partly shaded"
    if fraction >= 0.15:
        return "mostly in the sun"
    return "in full sun"


def format_distance(metres: float) -> str:
    if metres >= 1000:
        return f"{metres / 1000:.1f} km"
    if metres >= 100:
        return f"{int(round(metres / 10) * 10)} m"
    return f"{max(5, int(round(metres / 5) * 5))} m"


def format_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def _street_name(data: dict) -> str | None:
    name = data.get("name")
    if isinstance(name, list):
        name = name[0] if name else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _way_kind(data: dict) -> str:
    highway = data.get("highway")
    if isinstance(highway, list):
        highway = highway[0] if highway else None
    return {
        "steps": "a flight of steps",
        "footway": "a footpath",
        "path": "a path",
        "pedestrian": "a pedestrian street",
        "cycleway": "a shared path",
        "service": "a service road",
    }.get(highway, "an unnamed street")


def _edge(graph, u: int, v: int, weight: str) -> dict:
    return min(graph[u][v].values(), key=lambda d: d.get(weight, d["length"]))


def build_legs(graph, route: list[int], weight: str = "length") -> list[dict]:
    """Collapse the node path into legs, one per continuous named street."""
    legs: list[dict] = []
    for u, v in zip(route[:-1], route[1:]):
        data = _edge(graph, u, v, weight)
        name = _street_name(data)
        label = name or _way_kind(data)
        heading = bearing_between(
            graph.nodes[u]["y"], graph.nodes[u]["x"],
            graph.nodes[v]["y"], graph.nodes[v]["x"],
        )
        length = float(data["length"])
        shaded = length * float(data.get("shade_fraction", 0.0))
        is_steps = _way_kind(data) == "a flight of steps"

        # Extend the current leg when the street name is unchanged; a walker
        # does not want an instruction per OSM way segment.
        if legs and legs[-1]["label"] == label and not is_steps and not legs[-1]["steps"]:
            leg = legs[-1]
            leg["length_m"] += length
            leg["shaded_m"] += shaded
            leg["end_bearing"] = heading
            leg["end_node"] = v
        else:
            legs.append({
                "label": label,
                "named": name is not None,
                "length_m": length,
                "shaded_m": shaded,
                "start_bearing": heading,
                "end_bearing": heading,
                "start_node": u,
                "end_node": v,
                "steps": is_steps,
            })
    return _merge_trivial(legs)


def _merge_trivial(legs: list[dict]) -> list[dict]:
    """Fold away instructions a walker would never need.

    Crossing an intersection puts a short unnamed footway between two runs of
    the same street, so the raw legs read "continue along Broadway for 65 m,
    continue along a footpath for 15 m, continue along Broadway for 65 m" —
    three instructions for walking in a straight line across one junction.

    A leg merges into the previous one when the direction barely changes AND
    either side is unnamed or trivially short. Steps never merge: that is the
    one thing this route has to be able to warn about.
    """
    merged: list[dict] = []
    for leg in legs:
        if merged:
            previous = merged[-1]
            delta = abs((leg["start_bearing"] - previous["end_bearing"] + 540.0) % 360.0 - 180.0)
            straight_on = delta < SLIGHT
            incidental = (not leg["named"]) or (not previous["named"]) or leg["length_m"] < 30.0
            # Folding a crosswalk into the leg before it leaves two runs of the
            # same street adjacent, and the first pass has already gone by.
            # Without this the prose said "Continue along Southwest Taylor
            # Street for 85 m" five times in a row.
            same_street = leg["named"] and previous["named"] and leg["label"] == previous["label"]
            if straight_on and (incidental or same_street) \
                    and not leg["steps"] and not previous["steps"]:
                # Keep whichever label is a real street name.
                if not previous["named"] and leg["named"]:
                    previous["label"] = leg["label"]
                    previous["named"] = True
                previous["length_m"] += leg["length_m"]
                previous["shaded_m"] += leg["shaded_m"]
                previous["end_bearing"] = leg["end_bearing"]
                previous["end_node"] = leg["end_node"]
                continue
        merged.append(leg)
    return merged


def _benches_on_route(graph, route: list[int], rest_stops: list[dict]) -> list[dict]:
    """Rest stops within BENCH_NEAR_M of the route, with distance along it.

    A simple point-to-segment scan. The route is a few dozen segments and the
    rest-stop list a few hundred points, so this is thousands of comparisons —
    not worth a spatial index, and easier to be sure is correct.
    """
    if not rest_stops:
        return []

    # Metres per degree at this latitude, so distances are comparable.
    mid_lat = graph.nodes[route[len(route) // 2]]["y"]
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(mid_lat))

    points = [(graph.nodes[n]["y"], graph.nodes[n]["x"]) for n in route]
    found: list[dict] = []

    for stop in rest_stops:
        best_distance = float("inf")
        best_along = 0.0
        travelled = 0.0
        for (lat1, lon1), (lat2, lon2) in zip(points[:-1], points[1:]):
            ax = (lon1 - stop["lon"]) * m_per_deg_lon
            ay = (lat1 - stop["lat"]) * m_per_deg_lat
            bx = (lon2 - lon1) * m_per_deg_lon
            by = (lat2 - lat1) * m_per_deg_lat
            seg_len_sq = bx * bx + by * by
            seg_len = math.sqrt(seg_len_sq)
            if seg_len_sq == 0:
                t = 0.0
            else:
                t = max(0.0, min(1.0, -(ax * bx + ay * by) / seg_len_sq))
            dx = ax + t * bx
            dy = ay + t * by
            distance = math.hypot(dx, dy)
            if distance < best_distance:
                best_distance = distance
                best_along = travelled + t * seg_len
            travelled += seg_len

        if best_distance <= BENCH_NEAR_M:
            found.append({
                "kind": stop["kind"],
                "lat": stop["lat"],
                "lon": stop["lon"],
                "along_m": round(best_along, 1),
                "offset_m": round(best_distance, 1),
            })

    found.sort(key=lambda s: s["along_m"])
    return found


def rest_stop_summary(benches: list[dict], total_length_m: float) -> dict:
    """How well this route is served by places to sit.

    `longest_gap_m` is the honest headline: it is the stretch you would have to
    walk without being able to sit down, including the gaps at either end.
    """
    seats = [b for b in benches if b["kind"] == "bench"]
    water = [b for b in benches if b["kind"] == "drinking_water"]

    marks = [0.0] + [b["along_m"] for b in seats] + [total_length_m]
    longest_gap = max((b - a) for a, b in zip(marks[:-1], marks[1:])) if len(marks) > 1 else total_length_m

    return {
        "bench_count": len(seats),
        "drinking_water_count": len(water),
        "longest_gap_m": round(longest_gap, 1),
        "meets_300m_target": longest_gap <= REST_TARGET_M,
    }


def build_directions(graph, route: list[int], weight: str, *,
                     sun_casts_shadows: bool,
                     rest_stops: list[dict] | None = None,
                     destination_name: str | None = None) -> dict:
    """Full prose directions for one route."""
    legs = build_legs(graph, route, weight)
    benches = _benches_on_route(graph, route, rest_stops or [])
    total_length = sum(leg["length_m"] for leg in legs)

    steps: list[dict] = []
    travelled = 0.0
    previous_bearing: float | None = None

    for index, leg in enumerate(legs):
        shade_fraction = (leg["shaded_m"] / leg["length_m"]) if leg["length_m"] else 0.0

        if previous_bearing is None:
            opening = f"Head {compass_name(leg['start_bearing'])}"
        else:
            opening = turn_phrase(previous_bearing, leg["start_bearing"])

        preposition = "along" if opening == "Continue" else "onto"
        sentence = f"{opening} {preposition} {leg['label']} for {format_distance(leg['length_m'])}."

        if sun_casts_shadows:
            sentence += f" This stretch is {describe_shade(shade_fraction)}."

        if leg["steps"]:
            sentence += " Note: this section has steps."

        # Benches that fall within this leg, described relative to it.
        leg_start, leg_end = travelled, travelled + leg["length_m"]
        here = [b for b in benches if leg_start - 1 <= b["along_m"] < leg_end + 1]
        seats = [b for b in here if b["kind"] == "bench"]
        if seats:
            if len(seats) == 1:
                offset = seats[0]["along_m"] - leg_start
                sentence += f" There is a bench about {format_distance(max(offset, 5))} along this stretch."
            else:
                sentence += f" There are {len(seats)} benches along this stretch."
        # Drinking water is deliberately NOT mentioned per leg. With 66 taps in
        # the demo area it landed on nearly every instruction and drowned out
        # the benches, which are the thing that decides whether Marisol can
        # make the walk at all. It goes in the summary instead.

        steps.append({
            "index": index + 1,
            "text": sentence,
            "length_m": round(leg["length_m"], 1),
            "shade_fraction": round(shade_fraction, 4),
            "has_steps": leg["steps"],
            "street": leg["label"],
        })

        travelled = leg_end
        previous_bearing = leg["end_bearing"]

    arrival = f"You arrive at {destination_name}." if destination_name else "You have arrived."
    steps.append({
        "index": len(steps) + 1,
        "text": arrival,
        "length_m": 0.0,
        "shade_fraction": None,
        "has_steps": False,
        "street": None,
    })

    summary = rest_stop_summary(benches, total_length)
    return {
        "steps": steps,
        "rest_stops": benches,
        "rest_summary": summary,
        "has_steps": any(leg["steps"] for leg in legs),
        "walking_speed_m_s": config.WALKING_SPEED_M_S,
    }
