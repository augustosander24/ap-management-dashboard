# AP Management Dashboard

End-to-end Accounts Payable analytics project built to simulate a real business reporting workflow from raw ERP-style invoice data to management-facing KPI reporting.

## Dashboard Preview

![AP Management Dashboard](images/dashboard-overview.png)

## Key Files

- [Final Excel Dashboard Workbook](AP_Management_Dashboard.xlsx)
- [Project Pipeline View](images/project-pipeline.png)
- [Vendor Analysis View](images/vendor-analysis.png)

## Project Overview

This project was designed to demonstrate how Accounts Payable data can move through a full reporting pipeline:

- **Python** prepares and transforms raw invoice data
- **SQL** answers business questions on the cleaned dataset
- **Excel** presents the final KPIs and dashboard views for reporting

The final output is an Excel dashboard focused on invoice volume, payment status, aging, vendor activity, and payment-performance analysis.

## Business Goal

The goal of this project is to show practical finance-operations and reporting capability in a way that is relevant to Accounts Payable, finance operations, shared services, and analyst roles.

Rather than showing only spreadsheet formatting, this project demonstrates a more complete workflow:

**raw data -> transformation -> analysis -> dashboard reporting**

## Tools Used

- **Python** for data transformation and preparation
- **SQL** for business-question analysis on cleaned AP data
- **Excel** for KPI reporting, summary tables, formulas, and dashboard presentation

## What the Dashboard Tracks

The dashboard is designed to support common AP and finance reporting needs, including:

- Invoice volume trends
- Vendor-level activity
- Aging bucket analysis
- Payment status tracking
- Overdue exposure
- On-time payment performance
- Review and blocked invoice monitoring

## Project Structure

- `AP_Management_Dashboard.xlsx` — final Excel dashboard workbook
- `data/` — source and supporting data files
- `scripts/` — Python and SQL logic used in the pipeline
- `output/` — generated outputs and analysis results
- `images/` — project image assets

## Why This Project Matters

This project reflects the kind of work behind real finance reporting:

- turning raw transactional data into usable information
- checking business logic across multiple steps
- connecting operational AP activity to decision-useful reporting
- presenting results in a format that non-technical stakeholders can use

It was built as a portfolio project to demonstrate a blend of:

- Accounts Payable domain knowledge
- process thinking
- reporting discipline
- modern analytics tools

## Final Deliverable

The main deliverable in this repository is:

**`AP_Management_Dashboard.xlsx`**

This workbook includes the final dashboard plus supporting tabs documenting the project pipeline, formula logic, and analysis structure.
