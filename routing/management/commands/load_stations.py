import csv

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from routing.models import FuelStation
from routing.normalize import normalize_city

DATA_DIR = settings.BASE_DIR / "routing" / "data"
FUEL_CSV = DATA_DIR / "fuel-prices-for-be-assessment.csv"
CITIES_CSV = DATA_DIR / "uscities.csv"

CANADIAN_PROVINCES = {"AB", "BC", "MB", "NB", "NS", "ON", "QC", "SK", "YT"}


class Command(BaseCommand):
    help = "Load fuel stations from the OPIS CSV and attach city coordinates."

    def handle(self, *args, **options):
        coords = self._load_city_coordinates()
        cheapest, rows_read, canadian = self._load_cheapest_us_stations()

        stations, unmatched = [], []
        for opis_id, (row, price) in cheapest.items():
            city = row["City"].strip()
            state = row["State"].strip()
            location = coords.get((normalize_city(city), state))
            if location is None:
                unmatched.append((city, state))
                continue
            lat, lng = location
            stations.append(
                FuelStation(
                    opis_id=opis_id,
                    name=row["Truckstop Name"].strip(),
                    address=row["Address"].strip(),
                    city=city,
                    state=state,
                    price=price,
                    lat=lat,
                    lng=lng,
                )
            )

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=1000)

        self._report(rows_read, canadian, len(cheapest), len(stations), unmatched)

    def _load_city_coordinates(self):
        best = {}  # key -> (population, lat, lng)
        with open(CITIES_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (normalize_city(row["city_ascii"]), row["state_id"].strip())
                population = float(row["population"] or 0)
                if key not in best or population > best[key][0]:
                    best[key] = (population, float(row["lat"]), float(row["lng"]))
        return {key: (lat, lng) for key, (_, lat, lng) in best.items()}

    def _load_cheapest_us_stations(self):
        cheapest = {}  # opis_id -> (row, price)
        rows_read = canadian = 0
        with open(FUEL_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows_read += 1
                if row["State"].strip() in CANADIAN_PROVINCES:
                    canadian += 1
                    continue
                opis_id = int(row["OPIS Truckstop ID"])
                price = float(row["Retail Price"])
                if opis_id not in cheapest or price < cheapest[opis_id][1]:
                    cheapest[opis_id] = (row, price)
        return cheapest, rows_read, canadian

    def _report(self, rows_read, canadian, unique, matched, unmatched):
        out = self.stdout
        out.write(f"Rows read:              {rows_read}")
        out.write(f"Canadian rows skipped:  {canadian}")
        out.write(f"Unique US stations:     {unique}")
        out.write(f"Unmatched (skipped):    {len(unmatched)}")
        sample = sorted(set(unmatched))[:10]
        if sample:
            out.write("Sample unmatched:       " + "; ".join(f"{c}, {s}" for c, s in sample))
        pct = 100 * matched / unique if unique else 0
        out.write(self.style.SUCCESS(f"Loaded {matched} stations ({pct:.1f}% of US stations)."))
