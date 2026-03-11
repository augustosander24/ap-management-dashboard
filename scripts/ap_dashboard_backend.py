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

# Import required libraries
import pandas as pd


# File paths
RAW_FILE = "data/ap_invoices.csv"
OUTPUT_FILE = "output/ap_invoices_dashboard_ready.csv"
SNAPSHOT_DATE = pd.Timestamp("2025-06-30")

# FX conversion rates to USD — fixed as of snapshot date June 30, 2025
# These rates allow all KPI totals to be reported in a single reporting currency
# Original currency and original amounts are always preserved in the dataset
FX_RATES_TO_USD = {
    "USD": 1.0000,
    "EUR": 1.0721,
    "MXN": 0.0572,
}


def load_data(file_path):
    """
    Load the raw AP invoice dataset exported from the ERP-style source file.
    Validates that all required columns are present before any processing begins.

    Business meaning:
    In a real ERP environment, missing columns in an export would cause silent
    downstream errors. Early validation catches data quality issues immediately.
    """
    df = pd.read_csv(file_path)

    # Validate all required columns exist before any processing begins
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
    AP dashboards that mix currencies (USD, EUR, MXN) without conversion
    produce totals that are not finance-valid. A controller or CFO reviewing
    total spend or overdue exposure needs a single reporting currency.

    This function preserves all original amounts and currency codes, then adds
    USD-equivalent columns used exclusively for KPI summary calculations.

    Key outputs:
    - invoice_amount_usd: invoice_amount converted to USD
    - amount_paid_usd: amount_paid converted to USD
    - fx_rate_used: the conversion rate applied, for auditability

    Logic:
    - FX rates are fixed as of the snapshot date (June 30, 2025)
    - Unrecognized currencies default to a 1.0 rate and are flagged
    - Original currency and original amounts are never modified
    """
    df["fx_rate_used"] = df["currency"].map(FX_RATES_TO_USD)

    unrecognized = df[df["fx_rate_used"].isna()]["currency"].unique()
    if len(unrecognized) > 0:
        print(f"  WARNING: Unrecognized currencies found — defaulting to 1.0: {unrecognized}")
        df["fx_rate_used"] = df["fx_rate_used"].fillna(1.0)

    df["invoice_amount_usd"] = (df["invoice_amount"] * df["fx_rate_used"]).round(2)
    df["amount_paid_usd"] = (df["amount_paid"] * df["fx_rate_used"]).round(2)

    return df


def calculate_days_to_pay(df):
    """
    Calculate days_to_pay for fully paid invoices only.

    Business meaning:
    This measures how long it took AP to pay the invoice after it was posted.
    It is a core AP efficiency metric that feeds the average payment timing KPI.

    Logic:
    - Use payment_date minus posting_date
    - Only calculated for invoices with status Paid
    - Partially Paid is explicitly excluded — a partial payment does not mean
      the invoice is settled, and including it would distort the average
    - All other statuses (Open, Overdue, Blocked, In Review, Voided) are excluded
    """
    df["days_to_pay"] = (df["payment_date"] - df["posting_date"]).dt.days

    excluded_statuses = ["Open", "Overdue", "Blocked", "In Review", "Voided", "Partially Paid"]
    df.loc[df["status"].isin(excluded_statuses), "days_to_pay"] = pd.NA
    df.loc[df["payment_date"].isna(), "days_to_pay"] = pd.NA

    return df


def calculate_overdue_metrics(df, snapshot_date):
    """
    Calculate outstanding balance and overdue status as of the reporting snapshot date.

    Business meaning:
    AP managers need to know not just whether an invoice was paid, but what
    amount is still outstanding and whether that balance is now past due.
    Outstanding exposure drives cash flow planning and vendor relationship risk.

    Key outputs:
    - outstanding_amount: unpaid balance in original currency
    - outstanding_amount_usd: unpaid balance converted to USD for KPI totals
    - is_overdue: TRUE when unpaid balance exists and due date has passed
    - days_past_due: number of days overdue as of the snapshot date

    Logic:
    - outstanding_amount = invoice_amount minus amount_paid
    - clip at zero to prevent negative balances from data entry errors
    - voided invoices are excluded from overdue risk entirely
    - partial payments can still be overdue if a balance remains
    """
    df["outstanding_amount"] = (df["invoice_amount"] - df["amount_paid"]).clip(lower=0)
    df["outstanding_amount_usd"] = (df["invoice_amount_usd"] - df["amount_paid_usd"]).clip(lower=0)

    df["is_overdue"] = (
        (df["outstanding_amount"] > 0) &
        (df["due_date"] < snapshot_date) &
        (df["status"] != "Voided")
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
    Aging buckets are the most universal AP risk reporting tool.
    They show management how long overdue balances have been sitting unpaid
    and help prioritize which vendors need immediate payment or escalation.
    The further right a balance moves in the aging schedule, the higher the risk.

    Bucket logic:
    - Current:     invoice is not overdue
    - 0-30 Days:   overdue by 0 to 30 days
    - 31-60 Days:  overdue by 31 to 60 days
    - 61-90 Days:  overdue by 61 to 90 days
    - 90+ Days:    overdue by more than 90 days — highest risk category
    """
    df["aging_bucket"] = "Current"

    df.loc[df["is_overdue"] & df["days_past_due"].between(0, 30),  "aging_bucket"] = "0-30 Days"
    df.loc[df["is_overdue"] & df["days_past_due"].between(31, 60), "aging_bucket"] = "31-60 Days"
    df.loc[df["is_overdue"] & df["days_past_due"].between(61, 90), "aging_bucket"] = "61-90 Days"
    df.loc[df["is_overdue"] & (df["days_past_due"] > 90),          "aging_bucket"] = "90+ Days"

    return df


