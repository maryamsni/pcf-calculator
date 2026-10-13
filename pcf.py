"""
Simple cradle-to-gate Product Carbon Footprint (PCF) calculator.

Reads a bill of materials (BOM), emission factors and process data from CSV files,
checks the mass balance, and calculates the PCF per declared unit, split into:
  A1 raw materials, A2 transport to the plant, A3 manufacturing energy.

Supplier-specific PCFs (primary data) are used where available; otherwise a
secondary (generic) emission factor is used - the approach recommended by the
TfS PCF Guideline and PACT. The script also reports the Primary Data Share.

Run:  python pcf.py
"""

import json
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

DATA = Path(__file__).parent
OUTPUT = Path(__file__).parent


# ---------- 1. Load data ----------

def load_data(data_dir=DATA):
    bom = pd.read_csv(data_dir / "bom_geopolymer_binder.csv")
    factors = pd.read_csv(data_dir / "emission_factors.csv")
    process = pd.read_csv(data_dir / "process.csv").set_index("parameter")["value"]
    return bom, factors, process


def get_factor(factors, name):
    """Look up one emission factor by name. Stops with a clear message if it is missing."""
    row = factors[factors["name"] == name]
    if row.empty:
        raise ValueError(f"No emission factor found for '{name}'. Add it to emission_factors.csv.")
    return float(row["factor"].iloc[0])


# ---------- 2. Data quality check: mass balance ----------

def check_mass_balance(bom, process):
    """Inputs should equal product output + expected process losses (within a tolerance)."""
    total_input = bom["mass_kg"].sum()
    expected = float(process["declared_unit_kg"]) + float(process["expected_process_loss_kg"])
    deviation = abs(total_input - expected) / expected
    ok = deviation <= float(process["mass_balance_tolerance"])
    return {"total_input_kg": round(float(total_input), 4),
            "expected_input_kg": round(expected, 4),
            "deviation": round(float(deviation), 4),
            "ok": bool(ok)}


# ---------- 3. Calculate the PCF ----------

def calculate_pcf(bom, factors, process, electricity_factor=None):
    """Return a table with one row per emission source, in kg CO2e per declared unit.

    electricity_factor lets you run scenarios (e.g. green electricity) without editing the data.
    """
    rows = []

    # A1 - raw materials: supplier PCF (primary) if given, else generic factor (secondary)
    for _, item in bom.iterrows():
        if pd.notna(item["supplier_pcf_kgco2e_per_kg"]):
            factor, data_type = float(item["supplier_pcf_kgco2e_per_kg"]), "primary"
        else:
            factor, data_type = get_factor(factors, item["component"]), "secondary"
        rows.append({"stage": "A1 raw materials", "source": item["component"],
                     "kgco2e": item["mass_kg"] * factor, "data_type": data_type})

    # A2 - transport: mass (t) x distance (km) x factor (kg CO2e per tkm)
    for _, item in bom.iterrows():
        tkm = item["mass_kg"] / 1000 * item["transport_km"]
        rows.append({"stage": "A2 transport", "source": f"{item['component']} ({item['transport_mode']})",
                     "kgco2e": tkm * get_factor(factors, item["transport_mode"]), "data_type": "secondary"})

    # A3 - manufacturing energy (measured on our own site, so counted as primary data)
    elec_factor = electricity_factor if electricity_factor is not None else get_factor(factors, "electricity")
    rows.append({"stage": "A3 manufacturing", "source": "electricity",
                 "kgco2e": float(process["electricity_kwh"]) * elec_factor, "data_type": "primary"})
    rows.append({"stage": "A3 manufacturing", "source": "natural gas",
                 "kgco2e": float(process["natural_gas_kwh"]) * get_factor(factors, "natural_gas"),
                 "data_type": "primary"})

    results = pd.DataFrame(rows)
    # Express results per declared unit (here 1 kg of product)
    results["kgco2e"] = results["kgco2e"] / float(process["declared_unit_kg"])
    return results


def primary_data_share(results):
    """Share of the total PCF that is based on primary data (PACT / TfS indicator)."""
    total = results["kgco2e"].sum()
    primary = results.loc[results["data_type"] == "primary", "kgco2e"].sum()
    return primary / total if total else 0.0


# ---------- 4. Outputs ----------

def save_outputs(results, process, mass_balance, out_dir=OUTPUT):
    out_dir.mkdir(exist_ok=True)
    results.round(5).to_csv(out_dir / "pcf_results.csv", index=False)

    # Bar chart: contribution per stage
    by_stage = results.groupby("stage")["kgco2e"].sum()
    ax = by_stage.plot(kind="barh", color="#2E7D5B", figsize=(7, 3))
    ax.set_xlabel("kg CO2e per declared unit")
    ax.set_ylabel("")
    ax.set_title(f"PCF contribution by stage - {process['product_name']}")
    plt.tight_layout()
    plt.savefig(out_dir / "pcf_by_stage.png", dpi=150)
    plt.close()

    # Simplified, PACT-inspired data record (the kind of data a Digital Product Passport needs)
    record = {
        "productName": process["product_name"],
        "declaredUnit": f"{process['declared_unit_kg']} kg",
        "boundary": "cradle-to-gate (A1-A3)",
        "pcfExcludingBiogenic_kgCO2e": round(results["kgco2e"].sum(), 4),
        "primaryDataShare": round(primary_data_share(results), 3),
        "massBalanceCheck": mass_balance,
        "methodology": ["ISO 14067", "GHG Protocol Product Standard", "TfS PCF Guideline (simplified)"],
        "note": "Example only - emission factors are illustrative, not from a licensed database.",
    }
    (out_dir / "pcf_record.json").write_text(json.dumps(record, indent=2))
    return record


# ---------- 5. Run ----------

def main():
    bom, factors, process = load_data()

    mass_balance = check_mass_balance(bom, process)
    print("Mass balance:", "OK" if mass_balance["ok"] else "CHECK DATA", mass_balance)

    results = calculate_pcf(bom, factors, process)
    total = results["kgco2e"].sum()

    print(f"\nPCF of {process['product_name']}: {total:.3f} kg CO2e per kg (cradle-to-gate)")
    print(results.groupby("stage")["kgco2e"].sum().round(4).to_string())
    print(f"Primary data share: {primary_data_share(results):.0%}")

    # Scenario: same product with renewable electricity (illustrative factor)
    green = calculate_pcf(bom, factors, process, electricity_factor=0.03)["kgco2e"].sum()
    print(f"Scenario with renewable electricity: {green:.3f} kg CO2e per kg "
          f"({(green - total) / total:+.1%})")

    save_outputs(results, process, mass_balance)
    print(f"\nSaved results to {OUTPUT}/")


if __name__ == "__main__":
    main()
