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
    return pd.read_csv(file_path)


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
    average payment timing.

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
    - never allow negative outstanding balances
    - voided invoices should not be treated as overdue risk
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
    Aging buckets help AP management see how old unpaid exposure is.
    This is one of the most common ways to summarize payment risk.

    Bucket logic:
    - Current: invoice is not overdue
    - 0-30 days: overdue by 0 to 30 days
    - 31-60 days: overdue by 31 to 60 days
    - 61-90 days: overdue by 61 to 90 days
    - 90+ days: overdue by more than 90 days
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
    This supports a real AP management KPI:
    how often early-payment discounts were captured and how much value was missed.

    Key outputs:
    - is_discount_eligible: invoice has a valid 2/10 discount opportunity
    - discount_captured_calc: fully paid within the discount window
    - discount_missed_calc: discount opportunity expired without being captured
    - captured_discount_value: dollar value successfully captured
    - missed_discount_value: dollar value missed

    Logic:
    - Only 2/10 Net 30 invoices with a discount amount and due date are eligible
    - Capture only counts when the invoice is fully paid on or before discount_due_date
    - A discount is missed if:
        1. the invoice was fully paid after the discount window, or
        2. the discount window passed and the invoice still has an unpaid balance
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
    First-pass match rate is a practical AP efficiency measure.
    It tells us what share of PO-based invoices moved through the process
    without landing in exception statuses such as Blocked or In Review.

    Key outputs:
    - is_po_based: invoice is tied to a purchase order
    - has_po_exception: PO invoice is currently Blocked or In Review
    - first_pass_match: PO invoice had no matching exception flag

    Logic:
    - PO-based means po_number is populated
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


def prepare_dashboard_fields(df, snapshot_date):
    """
    Create Excel-friendly helper fields for dashboard building.

    Business meaning:
    These fields make it easier to build charts, KPI cards, and the exception table
    in Excel without repeatedly rebuilding logic in formulas or pivot tables.

    Key outputs:
    - posting_month_num / posting_month_name / posting_month_label
    - is_exception: highlights items needing management attention
    - issue_type: plain-English issue label for the exception table
    - days_open_as_of_snapshot: how long an unpaid balance has been open
    """
    df["posting_month_num"] = df["posting_date"].dt.month
    df["posting_month_name"] = df["posting_date"].dt.strftime("%b")
    df["posting_month_label"] = df["posting_date"].dt.strftime("%b %Y")

    df["is_exception"] = (
        df["status"].isin(["Blocked", "In Review", "Partially Paid", "Voided"]) |
        df["is_overdue"]
    )

    df["issue_type"] = ""
    df.loc[df["status"] == "Blocked", "issue_type"] = "Payment Block"
    df.loc[df["status"] == "In Review", "issue_type"] = "Invoice In Review"
    df.loc[df["status"] == "Partially Paid", "issue_type"] = "Partial Payment Outstanding"
    df.loc[df["status"] == "Voided", "issue_type"] = "Voided Invoice"
    df.loc[df["is_overdue"], "issue_type"] = "Overdue Invoice"

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
    This file is the bridge between Python and Excel:
    Python handles the AP logic, and Excel handles the final management dashboard.
    """
    df = df.sort_values(by=["posting_date", "invoice_num"]).reset_index(drop=True)
    df.to_csv(file_path, index=False)


def main():
    """
    Main workflow:
    1. Load raw invoice data
    2. Clean and standardize fields
    3. Calculate AP reporting metrics
    4. Export dashboard-ready data for Excel
    """
    df = load_data(RAW_FILE)
    df = clean_date_columns(df)
    df = calculate_days_to_pay(df)
    df = calculate_overdue_metrics(df, SNAPSHOT_DATE)
    df = assign_aging_bucket(df)
    df = calculate_discount_metrics(df, SNAPSHOT_DATE)
    df = calculate_po_match_metrics(df)
    df = prepare_dashboard_fields(df, SNAPSHOT_DATE)
    export_dashboard_file(df, OUTPUT_FILE)

    print("Data loaded successfully.")
    print(f"Rows: {len(df)}")
    print(f"Columns: {len(df.columns)}")
    print("Date columns cleaned successfully.")
    print("days_to_pay calculated successfully.")
    print("Overdue metrics calculated successfully.")
    print("Aging buckets assigned successfully.")
    print("Discount metrics calculated successfully.")
    print("PO exception and first-pass match metrics calculated successfully.")
    print("Dashboard helper fields prepared successfully.")
    print(f"Dashboard-ready file exported to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
