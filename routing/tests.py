"""Tests for city normalization, route geometry, fuel planning and the API.

ORS is mocked, so the suite runs offline and never uses the API quota.
"""
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from . import ors
from .fuel import FuelPlanError, plan_fuel_stops
from .geo import StationOnRoute, haversine_miles, sample_route, stations_along_route
from .models import FuelStation
from .normalize import normalize_city


def station(mile, price, opis_id=0):
    """A StationOnRoute at a given mile marker; location fields don't matter for planning."""
    return StationOnRoute(opis_id, f"S{opis_id}", "", "Town", "XX", price, 0.0, 0.0, mile, 0.0)


class NormalizeCityTests(SimpleTestCase):
    def test_strips_padding_and_lowercases(self):
        self.assertEqual(normalize_city("  Big Cabin      "), "big cabin")

    def test_punctuation_becomes_space(self):
        self.assertEqual(normalize_city("Bois D'Arc"), "bois d arc")
        self.assertEqual(normalize_city("Winston-Salem"), "winston salem")

    def test_expands_leading_abbreviations(self):
        self.assertEqual(normalize_city("St. Louis"), "saint louis")
        self.assertEqual(normalize_city("Ft Worth"), "fort worth")
        self.assertEqual(normalize_city("Mt Vernon"), "mount vernon")

    def test_does_not_expand_inside_words(self):
        self.assertEqual(normalize_city("Stanton"), "stanton")


class GeoTests(SimpleTestCase):
    def test_haversine_known_distance(self):
        # Chicago to Dallas is ~803 miles in a straight line.
        self.assertAlmostEqual(haversine_miles((41.8781, -87.6298), (32.7767, -96.7970)), 803, delta=5)

    def test_sample_route_spaces_points_and_matches_total(self):
        coordinates = [(40.0, -100.0), (40.0, -99.0)]  # one long segment, ~53 miles
        samples = sample_route(coordinates, total_miles=60.0)
        self.assertEqual(samples[0][2], 0.0)
        self.assertAlmostEqual(samples[-1][2], 60.0)  # scaled to the routing API's distance
        self.assertGreaterEqual(len(samples), 50)  # interpolated inside the segment


class StationsAlongRouteTests(TestCase):
    def test_keeps_nearby_stations_in_route_order(self):
        FuelStation.objects.create(opis_id=1, name="Near end", address="", city="B", state="KS", price=3.0, lat=40.02, lng=-99.1)
        FuelStation.objects.create(opis_id=2, name="Near start", address="", city="A", state="KS", price=3.0, lat=39.98, lng=-99.9)
        FuelStation.objects.create(opis_id=3, name="Far away", address="", city="C", state="KS", price=3.0, lat=41.0, lng=-99.5)

        found = stations_along_route([(40.0, -100.0), (40.0, -99.0)], total_miles=53.0)

        self.assertEqual([s.name for s in found], ["Near start", "Near end"])
        self.assertLess(found[0].mile, found[1].mile)


class FuelPlanTests(SimpleTestCase):
    def test_worked_example(self):
        stations = [station(0, 4, 1), station(100, 3, 2), station(450, 5, 3), station(700, 2, 4), station(900, 6, 5)]

        plan = plan_fuel_stops(stations, total_miles=1000)

        self.assertEqual([s.station.mile for s in plan.stops], [0, 100, 450, 700])
        self.assertEqual([round(s.gallons, 2) for s in plan.stops], [10, 50, 10, 30])
        self.assertAlmostEqual(plan.total_gallons, 100)
        self.assertAlmostEqual(plan.total_cost, 300)

    def test_gallons_cover_the_whole_trip_at_10_mpg(self):
        stations = [station(0, 3.2, 1), station(300, 3.0, 2), station(650, 3.4, 3)]
        plan = plan_fuel_stops(stations, total_miles=900)
        self.assertAlmostEqual(plan.total_gallons, 90)

    def test_short_trip_single_stop(self):
        plan = plan_fuel_stops([station(5, 3.5, 1)], total_miles=200)
        self.assertEqual(len(plan.stops), 1)
        self.assertAlmostEqual(plan.stops[0].gallons, 19.5)

    def test_starts_at_cheapest_station_near_start(self):
        stations = [station(2, 3.9, 1), station(10, 3.1, 2), station(30, 3.5, 3)]
        plan = plan_fuel_stops(stations, total_miles=300)
        self.assertEqual(plan.stops[0].station.opis_id, 2)

    def test_folds_tiny_purchase_into_previous_stop(self):
        # Pure greedy would buy ~0.5 gal at mile 395; that purchase moves to mile 0.
        stations = [station(0, 3.5, 1), station(395, 3.4, 2)]
        plan = plan_fuel_stops(stations, total_miles=400)
        self.assertEqual(len(plan.stops), 1)
        self.assertAlmostEqual(plan.total_gallons, 40)

    def test_never_exceeds_tank_or_runs_dry(self):
        stations = [station(m, p, k) for k, (m, p) in enumerate(
            [(0, 3.3), (120, 3.1), (260, 3.6), (390, 2.9), (610, 3.8), (720, 3.0), (980, 3.2)])]
        plan = plan_fuel_stops(stations, total_miles=1300)

        tank, position = 0.0, plan.stops[0].station.mile
        for stop in plan.stops:
            tank -= stop.station.mile - position
            self.assertGreaterEqual(tank, -1e-6)
            tank += stop.gallons * 10
            self.assertLessEqual(tank, 500 + 1e-6)
            position = stop.station.mile
        self.assertGreaterEqual(tank - (1300 - position), -1e-6)

    def test_gap_longer_than_range_raises(self):
        with self.assertRaises(FuelPlanError):
            plan_fuel_stops([station(0, 3, 1), station(600, 3, 2)], total_miles=900)

    def test_no_station_near_start_raises(self):
        with self.assertRaises(FuelPlanError):
            plan_fuel_stops([station(80, 3, 1)], total_miles=300)


