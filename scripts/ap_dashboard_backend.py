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
"""

# Import required libraries
import pandas as pd


# File paths
RAW_FILE = "data/ap_invoices.csv"
OUTPUT_FILE = "output/ap_invoices_dashboard_ready.csv"
SNAPSHOT_DATE = pd.Timestamp("2025-06-30")


def load_data(file_path):
    """
    Load the raw AP invoice dataset exported from the ERP-style source file.
    """
    df = pd.read_csv(file_path)

    # Validate required columns exist before any processing begins
    # In a real ERP export, missing columns would cause silent errors downstream
    required_columns = [
        "invoice_num", "posting_date", "due_date", "payment_date",
        "invoice_amount", "amount_paid", "status", "po_number",
        "discount_terms", "discount_amount", "discount_due_date"
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
        "discount_due_date"
    ]

    for col in date_columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def calculate_days_to_pay(df):
    """
    Calculate days_to_pay for paid invoices only.

    Business meaning:
    This measures how long it took AP to pay the invoice after it was posted.
    It is a practical AP efficiency metric and supports the dashboard KPI:
    average payment timing (Days Payable Outstanding proxy).

    Logic:
    - Use payment_date minus posting_date
    - Only calculate for invoices that have actually been paid
    - Leave blank for unpaid, blocked, overdue, voided, or in-review items
    """
    df["days_to_pay"] = (df["payment_date"] - df["posting_date"]).dt.days

    unpaid_statuses = ["Open", "Overdue", "Blocked", "In Review", "Voided"]
    df.loc[df["status"].isin(unpaid_statuses), "days_to_pay"] = pd.NA
    df.loc[df["payment_date"].isna(), "days_to_pay"] = pd.NA

    return df


def calculate_overdue_metrics(df, snapshot_date):
    """
    Calculate outstanding balance and overdue status as of the reporting snapshot date.

    Business meaning:
    AP managers do not only care whether an invoice was ever paid.
    They need to know what amount is still outstanding and whether that balance
    is now past due as of the reporting date.

    Key outputs:
    - outstanding_amount: unpaid balance still open on the invoice
    - is_overdue: TRUE when there is still an unpaid balance and the due date
      is before the snapshot date
    - days_past_due: number of days overdue as of the snapshot date

    Logic:
    - outstanding_amount = invoice_amount - amount_paid
    - never allow negative outstanding balances (clip at zero)
    - voided invoices are excluded from overdue risk
    - partial payments can still be overdue if a balance remains unpaid
    """
    df["outstanding_amount"] = df["invoice_amount"] - df["amount_paid"]
    df["outstanding_amount"] = df["outstanding_amount"].clip(lower=0)

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
    Aging buckets are one of the most universal tools in AP reporting.
    They show management how long overdue balances have been sitting unpaid,
    and help prioritize which vendors need immediate outreach or escalation.

    Bucket logic:
    - Current: invoice is not overdue
    - 0-30 days: overdue by 0 to 30 days
    - 31-60 days: overdue by 31 to 60 days
    - 61-90 days: overdue by 61 to 90 days
    - 90+ days: overdue by more than 90 days (highest risk)
    """
    df["aging_bucket"] = "Current"

    df.loc[
        df["is_overdue"] & df["days_past_due"].between(0, 30),
        "aging_bucket"
    ] = "0-30 Days"

    df.loc[
        df["is_overdue"] & df["days_past_due"].between(31, 60),
        "aging_bucket"
    ] = "31-60 Days"

    df.loc[
        df["is_overdue"] & df["days_past_due"].between(61, 90),
        "aging_bucket"
    ] = "61-90 Days"

    df.loc[
        df["is_overdue"] & (df["days_past_due"] > 90),
        "aging_bucket"
    ] = "90+ Days"

    return df


