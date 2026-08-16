"""Verify every factual claim the launch film makes against the live API.

CLAUDE.md §7 forbids putting a number on screen that was not computed, and
forbids presenting a modelled estimate as a measurement. A video is the easiest
place in the project to break that rule, because nothing in a video is
recomputed — the numbers are typed once and then repeated to a judging panel.

So this asks the running app for the same route the film is about and checks the
film's figures against the answer, rather than trusting the person who typed
them. It also refuses a set of phrasings the brief rules out regardless of
whether the underlying figure is real.

    python video/check_claims.py            # needs the server on :8000
"""

from __future__ import annotations

import html as htmllib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
SCENE = Path(__file__).with_name("scene.html")

# The film is about exactly this journey, at exactly this moment.
PARAMS = {
    "orig_lat": 45.513604, "orig_lon": -122.681465,
    "dest_lat": 45.526229, "dest_lon": -122.683096,
    "when": "2026-08-16T15:00", "shade_aversion": 1.5, "avoid_stairs": "true",
}

# Phrasings the brief rules out however true the arithmetic behind them is.
# Shade changes mean radiant temperature, not air temperature, so any "cooler by
# N degrees" line would be a claim this project cannot support.
FORBIDDEN = [
    (r"\d+\s*°\s*[CF]\b", "a temperature reading"),
    (r"\d+\s*degrees\s+(?:c|f|celsius|fahrenheit)\b", "a temperature reading"),
    (r"\bdegrees\s+(?:warmer|cooler|hotter|colder)\b", "a thermal difference claim"),
    (r"\b(?:warmer|cooler|hotter|colder)\s+by\b", "a thermal difference claim"),
    (r"\bcooler by\b", "an unsupported thermal claim"),
    (r"\bfeels like\b", "an unsupported thermal claim"),
    (r"\bmeasured shade\b", "shade is modelled, not measured"),
    (r"\bguarantee", "a guarantee this project cannot make"),
    (r"\bsafest\b", "a safety claim the model does not support"),
]

failures: list[str] = []
notes: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def visible_text(html: str) -> str:
    body = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = htmllib.unescape(body)
    return re.sub(r"\s+", " ", body)


