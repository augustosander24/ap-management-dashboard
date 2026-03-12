"""
AP Management Dashboard Backend
Author: Augusto Sander

Project purpose:
Transform raw ERP-style accounts payable invoice data into a dashboard-ready file
for Excel reporting and management analysis.

Business goal:
Show payment health, overdue risk, vendor concentration, discount performance,
and AP operational efficiency using realistic invoice data.

Snapshot date for reporting:
June 30, 2025

Reporting currency:
All KPI summaries are reported in USD.
Invoices in EUR and MXN are converted using fixed snapshot-date FX rates.
Original currency and original amounts are preserved in the dataset.

FX rates used (as of June 30, 2025 snapshot):
    EUR to USD: 1.0721
    MXN to USD: 0.0572
    USD to USD: 1.0000
"""

from pathlib import Path
import pandas as pd


# File paths
RAW_FILE = "data/ap_invoices.csv"
OUTPUT_FILE = "output/ap_invoices_dashboard_ready.csv"
SNAPSHOT_DATE = pd.Timestamp("2025-06-30")

# FX conversion rates to USD — fixed as of snapshot date June 30, 2025
FX_RATES_TO_USD = {
    "USD": 1.0000,
    "EUR": 1.0721,
    "MXN": 0.0572,
}


def load_data(file_path):
    """
    Load the raw AP invoice dataset exported from the ERP-style source file.
    Validate required columns before any processing begins.

    Business meaning:
    In a real ERP environment, missing columns in an export would create
    downstream reporting errors. Early validation protects the whole workflow.
    """
    df = pd.read_csv(file_path)

    required_columns = [
        "invoice_num",
        "invoice_date",
        "posting_date",
        "due_date",
        "payment_date",
        "invoice_amount",
        "amount_paid",
        "currency",
        "status",
        "vendor_num",
        "po_number",
        "discount_terms",
        "discount_amount",
        "discount_due_date",
    ]

    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return df


def clean_date_columns(df):
    """
    Convert ERP date fields into pandas datetime format so AP timing
    calculations can be performed accurately.

    These dates drive:
    - due date analysis
    - payment timing
    - overdue flags
    - aging buckets
    """
    date_columns = [
        "invoice_date",
        "posting_date",
        "due_date",
        "payment_date",
        "discount_due_date",
    ]

    for col in date_columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def apply_fx_conversion(df):
    """
    Convert invoice and payment amounts to USD reporting currency.

    Business meaning:
    AP dashboards that mix USD, EUR, and MXN without conversion produce totals
    that are not finance-valid. Management needs one reporting currency for KPIs.

    Key outputs:
    - fx_rate_used
    - invoice_amount_usd
    - amount_paid_usd

    Logic:
    - FX rates are fixed as of the reporting snapshot date
    - Original currency and original amounts are never changed
    - Unrecognized currencies default to 1.0 and trigger a warning
    """
    df["fx_rate_used"] = df["currency"].map(FX_RATES_TO_USD)

    unrecognized = df.loc[df["fx_rate_used"].isna(), "currency"].dropna().unique()
    if len(unrecognized) > 0:
        print(f"WARNING: Unrecognized currencies found — defaulting to 1.0: {list(unrecognized)}")
        df["fx_rate_used"] = df["fx_rate_used"].fillna(1.0)

    df["invoice_amount_usd"] = (df["invoice_amount"] * df["fx_rate_used"]).round(2)
    df["amount_paid_usd"] = (df["amount_paid"] * df["fx_rate_used"]).round(2)

    return df


def calculate_days_to_pay(df):
    """
    Calculate days_to_pay for fully paid invoices only.

    Business meaning:
    This measures how long it took AP to pay an invoice after it was posted.
    It supports the dashboard KPI for average payment timing.

    Logic:
    - payment_date minus posting_date
    - only valid for invoices with final status Paid
    - exclude Partially Paid because the invoice is not fully settled
    """
    df["days_to_pay"] = (df["payment_date"] - df["posting_date"]).dt.days

    excluded_statuses = [
        "Open",
        "Overdue",
        "Blocked",
        "In Review",
        "Voided",
        "Partially Paid",
    ]
    df.loc[df["status"].isin(excluded_statuses), "days_to_pay"] = pd.NA
    df.loc[df["payment_date"].isna(), "days_to_pay"] = pd.NA

    return df


