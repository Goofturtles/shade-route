"""Solar position.

Thin wrapper over pvlib. Exists mainly to enforce two things the rest of the
code must never get wrong: datetimes are timezone-aware, and a sun below the
horizon is reported as a distinct state rather than allowed to produce garbage
shadow geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pvlib

from app import config

# height / tan(elevation) diverges as the sun approaches the horizon: at 0.1
# degrees a 10 m building would mathematically cast a 5.7 km shadow. Real
# shadows are cut off long before that by terrain, haze and the fact that the
# sun is a disc rather than a point. Clamp, and say so in the README.
MAX_SHADOW_LENGTH_M = 200.0

# Below this the geometry is meaningless even with the clamp, and low-angle
# light is largely blocked by whatever is on the horizon anyway.
MIN_USEFUL_ELEVATION_DEG = 3.0


@dataclass(frozen=True)
class SolarPosition:
    elevation_deg: float
    azimuth_deg: float
    when: datetime

    @property
    def sun_is_up(self) -> bool:
        return self.elevation_deg > 0.0

    @property
    def casts_usable_shadows(self) -> bool:
        return self.elevation_deg >= MIN_USEFUL_ELEVATION_DEG

    def shadow_length_m(self, height_m: float) -> float:
        """Length of the shadow cast by an object of the given height."""
        if not self.casts_usable_shadows:
            return 0.0
        length = height_m / math.tan(math.radians(self.elevation_deg))
        return min(length, MAX_SHADOW_LENGTH_M)

    def shadow_offset_m(self, height_m: float) -> tuple[float, float]:
        """(dx, dy) in metres to translate a footprint into its shadow.

        Shadows fall *away* from the sun, hence azimuth + 180. Azimuth is
        measured clockwise from north, whereas maths convention is
        anticlockwise from east — so dx uses sin and dy uses cos, not the other
        way round. Getting this backwards produces shadows that are plausible
        but rotated, which is exactly the kind of bug nobody notices.
        """
        length = self.shadow_length_m(height_m)
        if length <= 0.0:
            return (0.0, 0.0)
        bearing = math.radians(self.azimuth_deg + 180.0)
        return (length * math.sin(bearing), length * math.cos(bearing))


def solar_position(when: datetime, lat: float | None = None, lon: float | None = None) -> SolarPosition:
    """Solar position for a moment and place.

    A naive datetime is interpreted as local Portland time, because that is what
    a user typing "3pm" into the interface means. pvlib silently returns a
    position that is wrong by hours if handed a naive timestamp treated as UTC.
    """
    lat = config.DEMO_CENTER_LAT if lat is None else lat
    lon = config.DEMO_CENTER_LON if lon is None else lon

    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(config.TIMEZONE))

    frame = pvlib.solarposition.get_solarposition(pd.DatetimeIndex([when]), lat, lon)
    row = frame.iloc[0]
    return SolarPosition(
        elevation_deg=float(row["apparent_elevation"]),
        azimuth_deg=float(row["azimuth"]),
        when=when,
    )
