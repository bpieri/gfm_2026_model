# engine/crack.py
GALLONS_PER_BARREL = 42


def crack_321(crude_bbl, gas_gal, ulsd_gal):
    """3 bbl crude → 2 bbl gasoline + 1 bbl ULSD. Returns $/bbl."""
    return (2 * gas_gal * 42 + 1 * ulsd_gal * 42 - 3 * crude_bbl) / 3


def crack_211(crude_bbl, gas_gal, ulsd_gal):
    """2 bbl crude → 1 bbl gasoline + 1 bbl ULSD. Returns $/bbl."""
    return (1 * gas_gal * 42 + 1 * ulsd_gal * 42 - 2 * crude_bbl) / 2


def crack_532(crude_bbl, gas_gal, ulsd_gal):
    """5 bbl crude → 3 bbl gasoline + 2 bbl ULSD. Returns $/bbl."""
    return (3 * gas_gal * 42 + 2 * ulsd_gal * 42 - 5 * crude_bbl) / 5


def crack_full(
    crude_bbl:   float,
    gas_gal:     float,
    ulsd_gal:    float,
    jet_gal:     float,
    bunker_gal:  float,
    asphalt_gal: float,
    lpg_gal:     float,
    yields:      dict,
) -> float:
    """
    Full refinery yield model. Returns gross margin $/bbl of crude.

    yields dict keys and typical US values:
        gasoline  0.465  (46.5% of barrel)
        ulsd      0.286  (28.6%)
        jet       0.095  ( 9.5%)
        bunker    0.048  ( 4.8%)
        asphalt   0.036  ( 3.6%)
        refinery_use 0.060 (6.0% — consumed, not sold)

    Fractions should sum to ≤ 1.0.
    Revenue is computed only on saleable products (refinery_use excluded).
    """
    revenue = (
        gas_gal     * yields.get("gasoline",     0.445) * 42 +
        ulsd_gal    * yields.get("ulsd",         0.29) * 42 +
        jet_gal     * yields.get("jet",          0.11) * 42 +
        bunker_gal  * yields.get("bunker",       0.035) * 42 +
        asphalt_gal * yields.get("asphalt",      0.025) * 42 +
        lpg_gal     * yields.get("lpg_other",    0.040) * 42
    )
    return revenue - crude_bbl


# # engine/crack.py
# GALLONS_PER_BARREL = 42


# def crack_321(crude_bbl, gas_gal, ulsd_gal):
#     return (2 * gas_gal * 42 + 1 * ulsd_gal * 42 - 3 * crude_bbl) / 3


# def crack_211(crude_bbl, gas_gal, ulsd_gal):
#     return (1 * gas_gal * 42 + 1 * ulsd_gal * 42 - 2 * crude_bbl) / 2


# def crack_532(crude_bbl, gas_gal, ulsd_gal):
#     return (3 * gas_gal * 42 + 2 * ulsd_gal * 42 - 5 * crude_bbl) / 5


# def crack_full(crude_bbl, gas_gal, ulsd_gal,
#                jet_gal, bunker_gal, asphalt_gal,
#                yields: dict) -> float:
#     """
#     Full refinery yield model.
#     yields: dict of {product: gallons_per_barrel_of_crude}
#     """
#     revenue = (
#         gas_gal     * yields.get("gasoline", 19.5) +
#         ulsd_gal    * yields.get("ulsd",     12.0) +
#         jet_gal     * yields.get("jet",       4.0) +
#         bunker_gal  * yields.get("bunker",    2.0) +
#         asphalt_gal * yields.get("asphalt",   1.5)
#     )
#     return revenue - crude_bbl