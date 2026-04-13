"""Canonical METRIC_SCHEMA for the surveillance pipeline.

Lifted out of fetch_and_parse.py so db.py, merge.py, and the narrative
extractor can reference a single source of truth for field names.

The key list here MUST match the columns in schema.sql (plus the three
bookkeeping fields ticker/filing_type/period_end/accession/filed_date/
source_url/extracted_at added by the orchestrator). Dashboard code reads
these keys verbatim; do not rename.
"""

from __future__ import annotations

METRIC_SCHEMA: dict[str, str] = {
    "gross_receivables_total_mm": "float, millions USD",
    "allowance_for_loan_losses_mm": "float, millions USD",
    "net_receivables_mm": "float, millions USD",
    "allowance_coverage_pct": "float 0-1, allowance as share of gross receivables",
    "provision_for_loan_losses_mm": "float, millions USD (period provision)",
    "delinquent_30_59_days_pct": "float 0-1",
    "delinquent_60_89_days_pct": "float 0-1",
    "delinquent_90_plus_days_pct": "float 0-1",
    "delinquent_total_pct": "float 0-1",
    "default_rate_annualized_pct": "float 0-1, annualized",
    "weighted_avg_fico_origination": "int FICO score, origination-weighted",
    "fico_700_plus_pct": "float 0-1",
    "fico_below_600_pct": "float 0-1",
    "avg_loan_size_dollars": "float, dollars",
    "avg_contract_term_months": "float, months",
    "securitized_receivables_mm": "float, millions USD",
    "retained_interests_mm": "float, millions USD",
    "warehouse_facility_balance_mm": "float, millions USD (outstanding)",
    "new_securitization_volume_mm": "float, millions USD (this period)",
    "new_securitization_advance_rate_pct": "float 0-1",
    "weighted_avg_coupon_new_deals_pct": "float 0-1",
    "overcollateralization_pct": "float 0-1",
    "gain_on_sale_mm": "float, millions USD",
    "gain_on_sale_margin_pct": "float 0-1, gain / originations",
    "originations_mm": "float, millions USD",
    "sales_to_existing_owners_pct": "float 0-1",
    "tour_flow_count": "int, number of tours this period",
    "vpg_dollars": "float, volume per guest (dollars)",
    "contract_rescission_rate_pct": "float 0-1",
    "weighted_avg_ltv_pct": "float 0-1",
    "vintage_pools": (
        "array of {vintage_year:int, original_balance_mm:float, "
        "cumulative_default_rate_pct:float 0-1, as_of_period:str}"
    ),
    "management_flagged_credit_concerns": "bool, true if management notes credit stress",
    "management_credit_commentary": "string, <=2 sentences summarizing management credit commentary",
}


def null_record() -> dict:
    """Fresh record with every metric key set to None (vintage_pools -> [])."""
    rec = {k: None for k in METRIC_SCHEMA}
    rec["vintage_pools"] = []
    return rec
