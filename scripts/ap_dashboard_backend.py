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

    print("Data loaded successfully.")
    print(f"Rows: {len(df)}")
    print(f"Columns: {len(df.columns)}")
    print("Date columns cleaned successfully.")

    # Next steps will be added here:
    # - calculate days_to_pay
    # - calculate overdue flags
    # - create aging buckets
    # - calculate discount capture logic
    # - flag PO exception invoices
    # - export final dashboard-ready CSV


if __name__ == "__main__":
    main()
