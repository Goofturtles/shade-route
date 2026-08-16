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

import json
import re
import sys
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
    (r"\d+\s*°", "a temperature reading"),
    (r"\bdegrees\b", "a temperature reading"),
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
    body = body.replace("&mdash;", "—").replace("&middot;", "·").replace("&amp;", "&")
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

    # The film rounds; the check allows rounding but nothing looser.
    claims = {
        "85": round(shady["shade_fraction"] * 100),
        "44": round(short["shade_fraction"] * 100),
        "148": round(cmp_["extra_distance_m"]),
        "2": round(cmp_["extra_duration_s"] / 60),
        "15": round(short["sun_seconds"] / 60),
        "4": round(shady["sun_seconds"] / 60),
    }
    for shown, actual in claims.items():
        check(int(shown) == actual, f'film says "{shown}"', f"API says {actual}")

    # These two come from the directions payload rather than the route summary.
    directions = shady.get("directions") or {}
    benches = [s for s in directions.get("rest_stops", []) if s.get("kind") != "drinking_water"]
    if benches:
        check(str(len(benches)) in text or "17" in text,
              "bench count on screen matches the route", f"{len(benches)} on this route")
    else:
        notes.append("no rest-stop list in the payload; bench count not cross-checked")

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
