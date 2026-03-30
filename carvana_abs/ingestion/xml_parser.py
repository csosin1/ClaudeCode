"""Parse EX-102 ABS-EE XML files for auto loan asset-level data."""

import logging
from typing import Optional
from lxml import etree

from carvana_abs.config import AUTO_LOAN_NS
from carvana_abs.db.schema import get_connection

logger = logging.getLogger(__name__)

# Namespace map for XPath queries
NS = {"al": AUTO_LOAN_NS}


def _get_text(element, tag: str) -> Optional[str]:
    """Extract text content from a child element, or None if not found."""
    child = element.find(f"al:{tag}", NS)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _get_float(element, tag: str) -> Optional[float]:
    """Extract float value from a child element."""
    text = _get_text(element, tag)
    if text:
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _get_int(element, tag: str) -> Optional[int]:
    """Extract integer value from a child element."""
    text = _get_text(element, tag)
    if text:
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def parse_auto_loan_xml(xml_content: str) -> dict:
    """Parse an ABS-EE auto loan XML file.

    Returns a dict with:
        - 'loans': list of static loan origination dicts
        - 'performance': list of loan performance snapshot dicts
    """
    loans = []
    performance = []

    try:
        root = etree.fromstring(xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content)
    except etree.XMLSyntaxError as e:
        logger.error(f"Failed to parse XML: {e}")
        return {"loans": [], "performance": []}

    # The XSD defines root element <assetData> containing <assets> elements.
    # Each <assets> is one loan record with all its fields as direct children.
    # Schema: eis_ABS_AutoLoanAssetData.xsd
    asset_elements = root.findall(".//al:assets", NS)
    if not asset_elements:
        # Fallback: try <asset> (singular) or direct children
        asset_elements = root.findall(".//al:asset", NS)
    if not asset_elements:
        asset_elements = root.findall(".//{%s}assets" % AUTO_LOAN_NS)
    if not asset_elements:
        # Last resort: find any element containing assetNumber
        for elem in root.iter():
            if elem.find("al:assetNumber", NS) is not None:
                asset_elements.append(elem)

    logger.info(f"Found {len(asset_elements)} asset records in XML")

    for asset in asset_elements:
        asset_number = _get_text(asset, "assetNumber")
        if not asset_number:
            continue

        # Extract static origination data
        # Element names match eis_ABS_AutoLoanAssetData.xsd exactly
        loan = {
            "asset_number": asset_number,
            "originator_name": _get_text(asset, "originatorName"),
            "origination_date": _get_text(asset, "originationDate"),
            "original_loan_amount": _get_float(asset, "originalLoanAmount"),
            "original_loan_term": _get_int(asset, "originalLoanTerm"),
            "original_interest_rate": _get_float(asset, "originalInterestRatePercentage"),
            "loan_maturity_date": _get_text(asset, "loanMaturityDate"),
            "original_ltv": None,  # Not in XSD — derived from loan amount / vehicle value
            "vehicle_manufacturer": _get_text(asset, "vehicleManufacturerName"),
            "vehicle_model": _get_text(asset, "vehicleModelName"),
            "vehicle_new_used": _get_text(asset, "vehicleNewUsedCode"),
            "vehicle_model_year": _get_int(asset, "vehicleModelYear"),
            "vehicle_type": _get_text(asset, "vehicleTypeCode"),
            "vehicle_value": _get_float(asset, "vehicleValueAmount"),
            "obligor_credit_score": _get_int(asset, "obligorCreditScore"),
            "obligor_credit_score_type": _get_text(asset, "obligorCreditScoreType"),
            "obligor_geographic_location": _get_text(asset, "obligorGeographicLocation"),
            "co_obligor_indicator": _get_text(asset, "coObligorIndicator"),
            "payment_to_income_ratio": _get_float(asset, "paymentToIncomePercentage"),
            "income_verification_level": _get_text(asset, "obligorIncomeVerificationLevelCode"),
            "payment_type": _get_text(asset, "paymentTypeCode"),
            "subvention_indicator": _get_text(asset, "subvented"),
        }
        # Compute LTV if we have both values
        if loan["original_loan_amount"] and loan["vehicle_value"] and loan["vehicle_value"] > 0:
            loan["original_ltv"] = loan["original_loan_amount"] / loan["vehicle_value"]
        loans.append(loan)

        # Extract performance data for this reporting period
        # XSD uses reportingPeriodEndingDate (not EndDate)
        perf = {
            "asset_number": asset_number,
            "reporting_period_end": _get_text(asset, "reportingPeriodEndingDate"),
            "beginning_balance": _get_float(asset, "reportingPeriodBeginningLoanBalanceAmount"),
            "ending_balance": _get_float(asset, "reportingPeriodActualEndBalanceAmount"),
            "scheduled_payment": _get_float(asset, "reportingPeriodScheduledPaymentAmount"),
            "actual_amount_paid": _get_float(asset, "totalActualAmountPaid"),
            "actual_interest_collected": _get_float(asset, "actualInterestCollectedAmount"),
            "actual_principal_collected": _get_float(asset, "actualPrincipalCollectedAmount"),
            "current_interest_rate": _get_float(asset, "reportingPeriodInterestRatePercentage"),
            "current_delinquency_status": _get_text(asset, "currentDelinquencyStatus"),
            "days_delinquent": None,  # Not in XSD; delinquency status is an integer (months)
            "remaining_term": _get_int(asset, "remainingTermToMaturityNumber"),
            "paid_through_date": _get_text(asset, "interestPaidThroughDate"),
            "zero_balance_code": _get_text(asset, "zeroBalanceCode"),
            "zero_balance_date": _get_text(asset, "zeroBalanceEffectiveDate"),
            "charged_off_amount": _get_float(asset, "chargedoffPrincipalAmount"),
            "recoveries": _get_float(asset, "recoveredAmount"),
            "modification_indicator": _get_text(asset, "reportingPeriodModificationIndicator"),
            "servicing_fee": (
                _get_float(asset, "servicingFlatFeeAmount") or
                _get_float(asset, "servicingFeePercentage")
            ),
        }
        if perf["reporting_period_end"]:
            performance.append(perf)

    return {"loans": loans, "performance": performance}