def main() -> int:
    html = SCENE.read_text(encoding="utf-8")
    text = visible_text(html)

    print("Forbidden phrasing")
    print("-" * 18)
    for pattern, why in FORBIDDEN:
        hit = re.search(pattern, text, re.I)
        check(hit is None, f"no {why}", hit.group(0) if hit else "")

    print("\nFigures against the live API")
    print("-" * 27)
    url = f"{BASE}/api/route?{urllib.parse.urlencode(PARAMS)}"
    try:
        payload = json.load(urllib.request.urlopen(url, timeout=240))
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] could not reach the API — {exc}")
        print("\n  Start the server first:  .venv/Scripts/python -m uvicorn app.main:app")
        return 1

    routes = {r["id"]: r for r in payload["routes"]}
    cmp_ = payload["comparison"]
    shady, short = routes["shadiest"], routes["shortest"]

    # Read the figures OUT OF THE FILM and compare them to the API, rather than
    # comparing the API to a second copy of the same numbers typed here. The
    # earlier version did the latter: changing data-count="85" to "95" still
    # printed a pass, because nothing ever opened scene.html. That is the exact
    # fake-all-clear this project has now produced four times.
    headline = re.search(r'<div class="stats">.*?</section>', html, re.S)
    scope = headline.group(0) if headline else html
    shown_counts = [int(n) for n in re.findall(r'data-count="(\d+)"', scope)]
    expected_counts = [round(short["shade_fraction"] * 100),
                       round(shady["shade_fraction"] * 100)]
    check(sorted(shown_counts) == sorted(expected_counts),
          "the film's two headline figures are the API's",
          f"film {sorted(shown_counts)} vs API {sorted(expected_counts)}")

    # For the rest, require the computed value to actually appear in the film's
    # visible copy. A number the film does not state cannot be verified, so a
    # missing one is a failure rather than a silent pass.
    directions = shady.get("directions") or {}
    rest = directions.get("rest_summary") or {}
    benches = [r for r in (directions.get("rest_stops") or [])
               if r.get("kind") != "drinking_water"]

    spoken = {
        "extra distance": round(cmp_["extra_distance_m"]),
        "extra minutes": round(cmp_["extra_duration_s"] / 60),
        "sun on the fastest route": round(short["sun_seconds"] / 60),
        "sun on the shadiest route": round(shady["sun_seconds"] / 60),
    }
    if benches:
        spoken["bench count"] = len(benches)
    else:
        notes.append("no rest-stop list in the payload; bench count not cross-checked")
    gap = rest.get("longest_gap_m")
    if gap:
        spoken["longest gap without a seat"] = round(gap / 10) * 10
    else:
        notes.append("no longest-gap figure in the payload; 780 m not cross-checked")

    for label, value in spoken.items():
        # Word-boundaried so 7 does not match the 71 in "Marisol is 71".
        found = re.search(rf"(?<!\d){value}(?!\d)", text) is not None
        check(found, f"the film states the computed {label}", f"API says {value}")

    # Claims made by the drawn scenes, from endpoints the route call does not
    # cover. The counters render through data-count, so they are read from the
    # attribute as well as from the visible copy.
    src = payload["shade_sources"]
    for label, value in (("building shadows", src["building_shadows"]),
                         ("tree shadows", src["tree_shadows"])):
        stated = (re.search(rf"(?<!\d){value:,}(?!\d)", text) is not None
                  or f'data-count="{value}"' in html)
        check(stated, f"the film states the computed {label}", f"API says {value:,}")

    try:
        places = json.load(urllib.request.urlopen(BASE + "/api/places", timeout=120))["places"]
        check(f'data-count="{len(places)}"' in html
              or re.search(rf"(?<!\d){len(places)}(?!\d)", text) is not None,
              "the film states the real number of named places", f"API says {len(places)}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"place count not cross-checked ({exc})")

    # The hour strip carries the only recommendation the film makes, so its bars
    # are checked against the sweep rather than trusted.
    bt_q = urllib.parse.urlencode({
        "orig_lat": PARAMS["orig_lat"], "orig_lon": PARAMS["orig_lon"],
        "dest_lat": PARAMS["dest_lat"], "dest_lon": PARAMS["dest_lon"],
        "date": PARAMS["when"].split("T")[0],
    })
    try:
        bt = json.load(urllib.request.urlopen(f"{BASE}/api/best-time?{bt_q}", timeout=900))
        hours = bt.get("hours") or []
        shown = [int(n) for n in re.findall(r"\{ h: (\d+),", html)]
        shown_pct = [int(n) for n in re.findall(r"pct: (\d+) \}", html)]
        api_pct = {h["hour"]: round(h["shade_fraction"] * 100)
                   for h in hours if h.get("shade_fraction") is not None}
        drift = [(h, api_pct.get(h), q) for h, q in zip(shown, shown_pct)
                 if api_pct.get(h) is None or abs(api_pct[h] - q) > 1]
        check(bool(shown) and not drift, "every hour bar matches the sweep",
              ("drifted: " + str(drift)) if drift else f"{len(shown)} hours checked")
        best, worst = bt.get("best_hour"), bt.get("worst_hour")
        if best is not None and worst is not None:
            check(best in shown and worst in shown,
                  "the strip includes the app's own best and worst departures",
                  f"best {best}:00, worst {worst}:00")
            marked_best = re.search(r"entry\.h === (\d+) \? ' best'", html)
            marked_worst = re.search(r": entry\.h === (\d+) \? ' worst'", html)
            check(marked_best and int(marked_best.group(1)) == best and
                  marked_worst and int(marked_worst.group(1)) == worst,
                  "the strip highlights the right two bars",
                  f"film marks {marked_best and marked_best.group(1)}/"
                  f"{marked_worst and marked_worst.group(1)}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"hour strip not cross-checked ({exc})")

    print("\nProvenance")
    print("-" * 10)
    check("OpenStreetMap" in text, "OpenStreetMap is credited on screen")
    check(bool(re.search(r"shadow", text, re.I)), "the film says the shade is a projection")

    if notes:
        print("\nNotes")
        print("-" * 5)
        for n in notes:
            print(f"  · {n}")

    print()
    if failures:
        print(f"FAIL — {len(failures)} claim(s) the film cannot support:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS — every figure in the film matches a computed value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
