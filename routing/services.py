"""Plan a trip end to end: locate, route, find stations, pick fuel stops."""
import hashlib
import math
import re
import time

from django.core.cache import cache

from . import ors
from .fuel import plan_fuel_stops
from .geo import stations_along_route

# Geocoding and route results are reused for a day, so repeat trips cost no API calls.
CACHE_SECONDS = 24 * 60 * 60

# Cap on route points returned to the client; enough to draw the route smoothly.
MAX_ROUTE_POINTS = 1000

# "lat,lng" input skips geocoding, e.g. "41.8781,-87.6298".
_COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def plan_trip(start: str, finish: str) -> dict:
    """Return the route, fuel stops and total fuel cost between two US locations."""
    started = time.perf_counter()
    api_calls = 0

    start_point, calls = _locate(start)
    api_calls += calls
    finish_point, calls = _locate(finish)
    api_calls += calls
    route, calls = _route(start_point, finish_point)
    api_calls += calls

    stations = stations_along_route(route["coordinates"], route["distance_miles"])
    plan = plan_fuel_stops(stations, route["distance_miles"])

    return {
        "start": _place(start, start_point),
        "finish": _place(finish, finish_point),
        "distance_miles": round(route["distance_miles"], 1),
        "duration_hours": round(route["duration_seconds"] / 3600, 1),
        "fuel_stops": [
            {
                "name": stop.station.name,
                "address": stop.station.address,
                "city": stop.station.city,
                "state": stop.station.state,
                "lat": stop.station.lat,
                "lng": stop.station.lng,
                "mile": round(stop.station.mile, 1),
                "price_per_gallon": round(stop.station.price, 3),
                "gallons": round(stop.gallons, 2),
                "cost": round(stop.cost, 2),
            }
            for stop in plan.stops
        ],
        "total_gallons": round(plan.total_gallons, 2),
        "total_fuel_cost": round(plan.total_cost, 2),
        "route": _geojson_line(route["coordinates"]),
        "meta": {
            "external_api_calls": api_calls,
            "stations_considered": len(stations),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        },
    }


def _locate(text: str):
    """Return ((lat, lng), api_calls) for a place name or a "lat,lng" string."""
    match = _COORDINATES.match(text)
    if match:
        lat, lng = float(match.group(1)), float(match.group(2))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ors.LocationNotFound(f"Invalid coordinates: {text}")
        return (lat, lng), 0

    key = "geocode:" + _hash(text.strip().lower())
    point = cache.get(key)
    if point is not None:
        return tuple(point), 0
    point = ors.geocode(text)
    cache.set(key, point, CACHE_SECONDS)
    return point, 1


def _route(start, finish):
    """Return (route, api_calls), using the cache when the same trip was planned before."""
    key = "route:" + _hash(f"{start[0]:.5f},{start[1]:.5f}|{finish[0]:.5f},{finish[1]:.5f}")
    route = cache.get(key)
    if route is not None:
        return route, 0
    route = ors.get_route(start, finish)
    cache.set(key, route, CACHE_SECONDS)
    return route, 1


def _place(query, point):
    return {"query": query, "lat": round(point[0], 5), "lng": round(point[1], 5)}


def _geojson_line(coordinates):
    """Route as a GeoJSON LineString, thinned to MAX_ROUTE_POINTS. GeoJSON uses [lng, lat]."""
    step = max(1, math.ceil(len(coordinates) / MAX_ROUTE_POINTS))
    points = coordinates[::step]
    if points[-1] != coordinates[-1]:
        points.append(coordinates[-1])
    return {
        "type": "LineString",
        "coordinates": [[round(lng, 5), round(lat, 5)] for lat, lng in points],
    }


def _hash(text: str) -> str:
    # Cache keys must be short and space-free.
    return hashlib.sha1(text.encode()).hexdigest()