def store_loan_data(xml_content: str, accession_number: str,
                    deal: str, db_path: Optional[str] = None) -> tuple[int, int]:
    """Parse XML and store loan data in the database.

    Returns (loans_stored, performance_records_stored).
    """
    from carvana_abs.config import DB_PATH

    parsed = parse_auto_loan_xml(xml_content)
    if not parsed["loans"]:
        logger.warning(f"No loan data found in XML for {accession_number}")
        return (0, 0)

    conn = get_connection(db_path or DB_PATH)
    cursor = conn.cursor()

    # Store static loan data (INSERT OR IGNORE — first filing wins)
    loan_count = 0
    for loan in parsed["loans"]:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO loans
                (deal, asset_number, originator_name, origination_date, original_loan_amount,
                 original_loan_term, original_interest_rate, loan_maturity_date, original_ltv,
                 vehicle_manufacturer, vehicle_model, vehicle_new_used, vehicle_model_year,
                 vehicle_type, vehicle_value, obligor_credit_score, obligor_credit_score_type,
                 obligor_geographic_location, co_obligor_indicator, payment_to_income_ratio,
                 income_verification_level, payment_type, subvention_indicator)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                deal, loan["asset_number"], loan["originator_name"], loan["origination_date"],
                loan["original_loan_amount"], loan["original_loan_term"],
                loan["original_interest_rate"], loan["loan_maturity_date"],
                loan["original_ltv"], loan["vehicle_manufacturer"], loan["vehicle_model"],
                loan["vehicle_new_used"], loan["vehicle_model_year"], loan["vehicle_type"],
                loan["vehicle_value"], loan["obligor_credit_score"],
                loan["obligor_credit_score_type"], loan["obligor_geographic_location"],
                loan["co_obligor_indicator"], loan["payment_to_income_ratio"],
                loan["income_verification_level"], loan["payment_type"],
                loan["subvention_indicator"],
            ))
            loan_count += cursor.rowcount
        except Exception as e:
            logger.error(f"Error storing loan {loan['asset_number']}: {e}")

    # Store performance snapshots (INSERT OR REPLACE for idempotency)
    perf_count = 0
    for perf in parsed["performance"]:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO loan_performance
                (deal, asset_number, reporting_period_end, beginning_balance, ending_balance,
                 scheduled_payment, actual_amount_paid, actual_interest_collected,
                 actual_principal_collected, current_interest_rate, current_delinquency_status,
                 days_delinquent, remaining_term, paid_through_date, zero_balance_code,
                 zero_balance_date, charged_off_amount, recoveries, modification_indicator,
                 servicing_fee)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                deal, perf["asset_number"], perf["reporting_period_end"],
                perf["beginning_balance"], perf["ending_balance"],
                perf["scheduled_payment"], perf["actual_amount_paid"],
                perf["actual_interest_collected"], perf["actual_principal_collected"],
                perf["current_interest_rate"], perf["current_delinquency_status"],
                perf["days_delinquent"], perf["remaining_term"],
                perf["paid_through_date"], perf["zero_balance_code"],
                perf["zero_balance_date"], perf["charged_off_amount"],
                perf["recoveries"], perf["modification_indicator"],
                perf["servicing_fee"],
            ))
            perf_count += cursor.rowcount
        except Exception as e:
            logger.error(f"Error storing performance for {perf['asset_number']}: {e}")

    # Mark filing as ingested
    cursor.execute("""
        UPDATE filings SET ingested_loans = 1 WHERE accession_number = ?
    """, (accession_number,))

    conn.commit()
    conn.close()

    logger.info(f"Stored {loan_count} loans, {perf_count} performance records for {deal}/{accession_number}")
    return (loan_count, perf_count)
