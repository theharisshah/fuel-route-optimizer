"""Find the fuel stations that lie along a driving route."""
import math
from collections import defaultdict
from dataclasses import dataclass

from .models import FuelStation

EARTH_RADIUS_MILES = 3958.8

# A station counts as "on the route" if it is within this distance of the road.
# Station positions are city centers.
MAX_DETOUR_MILES = 10.0

# Distance between sampled route points.
SAMPLE_SPACING_MILES = 1.0

# Grid cell size for the spatial index. 0.25 degrees is ~17 miles north-south and at least ~11 miles east-west anywhere in the contiguous US
# ...so a route point within MAX_DETOUR_MILES is always in the same cell or a neighbouring one.
GRID_CELL_DEGREES = 0.25


@dataclass
class StationOnRoute:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    price: float
    lat: float
    lng: float
    mile: float  
    offset_miles: float 


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Formula for measuring distances on a sphere"""
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def sample_route(coordinates: list[tuple[float, float]], total_miles: float):
    """Return [(lat, lng, mile)] spaced SAMPLE_SPACING_MILES apart along the route."""
    samples = [(coordinates[0][0], coordinates[0][1], 0.0)]
    travelled = 0.0
    next_sample_at = SAMPLE_SPACING_MILES

    for (lat1, lng1), (lat2, lng2) in zip(coordinates, coordinates[1:]):
        segment = haversine_miles((lat1, lng1), (lat2, lng2))
        while segment > 0 and travelled + segment >= next_sample_at:
            fraction = (next_sample_at - travelled) / segment
            samples.append(
                (
                    lat1 + fraction * (lat2 - lat1),
                    lng1 + fraction * (lng2 - lng1),
                    next_sample_at,
                )
            )
            next_sample_at += SAMPLE_SPACING_MILES
        travelled += segment

    samples.append((coordinates[-1][0], coordinates[-1][1], travelled))

    scale = total_miles / travelled if travelled else 1.0
    return [(lat, lng, mile * scale) for lat, lng, mile in samples]


def stations_along_route(
    coordinates: list[tuple[float, float]], total_miles: float
) -> list[StationOnRoute]:
    """Return stations within MAX_DETOUR_MILES of the route, ordered by mile marker."""
    samples = sample_route(coordinates, total_miles)

    # Spatial index: grid cell -> route samples inside it.
    grid = defaultdict(list)
    for sample in samples:
        grid[_cell(sample[0], sample[1])].append(sample)

    # Only load stations inside the route's bounding box (plus a margin).
    lats = [s[0] for s in samples]
    lngs = [s[1] for s in samples]
    margin = GRID_CELL_DEGREES
    candidates = FuelStation.objects.filter(
        lat__range=(min(lats) - margin, max(lats) + margin),
        lng__range=(min(lngs) - margin, max(lngs) + margin),
    )

    found = []
    for station in candidates:
        nearest = _nearest_sample(grid, station.lat, station.lng)
        if nearest is None:
            continue
        offset, mile = nearest
        if offset <= MAX_DETOUR_MILES:
            found.append(
                StationOnRoute(
                    opis_id=station.opis_id,
                    name=station.name,
                    address=station.address,
                    city=station.city,
                    state=station.state,
                    price=station.price,
                    lat=station.lat,
                    lng=station.lng,
                    mile=mile,
                    offset_miles=offset,
                )
            )

    found.sort(key=lambda s: s.mile)
    return found


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return math.floor(lat / GRID_CELL_DEGREES), math.floor(lng / GRID_CELL_DEGREES)


def _nearest_sample(grid, lat: float, lng: float):
    """Return (distance_miles, mile_marker) of the closest route sample in the 3x3
    block of cells around (lat, lng), or None if the route doesn't pass nearby."""
    row, col = _cell(lat, lng)
    best = None
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            for s_lat, s_lng, mile in grid.get((row + d_row, col + d_col), ()):
                distance = haversine_miles((lat, lng), (s_lat, s_lng))
                if best is None or distance < best[0]:
                    best = (distance, mile)
    return best