def calculate_discount_metrics(df, snapshot_date):
    """
    Calculate discount eligibility, discount capture, and missed discount value.

    Business meaning:
    Early payment discounts (typically 2% if paid within 10 days) represent
    real savings that AP teams are responsible for capturing. Missed discounts
    are a direct cost to the business and a measurable AP performance gap.

    Key outputs:
    - is_discount_eligible: invoice has a valid 2/10 discount opportunity
    - discount_captured_calc: fully paid within the discount window
    - discount_missed_calc: discount opportunity expired without being captured
    - captured_discount_value: dollar value successfully captured
    - missed_discount_value: dollar value left on the table

    Logic:
    - Only 2/10 Net 30 invoices with a discount amount and due date are eligible
    - Capture only counts when the invoice is fully paid on or before discount_due_date
    - A discount is missed if paid after the window or still unpaid after window closed
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
    df.loc[df["discount_captured_calc"], "captured_discount_value"] = df["discount_amount"]

    df["missed_discount_value"] = 0.00
    df.loc[df["discount_missed_calc"], "missed_discount_value"] = df["discount_amount"]

    return df


def calculate_po_match_metrics(df):
    """
    Flag PO-based invoices and identify first-pass match performance.

    Business meaning:
    First-pass match rate measures how often PO-backed invoices moved through
    the AP process without exceptions. A high first-pass rate means the
    procurement and AP workflow is aligned. A low rate signals mismatches
    between purchase orders and vendor invoices, which create processing delays
    and block timely payment.

    Key outputs:
    - is_po_based: invoice is tied to a purchase order
    - has_po_exception: PO invoice landed in Blocked or In Review status
    - first_pass_match: PO invoice cleared with no exception

    Logic:
    - PO-based means po_number is populated and not blank
    - Exception means status is Blocked or In Review
    - First-pass match is TRUE only for PO-based invoices with no exception
    """
    df["is_po_based"] = df["po_number"].notna() & (df["po_number"].astype(str).str.strip() != "")

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
    can surface issues that would otherwise require manual review.

    Anomalies flagged:
    - Late payment: invoice was paid but payment_date exceeded due_date
    - Blocked > 30 days: invoice has been sitting on payment block for over a month
    - Missed discount: eligible for early payment discount but window was not used
    - Duplicate risk: same vendor billed the same amount within a 30-day window
    - In Review > 15 days: invoice has been under review for an extended period
    """

    # Late payment: paid invoices where payment came in after the due date
    df["late_payment_flag"] = (
        (df["status"] == "Paid") &
        df["payment_date"].notna() &
        df["due_date"].notna() &
        (df["payment_date"] > df["due_date"])
    )

    # Blocked > 30 days: payment block has been active for more than 30 days
    df["blocked_over_30_days"] = (
        (df["status"] == "Blocked") &
        df["posting_date"].notna() &
        ((snapshot_date - df["posting_date"]).dt.days > 30)
    )

    # In Review > 15 days: invoice has been under review for more than 15 days
    df["in_review_over_15_days"] = (
        (df["status"] == "In Review") &
        df["posting_date"].notna() &
        ((snapshot_date - df["posting_date"]).dt.days > 15)
    )

    # Missed discount: eligible invoice where discount window passed without capture
    df["missed_discount_flag"] = df["discount_missed_calc"]

    # Duplicate risk: same vendor_num and same invoice_amount posted within 30 days
    # Sort by vendor and date to enable window comparison
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

    # Merge duplicate flag back to original dataframe on invoice_num
    df = df.merge(
        df_sorted[["invoice_num", "duplicate_risk_flag"]],
        on="invoice_num",
        how="left"
    )
    df["duplicate_risk_flag"] = df["duplicate_risk_flag"].fillna(False)

    return df


