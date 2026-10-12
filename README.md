# Fuel Route Optimizer API

A Django REST API that takes a start and finish location in the USA and returns the route, the most cost-effective fuel stops along it (500-mile vehicle range), and the total fuel cost at 10 miles per gallon.

## Setup

Requires Python 3.12+.

1. Create a virtual environment and install dependencies:
   ```Shell
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in the values:
   - `SECRET_KEY`: any long random string
   - `ORS_API_KEY`: a free key from [openrouteservice.org](https://openrouteservice.org/dev/#/signup)
3. Create the database and load the fuel stations (one-time, takes a few seconds):
   ```Shell
    python manage.py migrate
    python manage.py load_stations
   ```
4. Start the server:
   ```Shell
   python manage.py runserver
   ```

## API usage

**Endpoint:** `GET` or `POST /api/route/`

| Field | Description |
|---|---|
| `start` | A US place (`"Chicago, IL"`) or coordinates (`"41.8781,-87.6298"`) |
| `finish` | Same format as `start` |

Coordinates skip geocoding, so they save API calls.

**Request**

```Shell
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Chicago, IL", "finish": "Dallas, TX"}'
```

`GET /api/route/?start=Chicago, IL&finish=Dallas, TX` works too, and opens DRF's browsable view in a browser.

**Response** (abridged; exact figures depend on the route returned by OpenRouteService)

```json
{
  "start": {"query": "Chicago, IL", "lat": 41.87811, "lng": -87.6298},
  "finish": {"query": "Dallas, TX", "lat": 32.77666, "lng": -96.79699},
  "distance_miles": 911.7,
  "duration_hours": 13.9,
  "fuel_stops": [
    {
      "name": "RICKY ROCKETS FUEL CENTER",
      "address": "SR-50 & SR-83",
      "city": "Midlothian",
      "state": "IL",
      "lat": 41.6254,
      "lng": -87.7243,
      "mile": 18.0,
      "price_per_gallon": 3.099,
      "gallons": 24.6,
      "cost": 76.24
    }
  ],
  "total_gallons": 89.37,
  "total_fuel_cost": 263.62,
  "route": {"type": "LineString", "coordinates": [[-87.6298, 41.87811], "..."]},
  "meta": {"external_api_calls": 3, "stations_considered": 166, "elapsed_ms": 21},
  "map_url": "http://127.0.0.1:8000/map/?start=Chicago%2C+IL&finish=Dallas%2C+TX"
}
```

- `route` is a GeoJSON LineString (`[lng, lat]` order, per the GeoJSON spec), thinned to at most ~1,000 points.
- `mile` is the distance from the start, along the route, where you pass the station.
- `map_url` opens an interactive map of the route and fuel stops (Leaflet + OpenStreetMap tiles).
- `meta` shows how many external API calls the request made and how long it took.

**Errors**

| Status | When |
|---|---|
| `400` | Missing field, invalid coordinates, or a place that can't be found |
| `422` | The trip can't be covered: no station within 50 miles of the start, or a gap longer than 500 miles between stations |
| `502` | OpenRouteService is unreachable or returned an error |

## How it works

**External API calls: 3 per request.** All map and routing data comes from [OpenRouteService](https://openrouteservice.org) (free, no credit card required), isolated in `routing/ors.py`:

1. Geocode the start location (place name → coordinates)
2. Geocode the finish location
3. Get the driving route: distance in miles plus the route geometry (the list of points along the road)

Turn-by-turn instructions are disabled in the routing request, which keeps the response small and fast. The ORS API key is sent in a request header, never in the URL, so it cannot leak into logs or error messages.

**Finding stations along the route** (`routing/geo.py`)

1. The route is sampled every mile, interpolating inside long straight segments, and each sample gets a mile marker (distance from the start).
2. The samples are indexed in a grid of 0.25° cells (a spatial hash grid).
3. Only stations inside the route's bounding box are loaded from the database. Each one is matched to its nearest sample by checking just its own grid cell and the 8 around it.
4. Stations within 10 miles of the road are kept, sorted by mile marker.

This takes about 20 ms for a 900-mile route, versus about 4 s comparing every station with every route point.

**Choosing fuel stops** (`routing/fuel.py`)

The classic greedy algorithm for refuelling along a fixed route. At each station, look one tank (500 miles) ahead:

- If cheaper fuel is in reach, buy just enough to get there.
- Otherwise this is the cheapest fuel in reach: if the destination is within range, buy just enough to finish; if not, fill the tank and continue to the cheapest station in reach.

This is verified optimal against exhaustive search on randomly generated routes. Gallons bought are miles ÷ 10, and the total cost is the sum of gallons × price at each stop.

**Speed.** Geocoding and route results are cached for 24 hours, so a repeated trip makes 0 external API calls. Everything after the routing call runs locally in about 20–40 ms.

## Data & assumptions

**Station coordinates.** The provided fuel price CSV contains station name, address, city, state and price, but no coordinates. Calling a geocoding API for ~8,000 stations would be slow and break the "few external API calls" requirement, so stations are geocoded once, offline, at load time: each station's (city, state) is matched against a US cities dataset that includes latitude and longitude.

**Data cleaning applied by the loader:**

- **City names are normalized before matching.** The source pads city names with trailing spaces, so they are trimmed, lowercased, stripped of punctuation (`.`, `'`, `-`), and leading abbreviations are expanded (`St` → `Saint`, `Ft` → `Fort`, `Mt` → `Mount`).
- **Canadian stations are excluded.** About 620 rows are in Canadian provinces (ON, AB, BC, MB, SK, YT, QC, NS, NB). Routes are US-only, so these are dropped.
- **Duplicate stations keep the cheapest price.** 678 truckstop IDs appear more than once, and most of them with different prices. One row is kept per ID at the lowest price, since that is the price a driver would pay.
- **Name collisions use the larger city.** Where the cities dataset has two places with the same name in one state, the more populated one is used.

