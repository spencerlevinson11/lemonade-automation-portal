import re
from datetime import date
from typing import Dict, List

import pandas as pd
import openpyxl
import calendar

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
    # Added (workbook columns Y/Z)
    "8 liter wide NIR grey",
    "10 liter wide NIR grey",

    # NOTE: MAXIMA/Amalia are stored in a single numeric column ("MAXIMA") in the workbook,
    # but are split into the following derived columns using the row's "Bucket Type" label.
    "Maxima Buckets",
    "Maxima Lids",
    "Amalia Buckets",
    "Amalia Lids",
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

    # New columns that should appear in the projections table
    "8 liter wide NIR grey",
    "10 liter wide NIR grey",
    "Maxima Buckets",
    "Maxima Lids",
    "Amalia Buckets",
    "Amalia Lids",
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
    return col.replace("-", "_").replace(" ", "_").replace("/", "_").replace(".", "")


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
        "designer’s choice",  # curly apostrophe
        "desginer’s choice",  # curly apostrophe misspell
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

    # Normalize minor header variations we've seen in the workbook over time
    # (so downstream logic can use stable column names)
    header_renames = {}
    if "10 liter wideNIR grey" in data.columns and "10 liter wide NIR grey" not in data.columns:
        header_renames["10 liter wideNIR grey"] = "10 liter wide NIR grey"
    if "10 liter wideNIR grey " in data.columns and "10 liter wide NIR grey" not in data.columns:
        header_renames["10 liter wideNIR grey "] = "10 liter wide NIR grey"
    if header_renames:
        data = data.rename(columns=header_renames)

    data = data.rename(columns={"NLD": "date", "Customer": "customer", "City": "city"})

    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data[~data["date"].isna()].copy()

    # Normalize customer names and remove invalid ones
    data["customer"] = data["customer"].apply(normalize_customer_name)
    data = data[data["customer"].astype(str).str.strip() != ""].copy()

    # Only bucket columns that exist
    # 1) Coerce any *direct* bucket columns that exist (excludes derived MAXIMA/Amalia columns)
    direct_bucket_cols = [
        c for c in BUCKET_COLUMNS
        if c in data.columns and c not in {"Maxima Buckets", "Maxima Lids", "Amalia Buckets", "Amalia Lids"}
    ]
    if direct_bucket_cols:
        data[direct_bucket_cols] = data[direct_bucket_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    # 2) Split workbook "MAXIMA" numeric column into 4 derived columns based on "Bucket Type" (col AC)
    #    - Maxima Buckets / Maxima Lids / Amalia Buckets / Amalia Lids
    #    - If bucket type indicates "set(s)", count 1 bucket + 1 lid per set
    for c in ["Maxima Buckets", "Maxima Lids", "Amalia Buckets", "Amalia Lids"]:
        if c not in data.columns:
            data[c] = 0

    if "MAXIMA" in data.columns and "Bucket Type" in data.columns:
        maxima_qty = pd.to_numeric(data["MAXIMA"], errors="coerce").fillna(0)
        bt = data["Bucket Type"].astype(str).str.lower().fillna("")

        is_maxima = bt.str.contains("maxima", na=False)
        is_amalia = bt.str.contains("amalia", na=False)
        is_lid = bt.str.contains("lid", na=False)
        is_bucket = bt.str.contains("bucket", na=False)
        is_set = bt.str.contains("set", na=False)

        # Sets: treat as 1 bucket + 1 lid each
        data.loc[is_set & is_maxima, "Maxima Buckets"] += maxima_qty[is_set & is_maxima]
        data.loc[is_set & is_maxima, "Maxima Lids"] += maxima_qty[is_set & is_maxima]

        data.loc[is_set & is_amalia, "Amalia Buckets"] += maxima_qty[is_set & is_amalia]
        data.loc[is_set & is_amalia, "Amalia Lids"] += maxima_qty[is_set & is_amalia]

        # Explicit lids / buckets
        data.loc[(~is_set) & is_maxima & is_lid, "Maxima Lids"] += maxima_qty[(~is_set) & is_maxima & is_lid]
        data.loc[(~is_set) & is_maxima & is_bucket, "Maxima Buckets"] += maxima_qty[(~is_set) & is_maxima & is_bucket]

        data.loc[(~is_set) & is_amalia & is_lid, "Amalia Lids"] += maxima_qty[(~is_set) & is_amalia & is_lid]
        data.loc[(~is_set) & is_amalia & is_bucket, "Amalia Buckets"] += maxima_qty[(~is_set) & is_amalia & is_bucket]

        # Fallbacks if the label doesn't explicitly say "bucket" or "lid"
        data.loc[(~is_set) & is_maxima & (~is_lid) & (~is_bucket), "Maxima Buckets"] += maxima_qty[(~is_set) & is_maxima & (~is_lid) & (~is_bucket)]
        data.loc[(~is_set) & is_amalia & (~is_lid) & (~is_bucket), "Amalia Buckets"] += maxima_qty[(~is_set) & is_amalia & (~is_lid) & (~is_bucket)]

        # Ensure derived cols are numeric
        for c in ["Maxima Buckets", "Maxima Lids", "Amalia Buckets", "Amalia Lids"]:
            data[c] = pd.to_numeric(data[c], errors="coerce").fillna(0)

    data["month"] = data["date"].dt.to_period("M")

    return data



def _build_monthly_totals_from_month_blocks(uploaded_file) -> pd.DataFrame:
    """
    Build monthly totals by *summing the detail lines inside each month block* on the
    'Master List' sheet, instead of relying on the month-total formula rows.

    Why: Excel formula totals often have no cached values in uploaded files, and
    the existing reader ignores non-date rows. This method matches what you see
    on the sheet, and includes projection/adjustment lines even if column A isn't a date.
    """
    wb = openpyxl.load_workbook(uploaded_file, data_only=True)
    if "Master List" not in wb.sheetnames:
        return pd.DataFrame()

    ws = wb["Master List"]

    # Find the real header row (the one that contains NLD + Customer + bucket columns).
    header_row = None
    for r in range(1, 10):
        vals = [ws.cell(r, c).value for c in range(1, 15)]
        if "NLD" in vals and "Customer" in vals:
            header_row = r
            # In this template, row 3 is the true header; row 1 is a banner header.
            # Prefer the lower one if both exist.
            if r < 9:
                # keep searching in case there's another header below
                continue
    if header_row is None:
        # Fallback: assume row 3
        header_row = 3
    else:
        # If we found multiple, take the last one (lowest row)
        # Re-scan to get the last match
        last = None
        for r in range(1, 15):
            vals = [ws.cell(r, c).value for c in range(1, 20)]
            if "NLD" in vals and "Customer" in vals:
                last = r
        header_row = last or header_row

    headers: dict[str, int] = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if isinstance(v, str) and v.strip():
            headers[v.strip()] = c

    bucket_headers = [c for c in BUCKET_COLUMNS if c in headers]
    if not bucket_headers:
        return pd.DataFrame()

    # Month name lookup (case-insensitive)
    month_to_num = {calendar.month_name[i].upper(): i for i in range(1, 13)}

    current_year: int | None = None
    current_month_num: int | None = None

    totals: dict[pd.Period, dict[str, float]] = {}

    # Start scanning after the header row
    r = header_row + 1
    while r <= ws.max_row:
        a = ws.cell(r, 1).value

        # Year row: 2025, 2026, etc.
        if isinstance(a, (int, float)) and 2000 <= int(a) <= 2100:
            current_year = int(a)
            current_month_num = None
            r += 1
            continue

        # Month header row: "January", "FEBRUARY", etc.
        if isinstance(a, str):
            m = a.strip().upper()
            if m in month_to_num:
                current_month_num = month_to_num[m]
                # Initialize this month
                if current_year is not None:
                    period = pd.Period(f"{current_year}-{current_month_num:02d}", freq="M")
                    if period not in totals:
                        totals[period] = {bh: 0.0 for bh in bucket_headers}
                r += 1
                continue

        # If we're in a month block, sum detail lines until we hit the totals/summary area.
        if current_year is not None and current_month_num is not None:
            # Stop conditions for the month block:
            # - another header row ("NLD") appears
            # - next month header appears in col A
            # - we hit the "Last Year Totals" label in customer column (G)
            g = ws.cell(r, headers.get("Customer", 7)).value

            # Detect next month header quickly
            if isinstance(a, str) and a.strip().upper() in month_to_num:
                # will be handled next loop, but keep safe
                r += 1
                continue

            if isinstance(a, str) and a.strip() == "NLD":
                # header row repeats before next month
                r += 1
                continue

            if isinstance(g, str) and g.strip().upper() == "LAST YEAR TOTALS":
                # month summary section starts; skip ahead until next header/month
                r += 1
                continue

            # Sum bucket columns if any numeric values exist on this row.
            period = pd.Period(f"{current_year}-{current_month_num:02d}", freq="M")
            row_has_numbers = False
            for bh in bucket_headers:
                v = ws.cell(r, headers[bh]).value
                if isinstance(v, (int, float)) and v != 0:
                    row_has_numbers = True
                    totals[period][bh] += float(v)

            # If this row is completely blank and we're past a run of blanks, just move on.
            r += 1
            continue

        r += 1

    if not totals:
        return pd.DataFrame()

    monthly = pd.DataFrame.from_dict(totals, orient="index").sort_index()
    monthly.index.name = "month"

    # Ensure any missing bucket columns exist (for downstream display)
    for c in BUCKET_COLUMNS:
        if c not in monthly.columns:
            monthly[c] = 0.0

    return monthly


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

        out = {}
        out["Month"] = _period_to_label(p)

        classic_hq = float(row.get("CLASSIC HQ", 0))
        classic = float(row.get("CLASSIC", 0))

        def apply_growth(col_name: str, value: float) -> float:
            pct = float(growth_pct_by_col.get(col_name, 0) or 0)
            return value * (1.0 + pct / 100.0)

        classic_hq = apply_growth("CLASSIC HQ", classic_hq)
        classic = apply_growth("CLASSIC", classic)

        out["CLASSIC HQ"] = round(classic_hq)
        out["CLASSIC"] = round(classic)
        out["Total Classics"] = round(classic_hq + classic)

        for col in PROJECTION_COLUMNS:
            if col in {"Month", "CLASSIC HQ", "CLASSIC", "Total Classics"}:
                continue
            base_val = float(row.get(col, 0))
            base_val = apply_growth(col, base_val)
            out[col] = round(base_val)

        rows.append(out)

    proj_df = pd.DataFrame(rows, columns=["Month"] + PROJECTION_COLUMNS)

    end_month = start_month + (months_forward - 1)
    total_label = f"Total {start_month.year}-{str(end_month.year)[-2:]}"

    totals = {"Month": total_label}
    for col in PROJECTION_COLUMNS:
        totals[col] = int(proj_df[col].sum())

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

    prior_classic_hq = float(prior_sum.get("CLASSIC HQ", 0))
    prior_classic = float(prior_sum.get("CLASSIC", 0))
    prior_totals["CLASSIC HQ"] = int(round(prior_classic_hq))
    prior_totals["CLASSIC"] = int(round(prior_classic))
    prior_totals["Total Classics"] = int(round(prior_classic_hq + prior_classic))

    for col in PROJECTION_COLUMNS:
        if col in {"CLASSIC HQ", "CLASSIC", "Total Classics"}:
            continue
        prior_totals[col] = int(round(float(prior_sum.get(col, 0))))

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

        cur = monthly.loc[p] if p in monthly.index else pd.Series({c: 0 for c in monthly.columns})
        prev = monthly.loc[p_prev] if p_prev in monthly.index else pd.Series({c: 0 for c in monthly.columns})

        for col in needed_cols:
            cur_val = float(cur.get(col, 0))
            prev_val = float(prev.get(col, 0))

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


# -----------------------------
# NEW: Per-customer delta suggestions (micro-adjustments)
# Compare last year's customer-month-bucket vs this year's prognosis customer-month-bucket
# -----------------------------

def build_customer_delta_suggestions(
    data: pd.DataFrame,
    start_month: pd.Period,
    months_forward: int = 12,
) -> pd.DataFrame:
    """
    Produces rows like:
      Month | Customer | Bucket Type | Prev Year | Projection | Delta

    Where:
      Prev Year   = customer's qty in (month - 12)
      Projection  = customer's qty in (month)  [current prognosis]
      Delta       = Prev Year - Projection
    """
    # IMPORTANT: these are the bucket types you care about in projections (not SUB/HOLD/MAXIMA)
    bucket_types = [c for c in PROJECTION_COLUMNS if c != "Total Classics"]
    bucket_types = [c for c in bucket_types if c in data.columns]

    if not bucket_types:
        return pd.DataFrame(columns=["Month", "Customer", "Bucket Type", "Prev Year", "Projection", "Delta"])

    # Long table at (customer, month, bucket_type)
    long = data.melt(
        id_vars=["customer", "month"],
        value_vars=bucket_types,
        var_name="bucket_type",
        value_name="qty",
    )
    long["qty"] = pd.to_numeric(long["qty"], errors="coerce").fillna(0)

    per = (
        long.groupby(["customer", "month", "bucket_type"])["qty"]
        .sum()
        .reset_index()
    )

    # lookup: (customer, month, bucket_type) -> qty
    lookup = {
        (r["customer"], r["month"], r["bucket_type"]): float(r["qty"])
        for r in per.to_dict("records")
    }

    rows = []
    for i in range(months_forward):
        p = start_month + i
        p_prev = p - 12

        customers_cur = set(per.loc[per["month"] == p, "customer"].unique())
        customers_prev = set(per.loc[per["month"] == p_prev, "customer"].unique())
        customers = customers_cur.union(customers_prev)

        for cust in sorted(customers):
            if not str(cust).strip():
                continue

            for bucket in bucket_types:
                cur_val = lookup.get((cust, p, bucket), 0.0)
                prev_val = lookup.get((cust, p_prev, bucket), 0.0)
                delta = prev_val - cur_val

                if abs(delta) < 0.5:
                    continue

                rows.append(
                    {
                        "Month": _period_to_label(p),
                        "Customer": cust,
                        "Bucket Type": bucket,
                        "Prev Year": int(round(prev_val)),
                        "Projection": int(round(cur_val)),
                        "Delta": int(round(delta)),
                    }
                )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Month", "Customer", "Bucket Type", "Prev Year", "Projection", "Delta"])

    df["abs_delta"] = df["Delta"].abs()
    df = df.sort_values(["abs_delta", "Month", "Customer", "Bucket Type"], ascending=[False, True, True, True]).drop(
        columns=["abs_delta"]
    )

    return df


def analyze_prognosis_workbook(uploaded_file):
    """
    Existing metrics + includes:
      - monthly projection table (12 months forward from current month)
      - YoY suggestions dataframe
      - NEW: per-customer delta suggestions dataframe (micro-adjustments)
    """
    data = _read_master_list(uploaded_file)

    bucket_cols = [c for c in BUCKET_COLUMNS if c in data.columns]
    data["total_buckets"] = data[bucket_cols].sum(axis=1)

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
    long["qty"] = pd.to_numeric(long["qty"], errors="coerce").fillna(0)
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

    monthly = _build_monthly_totals_from_month_blocks(uploaded_file)
    if monthly is None or monthly.empty:
        monthly = build_monthly_totals(data)

    today = date.today()
    start_month = pd.Period(today, freq="M")

    yoy_suggestions = build_yoy_suggestions(monthly, start_month, months_forward=12)

    projection_df = build_projection_table(
        monthly=monthly,
        start_month=start_month,
        months_forward=12,
        growth_pct_by_col={},
    )

    # NEW: customer delta micro-adjustments
    customer_delta_suggestions = build_customer_delta_suggestions(
        data=data,
        start_month=start_month,
        months_forward=12,
    )

    growth_fields = []
    for col in PROJECTION_COLUMNS:
        if col == "Total Classics":
            continue
        growth_fields.append({"col": col, "key": _safe_key(col)})

    return {
        "per_customer_month": per_customer_month,
        "per_customer_city_item": per_customer_city_item,
        "per_customer_city_item_month": per_customer_city_item_month,
        "top_customers": top_customers,
        "projection_df": projection_df,
        "yoy_suggestions": yoy_suggestions,
        "customer_delta_suggestions": customer_delta_suggestions,  # NEW
        "growth_fields": growth_fields,
        "start_month_label": _period_to_label(start_month),
    }


def rebuild_projection_with_growth(uploaded_file, growth_pct_by_col: Dict[str, float]):
    """
    Recompute projections after the user enters growth % assumptions.
    (Keeps original return signature for backwards compatibility.)
    """
    data = _read_master_list(uploaded_file)
    monthly = _build_monthly_totals_from_month_blocks(uploaded_file)
    if monthly is None or monthly.empty:
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


# OPTIONAL helper (non-breaking): use this in views if you want deltas during growth rebuild too.
def rebuild_projection_with_growth_and_customer_deltas(uploaded_file, growth_pct_by_col: Dict[str, float]):
    """
    Same as rebuild_projection_with_growth, but also returns customer_delta_suggestions.
    """
    data = _read_master_list(uploaded_file)
    monthly = _build_monthly_totals_from_month_blocks(uploaded_file)
    if monthly is None or monthly.empty:
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

    customer_delta_suggestions = build_customer_delta_suggestions(
        data=data,
        start_month=start_month,
        months_forward=12,
    )

    return projection_df, yoy_suggestions, _period_to_label(start_month), customer_delta_suggestions

