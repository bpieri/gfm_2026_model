# engine/stress_test.py
from engine.crack import crack_321

SCENARIOS = [
    {"label": "Base Case",       "crude_pct":  0,    "product_pct":  0},
    {"label": "Crude −10%",      "crude_pct": -10,   "product_pct":  0},
    {"label": "Crude −25%",      "crude_pct": -25,   "product_pct":  0},
    {"label": "Crude +10%",      "crude_pct":  10,   "product_pct":  0},
    {"label": "Products −10%",   "crude_pct":  0,    "product_pct": -10},
    {"label": "Products −25%",   "crude_pct":  0,    "product_pct": -25},
    {"label": "Products +10%",   "crude_pct":  0,    "product_pct":  10},
    {"label": "Both −10%",       "crude_pct": -10,   "product_pct": -10},
    {"label": "Both −25%",       "crude_pct": -25,   "product_pct": -25},
]


def run_stress_test(location_margins: list) -> dict:
    """
    Run all stress scenarios against the base case for each location.

    Returns dict:
        {
          "scenarios": [list of scenario labels],
          "locations": [list of location display names],
          "grid":      {scenario_label: {location_display: spread_321}},
          "base":      {location_display: spread_321}
        }
    """
    base = {r["display"]: r["spread_321"] for r in location_margins
            if r.get("spread_321") is not None}

    grid = {}
    for scenario in SCENARIOS:
        label       = scenario["label"]
        crude_mult  = 1 + scenario["crude_pct"]  / 100
        prod_mult   = 1 + scenario["product_pct"] / 100
        grid[label] = {}

        for row in location_margins:
            display = row["display"]
            if row.get("spread_321") is None:
                grid[label][display] = None
                continue

            crude_adj = row["crude_light"]  * crude_mult
            gas_adj   = row["wholesale_gas"]  * prod_mult
            diesel_adj= row["wholesale_diesel"] * prod_mult

            grid[label][display] = round(
                crack_321(crude_adj, gas_adj, diesel_adj), 2
            )

    return {
        "scenarios": [s["label"] for s in SCENARIOS],
        "locations": [r["display"] for r in location_margins],
        "grid":      grid,
        "base":      base,
    }