def prepare_dashboard_fields(df, snapshot_date):
    """
    Create Excel-friendly helper fields for dashboard building.

    Business meaning:
    These fields make it easier to build charts, KPI cards, and the exception
    table in Excel without rebuilding logic in formulas or pivot tables.
    The goal is to make the Excel layer purely visual with no calculation burden.

    Key outputs:
    - posting_month_num / posting_month_name / posting_month_label
    - is_exception: highlights items needing management attention
    - issue_type: plain-English issue label for the exception report tab
    - days_open_as_of_snapshot: how long an unpaid balance has been outstanding
    - urgency_level: priority flag for sorting the exception report
    """
    df["posting_month_num"] = df["posting_date"].dt.month
    df["posting_month_name"] = df["posting_date"].dt.strftime("%b")
    df["posting_month_label"] = df["posting_date"].dt.strftime("%b %Y")

    # is_exception: any invoice that requires management attention
    df["is_exception"] = (
        df["status"].isin(["Blocked", "In Review", "Partially Paid", "Voided"]) |
        df["is_overdue"] |
        df["late_payment_flag"] |
        df["duplicate_risk_flag"] |
        df["missed_discount_flag"] |
        df["blocked_over_30_days"] |
        df["in_review_over_15_days"]
    )

    # issue_type: plain-English label for the exception report
    # Priority order: most severe condition takes the label
    df["issue_type"] = ""
    df.loc[df["late_payment_flag"], "issue_type"] = "Late Payment"
    df.loc[df["missed_discount_flag"], "issue_type"] = "Missed Discount"
    df.loc[df["duplicate_risk_flag"], "issue_type"] = "Duplicate Risk"
    df.loc[df["status"] == "Partially Paid", "issue_type"] = "Partial Payment Outstanding"
    df.loc[df["status"] == "Voided", "issue_type"] = "Voided Invoice"
    df.loc[df["in_review_over_15_days"], "issue_type"] = "In Review Over 15 Days"
    df.loc[df["blocked_over_30_days"], "issue_type"] = "Blocked Over 30 Days"
    df.loc[df["is_overdue"], "issue_type"] = "Overdue Invoice"  # highest priority — overwrites

    # urgency_level: for sorting the exception table in Excel
    # Red = act now, Amber = monitor, Yellow = low priority
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

    # days_open_as_of_snapshot: how long any unpaid balance has been sitting open
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
    Python handles all AP logic and calculations.
    Excel handles the final management dashboard and visual presentation.
    Sorted by posting date so the Excel layer reads chronologically.
    """
    df = df.sort_values(by=["posting_date", "invoice_num"]).reset_index(drop=True)
    df.to_csv(file_path, index=False)


def print_summary(df):
    """
    Print a business-readable summary to the terminal when the script runs.

    Business meaning:
    When a recruiter or manager runs this script, they should see real AP
    numbers immediately — not just technical confirmation messages.
    This output mirrors what an AP manager would want to see in a morning report.
    """
    total_invoices = len(df)
    total_spend = df["invoice_amount"].sum()
    overdue_count = df["is_overdue"].sum()
    overdue_exposure = df.loc[df["is_overdue"], "outstanding_amount"].sum()
    avg_days_to_pay = df["days_to_pay"].mean()
    discount_eligible = df["is_discount_eligible"].sum()
    discount_captured = df["discount_captured_calc"].sum()
    missed_discount_value = df["missed_discount_value"].sum()
    po_based = df["is_po_based"].sum()
    first_pass = df["first_pass_match"].sum()
    exceptions = df["is_exception"].sum()

    print("=" * 55)
    print("  AP OPERATIONS SUMMARY — Snapshot: June 30, 2025")
    print("=" * 55)
    print(f"  Total invoices processed    : {total_invoices}")
    print(f"  Total invoice spend         : ${total_spend:,.2f}")
    print("-" * 55)
    print(f"  Overdue invoices            : {overdue_count}")
    print(f"  Overdue exposure            : ${overdue_exposure:,.2f}")
    print(f"  Avg days to pay             : {avg_days_to_pay:.1f} days")
    print("-" * 55)
    print(f"  Discount eligible invoices  : {discount_eligible}")
    print(f"  Discounts captured          : {discount_captured} of {discount_eligible}")
    if discount_eligible > 0:
        capture_rate = (discount_captured / discount_eligible) * 100
        print(f"  Discount capture rate       : {capture_rate:.0f}%")
    print(f"  Missed discount value       : ${missed_discount_value:,.2f}")
    print("-" * 55)
    print(f"  PO-based invoices           : {po_based}")
    print(f"  First-pass match            : {first_pass} of {po_based}")
    if po_based > 0:
        fpm_rate = (first_pass / po_based) * 100
        print(f"  First-pass match rate       : {fpm_rate:.0f}%")
    print("-" * 55)
    print(f"  Total exceptions flagged    : {exceptions}")
    print("=" * 55)
    print(f"  Dashboard file exported to  : {OUTPUT_FILE}")
    print("=" * 55)


def main():
    """
    Main workflow:
    1. Load and validate raw invoice data
    2. Clean and standardize date fields
    3. Calculate AP reporting metrics
    4. Detect anomalies and exceptions
    5. Prepare Excel-friendly dashboard fields
    6. Export dashboard-ready CSV
    7. Print business summary to terminal
    """
    df = load_data(RAW_FILE)
    df = clean_date_columns(df)
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
