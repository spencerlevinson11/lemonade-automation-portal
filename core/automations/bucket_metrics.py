import re
from datetime import date
from typing import Dict, Tuple, List

import pandas as pd

# Columns that actually represent bucket quantities (source columns)
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
    "8 liter round NG",
    "13 NextGen",
    "3 liter round",
    "MAXIMA",
    "SUB",
    "HOLD",
]

# Columns we want to show in the projection table (and in what order)
PROJECTION_COLUMNS = [
    "CLASSIC HQ",
    "CLASSIC",
    "Total Classics",
    "NextGen N2",
    "5-liter round",
    "5-liter Vase",
    "7-liter Vase",
    "7-liter Vase HQ",
    "10 Conical",
    "10 Conical NG",
    "13 Conical",
    "8 liter round NG",
    "13 NextGen",
    "3 liter round",
]

_YEAR_RE = re.compile(r"^\s*(19|20)\d{2}\s*$")


def _looks_like_year(s: str) -> bool:
    return bool(s and _YEAR_RE.match(str(s)))


def _period_to_label(p: pd.Period) -> str:
    # Sep-25 style labels
    return p.to_timestamp().strftime("%b-%y")


def _safe_key(col: str) -> str:
    # Convert a display column name into a safe HTML field key
    # Example: "CLASSIC HQ" -> "CLASSIC_HQ", "5-liter Vase" -> "5_liter_Vase"
    return (
        col.replace("-", "_")
        .replace(" ", "_")
        .replace("/", "_")
        .replace(".", "")
    )


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
        "designer’s choice",   # curly apostrophe
        "desginer’s choice",   # curly apostrophe misspell
    }:
        return "Designers Choice"

    # Kendal rollups
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

    return s


