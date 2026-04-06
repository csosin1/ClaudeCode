"""Data Fields reference page."""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Data Fields", layout="wide")
st.header("Available Data Fields")

st.markdown("### Loan Static Data")
st.dataframe(pd.DataFrame({
    "Field": ["asset_number","originator_name","origination_date","original_loan_amount",
              "original_loan_term","original_interest_rate","loan_maturity_date","original_ltv",
              "vehicle_manufacturer","vehicle_model","vehicle_new_used","vehicle_model_year",
              "vehicle_type","vehicle_value","obligor_credit_score","obligor_credit_score_type",
              "obligor_geographic_location","co_obligor_indicator","payment_to_income_ratio",
              "income_verification_level","payment_type","subvention_indicator"],
    "Description": ["Unique loan ID","Originator","Month/year originated","Loan amount ($)",
                    "Term (months)","Rate (decimal, 0.0599=5.99%)","Maturity date","Loan-to-value",
                    "Vehicle make","Vehicle model","1=New, 2=Used","Model year",
                    "Type code","Value ($)","Credit score","Score model",
                    "State","Co-borrower","Payment/income (decimal)",
                    "Verification level","Payment type","Subsidized rate"],
}), use_container_width=True, hide_index=True)

st.markdown("### Monthly Performance Data")
st.dataframe(pd.DataFrame({
    "Field": ["reporting_period_end","beginning_balance","ending_balance","scheduled_payment",
              "actual_amount_paid","actual_interest_collected","actual_principal_collected",
              "current_interest_rate","current_delinquency_status","remaining_term",
              "paid_through_date","zero_balance_code","zero_balance_date",
              "charged_off_amount","recoveries","modification_indicator","servicing_fee"],
    "Description": ["Period end date","Start balance ($)","End balance ($)","Scheduled payment ($)",
                    "Actual paid ($)","Interest ($)","Principal ($)",
                    "Current rate (decimal)","Months delinquent (0=current,1=30d,2=60d,3=90d,4+=120d+)",
                    "Months remaining","Interest paid through",
                    "1=prepaid,2=matured,3=charged off","When zeroed",
                    "Chargeoff amount ($)","Recovery amount ($)","Modified (true/false)","Servicing fee rate"],
}), use_container_width=True, hide_index=True)
