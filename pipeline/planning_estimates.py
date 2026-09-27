"""Replace legacy finance stand-ins with explicit reproducible budget scenarios."""

from __future__ import annotations

import json

from core.artifact_files import replace_text
from core.config import ROOT, load_config
from core.finance_model import build_finance_defaults


def annual_payment_rate(rate: float, years: float) -> float:
    return rate / (1 - (1 + rate) ** -years) if rate else 1 / years


def build() -> dict:
    cfg = load_config()
    defaults = build_finance_defaults(cfg, "small_multi")
    def debt_case(rate_key, term_key, return_key):
        return .7 * annual_payment_rate(defaults["rental_debt_rate"][rate_key], defaults["rental_debt_term_years"][term_key]) + .3 * defaults["rental_equity_return_rate"][return_key]
    capital = {"value": debt_case("value", "value", "value"),
               "low": debt_case("low", "high", "low"), "high": debt_case("high", "low", "high")}
    operating = {}
    opex_keys = [f"{key}_per_unit_month" for key in ("insurance", "utilities", "maintenance", "management", "reserves")]
    for typology in cfg.typologies:
        current = build_finance_defaults(cfg, typology.id)
        hard = current["hard_cost_psf"]
        # A transparent reference cost scenario, used only if the full parcel
        # finance model is unavailable. It does not stand in for a tax assessment.
        operating[typology.id] = {
            key: sum(current[opex][key] for opex in opex_keys) +
            typology.unit_size_sf * hard[key] * (1 + current["soft_cost_share"][key] + current["site_cost_share"][key] + current["contingency_share"][key]) * current["property_tax_mills"][key] / 1000 / 12
            for key in ("value", "low", "high")
        }
    risk = {
        "steep_slope_cost_share": {"value": .05 * 2, "low": 0, "high": .05 * 4, "reserve_blocks": 2},
        "landslide_cost_share": {"value": .05 * 3, "low": 0, "high": .05 * 6, "reserve_blocks": 3},
        "undermined_cost_share": {"value": .05, "low": 0, "high": .05 * 2, "reserve_blocks": 1},
    }
    result = {
        "model_id": "lotline:declared-planning-budget:v1", "as_of": "2026-09-27",
        "annual_capital_cost_share": capital,
        "operating_cost_per_unit_month": {**operating["small_multi"], "by_typology": operating},
        "risk_reserves": risk,
        "inputs": {key: value for key, value in defaults.items() if key in opex_keys or key.startswith("rental_") or key == "property_tax_mills"},
        "source_ids": ["lotline_finance_scenario_defaults", "lotline_risk_reserves", "phfa_operating_budget_2025", "pwsa_rates_2026", "pittsburgh_tax_rates_2026"],
        "limitations": [
            "Capital recovery is 70% amortizing debt plus 30% equity return using the declared finance scenario, not an observed loan quote.",
            "Operating fallback adds line-item budget allowances and 2026 millage applied to prototype development cost; excludes land, abatements and parcel-specific assessed value. The full finance model takes precedence.",
            "Additional hazard reserve blocks are deliberately selected budget stress scenarios. A map flag is not evidence that intervention is required; zero is included in each range. No claim is made that the reserve can fund safe remediation.",
            "PHFA's cited 5% contingency is a reference scale, not authority for the selected extra risk multipliers.",
        ],
    }
    path = ROOT / "data" / "models" / "planning_estimates.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_text(path, json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({key: result[key] for key in ("annual_capital_cost_share", "operating_cost_per_unit_month", "risk_reserves")}, indent=2))
