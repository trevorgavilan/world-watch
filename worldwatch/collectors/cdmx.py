"""Where Trevor is: Mexico City. The distance from it, and the rule for a quake worth an alert.

The rule is ours, not a source's (an alert is basis "inferred"): a quake is "near CDMX" when it is
at least so strong for its distance. The rows are a rough "likely felt in the city" guide — the
lake-bed soil amplifies far quakes (Puebla 2017 at ~120 km, Pinotepa 2018 at ~350 km, Chiapas 2017
at ~1,000 km were all felt). It is not SASMEX and never a warning: it comes after the fact (D-22).
"""

from __future__ import annotations

import math

CDMX_LAT, CDMX_LON = 19.4326, -99.1332  # the Zócalo
EARTH_RADIUS_KM = 6371.0

# (up to this many km from CDMX, at least this magnitude) — the first row that fits decides.
NEAR_RULES = ((150.0, 2.5), (400.0, 5.0), (700.0, 6.0), (1200.0, 7.0))


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine), in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def km_from_cdmx(lat: float, lon: float) -> float:
    return km_between(CDMX_LAT, CDMX_LON, lat, lon)


def near_cdmx(mag: float | None, lat: object, lon: object) -> bool:
    if not isinstance(mag, (int, float)) or isinstance(mag, bool) or mag != mag:
        return False
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
        return False
    distance = km_from_cdmx(float(lat), float(lon))
    return any(distance <= km and mag >= min_mag for km, min_mag in NEAR_RULES)
