"""Basic checks that the calculator does what it should. Run: pytest"""

import pandas as pd
import pytest

from pcf import load_data, calculate_pcf, check_mass_balance, primary_data_share


def test_mass_balance_of_example_is_ok():
    bom, _, process = load_data()
    assert check_mass_balance(bom, process)["ok"]


def test_supplier_pcf_is_preferred_over_generic_factor():
    bom, factors, process = load_data()
    results = calculate_pcf(bom, factors, process)
    ggbs = results[(results["stage"] == "A1 raw materials") & (results["source"] == "ggbs")].iloc[0]
    assert ggbs["data_type"] == "primary"
    assert ggbs["kgco2e"] == pytest.approx(0.30 * 0.06)


def test_green_electricity_lowers_the_pcf():
    bom, factors, process = load_data()
    base = calculate_pcf(bom, factors, process)["kgco2e"].sum()
    green = calculate_pcf(bom, factors, process, electricity_factor=0.03)["kgco2e"].sum()
    assert green < base


def test_missing_emission_factor_gives_clear_error():
    bom, factors, process = load_data()
    bom = pd.concat([bom, pd.DataFrame([{"component": "unknown_material", "mass_kg": 0.01,
                                          "supplier": "X", "supplier_pcf_kgco2e_per_kg": None,
                                          "transport_mode": "truck", "transport_km": 10}])])
    with pytest.raises(ValueError, match="unknown_material"):
        calculate_pcf(bom, factors, process)


def test_primary_data_share_is_between_0_and_1():
    bom, factors, process = load_data()
    share = primary_data_share(calculate_pcf(bom, factors, process))
    assert 0 <= share <= 1