def calculate_overdue_metrics(df, snapshot_date):
    """
    Calculate outstanding balance and overdue status as of the reporting snapshot date.

    Business meaning:
    AP managers need to know what amount is still outstanding and whether that
    balance is past due as of the key reporting date.

    Key outputs:
    - outstanding_amount
    - outstanding_amount_usd
    - is_overdue
    - days_past_due

    Bug fix:
    outstanding_amount and outstanding_amount_usd are rounded to 2 decimal places
    to prevent floating point precision strings like 1336.9199999999998
    appearing in the CSV export.
    """
    df["outstanding_amount"] = (
        (df["invoice_amount"] - df["amount_paid"]).clip(lower=0).round(2)
    )
    df["outstanding_amount_usd"] = (
        (df["invoice_amount_usd"] - df["amount_paid_usd"]).clip(lower=0).round(2)
    )

    df["is_overdue"] = (
        (df["outstanding_amount"] > 0)
        & (df["due_date"] < snapshot_date)
        & (df["status"] != "Voided")
    )

    df["days_past_due"] = pd.NA
    df.loc[df["is_overdue"], "days_past_due"] = (
        snapshot_date - df.loc[df["is_overdue"], "due_date"]
    ).dt.days

    return df


def assign_aging_bucket(df):
    """
    Assign aging buckets for unpaid overdue balances.

    Business meaning:
    Aging buckets are one of the most common AP risk summaries.
    They show how old unpaid exposure is and help prioritize action.

    Bucket logic:
    - Current
    - 0-30 Days
    - 31-60 Days
    - 61-90 Days
    - 90+ Days
    """
    df["aging_bucket"] = "Current"

    df.loc[df["is_overdue"] & df["days_past_due"].between(0, 30), "aging_bucket"] = "0-30 Days"
    df.loc[df["is_overdue"] & df["days_past_due"].between(31, 60), "aging_bucket"] = "31-60 Days"
    df.loc[df["is_overdue"] & df["days_past_due"].between(61, 90), "aging_bucket"] = "61-90 Days"
    df.loc[df["is_overdue"] & (df["days_past_due"] > 90), "aging_bucket"] = "90+ Days"

    return df


def calculate_discount_metrics(df, snapshot_date):
    """
    Calculate discount eligibility, capture, and missed value.

    Business meaning:
    Early payment discounts are a real AP performance measure.
    Missed discounts represent savings the business did not capture.

    Key outputs:
    - is_discount_eligible
    - discount_captured_calc
    - discount_missed_calc
    - captured_discount_value
    - missed_discount_value

    Logic:
    - only 2/10 Net 30 invoices with valid discount data are eligible
    - captured = fully paid on or before discount_due_date
    - missed = paid after the discount window, or still unpaid after it expired
    """
    df["is_discount_eligible"] = (
        df["discount_terms"].fillna("").str.contains("2/10", case=False)
        & (df["discount_amount"] > 0)
        & df["discount_due_date"].notna()
    )

    df["discount_captured_calc"] = (
        df["is_discount_eligible"]
        & (df["status"] == "Paid")
        & df["payment_date"].notna()
        & (df["payment_date"] <= df["discount_due_date"])
    )

    df["discount_missed_calc"] = (
        df["is_discount_eligible"]
        & (
            (
                (df["status"] == "Paid")
                & df["payment_date"].notna()
                & (df["payment_date"] > df["discount_due_date"])
            )
            | (
                (df["outstanding_amount"] > 0)
                & (df["discount_due_date"] < snapshot_date)
            )
        )
    )

    df["captured_discount_value"] = 0.00
    df.loc[df["discount_captured_calc"], "captured_discount_value"] = (
        df["discount_amount"] * df["fx_rate_used"]
    ).round(2)

    df["missed_discount_value"] = 0.00
    df.loc[df["discount_missed_calc"], "missed_discount_value"] = (
        df["discount_amount"] * df["fx_rate_used"]
    ).round(2)

    return df


def calculate_po_match_metrics(df):
    """
    Flag PO-based invoices and calculate first-pass match performance.

    Business meaning:
    First-pass match rate shows what share of PO-backed invoices moved through
    AP without Blocked or In Review exceptions.
    """
    df["is_po_based"] = (
        df["po_number"].notna()
        & (df["po_number"].astype(str).str.strip() != "")
    )

    df["has_po_exception"] = (
        df["is_po_based"]
        & df["status"].isin(["Blocked", "In Review"])
    )

    df["first_pass_match"] = (
        df["is_po_based"]
        & ~df["status"].isin(["Blocked", "In Review"])
    )

    return df


