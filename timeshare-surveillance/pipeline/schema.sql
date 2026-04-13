-- Timeshare surveillance persistence schema.
--
-- One row per filing, keyed by (ticker, accession). Every METRIC_SCHEMA field
-- lives as its own column so merge.py can SELECT * and hand the rows straight
-- back to the dashboard. `vintage_pools` is the only compound field and is
-- stored as a JSON TEXT blob.

CREATE TABLE IF NOT EXISTS filings (
    ticker                                TEXT NOT NULL,
    accession                             TEXT NOT NULL,
    filing_type                           TEXT,
    period_end                            TEXT,
    filed_date                            TEXT,
    source_url                            TEXT,
    extracted_at                          TEXT,
    dry_run                               INTEGER DEFAULT 0,
    extraction_error                      INTEGER DEFAULT 0,

    -- Balance-sheet / P&L (XBRL-sourced)
    gross_receivables_total_mm            REAL,
    allowance_for_loan_losses_mm          REAL,
    net_receivables_mm                    REAL,
    allowance_coverage_pct                REAL,
    provision_for_loan_losses_mm          REAL,

    -- Credit-quality (narrative-sourced)
    delinquent_30_59_days_pct             REAL,
    delinquent_60_89_days_pct             REAL,
    delinquent_90_plus_days_pct           REAL,
    delinquent_total_pct                  REAL,
    default_rate_annualized_pct           REAL,
    weighted_avg_fico_origination         INTEGER,
    fico_700_plus_pct                     REAL,
    fico_below_600_pct                    REAL,
    avg_loan_size_dollars                 REAL,
    avg_contract_term_months              REAL,

    -- Securitization
    securitized_receivables_mm            REAL,
    retained_interests_mm                 REAL,
    warehouse_facility_balance_mm         REAL,
    new_securitization_volume_mm          REAL,
    new_securitization_advance_rate_pct   REAL,
    weighted_avg_coupon_new_deals_pct     REAL,
    overcollateralization_pct             REAL,

    -- Revenue / operations
    gain_on_sale_mm                       REAL,
    gain_on_sale_margin_pct               REAL,
    originations_mm                       REAL,
    sales_to_existing_owners_pct          REAL,
    tour_flow_count                       INTEGER,
    vpg_dollars                           REAL,
    contract_rescission_rate_pct          REAL,
    weighted_avg_ltv_pct                  REAL,

    -- Compound / narrative
    vintage_pools                         TEXT,    -- JSON
    management_flagged_credit_concerns    INTEGER,
    management_credit_commentary          TEXT,

    PRIMARY KEY (ticker, accession)
);

CREATE INDEX IF NOT EXISTS idx_filings_ticker_period
    ON filings (ticker, period_end);