def calculate_discount_metrics(df, snapshot_date):
    """
    Calculate discount eligibility, capture, and missed value.

    Business meaning:
    Early payment discounts (2% if paid within 10 days on 2/10 Net 30 terms)
    represent real savings that AP teams are responsible for capturing.
    Missed discounts are a direct, measurable cost to the business.
    Discount capture rate is a standard AP performance KPI.

    Key outputs:
    - is_discount_eligible: invoice qualifies for an early payment discount
    - discount_captured_calc: invoice was fully paid within the discount window
    - discount_missed_calc: discount window closed without full payment
    - captured_discount_value: USD value of discounts successfully captured
    - missed_discount_value: USD value left on the table

    Logic:
    - Only 2/10 Net 30 invoices with a discount amount and discount_due_date qualify
    - Capture requires full payment (status Paid) on or before discount_due_date
    - Missed means paid after the window OR still unpaid after the window closed
    """
    df["is_discount_eligible"] = (
        df["discount_terms"].fillna("").str.contains("2/10", case=False) &
        (df["discount_amount"] > 0) &
        df["discount_due_date"].notna()
    )

    df["discount_captured_calc"] = (
        df["is_discount_eligible"] &
        (df["status"] == "Paid") &
        df["payment_date"].notna() &
        (df["payment_date"] <= df["discount_due_date"])
    )

    df["discount_missed_calc"] = (
        df["is_discount_eligible"] &
        (
            (
                (df["status"] == "Paid") &
                df["payment_date"].notna() &
                (df["payment_date"] > df["discount_due_date"])
            ) |
            (
                (df["outstanding_amount"] > 0) &
                (df["discount_due_date"] < snapshot_date)
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
    First-pass match rate measures how often PO-backed invoices moved through
    AP without exceptions. A high rate means procurement and AP are aligned.
    A low rate signals PO-to-invoice mismatches that cause delays and block
    vendor payments — a common source of vendor relationship friction.

    Key outputs:
    - is_po_based: invoice is linked to a purchase order
    - has_po_exception: PO invoice is currently Blocked or In Review
    - first_pass_match: PO invoice cleared with no exception

    Logic:
    - PO-based means po_number is populated and not blank
    - Exception means status is Blocked or In Review
    - First-pass match is TRUE only for PO-based invoices with no exception
    """
    df["is_po_based"] = (
        df["po_number"].notna() &
        (df["po_number"].astype(str).str.strip() != "")
    )

    df["has_po_exception"] = (
        df["is_po_based"] &
        df["status"].isin(["Blocked", "In Review"])
    )

    df["first_pass_match"] = (
        df["is_po_based"] &
        ~df["status"].isin(["Blocked", "In Review"])
    )

    return df


def flag_anomalies(df, snapshot_date):
    """
    Detect AP process anomalies and exceptions requiring management attention.

    Business meaning:
    Exception management is one of the most time-consuming parts of real AP
    operations. This function automates anomaly detection so the dashboard
    surfaces issues that would otherwise require manual daily review.

    Anomalies flagged:
    - Late payment:        invoice was paid after the due date
    - Blocked > 30 days:   payment block active for more than 30 days
    - In Review > 15 days: invoice under review for more than 15 days
    - Missed discount:     eligible for early payment discount but window passed
    - Duplicate risk:      same vendor billed the same amount within 30 days
    """
    df["late_payment_flag"] = (
        (df["status"] == "Paid") &
        df["payment_date"].notna() &
        df["due_date"].notna() &
        (df["payment_date"] > df["due_date"])
    )

    df["blocked_over_30_days"] = (
        (df["status"] == "Blocked") &
        df["posting_date"].notna() &
        ((snapshot_date - df["posting_date"]).dt.days > 30)
    )

    df["in_review_over_15_days"] = (
        (df["status"] == "In Review") &
        df["posting_date"].notna() &
        ((snapshot_date - df["posting_date"]).dt.days > 15)
    )

    df["missed_discount_flag"] = df["discount_missed_calc"]

    df_sorted = df.sort_values(["vendor_num", "posting_date"]).copy()
    df_sorted["prev_amount"] = df_sorted.groupby("vendor_num")["invoice_amount"].shift(1)
    df_sorted["prev_posting"] = df_sorted.groupby("vendor_num")["posting_date"].shift(1)
    df_sorted["days_since_prev"] = (
        df_sorted["posting_date"] - df_sorted["prev_posting"]
    ).dt.days

    df_sorted["duplicate_risk_flag"] = (
        (df_sorted["invoice_amount"] == df_sorted["prev_amount"]) &
        (df_sorted["days_since_prev"] <= 30)
    )

    df = df.merge(
        df_sorted[["invoice_num", "duplicate_risk_flag"]],
        on="invoice_num",
        how="left"
    )
    df["duplicate_risk_flag"] = df["duplicate_risk_flag"].fillna(False)

    return df


def prepare_dashboard_fields(df, snapshot_date):
    """
    Create Excel-friendly helper fields for dashboard and exception reporting.

    Business meaning:
    These fields eliminate formula complexity in Excel so the dashboard layer
    is purely visual. Every calculation stays in Python where it can be
    version-controlled, tested, and explained.

    Issue type priority order (most specific label wins):
    Overdue is assigned first as a base, then more specific conditions overwrite it.
    This ensures a blocked invoice that is also overdue shows Blocked Over 30 Days
    rather than the generic Overdue Invoice label.
    """
    df["posting_month_num"] = df["posting_date"].dt.month
    df["posting_month_name"] = df["posting_date"].dt.strftime("%b")
    df["posting_month_label"] = df["posting_date"].dt.strftime("%b %Y")

    df["is_exception"] = (
        df["status"].isin(["Blocked", "In Review", "Partially Paid", "Voided"]) |
        df["is_overdue"] |
        df["late_payment_flag"] |
        df["duplicate_risk_flag"] |
        df["missed_discount_flag"] |
        df["blocked_over_30_days"] |
        df["in_review_over_15_days"]
    )

    df["issue_type"] = ""
    df.loc[df["is_overdue"],                "issue_type"] = "Overdue Invoice"
    df.loc[df["late_payment_flag"],          "issue_type"] = "Late Payment"
    df.loc[df["missed_discount_flag"],       "issue_type"] = "Missed Discount"
    df.loc[df["duplicate_risk_flag"],        "issue_type"] = "Duplicate Risk"
    df.loc[df["status"] == "Partially Paid", "issue_type"] = "Partial Payment Outstanding"
    df.loc[df["status"] == "Voided",         "issue_type"] = "Voided Invoice"
    df.loc[df["in_review_over_15_days"],     "issue_type"] = "In Review Over 15 Days"
    df.loc[df["blocked_over_30_days"],       "issue_type"] = "Blocked Over 30 Days"

    df["urgency_level"] = ""
    df.loc[df["issue_type"].isin([
        "Overdue Invoice", "Blocked Over 30 Days"
    ]), "urgency_level"] = "Red"
    df.loc[df["issue_type"].isin([
        "Missed Discount", "Partial Payment Outstanding", "In Review Over 15 Days"
    ]), "urgency_level"] = "Amber"
    df.loc[df["issue_type"].isin([
        "Late Payment", "Duplicate Risk", "Voided Invoice"
    ]), "urgency_level"] = "Yellow"

    df["days_open_as_of_snapshot"] = pd.NA
    open_balance_mask = (df["outstanding_amount"] > 0) & (df["status"] != "Voided")
    df.loc[open_balance_mask, "days_open_as_of_snapshot"] = (
        snapshot_date - df.loc[open_balance_mask, "posting_date"]
    ).dt.days

    return df


def export_dashboard_file(df, file_path):
    """
    Export the final dashboard-ready dataset for Excel.

    Business meaning:
    This file is the bridge between Python and Excel.
    Python owns all AP logic, calculations, and anomaly detection.
    Excel owns the visual dashboard and management presentation layer.
    """
    df = df.sort_values(by=["posting_date", "invoice_num"]).reset_index(drop=True)
    df.to_csv(file_path, index=False)


def print_summary(df):
    """
    Print a business-readable AP summary to the terminal when the script runs.
    All KPI totals are in USD (reporting currency).
    """
    total_invoices  = len(df)
    total_spend_usd = df["invoice_amount_usd"].sum()
    overdue_count   = df["is_overdue"].sum()
    overdue_usd     = df.loc[df["is_overdue"], "outstanding_amount_usd"].sum()
    avg_days        = df["days_to_pay"].mean()
    disc_eligible   = df["is_discount_eligible"].sum()
    disc_captured   = df["discount_captured_calc"].sum()
    missed_disc_usd = df["missed_discount_value"].sum()
    po_based        = df["is_po_based"].sum()
    first_pass      = df["first_pass_match"].sum()
    exceptions      = df["is_exception"].sum()
    currency_mix    = dict(df["currency"].value_counts())

    print("=" * 55)
    print("  AP OPERATIONS SUMMARY — Snapshot: June 30, 2025")
    print("  All totals reported in USD (reporting currency)")
    print("=" * 55)
    print(f"  Total invoices processed    : {total_invoices}")
    print(f"  Total invoice spend (USD)   : ${total_spend_usd:,.2f}")
    print(f"  Currency mix                : {currency_mix}")
    print("-" * 55)
    print(f"  Overdue invoices            : {overdue_count}")
    print(f"  Overdue exposure (USD)      : ${overdue_usd:,.2f}")
    print(f"  Avg days to pay             : {avg_days:.1f} days")
    print("-" * 55)
    print(f"  Discount eligible invoices  : {disc_eligible}")
    print(f"  Discounts captured          : {disc_captured} of {disc_eligible}")
    if disc_eligible > 0:
        print(f"  Discount capture rate       : {(disc_captured / disc_eligible) * 100:.0f}%")
    print(f"  Missed discount value (USD) : ${missed_disc_usd:,.2f}")
    print("-" * 55)
    print(f"  PO-based invoices           : {po_based}")
    print(f"  First-pass match            : {first_pass} of {po_based}")
    if po_based > 0:
        print(f"  First-pass match rate       : {(first_pass / po_based) * 100:.0f}%")
    print("-" * 55)
    print(f"  Total exceptions flagged    : {exceptions}")
    print("=" * 55)
    print(f"  Dashboard file exported to  : {OUTPUT_FILE}")
    print("=" * 55)


def main():
    """
    Main workflow:
    1.  Load and validate raw invoice data
    2.  Clean and standardize date fields
    3.  Apply FX conversion to USD reporting currency
    4.  Calculate days to pay (fully paid invoices only)
    5.  Calculate overdue metrics and outstanding balances
    6.  Assign aging buckets
    7.  Calculate discount capture metrics
    8.  Calculate PO match and first-pass rate
    9.  Flag anomalies and exceptions
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