def flag_anomalies(df, snapshot_date):
    """
    Detect AP process anomalies and exceptions requiring management attention.

    Anomalies flagged:
    - late payment
    - blocked over 30 days
    - in review over 15 days
    - missed discount
    - duplicate risk
    """
    df["late_payment_flag"] = (
        (df["status"] == "Paid")
        & df["payment_date"].notna()
        & df["due_date"].notna()
        & (df["payment_date"] > df["due_date"])
    )

    df["blocked_over_30_days"] = (
        (df["status"] == "Blocked")
        & df["posting_date"].notna()
        & ((snapshot_date - df["posting_date"]).dt.days > 30)
    )

    df["in_review_over_15_days"] = (
        (df["status"] == "In Review")
        & df["posting_date"].notna()
        & ((snapshot_date - df["posting_date"]).dt.days > 15)
    )

    df["missed_discount_flag"] = df["discount_missed_calc"]

    # Duplicate risk:
    # same vendor, same invoice amount, posted again within 30 days
    df_sorted = df.sort_values(["vendor_num", "posting_date"]).copy()
    df_sorted["prev_amount"] = df_sorted.groupby("vendor_num")["invoice_amount"].shift(1)
    df_sorted["prev_posting"] = df_sorted.groupby("vendor_num")["posting_date"].shift(1)
    df_sorted["days_since_prev"] = (
        df_sorted["posting_date"] - df_sorted["prev_posting"]
    ).dt.days

    df_sorted["duplicate_risk_flag"] = (
        (df_sorted["invoice_amount"] == df_sorted["prev_amount"])
        & (df_sorted["days_since_prev"] <= 30)
    )

    df = df.merge(
        df_sorted[["invoice_num", "duplicate_risk_flag"]],
        on="invoice_num",
        how="left",
    )
    df["duplicate_risk_flag"] = df["duplicate_risk_flag"].fillna(False)

    return df


def prepare_dashboard_fields(df, snapshot_date):
    """
    Create Excel-friendly helper fields for dashboard and exception reporting.

    Business meaning:
    These fields keep the logic in Python and make the Excel layer mostly visual.

    Issue type priority:
    - base status labels first
    - overdue next
    - more specific anomaly labels last
    - last assignment wins

    Bug fix:
    posting_month_label is cast to string explicitly after strftime to prevent
    pandas from treating it as a datetime object during CSV export, which caused
    it to serialize as a date serial (e.g. 2026-01-25) instead of Jan 2025.
    """
    df["posting_month_num"] = df["posting_date"].dt.month
    df["posting_month_name"] = df["posting_date"].dt.strftime("%b")

    # Cast to string explicitly — prevents pandas export treating this as a date
    df["posting_month_label"] = df["posting_date"].dt.strftime("%b %Y").astype(str)

    df["is_exception"] = (
        df["status"].isin(["Blocked", "In Review", "Partially Paid", "Voided"])
        | df["is_overdue"]
        | df["late_payment_flag"]
        | df["duplicate_risk_flag"]
        | df["missed_discount_flag"]
        | df["blocked_over_30_days"]
        | df["in_review_over_15_days"]
    )

    # Base labels from status
    df["issue_type"] = ""
    df.loc[df["status"] == "Blocked", "issue_type"] = "Blocked Invoice"
    df.loc[df["status"] == "In Review", "issue_type"] = "Invoice In Review"
    df.loc[df["status"] == "Partially Paid", "issue_type"] = "Partial Payment Outstanding"
    df.loc[df["status"] == "Voided", "issue_type"] = "Voided Invoice"

    # General overdue label for anything open past due
    df.loc[df["is_overdue"], "issue_type"] = "Overdue Invoice"

    # More specific anomaly labels overwrite the general label
    df.loc[df["late_payment_flag"], "issue_type"] = "Late Payment"
    df.loc[df["duplicate_risk_flag"], "issue_type"] = "Duplicate Risk"
    df.loc[df["missed_discount_flag"], "issue_type"] = "Missed Discount"
    df.loc[df["in_review_over_15_days"], "issue_type"] = "In Review Over 15 Days"
    df.loc[df["blocked_over_30_days"], "issue_type"] = "Blocked Over 30 Days"

    df["urgency_level"] = ""
    df.loc[df["issue_type"].isin([
        "Overdue Invoice",
        "Blocked Invoice",
        "Blocked Over 30 Days",
    ]), "urgency_level"] = "Red"

    df.loc[df["issue_type"].isin([
        "Missed Discount",
        "Partial Payment Outstanding",
        "Invoice In Review",
        "In Review Over 15 Days",
    ]), "urgency_level"] = "Amber"

    df.loc[df["issue_type"].isin([
        "Late Payment",
        "Duplicate Risk",
        "Voided Invoice",
    ]), "urgency_level"] = "Yellow"

    df["urgency_sort"] = df["urgency_level"].map({
        "Red": 1,
        "Amber": 2,
        "Yellow": 3,
    }).fillna(9)

    df["days_open_as_of_snapshot"] = pd.NA
    open_balance_mask = (df["outstanding_amount"] > 0) & (df["status"] != "Voided")
    df.loc[open_balance_mask, "days_open_as_of_snapshot"] = (
        snapshot_date - df.loc[open_balance_mask, "posting_date"]
    ).dt.days

    return df


