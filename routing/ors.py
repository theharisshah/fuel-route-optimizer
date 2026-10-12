"""Client for OpenRouteService"""
import requests
from django.conf import settings

GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
TIMEOUT_SECONDS = 10


class RoutingError(Exception):
    """Custom exception"""


def geocode(place: str) -> tuple[float, float]:
    params = {
        "text": place,
        "boundary.country": "US",
        "size": 1,
    }
    data = _request("GET", GEOCODE_URL, params=params)

    features = data.get("features") or []
    if not features:
        raise RoutingError(f"Could not find location: {place}")

    lng, lat = features[0]["geometry"]["coordinates"]
    return lat, lng


def get_route(start: tuple[float, float], finish: tuple[float, float]) -> dict:
    body = {
        "coordinates": [[start[1], start[0]], [finish[1], finish[0]]],
        "units": "mi",
        "instructions": False,
    }
    data = _request("POST", DIRECTIONS_URL, json=body)

    features = data.get("features") or []
    if not features:
        raise RoutingError("No route found between these locations.")

    feature = features[0]
    summary = feature["properties"].get("summary", {})
    return {
        "distance_miles": summary.get("distance", 0.0),
        "duration_seconds": summary.get("duration", 0.0),
        "coordinates": [(lat, lng) for lng, lat in feature["geometry"]["coordinates"]],
    }


def _api_key() -> str:
    key = settings.ORS_API_KEY
    if not key:
        raise RoutingError("ORS_API_KEY is not set. Add it to your .env file.")
    return key


def _request(method: str, url: str, **kwargs) -> dict:
    headers = {"Authorization": _api_key()}
    try:
        response = requests.request(
            method, url, headers=headers, timeout=TIMEOUT_SECONDS, **kwargs
        )
    except requests.RequestException as exc:
        raise RoutingError(f"Could not reach OpenRouteService ({type(exc).__name__}).") from exc

    if response.status_code != 200:
        raise RoutingError(
            f"OpenRouteService returned HTTP {response.status_code}: {response.text[:200]}"
        )
    return response.json()