**Coverage.** 6,160 of 6,626 US stations (93%) are matched to coordinates. The unmatched ones are mostly small New England and Pennsylvania towns and townships that the free cities dataset doesn't include; they are skipped and logged by the loader.

**Price storage.** Prices are stored as floats. They are averaged estimates with up to 8 decimal places, and all route calculations are floating-point. Only the final total cost is rounded to cents.

**Fuel-stop assumptions:**

- **The truck starts with an empty tank** and fills up at the cheapest station within the first 50 miles, so the total cost covers fuel for the whole trip. The few miles driven to reach that first station are not costed.
- **A station is "on the route" if it is within 10 miles of the road.** Station positions are city centers, so this allows for highway exits outside town.
- **Practical rules to avoid pointless stops.** After filling the tank, the next stop is at least 50 miles away, and purchases under 5 gallons are folded into the previous stop when the tank has room. These add about 0.3% to the cost on average, in exchange for no one-gallon stops.

## Running tests

```Shell
python manage.py test routing
```

23 tests cover city-name normalization, route geometry, the fuel planner (including tank-capacity checks) and the API (response shape, caching, and error codes). OpenRouteService is mocked, so the tests run offline and use no API quota.

## Limitations

- **Station positions are city-level.** Each station is placed at its city's center, not its exact address, which is good enough to pick stops along a long route but can be off by a few miles.
- **Some stations are missing.** About 7% of stations (unmatched cities) are not considered, so a few cheaper options in the Northeast may be missed.
- **Detours aren't costed.** A station up to 10 miles off the road is treated as being on it; the extra driving isn't added to the fuel total.
- **The cache is in-memory.** It lasts as long as the server process; a shared cache such as Redis would be the production choice.

## Credits

- Fuel prices: provided by Spotter for this assessment.
- US city coordinates: [Simplemaps US Cities Database (Basic)](https://simplemaps.com/data/us-cities), licensed under CC BY 4.0.
- Routing and geocoding: [openrouteservice.org](https://openrouteservice.org) by HeiGIT. Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
- Map page: [Leaflet](https://leafletjs.com) with OpenStreetMap tiles.