FAKE_ROUTE = {
    "distance_miles": 53.0,
    "duration_seconds": 3000.0,
    "coordinates": [(40.0, -100.0), (40.0, -99.5), (40.0, -99.0)],
}


@patch("routing.ors.get_route", return_value=FAKE_ROUTE)
@patch("routing.ors.geocode", side_effect=lambda place: {"a": (40.0, -100.0), "b": (40.0, -99.0)}[place.lower()])
class RouteApiTests(TestCase):
    def setUp(self):
        cache.clear()
        FuelStation.objects.create(opis_id=1, name="Start Stop", address="I-70 Exit 1", city="A", state="KS", price=3.1, lat=40.01, lng=-99.98)

    def test_returns_plan(self, geocode, get_route):
        response = self.client.get("/api/route/", {"start": "A", "finish": "B"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["distance_miles"], 53.0)
        self.assertEqual(len(data["fuel_stops"]), 1)
        self.assertAlmostEqual(data["total_fuel_cost"], data["total_gallons"] * 3.1, delta=0.02)
        self.assertEqual(data["route"]["type"], "LineString")
        self.assertEqual(data["route"]["coordinates"][0], [-100.0, 40.0])  # GeoJSON is [lng, lat]
        self.assertIn("/map/?", data["map_url"])

    def test_post_and_three_api_calls_then_cached(self, geocode, get_route):
        first = self.client.post("/api/route/", {"start": "A", "finish": "B"}, content_type="application/json")
        second = self.client.post("/api/route/", {"start": "A", "finish": "B"}, content_type="application/json")

        self.assertEqual(first.json()["meta"]["external_api_calls"], 3)
        self.assertEqual(second.json()["meta"]["external_api_calls"], 0)
        self.assertEqual(geocode.call_count, 2)
        self.assertEqual(get_route.call_count, 1)

    def test_coordinates_skip_geocoding(self, geocode, get_route):
        response = self.client.get("/api/route/", {"start": "40.0,-100.0", "finish": "40.0,-99.0"})
        self.assertEqual(response.status_code, 200)
        geocode.assert_not_called()

    def test_missing_field_is_400(self, geocode, get_route):
        response = self.client.post("/api/route/", {"start": "A"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("finish", response.json())

    def test_unknown_place_is_400(self, geocode, get_route):
        geocode.side_effect = ors.LocationNotFound("Could not find location: Nowhere")
        response = self.client.get("/api/route/", {"start": "Nowhere", "finish": "B"})
        self.assertEqual(response.status_code, 400)

    def test_unreachable_trip_is_422(self, geocode, get_route):
        FuelStation.objects.all().delete()
        response = self.client.get("/api/route/", {"start": "A", "finish": "B"})
        self.assertEqual(response.status_code, 422)

    def test_routing_failure_is_502(self, geocode, get_route):
        get_route.side_effect = ors.RoutingError("OpenRouteService returned HTTP 503")
        response = self.client.get("/api/route/", {"start": "A", "finish": "B"})
        self.assertEqual(response.status_code, 502)

    def test_map_page_renders(self, geocode, get_route):
        response = self.client.get("/map/", {"start": "A", "finish": "B"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="trip-data"')
