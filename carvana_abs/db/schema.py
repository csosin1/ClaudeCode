"""SQLite database schema and initialization for Carvana 2020-P1 ABS data."""

import sqlite3
import os
from carvana_abs.config import DB_PATH, DB_DIR


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Get a SQLite connection with row factory enabled."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Create all tables if they don't exist."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.executescript("""
        -- Tracks each SEC filing discovered
        CREATE TABLE IF NOT EXISTS filings (
            accession_number TEXT PRIMARY KEY,
            filing_type TEXT NOT NULL,           -- '10-D' or 'ABS-EE'
            filing_date TEXT,
            reporting_period_start TEXT,
            reporting_period_end TEXT,
            distribution_date TEXT,
            filing_url TEXT,
            absee_url TEXT,                      -- URL to EX-102 XML data file
            servicer_cert_url TEXT,              -- URL to Exhibit 99.1
            ingested_loans INTEGER DEFAULT 0,
            ingested_pool INTEGER DEFAULT 0
        );

        -- Pool-level performance data from Servicer Certificate (Exhibit 99.1)
        CREATE TABLE IF NOT EXISTS pool_performance (
            distribution_date TEXT PRIMARY KEY,
            accession_number TEXT REFERENCES filings(accession_number),
            beginning_pool_balance REAL,
            ending_pool_balance REAL,
            beginning_pool_count INTEGER,
            ending_pool_count INTEGER,
            principal_collections REAL,
            interest_collections REAL,
            recoveries REAL,
            charged_off_amount REAL,
            cumulative_net_losses REAL,
            delinquent_31_60_balance REAL,
            delinquent_61_90_balance REAL,
            delinquent_91_120_balance REAL,
            delinquent_121_plus_balance REAL,
            total_delinquent_balance REAL,
            delinquent_31_60_count INTEGER,
            delinquent_61_90_count INTEGER,
            delinquent_91_120_count INTEGER,
            delinquent_121_plus_count INTEGER,
            note_balance_a1 REAL,
            note_balance_a2 REAL,
            note_balance_a3 REAL,
            note_balance_a4 REAL,
            note_balance_b REAL,
            note_balance_c REAL,
            note_balance_d REAL,
            overcollateralization_amount REAL,
            reserve_account_balance REAL
        );

        -- Static loan origination data (from EX-102 XML, one row per loan)
        CREATE TABLE IF NOT EXISTS loans (
            asset_number TEXT PRIMARY KEY,
            originator_name TEXT,
            origination_date TEXT,
            original_loan_amount REAL,
            original_loan_term INTEGER,
            original_interest_rate REAL,
            loan_maturity_date TEXT,
            original_ltv REAL,
            vehicle_manufacturer TEXT,
            vehicle_model TEXT,
            vehicle_new_used TEXT,
            vehicle_model_year INTEGER,
            vehicle_type TEXT,
            vehicle_value REAL,
            obligor_credit_score INTEGER,
            obligor_credit_score_type TEXT,
            obligor_geographic_location TEXT,
            co_obligor_indicator TEXT,
            payment_to_income_ratio REAL,
            income_verification_level TEXT,
            payment_type TEXT,
            subvention_indicator TEXT
        );

        -- Monthly loan performance snapshots (from EX-102 XML)
        CREATE TABLE IF NOT EXISTS loan_performance (
            asset_number TEXT NOT NULL REFERENCES loans(asset_number),
            reporting_period_end TEXT NOT NULL,
            beginning_balance REAL,
            ending_balance REAL,
            scheduled_payment REAL,
            actual_amount_paid REAL,
            actual_interest_collected REAL,
            actual_principal_collected REAL,
            current_interest_rate REAL,
            current_delinquency_status TEXT,
            days_delinquent INTEGER,
            remaining_term INTEGER,
            paid_through_date TEXT,
            zero_balance_code TEXT,
            zero_balance_date TEXT,
            charged_off_amount REAL,
            recoveries REAL,
            modification_indicator TEXT,
            servicing_fee REAL,
            PRIMARY KEY (asset_number, reporting_period_end)
        );

        -- Indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_loan_perf_period
            ON loan_performance(reporting_period_end);
        CREATE INDEX IF NOT EXISTS idx_loan_perf_delinquency
            ON loan_performance(reporting_period_end, current_delinquency_status);
        CREATE INDEX IF NOT EXISTS idx_loans_state
            ON loans(obligor_geographic_location);
        CREATE INDEX IF NOT EXISTS idx_loans_score
            ON loans(obligor_credit_score);
        CREATE INDEX IF NOT EXISTS idx_filings_date
            ON filings(filing_date);
        CREATE INDEX IF NOT EXISTS idx_filings_type
            ON filings(filing_type);
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