def export_dashboard_file(df, file_path):
    """
    Export the final dashboard-ready dataset to CSV for Excel.

    Business meaning:
    Python owns the AP logic.
    Excel owns the final dashboard presentation.

    Note on date_format:
    date_format applies only to true datetime columns.
    posting_month_label is already cast to string in prepare_dashboard_fields
    so it exports as Jan 2025 not as a date serial.
    """
    output_path = Path(file_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = df.sort_values(by=["posting_date", "invoice_num"]).reset_index(drop=True)
    df.to_csv(output_path, index=False, date_format="%Y-%m-%d")


def print_summary(df):
    """
    Print a business-readable AP summary to the terminal when the script runs.
    All KPI totals are reported in USD.
    """
    total_invoices = len(df)
    total_spend_usd = df["invoice_amount_usd"].sum()
    overdue_count = int(df["is_overdue"].sum())
    overdue_usd = df.loc[df["is_overdue"], "outstanding_amount_usd"].sum()
    avg_days = df["days_to_pay"].mean()

    disc_eligible_total = int(df["is_discount_eligible"].sum())
    disc_captured = int(df["discount_captured_calc"].sum())
    disc_missed = int(df["discount_missed_calc"].sum())
    disc_matured = disc_captured + disc_missed
    missed_disc_usd = df["missed_discount_value"].sum()

    po_based = int(df["is_po_based"].sum())
    first_pass = int(df["first_pass_match"].sum())
    exceptions = int(df["is_exception"].sum())
    currency_mix = dict(df["currency"].value_counts())

    print("=" * 58)
    print("  AP OPERATIONS SUMMARY — Snapshot: June 30, 2025")
    print("  All totals reported in USD (reporting currency)")
    print("=" * 58)
    print(f"  Total invoices processed    : {total_invoices}")
    print(f"  Total invoice spend (USD)   : ${total_spend_usd:,.2f}")
    print(f"  Currency mix                : {currency_mix}")
    print("-" * 58)
    print(f"  Overdue invoices            : {overdue_count}")
    print(f"  Overdue exposure (USD)      : ${overdue_usd:,.2f}")
    if pd.notna(avg_days):
        print(f"  Avg days to pay             : {avg_days:.1f} days")
    else:
        print("  Avg days to pay             : N/A")
    print("-" * 58)
    print(f"  Discount eligible invoices  : {disc_eligible_total}")
    print(f"  Discount matured outcomes   : {disc_matured}")
    print(f"  Discounts captured          : {disc_captured}")
    if disc_matured > 0:
        print(f"  Discount capture rate       : {(disc_captured / disc_matured) * 100:.0f}%")
    else:
        print("  Discount capture rate       : N/A")
    print(f"  Missed discount value (USD) : ${missed_disc_usd:,.2f}")
    print("-" * 58)
    print(f"  PO-based invoices           : {po_based}")
    print(f"  First-pass match            : {first_pass} of {po_based}")
    if po_based > 0:
        print(f"  First-pass match rate       : {(first_pass / po_based) * 100:.0f}%")
    else:
        print("  First-pass match rate       : N/A")
    print("-" * 58)
    print(f"  Total exceptions flagged    : {exceptions}")
    print("=" * 58)
    print(f"  Dashboard file exported to  : {OUTPUT_FILE}")
    print("=" * 58)


def main():
    """
    Main workflow:
    1. Load and validate raw invoice data
    2. Clean and standardize date fields
    3. Apply FX conversion to USD reporting currency
    4. Calculate days to pay
    5. Calculate overdue metrics and outstanding balances
    6. Assign aging buckets
    7. Calculate discount capture metrics
    8. Calculate PO match and first-pass rate
    9. Flag anomalies and exceptions
    10. Prepare Excel-friendly dashboard fields
    11. Export dashboard-ready CSV
    12. Print business summary to terminal
    """
    df = load_data(RAW_FILE)
    df = clean_date_columns(df)
    df = apply_fx_conversion(df)
    df = calculate_days_to_pay(df)
    df = calculate_overdue_metrics(df, SNAPSHOT_DATE)
    df = assign_aging_bucket(df)
    df = calculate_discount_metrics(df, SNAPSHOT_DATE)
    df = calculate_po_match_metrics(df)
    df = flag_anomalies(df, SNAPSHOT_DATE)
    df = prepare_dashboard_fields(df, SNAPSHOT_DATE)
    export_dashboard_file(df, OUTPUT_FILE)
    print_summary(df)


if __name__ == "__main__":
    main()
