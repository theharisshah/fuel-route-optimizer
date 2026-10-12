"""Pick the cheapest fuel stops along a route."""
from dataclasses import dataclass

from .geo import StationOnRoute

# Miles the vehicle can drive on a full tank.
VEHICLE_RANGE_MILES = 500.0

MILES_PER_GALLON = 10.0

# The tank starts empty; first fill is at the cheapest station within this distance of the start.
START_SEARCH_MILES = 50.0

# Smallest purchase worth a separate stop.
MIN_STOP_GALLONS = 5.0


class FuelPlanError(Exception):
    """Raised when the destination can't be reached with the known stations."""


@dataclass
class FuelStop:
    station: StationOnRoute
    gallons: float
    cost: float


@dataclass
class FuelPlan:
    stops: list[FuelStop]
    total_gallons: float
    total_cost: float


@dataclass
class _Purchase:
    station: StationOnRoute
    miles: float
    tank_after: float


def plan_fuel_stops(stations: list[StationOnRoute], total_miles: float) -> FuelPlan:
    """Return the cheapest fuel stops for a route; stations must be sorted by mile."""
    stations = [s for s in stations if s.mile <= total_miles]
    near_start = [k for k, s in enumerate(stations) if s.mile <= START_SEARCH_MILES]
    if not near_start:
        raise FuelPlanError(
            f"No fuel station found within {START_SEARCH_MILES:.0f} miles of the start."
        )

    purchases: list[_Purchase] = []
    i = min(near_start, key=lambda k: stations[k].price)
    # Fuel is tracked in miles of driving, not gallons.
    fuel = 0.0

    while True:
        current = stations[i]
        reach = current.mile + VEHICLE_RANGE_MILES

        # Cheaper fuel ahead: buy just enough to get there.
        cheaper = _first_cheaper_in_reach(stations, i, reach)
        if cheaper is not None:
            target = stations[cheaper]
            fuel = _buy(purchases, current, fuel, needed=target.mile - current.mile)
            fuel -= target.mile - current.mile
            i = cheaper
            continue

        # Cheapest fuel in reach and the destination is in range: buy just enough to finish.
        if total_miles - current.mile <= VEHICLE_RANGE_MILES:
            _buy(purchases, current, fuel, needed=total_miles - current.mile)
            break

        # Cheapest fuel in reach but the destination isn't: fill up, go to the best next station.
        cheapest = _cheapest_in_reach(
            stations, i, reach, min_distance=MIN_STOP_GALLONS * MILES_PER_GALLON
        )
        if cheapest is None:
            raise FuelPlanError(
                f"No fuel station within {VEHICLE_RANGE_MILES:.0f} miles after mile "
                f"{current.mile:.0f}; the destination can't be reached."
            )
        target = stations[cheapest]
        fuel = _buy(purchases, current, fuel, needed=VEHICLE_RANGE_MILES)
        fuel -= target.mile - current.mile
        i = cheapest

    stops = [
        FuelStop(
            station=p.station,
            gallons=p.miles / MILES_PER_GALLON,
            cost=p.miles / MILES_PER_GALLON * p.station.price,
        )
        for p in _fold_small_purchases(purchases)
    ]
    return FuelPlan(
        stops=stops,
        total_gallons=sum(s.gallons for s in stops),
        total_cost=sum(s.cost for s in stops),
    )


def _first_cheaper_in_reach(stations, i, reach):
    """Index of the first station within reach that is cheaper than station i, or None."""
    price = stations[i].price
    for k in range(i + 1, len(stations)):
        if stations[k].mile > reach:
            return None
        if stations[k].price < price:
            return k
    return None


def _cheapest_in_reach(stations, i, reach, min_distance):
    """Index of the cheapest station within reach, preferring ones at least min_distance away."""
    near, far = None, None
    for k in range(i + 1, len(stations)):
        if stations[k].mile > reach:
            break
        if stations[k].mile - stations[i].mile < min_distance:
            if near is None or stations[k].price <= stations[near].price:
                near = k
        elif far is None or stations[k].price <= stations[far].price:
            far = k
    return far if far is not None else near


def _buy(purchases, station, fuel, needed):
    """Top the tank up to `needed` miles of fuel, record it, and return the new fuel level."""
    to_buy = max(0.0, needed - fuel)
    if to_buy > 1e-9:
        purchases.append(_Purchase(station=station, miles=to_buy, tank_after=fuel + to_buy))
    return fuel + to_buy


def _fold_small_purchases(purchases):
    """Merge purchases under MIN_STOP_GALLONS into the previous stop when the tank has room."""
    min_miles = MIN_STOP_GALLONS * MILES_PER_GALLON
    folded: list[_Purchase] = []
    for p in purchases:
        previous = folded[-1] if folded else None
        if (
            previous is not None
            and p.miles < min_miles
            and previous.tank_after + p.miles <= VEHICLE_RANGE_MILES + 1e-9
        ):
            previous.miles += p.miles
            previous.tank_after += p.miles
        else:
            folded.append(p)
    return folded
