import re
import pandas as pd

# Columns that actually represent bucket quantities
BUCKET_COLUMNS = [
    "CLASSIC HQ",
    "CLASSIC",
    "NextGen HQ",
    "NextGen N2",
    "5-liter round",
    "5-liter Vase",
    "7-liter Vase",
    "7-liter Vase HQ",
    "10 Conical",
    "10 Conical NG",
    "13 Conical",
    "13 NextGen",
    "MAXIMA",
    "SUB",
    "HOLD",
]

_YEAR_RE = re.compile(r"^\s*(19|20)\d{2}\s*$")


def _looks_like_year(s: str) -> bool:
    return bool(s and _YEAR_RE.match(str(s)))


def normalize_customer_name(raw) -> str:
    """
    Normalize customer naming variants so metrics aggregate correctly.
    Returns "" for rows that should not be counted as customers (e.g., year headers).
    """
    if raw is None:
        return ""

    s = str(raw).strip()
    if not s or s.lower() in {"nan", "none"}:
        return ""

    # Filter out accidental "customers" like 2024 / 2026
    if _looks_like_year(s):
        return ""

    s_lower = s.lower()

    # Retriever variants
    if s_lower in {
        "retriever",
        "retriever packaging",
        "retriever packaging company",
        "retriever packaging co.",
        "retriever packaging co",
        "retriever packaging corp",
        "retriever packaging corporation",
        "retriever packaging, inc",
        "retriever packaging inc",
        "retriever packaging llc",
    }:
        return "Retriever Packaging"

    # Seaside variants
    if s_lower in {"seaside", "seaside packaging"}:
        return "Seaside Packaging"

    # Mobi's variants
    if s_lower in {"mobi's", "mobis", "mobi's flowers", "mobis flowers"}:
        return "Mobi's Flowers"

    # Designers Choice variants (incl. common misspellings)
    if s_lower in {
        "designer's choice",
        "designers choice",
        "designer choice",
        "desginer's choice",
        "desginers choice",
        "desginer choice",
        "desginers choice llc",
        "designer's choice llc",
        "designers choice llc",
    }:
        return "Designers Choice"

        # Bay State variants
    if s_lower in {
        "bay state",
        "baystate",
        "bay state & johnson's ct",
        "baystate & johnson's ct",
        "bay state and johnson's ct",
        "baystate and johnson's ct",
    }:
        return "Bay State"


    # Kendal variants (roll up all kendal north/central/south, etc.)
    if s_lower in {
        "kendal",
        "kendal north",
        "kendal south",
        "kendal central",
        "kendal floral, llc",
        "kendal floral llc",
        "kendal floral",
        "kendal north bouquet co.",
        "kendal north bouquet co",
        "kendal north bouquet company",
    }:
        return "Kendal"

    return s


def analyze_prognosis_workbook(uploaded_file):
    """
    uploaded_file: request.FILES['file'] from Django (InMemoryUploadedFile)

    Returns a dict of Pandas DataFrames with the metrics we care about.
    """

    # Read just the "Master List" sheet
    xls = pd.ExcelFile(uploaded_file)
    df = pd.read_excel(xls, sheet_name="Master List")

    # In your file, row 1 (0-based index) is the true header row
    header_row = df.iloc[1]

    # Data starts at row index 3 (i.e., 4th visible Excel row)
    data = df.iloc[3:].copy()
    data.columns = header_row

    # Normalize column names we care about
    data = data.rename(
        columns={
            "NLD": "date",
            "Customer": "customer",
            "City": "city",
        }
    )

    # Keep only rows with a real date
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data[~data["date"].isna()].copy()

    # Normalize customer names BEFORE any grouping
    data["customer"] = data["customer"].apply(normalize_customer_name)

    # Drop rows that are not actual customers (blank after normalization)
    data = data[data["customer"].astype(str).str.strip() != ""].copy()

    # Keep only bucket columns that actually exist in this file
    bucket_cols = [c for c in BUCKET_COLUMNS if c in data.columns]

    # Convert bucket columns to numbers (NaN -> 0)
    data[bucket_cols] = data[bucket_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    # Month string like "2025-02"
    data["month"] = data["date"].dt.to_period("M").astype(str)

    # Total buckets in this row (sum all bucket types)
    data["total_buckets"] = data[bucket_cols].sum(axis=1)

    # 1) Buckets sold per customer per month
    per_customer_month = (
        data.groupby(["customer", "month"])["total_buckets"]
        .sum()
        .reset_index()
        .sort_values(["customer", "month"])
    )

    # Long form
    long = data.melt(
        id_vars=["customer", "city", "month"],
        value_vars=bucket_cols,
        var_name="bucket_type",
        value_name="qty",
    )
    long = long[long["qty"] > 0]

    # 2) Amount of each item sold per customer per location (across all months)
    per_customer_city_item = (
        long.groupby(["customer", "city", "bucket_type"])["qty"]
        .sum()
        .reset_index()
        .sort_values(["customer", "city", "bucket_type"])
    )

    # 3) Amount of each item sold per customer per location per month
    per_customer_city_item_month = (
        long.groupby(["customer", "city", "month", "bucket_type"])["qty"]
        .sum()
        .reset_index()
        .sort_values(["customer", "city", "month", "bucket_type"])
    )

    # 4) Top customers overall by total buckets
    top_customers = (
        per_customer_month.groupby("customer")["total_buckets"]
        .sum()
        .reset_index()
        .sort_values("total_buckets", ascending=False)
        .head(20)
    )

    return {
        "per_customer_month": per_customer_month,
        "per_customer_city_item": per_customer_city_item,
        "per_customer_city_item_month": per_customer_city_item_month,
        "top_customers": top_customers,
    }
