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



def _build_monthly_totals_master_list_this_year_only(uploaded_file) -> pd.DataFrame:
    """Build monthly totals from the *monthly totals rows* in the 'Master List' sheet.

    Your Master List template is organized in month blocks, where:
      - Row (month_header_row - 1) contains the bucket-type headers (e.g., 'CLASSIC HQ', 'NextGen N2', ...)
      - Row (month_header_row) contains the month label repeated across columns (e.g., 'FEBRUARY')
      - A black separator row appears at the bottom of the month block
      - The *very next row* after that black separator contains **this year's monthly totals** (numbers)
      - The following row typically contains **last year's totals** and has Customer == 'Last Year Totals'

    The projections table must use the *this-year totals row* for each month ahead, and (optionally)
    use the 'Last Year Totals' row to populate (month-12) for YoY comparisons / the final comparison row.
    """
    try:
        wb = openpyxl.load_workbook(uploaded_file, data_only=True)
    except Exception:
        return pd.DataFrame()

    if "Master List" not in wb.sheetnames:
        return pd.DataFrame()

    ws = wb["Master List"]

    # Month parsing helpers (case-insensitive, tolerant of extra text like "FEBRUARY 2026")
    month_name_to_num = {calendar.month_name[i].lower(): i for i in range(1, 13)}
    month_abbr_to_num = {calendar.month_abbr[i].lower(): i for i in range(1, 13)}

    def _parse_month_num(val) -> int | None:
        if not isinstance(val, str):
            return None
        s = val.strip()
        if not s:
            return None
        s = re.sub(r"[^A-Za-z]+", " ", s).strip()
        if not s:
            return None
        token = s.split()[0].lower()
        if token in month_name_to_num:
            return month_name_to_num[token]
        if token in month_abbr_to_num:
            return month_abbr_to_num[token]
        for k, v in month_name_to_num.items():
            if k.startswith(token) or token.startswith(k[:3]):
                return v
        return None

    def _is_month_header(val) -> bool:
        """True only for pure month header labels like 'FEBRUARY' (not 'Feb-26, ...')."""
        if not isinstance(val, str):
            return False
        s = val.strip()
        if not s:
            return False
        if any(ch.isdigit() for ch in s):
            return False
        cleaned = re.sub(r"[^A-Za-z]", "", s).lower()
        if cleaned in month_name_to_num:
            return True
        if cleaned in month_abbr_to_num and len(cleaned) <= 3:
            return True
        return False

    def _is_black_separator_row(row_idx: int) -> bool:
        # In your file, the black separator row uses a solid fill with theme=1.
        c = ws.cell(row_idx, 1)
        try:
            fill = c.fill
            if not fill or fill.patternType != "solid":
                return False
            fg = fill.fgColor
            # Most of your styling is theme-based (not RGB)
            if getattr(fg, "type", None) == "theme" and getattr(fg, "theme", None) == 1:
                # separator row usually has no values in the first columns
                vals = [ws.cell(row_idx, j).value for j in range(1, 9)]
                return all(v is None or (isinstance(v, str) and v.strip() == "") for v in vals)
        except Exception:
            return False
        return False

    def _build_header_map(header_row: int) -> Dict[str, int]:
        hm: Dict[str, int] = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(header_row, c).value
            if isinstance(v, str) and v.strip():
                hm[v.strip()] = c
        return hm

    month_accum: Dict[pd.Period, Dict[str, float]] = {}
    current_year: int | None = None

    # Scan all rows: year markers appear above the month blocks
    for r in range(1, ws.max_row + 1):
        a = ws.cell(r, 1).value

        # Year marker: 2026, 2027, ...
        if isinstance(a, (int, float)) and 2000 <= int(a) <= 2100:
            current_year = int(a)
            continue

        # Month header row: "FEBRUARY" etc in column A
        if not _is_month_header(a) or current_year is None:
            continue

        mnum = _parse_month_num(a)
        if mnum is None:
            continue

        # The bucket headers are on the row above the month header row
        header_row = r - 1
        if header_row < 1:
            continue

        header_map = _build_header_map(header_row)
        bucket_cols = [c for c in BUCKET_COLUMNS if c in header_map]
        if not bucket_cols:
            continue

        # Find the black separator row within a reasonable window below the month header
        sep_row = None
        scan_limit = min(ws.max_row, r + 300)  # month blocks are well under this
        for rr in range(r + 1, scan_limit + 1):
            # Stop early if we hit another month header (something went wrong)
            a2 = ws.cell(rr, 1).value
            if _is_month_header(a2):
                break
            if _is_black_separator_row(rr):
                sep_row = rr
                break

        if sep_row is None:
            continue

        # This year's totals row is the first row after the separator that contains numbers in bucket columns
        totals_row = None
        for rr in range(sep_row + 1, min(ws.max_row, sep_row + 10) + 1):
            any_num = False
            for bc in bucket_cols:
                v = ws.cell(rr, header_map[bc]).value
                if isinstance(v, (int, float)) and v != 0:
                    any_num = True
                    break
            if any_num:
                totals_row = rr
                break

        if totals_row is None:
            continue

        period = pd.Period(f"{current_year}-{mnum:02d}", freq="M")
        month_accum.setdefault(period, {bc: 0.0 for bc in bucket_cols})

        for bc in bucket_cols:
            v = ws.cell(totals_row, header_map[bc]).value
            if isinstance(v, (int, float)):
                month_accum[period][bc] = float(v)
            else:
                month_accum[period][bc] = 0.0

        # If the next row is "Last Year Totals", store it into (period - 12)
        cust_col = header_map.get("Customer", 7)
        last_year_row = totals_row + 1
        cust = ws.cell(last_year_row, cust_col).value
        if isinstance(cust, str) and cust.strip().lower() == "last year totals":
            prev_period = period - 12
            month_accum.setdefault(prev_period, {bc: 0.0 for bc in bucket_cols})
            for bc in bucket_cols:
                v = ws.cell(last_year_row, header_map[bc]).value
                if isinstance(v, (int, float)):
                    month_accum[prev_period][bc] = float(v)
                else:
                    month_accum[prev_period][bc] = 0.0

    if not month_accum:
        return pd.DataFrame()

    df = pd.DataFrame.from_dict(month_accum, orient="index").sort_index()
    df.index.name = "month"

    # Ensure all bucket columns exist
    for c in BUCKET_COLUMNS:
        if c not in df.columns:
            df[c] = 0.0

    return df


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

    monthly = _build_monthly_totals_master_list_this_year_only(uploaded_file)
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
    monthly = _build_monthly_totals_master_list_this_year_only(uploaded_file)
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
    monthly = _build_monthly_totals_master_list_this_year_only(uploaded_file)
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

