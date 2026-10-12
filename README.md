# Fuel Route Optimizer API

A Django REST API that takes a start and finish location in the USA and returns the route, the most cost-effective fuel stops along it (500-mile vehicle range), and the total fuel cost at 10 miles per gallon.

## Setup

TODO: venv, `pip install -r requirements.txt`, `.env`, `migrate`, `load_stations`

## API usage

TODO: endpoint, request/response example

## How it works

TODO: routing call, finding stations near the route, fuel-stop algorithm

## Data & assumptions

**Station coordinates.** The provided fuel price CSV contains station name, address, city, state and price, but no coordinates. Calling a geocoding API for ~8,000 stations would be slow and break the "few external API calls" requirement, so stations are geocoded once, offline, at load time: each station's (city, state) is matched against a US cities dataset that includes latitude and longitude.

**Data cleaning applied by the loader:**

- **City names are normalized before matching.** The source pads city names with trailing spaces, so they are trimmed, lowercased, stripped of punctuation (`.`, `'`, `-`), and leading abbreviations are expanded (`St` → `Saint`, `Ft` → `Fort`, `Mt` → `Mount`).
- **Canadian stations are excluded.** About 620 rows are in Canadian provinces (ON, AB, BC, MB, SK, YT, QC, NS, NB). Routes are US-only, so these are dropped.
- **Duplicate stations keep the cheapest price.** 678 truckstop IDs appear more than once, and most of them with different prices. One row is kept per ID at the lowest price, since that is the price a driver would pay.
- **Name collisions use the larger city.** Where the cities dataset has two places with the same name in one state, the more populated one is used.

**Coverage.** 6,160 of 6,626 US stations (93%) are matched to coordinates. The unmatched ones are mostly small New England and Pennsylvania towns and townships that the free cities dataset doesn't include; they are skipped and logged by the loader.

**Price storage.** Prices are stored as floats. They are averaged estimates with up to 8 decimal places, and all route calculations are floating-point. Only the final total cost is rounded to cents.

## Limitations

- **Station positions are city-level.** Each station is placed at its city's center, not its exact address, which is good enough to pick stops along a long route but can be off by a few miles.
- **Some stations are missing.** About 7% of stations (unmatched cities) are not considered, so a few cheaper options in the Northeast may be missed.

## Credits

- Fuel prices: provided by Spotter for this assessment.
- US city coordinates: [Simplemaps US Cities Database (Basic)](https://simplemaps.com/data/us-cities), licensed under CC BY 4.0.