def _read_master_list(uploaded_file) -> pd.DataFrame:
    """
    Reads 'Master List' and returns a cleaned dataframe with:
      date, customer, city, month (Period), plus numeric bucket columns.
    """
    xls = pd.ExcelFile(uploaded_file)
    df = pd.read_excel(xls, sheet_name="Master List")

    # In your file, row 1 (0-based index) is the true header row
    header_row = df.iloc[1]

    # Data starts at row index 3 (4th visible row)
    data = df.iloc[3:].copy()
    data.columns = header_row

    data = data.rename(columns={"NLD": "date", "Customer": "customer", "City": "city"})

    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data[~data["date"].isna()].copy()

    # Normalize customer names and remove invalid ones
    data["customer"] = data["customer"].apply(normalize_customer_name)
    data = data[data["customer"].astype(str).str.strip() != ""].copy()

    # Only bucket columns that exist
    bucket_cols = [c for c in BUCKET_COLUMNS if c in data.columns]

    # Ensure numeric
    data[bucket_cols] = data[bucket_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    data["month"] = data["date"].dt.to_period("M")

    return data


def build_monthly_totals(data: pd.DataFrame) -> pd.DataFrame:
    """
    Returns monthly totals by bucket type with PeriodIndex 'month'.
    """
    bucket_cols = [c for c in BUCKET_COLUMNS if c in data.columns]
    monthly = data.groupby("month")[bucket_cols].sum().sort_index()
    return monthly


def build_projection_table(
    monthly: pd.DataFrame,
    start_month: pd.Period,
    months_forward: int = 12,
    growth_pct_by_col: Dict[str, float] | None = None,
) -> pd.DataFrame:
    """
    Builds the projection table for months [start_month .. start_month+11]
    from existing monthly totals (which already includes future projections).

    growth_pct_by_col:
      - dict of {bucket_column_name: percent} where percent is e.g. 10 for +10%
      - applied to the forward-looking months only (not prior-year rows)
    """
    growth_pct_by_col = growth_pct_by_col or {}

    # Ensure all required columns exist in monthly (missing -> 0)
    for col in PROJECTION_COLUMNS:
        if col == "Total Classics":
            continue
        if col not in monthly.columns:
            monthly[col] = 0

    rows = []
    idx_periods: List[pd.Period] = [start_month + i for i in range(months_forward)]

    for p in idx_periods:
        if p in monthly.index:
            row = monthly.loc[p].copy()
        else:
            row = pd.Series({c: 0 for c in monthly.columns})

        # Build projection row with the exact layout
        out = {}
        out["Month"] = _period_to_label(p)

        classic_hq = float(row.get("CLASSIC HQ", 0))
        classic = float(row.get("CLASSIC", 0))

        # Apply growth adjustments (per bucket type) to forward-looking rows
        # (User-driven assumptions)
        def apply_growth(col_name: str, value: float) -> float:
            pct = float(growth_pct_by_col.get(col_name, 0) or 0)
            return value * (1.0 + pct / 100.0)

        classic_hq = apply_growth("CLASSIC HQ", classic_hq)
        classic = apply_growth("CLASSIC", classic)

        out["CLASSIC HQ"] = round(classic_hq)
        out["CLASSIC"] = round(classic)
        out["Total Classics"] = round(classic_hq + classic)

        # Map the remaining columns in order
        for col in PROJECTION_COLUMNS:
            if col in {"Month", "CLASSIC HQ", "CLASSIC", "Total Classics"}:
                continue
            base_val = float(row.get(col, 0))
            base_val = apply_growth(col, base_val)
            out[col] = round(base_val)

        rows.append(out)

    proj_df = pd.DataFrame(rows, columns=["Month"] + PROJECTION_COLUMNS)

    # Totals row label (e.g., Total 2025-26)
    end_month = start_month + (months_forward - 1)
    total_label = f"Total {start_month.year}-{str(end_month.year)[-2:]}"

    totals = {"Month": total_label}
    for col in PROJECTION_COLUMNS:
        totals[col] = int(proj_df[col].sum()) if col != "Total Classics" else int(proj_df[col].sum())

    # Prior year totals row (same 12 months one year back)
    prior_periods = [p - 12 for p in idx_periods]
    prior_rows = []
    for p in prior_periods:
        if p in monthly.index:
            prior_rows.append(monthly.loc[p])
        else:
            prior_rows.append(pd.Series({c: 0 for c in monthly.columns}))

    prior_sum = pd.DataFrame(prior_rows).sum(numeric_only=True)

    prior_label = f"Total {start_month.year - 1}-{str(end_month.year - 1)[-2:]}"
    prior_totals = {"Month": prior_label}

    # Prior totals for projection columns
    prior_classic_hq = float(prior_sum.get("CLASSIC HQ", 0))
    prior_classic = float(prior_sum.get("CLASSIC", 0))
    prior_totals["CLASSIC HQ"] = int(round(prior_classic_hq))
    prior_totals["CLASSIC"] = int(round(prior_classic))
    prior_totals["Total Classics"] = int(round(prior_classic_hq + prior_classic))

    for col in PROJECTION_COLUMNS:
        if col in {"CLASSIC HQ", "CLASSIC", "Total Classics"}:
            continue
        prior_totals[col] = int(round(float(prior_sum.get(col, 0))))

    # Append totals rows
    proj_df = pd.concat([proj_df, pd.DataFrame([totals, prior_totals])], ignore_index=True)

    return proj_df


def build_yoy_suggestions(
    monthly: pd.DataFrame,
    start_month: pd.Period,
    months_forward: int = 12,
) -> pd.DataFrame:
    """
    For each projected month and each bucket type, compute YoY delta %
    comparing month vs same month last year (month-12).
    This is used for "suggestions" in the UI.
    """
    needed_cols = [c for c in PROJECTION_COLUMNS if c != "Total Classics"]
    for col in needed_cols:
        if col not in monthly.columns:
            monthly[col] = 0

    rows = []
    for i in range(months_forward):
        p = start_month + i
        p_prev = p - 12

        # If either month missing, we still compute with zeros (safe)
        cur = monthly.loc[p] if p in monthly.index else pd.Series({c: 0 for c in monthly.columns})
        prev = monthly.loc[p_prev] if p_prev in monthly.index else pd.Series({c: 0 for c in monthly.columns})

        for col in needed_cols:
            cur_val = float(cur.get(col, 0))
            prev_val = float(prev.get(col, 0))

            # YoY %: if prev is 0, we avoid division; show blank unless cur is also 0
            if prev_val == 0:
                yoy = None
            else:
                yoy = ((cur_val - prev_val) / prev_val) * 100.0

            rows.append(
                {
                    "Month": _period_to_label(p),
                    "Bucket Type": col,
                    "This Year (current prognosis)": int(round(cur_val)),
                    "Last Year (same month)": int(round(prev_val)),
                    "YoY %": None if yoy is None else round(yoy, 1),
                }
            )

    return pd.DataFrame(rows)


def analyze_prognosis_workbook(uploaded_file):
    """
    Existing metrics + now includes:
      - monthly projection table (12 months forward from current month)
      - YoY suggestions dataframe
    """
    data = _read_master_list(uploaded_file)

    # Bucket columns that exist
    bucket_cols = [c for c in BUCKET_COLUMNS if c in data.columns]
    data["total_buckets"] = data[bucket_cols].sum(axis=1)

    # Existing metrics
    data["month_str"] = data["month"].astype(str)

    per_customer_month = (
        data.groupby(["customer", "month_str"])["total_buckets"]
        .sum()
        .reset_index()
        .sort_values(["customer", "month_str"])
    )

    long = data.melt(
        id_vars=["customer", "city", "month_str"],
        value_vars=bucket_cols,
        var_name="bucket_type",
        value_name="qty",
    )
    long = long[long["qty"] > 0]

    per_customer_city_item = (
        long.groupby(["customer", "city", "bucket_type"])["qty"]
        .sum()
        .reset_index()
        .sort_values(["customer", "city", "bucket_type"])
    )

    per_customer_city_item_month = (
        long.groupby(["customer", "city", "month_str", "bucket_type"])["qty"]
        .sum()
        .reset_index()
        .sort_values(["customer", "city", "month_str", "bucket_type"])
    )

    top_customers = (
        per_customer_month.groupby("customer")["total_buckets"]
        .sum()
        .reset_index()
        .sort_values("total_buckets", ascending=False)
        .head(20)
    )

    # NEW: projections
    monthly = build_monthly_totals(data)

    # Start in current month (server time)
    today = date.today()
    start_month = pd.Period(today, freq="M")

    # Suggestions table (YoY comparisons)
    yoy_suggestions = build_yoy_suggestions(monthly, start_month, months_forward=12)

    # Default projection table (no growth adjustments)
    projection_df = build_projection_table(
        monthly=monthly,
        start_month=start_month,
        months_forward=12,
        growth_pct_by_col={},  # no adjustments by default
    )

    # Provide growth input fields list to the UI
    growth_fields = []
    for col in PROJECTION_COLUMNS:
        if col == "Total Classics":
            continue
        growth_fields.append(
            {
                "col": col,
                "key": _safe_key(col),
            }
        )

    return {
        "per_customer_month": per_customer_month,
        "per_customer_city_item": per_customer_city_item,
        "per_customer_city_item_month": per_customer_city_item_month,
        "top_customers": top_customers,
        "projection_df": projection_df,
        "yoy_suggestions": yoy_suggestions,
        "growth_fields": growth_fields,
        "start_month_label": _period_to_label(start_month),
    }


def rebuild_projection_with_growth(uploaded_file, growth_pct_by_col: Dict[str, float]):
    """
    Recompute projections after the user enters growth % assumptions.
    """
    data = _read_master_list(uploaded_file)
    monthly = build_monthly_totals(data)

    today = date.today()
    start_month = pd.Period(today, freq="M")

    projection_df = build_projection_table(
        monthly=monthly,
        start_month=start_month,
        months_forward=12,
        growth_pct_by_col=growth_pct_by_col,
    )

    yoy_suggestions = build_yoy_suggestions(monthly, start_month, months_forward=12)

    return projection_df, yoy_suggestions, _period_to_label(start_month)
