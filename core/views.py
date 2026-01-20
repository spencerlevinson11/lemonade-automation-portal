from __future__ import annotations

import copy
import os
import re
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from io import BytesIO

import openpyxl
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_COLOR_INDEX

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Sum, Q
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.forms import inlineformset_factory
from django.views.decorators.http import require_POST
from .automations.bucket_metrics import analyze_prognosis_workbook, rebuild_projection_with_growth
from .bol_generation import generate_bol_from_form, generate_bol_from_templates
from .forms import (
    BOLForm,
    PricingUploadForm,
    RpcMasterFormatUploadForm,
    TipEntryForm,
    ProjectPlanEntryForm,
    ScheduleActivityForm,
    ScheduleGlobalNoteForm,
    OrderContainerForm,
    OrderContainerLineForm,
    OrderContainerDocumentForm,
)
from .models import (
    Automation,
    Company,
    PricingCustomer,
    PricingQuoteLine,
    TipEntry,
    ProjectPlanEntry,
    ScheduleActivity,
    ScheduleGlobalNote,
    OrderContainer,
    OrderContainerLine,
    OrderContainerDocument,
)

from .rpc_generation import generate_rpc_from_form
from .rpcforms import RpcOrderForm
from .services.pricing_import import parse_pricing_matrix_csv
from .services.order_tracker import upsert_container_from_rpc_order
from .services.rpc_master_formatter import parse_rpc_order_xlsx, build_master_format_workbook
from .services.ms_graph_excel import (
    GraphError,
    exchange_code_for_token,
    find_insert_row_for_nld,
    get_access_token_for_user,
    get_authorization_url,
    get_range_values,
    get_used_range,
    insert_range_down,
    parse_excel_date,
    resolve_drive_item_from_share_url,
    set_range_fill,
    set_range_values,
    store_token_for_user,
)
from .services.bucket_color_map import get_bucket_type_argb
import datetime as dt

from dateutil.relativedelta import relativedelta




# -----------------------------
# Pricing helpers
# -----------------------------

def normalize_customer_name(raw: str) -> str | None:
    if raw is None:
        return None

    s = str(raw).strip()
    if not s:
        return None

    low = s.lower().strip()

    # Remove the "Los" / LA general pricing customer entirely
    if low in {"los", "los angeles", "los angeles pricing", "la"}:
        return None

    s = re.sub(r"\s+", " ", s).strip()

    # Kendal == Kendal - (remove trailing dash variants)
    s = re.sub(r"\s*-\s*$", "", s).strip()
    low = s.lower()

    mapping = {
        "designers": "Designers Choice",
        "desginers": "Designers Choice",
        "designer's choice": "Designers Choice",
        "designers choice": "Designers Choice",
        "falcon": "Falcon",
        "falcon long": "Falcon",
        "golden": "Golden State",
        "golden state": "Golden State",
        "bandy": "Bandy Ranch",
    }

    if low in mapping:
        return mapping[low]

    return s


def is_euro_customer_name(name: str) -> bool:
    if not name:
        return False

    s = name.strip().lower()
    s = s.replace("'", "")
    s = re.sub(r"\s+", " ", s)

    if s == "pyramid" or s.startswith("pyramid "):
        return True

    if s == "mobis" or s.startswith("mobis "):
        return True
    if s == "mobis flowers" or s.startswith("mobis flowers"):
        return True
    if s.startswith("mobi s"):
        return True

    return False


def get_currency_for_customer_name(name: str):
    if is_euro_customer_name(name):
        return ("EUR", "$")
    return ("USD", "$")


def normalize_destination(customer_name: str, raw_destination: str) -> str:
    if raw_destination is None:
        return ""

    dest = str(raw_destination).strip()
    if not dest:
        return ""

    dest = re.sub(r"\s+", " ", dest).strip()

    # Strip leading "-" artifacts like "- S,C,N" or "-S,C,N"
    dest = re.sub(r"^\-\s*", "", dest).strip()

    cust = (customer_name or "").strip()

    # If destination starts with the customer name, strip it
    if cust:
        cust_re = re.escape(cust)
        dest = re.sub(rf"^{cust_re}\s*-\s*", "", dest, flags=re.IGNORECASE).strip()
        dest = re.sub(rf"^{cust_re}\s+", "", dest, flags=re.IGNORECASE).strip()

    cust_low = cust.lower()

    if cust_low == "designers choice":
        dest = re.sub(r"^choice\s+", "", dest, flags=re.IGNORECASE).strip()

    if cust_low == "golden state":
        dest = re.sub(r"^state\s+", "", dest, flags=re.IGNORECASE).strip()

    if cust_low == "bandy ranch":
        return "Vista"

    # Native fixed destinations
    if cust_low == "native":
        dlow = dest.lower().strip()
        if dlow == "ca":
            return "California"
        if dlow == "co":
            return "Denver"

    dest = re.sub(r"\s+", " ", dest).strip()
    return dest


@login_required
def bucket_projections_zip_export_view(request):
    """
    Downloads BOTH:
      - Bucket_Projections.xlsx
      - Prognosis_With_Projections.xlsx
    as a single ZIP.

    It also ensures the adjusted prognosis is generated fresh at click-time.
    """
    tmp_path = request.session.get("bucket_metrics_tmp_path")
    if not tmp_path or not os.path.exists(tmp_path):
        return HttpResponseForbidden("Your uploaded file has expired. Please upload again.")

    projections_path = request.session.get("bucket_metrics_projection_export_path")
    if not projections_path or not os.path.exists(projections_path):
        return HttpResponseForbidden("No projections export available yet. Open projections first.")

    # Ensure adjusted prognosis exists (generate it if missing)
    prognosis_path = request.session.get("bucket_metrics_adjusted_prognosis_export_path")
    if not prognosis_path or not os.path.exists(prognosis_path):
        try:
            # Baseline projection (from original prognosis)
            with open(tmp_path, "rb") as fh:
                f = BytesIO(fh.read())
            results = analyze_prognosis_workbook(f)
            baseline_projection_df = results.get("projection_df")

            # Adjusted projection = what we're exporting (read it back from the export file)
            adjusted_projection_df = pd.read_excel(projections_path, sheet_name="Projections")

            applied_customer_deltas = _get_applied_customer_deltas(request)

            prognosis_out = _generate_adjusted_prognosis_from_current_session(
                tmp_path=tmp_path,
                user_id=request.user.id,
                baseline_projection_df=baseline_projection_df,
                adjusted_projection_df=adjusted_projection_df,
                applied_customer_deltas=applied_customer_deltas,
            )

            if prognosis_out and os.path.exists(prognosis_out):
                prognosis_path = prognosis_out
                request.session["bucket_metrics_adjusted_prognosis_export_path"] = prognosis_out
                request.session.modified = True
            else:
                return HttpResponseForbidden("Could not generate adjusted prognosis export.")
        except Exception as e:
            return HttpResponseForbidden(f"Could not generate adjusted prognosis export: {e}")

    # Build ZIP
    zip_path = os.path.join(tempfile.gettempdir(), f"bucket_exports_{request.user.id}.zip")
    try:
        if os.path.exists(zip_path):
            os.remove(zip_path)
    except Exception:
        pass

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(projections_path, arcname="Bucket_Projections.xlsx")
        z.write(prognosis_path, arcname="Prognosis_With_Projections.xlsx")

    return FileResponse(
        open(zip_path, "rb"),
        as_attachment=True,
        filename="Bucket_Exports.zip",
    )


def get_or_create_customer_safe(company, name: str):
    """
    Safe under concurrency AND safe inside outer atomic blocks (savepoint).
    """
    try:
        obj = PricingCustomer.objects.get(company=company, name=name)
        return obj, False
    except PricingCustomer.DoesNotExist:
        try:
            with transaction.atomic():
                obj = PricingCustomer.objects.create(company=company, name=name)
            return obj, True
        except IntegrityError:
            obj = PricingCustomer.objects.get(company=company, name=name)
            return obj, False


def upsert_pricing_line_safe(*, company, customer, destination, product_description, price_delivered):
    """
    Safe upsert for PricingQuoteLine unique constraint:
    (company, customer, destination, product_description)
    Uses inner savepoint so IntegrityError doesn't poison outer tx.
    """
    destination = (destination or "").strip()
    product_description = (product_description or "").strip()

    try:
        obj = PricingQuoteLine.objects.get(
            company=company,
            customer=customer,
            destination=destination,
            product_description=product_description,
        )
        created = False
    except PricingQuoteLine.DoesNotExist:
        try:
            with transaction.atomic():
                obj = PricingQuoteLine.objects.create(
                    company=company,
                    customer=customer,
                    destination=destination,
                    product_description=product_description,
                    price_delivered=price_delivered,
                )
            return obj, True
        except IntegrityError:
            obj = PricingQuoteLine.objects.get(
                company=company,
                customer=customer,
                destination=destination,
                product_description=product_description,
            )
            created = False

    if obj.price_delivered != price_delivered:
        obj.price_delivered = price_delivered
        obj.save(update_fields=["price_delivered"])

    return obj, created


@transaction.atomic
def merge_duplicate_pricing_customers(company):
    customers = list(PricingCustomer.objects.filter(company=company).order_by("id"))

    # --- Falcon legacy cleanup: "Beach" -> "Long Beach" ---
    falcon_customers = PricingCustomer.objects.filter(
        company=company,
        name__iexact="Falcon",
    )

    for falcon in falcon_customers:
        bad_lines = PricingQuoteLine.objects.filter(
            company=company,
            customer=falcon,
            destination__iexact="Beach",
        )

        for line in bad_lines:
            existing = PricingQuoteLine.objects.filter(
                company=company,
                customer=falcon,
                destination="Long Beach",
                product_description=line.product_description,
            ).first()

            if existing:
                if existing.price_delivered != line.price_delivered:
                    existing.price_delivered = line.price_delivered
                    existing.save(update_fields=["price_delivered"])
                line.delete()
            else:
                line.destination = "Long Beach"
                line.save(update_fields=["destination"])

    # --- Native legacy cleanup: "CA" -> "California", "CO" -> "Denver" ---
    native_customers = PricingCustomer.objects.filter(
        company=company,
        name__iexact="Native",
    )

    for cust in native_customers:
        lines = PricingQuoteLine.objects.filter(company=company, customer=cust)

        for line in lines:
            dlow = (line.destination or "").strip().lower()

            fixed_dest = None
            if dlow == "ca":
                fixed_dest = "California"
            elif dlow == "co":
                fixed_dest = "Denver"

            if not fixed_dest:
                continue

            if line.destination == fixed_dest:
                continue

            existing = PricingQuoteLine.objects.filter(
                company=company,
                customer=cust,
                destination=fixed_dest,
                product_description=line.product_description,
            ).first()

            if existing:
                if existing.price_delivered != line.price_delivered:
                    existing.price_delivered = line.price_delivered
                    existing.save(update_fields=["price_delivered"])
                line.delete()
            else:
                line.destination = fixed_dest
                line.save(update_fields=["destination"])

    buckets: dict[str, list[PricingCustomer]] = {}
    for c in customers:
        canon = normalize_customer_name(c.name)
        if canon is None:
            buckets.setdefault("__DELETE__", []).append(c)
        else:
            buckets.setdefault(canon, []).append(c)

    for c in buckets.get("__DELETE__", []):
        PricingQuoteLine.objects.filter(company=company, customer=c).delete()
        c.delete()

    for canon_name, cust_list in buckets.items():
        if canon_name == "__DELETE__":
            continue
        if not cust_list:
            continue

        primary = next((c for c in cust_list if (c.name or "").strip() == canon_name), None)
        if primary is None:
            primary = cust_list[0]
            if primary.name != canon_name:
                primary.name = canon_name
                primary.save(update_fields=["name"])

        # Normalize destinations for existing primary lines with collision safety
        for line in PricingQuoteLine.objects.filter(company=company, customer=primary):
            new_dest = normalize_destination(primary.name, line.destination)
            if not new_dest or new_dest == line.destination:
                continue
            try:
                with transaction.atomic():
                    line.destination = new_dest
                    line.save(update_fields=["destination"])
            except IntegrityError:
                existing = PricingQuoteLine.objects.filter(
                    company=company,
                    customer=primary,
                    destination=new_dest,
                    product_description=line.product_description,
                ).first()
                if existing:
                    if existing.price_delivered != line.price_delivered:
                        existing.price_delivered = line.price_delivered
                        existing.save(update_fields=["price_delivered"])
                line.delete()

        duplicates = [c for c in cust_list if c.id != primary.id]

        for dup in duplicates:
            for line in PricingQuoteLine.objects.filter(company=company, customer=dup):
                norm_dest = normalize_destination(primary.name, line.destination)

                existing = PricingQuoteLine.objects.filter(
                    company=company,
                    customer=primary,
                    destination=norm_dest,
                    product_description=line.product_description,
                ).first()

                if existing:
                    if existing.price_delivered != line.price_delivered:
                        existing.price_delivered = line.price_delivered
                        existing.save(update_fields=["price_delivered"])
                    line.delete()
                else:
                    try:
                        with transaction.atomic():
                            line.customer = primary
                            line.destination = norm_dest
                            line.save(update_fields=["customer", "destination"])
                    except IntegrityError:
                        existing2 = PricingQuoteLine.objects.filter(
                            company=company,
                            customer=primary,
                            destination=norm_dest,
                            product_description=line.product_description,
                        ).first()
                        if existing2:
                            if existing2.price_delivered != line.price_delivered:
                                existing2.price_delivered = line.price_delivered
                                existing2.save(update_fields=["price_delivered"])
                        line.delete()

            dup.delete()


# -----------------------------
# Quote-only description overrides (SESSION)
# -----------------------------

def _quote_desc_session_key(company_id: int, customer_id: int) -> str:
    return f"quote_desc_overrides__c{company_id}__cust{customer_id}"


def get_quote_desc_overrides(request, company_id: int, customer_id: int) -> dict:
    """
    Returns { "<line_id>": "New Description", ... } (all string keys for safety).
    """
    key = _quote_desc_session_key(company_id, customer_id)
    data = request.session.get(key, {})
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items() if v is not None}
    return {}


def set_quote_desc_overrides(request, company_id: int, customer_id: int, overrides: dict):
    key = _quote_desc_session_key(company_id, customer_id)
    request.session[key] = {str(k): str(v) for k, v in overrides.items() if v is not None}
    request.session.modified = True


def clear_quote_desc_overrides(request, company_id: int, customer_id: int):
    key = _quote_desc_session_key(company_id, customer_id)
    if key in request.session:
        del request.session[key]
        request.session.modified = True


# -----------------------------
# Prognosis rebuild (with applied tweaks)
# - Adds NEW highlighted lines to "Clean Data (Use for Metrics)"
# - Customer micro adjustments -> "<Customer> Projection"
# - All other deltas -> "General Projection"
# -----------------------------

def _month_label_to_first_of_month(label: str):
    """
    "Jan-26" -> datetime.date(2026, 1, 1)
    Returns None on failure.
    """
    s = (label or "").strip()
    if not s:
        return None
    try:
        dt = pd.to_datetime(s, format="%b-%y")
        return dt.to_pydatetime().date().replace(day=1)
    except Exception:
        return None


def _safe_float(v) -> float:
    try:
        if v is None:
            return 0.0
        if isinstance(v, str) and not v.strip():
            return 0.0
        return float(v)
    except Exception:
        return 0.0


def _normalize_month_str(x) -> str:
    # Always compare months as "Mon-YY" labels
    try:
        if x is None:
            return ""
        s = str(x).strip()
        return s
    except Exception:
        return ""


def _build_month_bucket_df(projection_df: pd.DataFrame) -> pd.DataFrame:
    """
    Input: projection_df with month label in first col, bucket columns thereafter.
    Output: DataFrame indexed by month_label (str), columns are bucket names, floats.
    """
    if projection_df is None or projection_df.empty:
        return pd.DataFrame()

    month_col = projection_df.columns[0]
    df = projection_df.copy()

    df[month_col] = df[month_col].astype(str).map(_normalize_month_str)
    df = df.set_index(month_col, drop=True)

    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    return df


def _append_projection_rows_to_clean_data(
    *,
    workbook_path: str,
    out_path: str,
    customer_rows: list[dict],
    general_rows: list[dict],
):
    wb = openpyxl.load_workbook(workbook_path, data_only=False)

    sheet_name = "Clean Data (Use for Metrics)"
    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(sheet_name)
        # Add default headers
        ws.append(["NLD", "RPC#", "City", "Customer", "Bucket Type", "Quantity", "Delivered"])
    else:
        ws = wb[sheet_name]

    # Map header names -> column index (1-based)
    header_row = 1
    headers = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if v is None:
            continue
        key = str(v).strip()
        if key:
            headers[key] = c

    def col_idx(name: str, fallback: int) -> int:
        return headers.get(name, fallback)

    c_nld = col_idx("NLD", 1)
    c_rpc = col_idx("RPC#", 2)
    c_city = col_idx("City", 3)
    c_cust = col_idx("Customer", 4)
    c_bucket = col_idx("Bucket Type", 5)
    c_qty = col_idx("Quantity", 6)
    c_deliv = col_idx("Delivered", 7)

    # Find the last used row (based on key columns)
    def row_has_data(r: int) -> bool:
        for cc in (c_nld, c_cust, c_bucket, c_qty):
            v = ws.cell(r, cc).value
            if v is not None and str(v).strip() != "":
                return True
        return False

    last = ws.max_row
    while last > 1 and not row_has_data(last):
        last -= 1
    next_row = last + 1

    highlight_fill = PatternFill("solid", fgColor="FFF2CC")  # light yellow
    italic_font = Font(italic=True, color="000000")


    def write_row(r: int, *, nld, customer, bucket_type, quantity):
        ws.cell(r, c_nld).value = nld
        ws.cell(r, c_rpc).value = ""  # blank
        ws.cell(r, c_city).value = ""  # blank
        ws.cell(r, c_cust).value = customer
        ws.cell(r, c_bucket).value = bucket_type
        ws.cell(r, c_qty).value = quantity
        ws.cell(r, c_deliv).value = ""  # blank

        # Highlight + italicize the “projection” line
        for cc in (c_nld, c_rpc, c_city, c_cust, c_bucket, c_qty, c_deliv):
            cell = ws.cell(r, cc)
            cell.fill = highlight_fill
            cell.font = italic_font

    # Write customer micro rows first (so they’re clearly separated)
    for rec in customer_rows:
        nld = rec.get("nld")
        customer = rec.get("customer")
        bucket_type = rec.get("bucket_type")
        qty = rec.get("quantity")

        if nld is None or not customer or not bucket_type:
            continue
        if abs(_safe_float(qty)) < 1e-9:
            continue

        write_row(next_row, nld=nld, customer=customer, bucket_type=bucket_type, quantity=float(qty))
        next_row += 1

    # Write general projection rows
    for rec in general_rows:
        nld = rec.get("nld")
        customer = rec.get("customer")
        bucket_type = rec.get("bucket_type")
        qty = rec.get("quantity")

        if nld is None or not customer or not bucket_type:
            continue
        if abs(_safe_float(qty)) < 1e-9:
            continue

        write_row(next_row, nld=nld, customer=customer, bucket_type=bucket_type, quantity=float(qty))
        next_row += 1

    wb.save(out_path)


def _generate_adjusted_prognosis_from_current_session(
    *,
    tmp_path: str,
    user_id: int,
    baseline_projection_df: pd.DataFrame,
    adjusted_projection_df: pd.DataFrame,
    applied_customer_deltas: dict,
) -> str | None:
    """
    Creates a NEW prognosis workbook by appending highlighted projection rows
    to "Clean Data (Use for Metrics)".

    Customer micro adjustments:
      - One line per (Month, Bucket Type, Customer) with Quantity = delta
      - Customer value: "<Customer> Projection"

    General adjustments (YoY + YoY% + Growth, etc):
      - For each (Month, Bucket Type): total_delta - customer_delta_total
      - Customer value: "General Projection"
    """
    if not tmp_path or not os.path.exists(tmp_path):
        return None

    base_df = _build_month_bucket_df(baseline_projection_df)
    adj_df = _build_month_bucket_df(adjusted_projection_df)

    if base_df.empty or adj_df.empty:
        return None

    # Align (months, buckets)
    all_months = sorted(set(base_df.index).union(set(adj_df.index)))
    all_buckets = sorted(set(base_df.columns).union(set(adj_df.columns)))

    base_aligned = base_df.reindex(index=all_months, columns=all_buckets).fillna(0.0)
    adj_aligned = adj_df.reindex(index=all_months, columns=all_buckets).fillna(0.0)

    total_delta = adj_aligned - base_aligned  # month x bucket

    # Aggregate customer deltas into month+bucket totals
    cust_totals = pd.DataFrame(0.0, index=all_months, columns=all_buckets)

    customer_rows: list[dict] = []
    for key, delta in (applied_customer_deltas or {}).items():
        try:
            month_label, bucket_type, customer_name = key.split("||", 2)
        except ValueError:
            continue

        month_label = str(month_label).strip()
        bucket_type = str(bucket_type).strip()
        customer_name = str(customer_name).strip()

        if not month_label or not bucket_type or not customer_name:
            continue

        d = _safe_float(delta)
        if abs(d) < 1e-9:
            continue

        # Add to aggregate
        if month_label in cust_totals.index and bucket_type in cust_totals.columns:
            cust_totals.loc[month_label, bucket_type] = cust_totals.loc[month_label, bucket_type] + d

        nld = _month_label_to_first_of_month(month_label)
        if nld is None:
            continue

        customer_rows.append(
            {
                "nld": nld,
                "customer": f"{customer_name} Projection",
                "bucket_type": bucket_type,
                "quantity": d,
            }
        )

    # Remaining delta is "general projection" delta
    general_delta = total_delta - cust_totals

    general_rows: list[dict] = []
    for month_label in general_delta.index:
        nld = _month_label_to_first_of_month(month_label)
        if nld is None:
            continue
        for bucket_type in general_delta.columns:
            d = _safe_float(general_delta.loc[month_label, bucket_type])
            if abs(d) < 1e-9:
                continue
            general_rows.append(
                {
                    "nld": nld,
                    "customer": "General Projection",
                    "bucket_type": bucket_type,
                    "quantity": d,
                }
            )

    # Sort rows nicely for readability: Month then Customer then Bucket
    def _sort_key(rec: dict):
        # month sort by actual date
        nld = rec.get("nld")
        cust = rec.get("customer") or ""
        b = rec.get("bucket_type") or ""
        return (nld or pd.Timestamp("1900-01-01").date(), cust, b)

    customer_rows.sort(key=_sort_key)
    general_rows.sort(key=_sort_key)

    out_path = os.path.join(tempfile.gettempdir(), f"prognosis_with_projections_{user_id}.xlsx")
    _append_projection_rows_to_clean_data(
        workbook_path=tmp_path,
        out_path=out_path,
        customer_rows=customer_rows,
        general_rows=general_rows,
    )
    return out_path


# -----------------------------
# Core portal views
# -----------------------------

@login_required
def dashboard(request):
    user = request.user
    company = None

    if user.is_superuser:
        automations = Automation.objects.select_related("company").all()
    else:
        try:
            company = Company.objects.get(owner=user)
        except Company.DoesNotExist:
            company = None

        if company:
            automations = Automation.objects.select_related("company").filter(company=company)
        else:
            automations = Automation.objects.none()

    context = {
        "automations": automations,
        "company": company,
        "is_admin": user.is_superuser,
    }
    return render(request, "core/dashboard.html", context)


def custom_logout(request):
    logout(request)
    return redirect("login")



# -----------------------------
# Microsoft Graph OAuth
# -----------------------------

@login_required
def microsoft_connect_view(request):
    """Start Microsoft OAuth so we can write into the user's OneDrive master workbook."""
    try:
        url = get_authorization_url(state=str(request.user.id))
    except Exception as e:
        messages.error(request, f"Microsoft connect is not configured: {e}")
        return redirect("rpc_master_formatter")
    return redirect(url)


@login_required
def microsoft_callback_view(request):
    """OAuth redirect URI for Microsoft Graph."""
    if request.GET.get("error"):
        err = request.GET.get("error_description") or request.GET.get("error")
        messages.error(request, f"Microsoft authorization failed: {err}")
        return redirect("rpc_master_formatter")

    code = request.GET.get("code")
    if not code:
        messages.error(request, "Missing authorization code from Microsoft.")
        return redirect("rpc_master_formatter")

    try:
        result = exchange_code_for_token(code)
        store_token_for_user(request.user, result)
    except Exception as e:
        messages.error(request, f"Could not save Microsoft connection: {e}")
        return redirect("rpc_master_formatter")

    messages.success(request, "Microsoft connected. You can now insert RPC rows into your OneDrive master.")
    return redirect("rpc_master_formatter")

# -----------------------------
# RPC Order -> Master Spreadsheet Formatter
# -----------------------------

@login_required
@require_http_methods(["GET", "POST"])
def rpc_master_formatter_view(request):
    """
    Upload an RPC order spreadsheet (.xlsx) and return an output workbook
    that matches the row layout of your master spreadsheet.

    Output:
      - headers on row 3
      - data starting row 4
      - one row per bucket type (aggregated totals)
    """
    ms_connected = hasattr(request.user, "ms_graph_token")
    ms_connect_url = reverse("microsoft_connect")

    if request.method == "POST":

        form = RpcMasterFormatUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # With MultipleFileField, this is a list of UploadedFile objects.
            upload_files = form.cleaned_data.get("files") or []
            if not upload_files:
                messages.error(request, "Please choose at least one RPC order spreadsheet.")
                return render(
                    request,
                    "core/rpc_master_formatter.html",
                    {"automation_name": "RPC → Master Formatter", "form": form, "ms_connected": ms_connected, "ms_connect_url": ms_connect_url},
                )

            all_rows = []
            first_meta = None
            for f in upload_files:
                file_bytes = f.read()
                meta, rows = parse_rpc_order_xlsx(file_bytes)
                if first_meta is None:
                    first_meta = meta
                if rows:
                    all_rows.extend(rows)

            # Sort all rows by NLD date (then RPC#, then bucket type) so the output is ready to paste.
            all_rows.sort(
                key=lambda r: (
                    r.nld_date or dt.date(9999, 12, 31),
                    r.rpc_number or 0,
                    (r.bucket_type or "").lower(),
                )
            )

            if not all_rows:
                messages.error(
                    request,
                    "Could not find any line items in the uploaded RPC spreadsheet(s). Make sure they're the standard RPC template.",
                )
                return render(
                    request,
                    "core/rpc_master_formatter.html",
                    {"automation_name": "RPC → Master Formatter", "form": form, "meta": first_meta or {}, "rows": all_rows, "ms_connected": ms_connected, "ms_connect_url": ms_connect_url},
                )

            insert_into_master = request.POST.get("insert_into_master") == "1"
            if insert_into_master and len(upload_files) > 1:
                messages.error(request, "Automatic OneDrive insertion currently supports a single RPC upload at a time. Uncheck the box (or upload one RPC) and generate a combined file instead.")
            elif insert_into_master:
                try:
                    access_token = get_access_token_for_user(request.user)
                    share_url = getattr(settings, "RPC_MASTER_ONEDRIVE_SHARE_URL", None)
                    if not share_url:
                        raise GraphError("RPC_MASTER_ONEDRIVE_SHARE_URL is not set on the server")
                    sheet_name = getattr(settings, "RPC_MASTER_SHEET_NAME", None)
                    ref = resolve_drive_item_from_share_url(access_token, share_url)
                    used = get_used_range(access_token, ref, sheet_name)
                    row_count = used.get("rowCount")
                    if not row_count:
                        # fallback parse from address like Sheet1!A1:AE123
                        addr = (used.get("address") or "")
                        m = re.search(r":\D*(\d+)$", addr)
                        row_count = int(m.group(1)) if m else 0
                    start_row = 4
                    last_row = max(int(row_count or 0), start_row - 1)
                    existing_dates = []
                    if last_row >= start_row:
                        col_vals = get_range_values(access_token, ref, sheet_name, f"A{start_row}:A{last_row}")
                        for row in col_vals:
                            v = row[0] if row else None
                            existing_dates.append(parse_excel_date(v))
                    new_nld = all_rows[0].nld_date
                    if not new_nld:
                        raise GraphError("RPC sheet is missing an NLD date")
                    insert_row = find_insert_row_for_nld(existing_dates, new_nld, start_row)
                    # Insert N blank rows (shift down)
                    for _ in range(len(all_rows)):
                        insert_range_down(access_token, ref, sheet_name, f"A{insert_row}:AE{insert_row}")
                    # Write values + formatting
                    for idx, mr in enumerate(all_rows):
                        rno = insert_row + idx
                        values = [None] * 31
                        values[0] = mr.nld_date.isoformat() if mr.nld_date else None
                        values[1] = mr.nld_week
                        values[3] = int(mr.customer_po) if mr.customer_po and str(mr.customer_po).isdigit() else mr.customer_po
                        values[4] = mr.rpc_number
                        values[5] = mr.city
                        values[6] = mr.customer_name
                        values[7] = mr.mix_flag
                        # quantity into the correct bucket column if known
                        from .services.rpc_master_formatter import BUCKETTYPE_TO_COLUMN, get_transit_times
                        qty_col = BUCKETTYPE_TO_COLUMN.get(mr.bucket_type)
                        if qty_col:
                            values[qty_col - 1] = mr.quantity
                        values[25] = mr.quantity
                        values[26] = mr.bucket_type
                        values[27] = mr.due_by.isoformat() if mr.due_by else None
                        values[28] = mr.due_week
                        avg_days, fast_days = get_transit_times(mr.city)
                        values[29] = avg_days
                        values[30] = fast_days
                        set_range_values(access_token, ref, sheet_name, f"A{rno}:AE{rno}", [values])
                        # light green fills for NLD date + RPC number
                        set_range_fill(access_token, ref, sheet_name, f"A{rno}:A{rno}", "FFE2EFDA")
                        set_range_fill(access_token, ref, sheet_name, f"E{rno}:E{rno}", "FFC6E0B4")
                        bt_fill = get_bucket_type_argb(mr.bucket_type)
                        if bt_fill:
                            set_range_fill(access_token, ref, sheet_name, f"AA{rno}:AA{rno}", bt_fill)
                    messages.success(request, f"Inserted {len(all_rows)} row(s) into your OneDrive master workbook.")
                except Exception as e:
                    messages.error(request, f"Could not insert into OneDrive master: {e}")
            out_bytes = build_master_format_workbook(all_rows)

            # return as downloadable .xlsx
            tmp_path = os.path.join(tempfile.gettempdir(), f"rpc_master_format_{request.user.id}.xlsx")
            with open(tmp_path, "wb") as fh:
                fh.write(out_bytes)

            # If multiple RPCs were uploaded, use a neutral filename.
            rpc_number = (first_meta or {}).get("rpc_number") or "rpc"
            return FileResponse(
                open(tmp_path, "rb"),
                as_attachment=True,
                filename=(f"RPC_{rpc_number}_master_format.xlsx" if len(upload_files) == 1 else "RPC_master_format_combined.xlsx"),
            )
        else:
            # Surface validation issues (e.g., no files selected) so the user
            # doesn't see a "nothing happened" refresh.
            if form.errors:
                messages.error(request, "Please fix the upload form and try again.")
    else:
        form = RpcMasterFormatUploadForm()

    return render(
        request,
        "core/rpc_master_formatter.html",
        {"automation_name": "RPC → Master Formatter", "form": form, "ms_connected": ms_connected, "ms_connect_url": ms_connect_url},
    )


# -----------------------------
# Tip Tracker (Family Automations)
# -----------------------------

@login_required
@require_http_methods(["GET", "POST"])
def tip_tracker_view(request):
    """
    Simple tip tracker:
      - default tip date = today (editable)
      - shift start/end (handles crossing midnight in the model helper)
      - total tips + notes
      - expanded analytics:
          * weekday, start hour, job type
          * weekday×start-hour heatmaps (avg + count)
          * shift length buckets
          * end hour + crossed midnight
          * consistency metrics (median/std/risk score)
          * weekly totals + best/worst + daily trend w/ rolling 30D avg tips/hr
    """
    user = request.user

    # Match your portal pattern: a normal user "owns" exactly one company
    if user.is_superuser:
        company_id = request.GET.get("company_id")
        if company_id:
            company = get_object_or_404(Company, id=company_id)
        else:
            company = Company.objects.order_by("id").first()
    else:
        try:
            company = Company.objects.get(owner=user)
        except Company.DoesNotExist:
            company = None

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    # Two different POSTs hit this route:
    #   1) Add a new entry (main form)
    #   2) Inline edit of a prior entry's tips_total
    if request.method == "POST" and request.POST.get("action") == "update_tip":
        entry_id = request.POST.get("entry_id")
        tips_raw = (request.POST.get("tips_total") or "").strip()

        entry = get_object_or_404(TipEntry, id=entry_id, company=company, user=user)

        try:
            entry.tips_total = Decimal(tips_raw) if tips_raw != "" else Decimal("0")
        except (InvalidOperation, ValueError):
            messages.error(request, "Invalid tip amount.")
            return redirect("tip_tracker")

        entry.save(update_fields=["tips_total"])
        messages.success(request, "Tip amount updated.")
        return redirect("tip_tracker")

    if request.method == "POST":
        form = TipEntryForm(request.POST)
        if form.is_valid():
            TipEntry.objects.create(
                company=company,
                user=user,
                tip_date=form.cleaned_data["tip_date"],
                shift_start=form.cleaned_data["shift_start"],
                shift_end=form.cleaned_data["shift_end"],
                tips_total=form.cleaned_data["tips_total"],
                notes=form.cleaned_data.get("notes", "") or "",
                job_type=form.cleaned_data["job_type"],
            )
            messages.success(request, "Tip entry saved.")
            return redirect("tip_tracker")
    else:
        form = TipEntryForm()

    entries = (
        TipEntry.objects
        .filter(company=company, user=user)
        .order_by("-tip_date", "-created_at")[:60]
    )

    all_time_qs = TipEntry.objects.filter(company=company, user=user)

    grand_total_tips = (
        all_time_qs.aggregate(total=Sum("tips_total")).get("total")
    ) or Decimal("0")

    # All-time average tips per hour = (sum tips) / (sum hours)
    # Duration is derived from shift_start/shift_end, so we compute hours in Python.
    grand_total_hours = sum((e.shift_duration_hours() for e in all_time_qs), 0.0)
    avg_tips_per_hour_all_time = (
        float(grand_total_tips) / grand_total_hours
        if grand_total_hours > 0
        else 0.0
    )

    # Analytics outputs
    weekday_table_html = None
    start_hour_table_html = None
    job_type_table_html = None
    weekday_by_job_table_html = None
    end_hour_table_html = None
    duration_bucket_table_html = None
    heatmap_avg_table_html = None
    heatmap_count_table_html = None
    weekly_table_html = None
    trend_table_html = None
    best_week_summary = None
    worst_week_summary = None
    recommended_shifts_table_html = None


    try:
        qs = TipEntry.objects.filter(company=company, user=user)
        if qs.exists():
            # Build a DataFrame of all entries for analytics.
            rows = []
            for e in qs:
               
                rows.append(
                    {
                        "tip_date": e.tip_date,
                        "weekday": e.tip_date.strftime("%A"),
                        "job_type": e.get_job_type_display(),
                        "start_hour": e.shift_start.hour,
                        "end_hour": e.shift_end.hour,
                        "tips_total": float(e.tips_total),
                        "hours": float(e.shift_duration_hours()),
                        "tips_per_hour": float(e.tips_per_hour()),
                    }
                )

            df = pd.DataFrame(rows)

            # ---- Common formatting helpers ----
            weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            df["weekday"] = pd.Categorical(df["weekday"], categories=weekday_order, ordered=True)

            def add_consistency_columns(g: pd.DataFrame) -> pd.DataFrame:
                """
                Assumes columns:
                  - avg_tips_per_hour
                  - median_tips_per_hour
                  - std_tips_per_hour
                Adds:
                  - risk_score = std / mean
                """
                g = g.copy()
                g["median_tips_per_hour"] = g["median_tips_per_hour"].round(2)
                g["std_tips_per_hour"] = g["std_tips_per_hour"].fillna(0).round(2)
                g["risk_score"] = (
                    g["std_tips_per_hour"]
                    / g["avg_tips_per_hour"].replace({0: pd.NA})
                ).fillna(0).round(2)
                return g

            # -----------------------------
            # 1) By weekday (with consistency metrics)
            # -----------------------------
            wd = (
                df.groupby("weekday", as_index=False)
                .agg(
                    shifts=("tips_total", "count"),
                    total_tips=("tips_total", "sum"),
                    avg_tips=("tips_total", "mean"),
                    avg_hours=("hours", "mean"),
                    avg_tips_per_hour=("tips_per_hour", "mean"),
                    median_tips_per_hour=("tips_per_hour", "median"),
                    std_tips_per_hour=("tips_per_hour", "std"),
                )
                .sort_values("weekday")
            )
            wd = add_consistency_columns(wd)
            for c in ["total_tips", "avg_tips", "avg_hours", "avg_tips_per_hour"]:
                wd[c] = wd[c].round(2)
            weekday_table_html = wd.to_html(classes="table table-striped table-sm", index=False, border=0)

            # -----------------------------
            # 2) Most profitable start times (with consistency metrics)
            # -----------------------------
            sh = (
                df.groupby("start_hour", as_index=False)
                .agg(
                    shifts=("tips_total", "count"),
                    total_tips=("tips_total", "sum"),
                    avg_tips=("tips_total", "mean"),
                    avg_tips_per_hour=("tips_per_hour", "mean"),
                    median_tips_per_hour=("tips_per_hour", "median"),
                    std_tips_per_hour=("tips_per_hour", "std"),
                )
                .sort_values("avg_tips_per_hour", ascending=False)
            )
            sh = add_consistency_columns(sh)
            for c in ["total_tips", "avg_tips", "avg_tips_per_hour"]:
                sh[c] = sh[c].round(2)
            start_hour_table_html = sh.to_html(classes="table table-striped table-sm", index=False, border=0)

            # -----------------------------
            # 3) Breakdown by job type (with consistency metrics)
            # -----------------------------
            jt = (
                df.groupby("job_type", as_index=False)
                .agg(
                    shifts=("tips_total", "count"),
                    total_tips=("tips_total", "sum"),
                    avg_tips=("tips_total", "mean"),
                    avg_hours=("hours", "mean"),
                    avg_tips_per_hour=("tips_per_hour", "mean"),
                    median_tips_per_hour=("tips_per_hour", "median"),
                    std_tips_per_hour=("tips_per_hour", "std"),
                )
                .sort_values("avg_tips_per_hour", ascending=False)
            )
            jt = add_consistency_columns(jt)
            for c in ["total_tips", "avg_tips", "avg_hours", "avg_tips_per_hour"]:
                jt[c] = jt[c].round(2)
            job_type_table_html = jt.to_html(classes="table table-striped table-sm", index=False, border=0)

            # Optional: job type by weekday
            jtw = (
                df.groupby(["weekday", "job_type"], as_index=False)
                .agg(
                    shifts=("tips_total", "count"),
                    avg_tips_per_hour=("tips_per_hour", "mean"),
                    median_tips_per_hour=("tips_per_hour", "median"),
                    std_tips_per_hour=("tips_per_hour", "std"),
                )
                .sort_values(["weekday", "avg_tips_per_hour"], ascending=[True, False])
            )
            jtw = add_consistency_columns(jtw)
            for c in ["avg_tips_per_hour"]:
                jtw[c] = jtw[c].round(2)
            weekday_by_job_table_html = jtw.to_html(classes="table table-striped table-sm", index=False, border=0)

            # -----------------------------
            # 4) Shift length buckets (sweet spot)
            # -----------------------------
            df["hours_clamped"] = df["hours"].clip(lower=0)
            df["duration_bucket"] = pd.cut(
                df["hours_clamped"],
                bins=[-0.001, 3, 5, 7, 1000],
                labels=["0–3", "3–5", "5–7", "7+"],
            )
            dur = (
                df.groupby("duration_bucket", as_index=False)
                .agg(
                    shifts=("tips_total", "count"),
                    total_tips=("tips_total", "sum"),
                    avg_tips=("tips_total", "mean"),
                    avg_hours=("hours", "mean"),
                    avg_tips_per_hour=("tips_per_hour", "mean"),
                    median_tips_per_hour=("tips_per_hour", "median"),
                    std_tips_per_hour=("tips_per_hour", "std"),
                )
            )
            dur = add_consistency_columns(dur)
            for c in ["total_tips", "avg_tips", "avg_hours", "avg_tips_per_hour"]:
                dur[c] = dur[c].round(2)
            duration_bucket_table_html = dur.to_html(classes="table table-striped table-sm", index=False, border=0)

            # -----------------------------
            # 5) Start vs end time + crossed midnight
            # -----------------------------
            eh = (
                df.groupby("end_hour", as_index=False)
                .agg(
                    shifts=("tips_total", "count"),
                    avg_tips_per_hour=("tips_per_hour", "mean"),
                    median_tips_per_hour=("tips_per_hour", "median"),
                    std_tips_per_hour=("tips_per_hour", "std"),
                )
                .sort_values("avg_tips_per_hour", ascending=False)
            )
            eh = add_consistency_columns(eh)
            for c in ["avg_tips_per_hour"]:
                eh[c] = eh[c].round(2)
            end_hour_table_html = eh.to_html(classes="table table-striped table-sm", index=False, border=0)


            # -----------------------------
            # 6) Heatmap: weekday × start hour (avg tips/hr + count)
            # -----------------------------
            heat_avg = (
                df.pivot_table(
                    index="weekday",
                    columns="start_hour",
                    values="tips_per_hour",
                    aggfunc="mean",
                )
                .reindex(weekday_order)
            )
            heat_cnt = (
                df.pivot_table(
                    index="weekday",
                    columns="start_hour",
                    values="tips_per_hour",
                    aggfunc="count",
                )
                .reindex(weekday_order)
            )
            heat_avg = heat_avg.round(2)

            if len(heat_avg.columns) > 0:
                heat_avg = heat_avg.reindex(sorted(heat_avg.columns), axis=1)
                heat_cnt = heat_cnt.reindex(sorted(heat_cnt.columns), axis=1)

            heatmap_avg_table_html = heat_avg.to_html(classes="table table-striped table-sm", border=0)
            heatmap_count_table_html = heat_cnt.to_html(classes="table table-striped table-sm", border=0)
            # -----------------------------
            # 6b) Recommended shifts (weekday × start hour)
            # -----------------------------
            MIN_SHIFTS_PER_CELL = 3   # bump to 5 later once you have more data
            TOP_N = 10

            # Flatten the pivot tables to rows: weekday, start_hour, avg_tips_per_hour, shifts
            rec = (
                heat_avg.stack(dropna=False)
                .rename("avg_tips_per_hour")
                .reset_index()
                .merge(
                    heat_cnt.stack(dropna=False).rename("shifts").reset_index(),
                    on=["weekday", "start_hour"],
                    how="left",
                )
            )

            # Clean + filter
            rec["shifts"] = rec["shifts"].fillna(0).astype(int)
            rec = rec.dropna(subset=["avg_tips_per_hour"])
            rec = rec[rec["shifts"] >= MIN_SHIFTS_PER_CELL].copy()

            # Sort best first, and format start_hour nicely
            rec = rec.sort_values(["avg_tips_per_hour", "shifts"], ascending=[False, False]).head(TOP_N)
            rec["avg_tips_per_hour"] = rec["avg_tips_per_hour"].round(2)
            rec["start_time"] = rec["start_hour"].astype(int).astype(str).str.zfill(2) + ":00"

            # Display columns
            rec_display = rec[["weekday", "start_time", "shifts", "avg_tips_per_hour"]].rename(
                columns={
                    "weekday": "Weekday",
                    "start_time": "Start",
                    "shifts": "Shifts (sample)",
                    "avg_tips_per_hour": "Avg tips/hr",
                }
            )

            recommended_shifts_table_html = rec_display.to_html(
                classes="table table-striped table-sm",
                index=False,
                border=0,
            )

            # -----------------------------
            # 7) Weekly totals + best/worst week + rolling averages (7-shift, 30-day)
            # -----------------------------
            df2 = df.copy()
            df2["tip_date"] = pd.to_datetime(df2["tip_date"])
            df2 = df2.sort_values(["tip_date", "start_hour"], ascending=[True, True])

            # Weekly summary (week starts Monday)
            df2["week_start"] = df2["tip_date"].dt.to_period("W-MON").apply(lambda p: p.start_time.date())
            wk = (
                df2.groupby("week_start", as_index=False)
                .agg(
                    shifts=("tips_total", "count"),
                    total_tips=("tips_total", "sum"),
                    avg_tips_per_hour=("tips_per_hour", "mean"),
                    avg_hours=("hours", "mean"),
                )
                .sort_values("week_start", ascending=False)
            )
            for c in ["total_tips", "avg_tips_per_hour", "avg_hours"]:
                wk[c] = wk[c].round(2)
            weekly_table_html = wk.to_html(classes="table table-striped table-sm", index=False, border=0)

            if not wk.empty:
                best_row = wk.sort_values(["avg_tips_per_hour", "total_tips"], ascending=[False, False]).iloc[0]
                worst_row = wk.sort_values(["avg_tips_per_hour", "total_tips"], ascending=[True, True]).iloc[0]
                best_week_summary = {
                    "week_start": str(best_row["week_start"]),
                    "shifts": int(best_row["shifts"]),
                    "total_tips": float(best_row["total_tips"]),
                    "avg_tips_per_hour": float(best_row["avg_tips_per_hour"]),
                }
                worst_week_summary = {
                    "week_start": str(worst_row["week_start"]),
                    "shifts": int(worst_row["shifts"]),
                    "total_tips": float(worst_row["total_tips"]),
                    "avg_tips_per_hour": float(worst_row["avg_tips_per_hour"]),
                }

            # Rolling averages (daily)
            daily = (
                df2.groupby(df2["tip_date"].dt.date, as_index=False)
                .agg(
                    date=("tip_date", "first"),
                    shifts=("tips_total", "count"),
                    total_tips=("tips_total", "sum"),
                    avg_tips_per_hour=("tips_per_hour", "mean"),
                )
                .sort_values("date")
            )
            daily["avg_tips_per_hour"] = daily["avg_tips_per_hour"].round(2)
            daily["total_tips"] = daily["total_tips"].round(2)
            daily["rolling_30_day_avg_tips_per_hour"] = (
                daily.set_index("date")["avg_tips_per_hour"]
                .rolling("30D", min_periods=1)
                .mean()
                .round(2)
                .values
            )

            trend = daily.tail(45).copy()
            trend["date"] = trend["date"].dt.date.astype(str)
            trend_table_html = trend.to_html(classes="table table-striped table-sm", index=False, border=0)

    except Exception as e:
        messages.warning(request, f"Analytics error: {e}")

    context = {
        "automation_name": "Tip Tracker",
        "company": company,
        "form": form,
        "entries": entries,
        "grand_total_tips": grand_total_tips,
        "avg_tips_per_hour_all_time": avg_tips_per_hour_all_time,
        "weekday_table_html": weekday_table_html,
        "start_hour_table_html": start_hour_table_html,
        "job_type_table_html": job_type_table_html,
        "weekday_by_job_table_html": weekday_by_job_table_html,
        "end_hour_table_html": end_hour_table_html,
        "duration_bucket_table_html": duration_bucket_table_html,
        "heatmap_avg_table_html": heatmap_avg_table_html,
        "heatmap_count_table_html": heatmap_count_table_html,
        "weekly_table_html": weekly_table_html,
        "trend_table_html": trend_table_html,
        "best_week_summary": best_week_summary,
        "worst_week_summary": worst_week_summary,
        "recommended_shifts_table_html": recommended_shifts_table_html,

    }
    return render(request, "core/tip_tracker.html", context)


@login_required
@require_http_methods(["GET"])
def tip_tracker_export_excel(request):
    """
    Export a polished Excel tip report that also prints cleanly to PDF.
    Includes:
      - Summary (grand total, averages)
      - Recent entries table (all entries for the user/company)
      - Key analytics tables already computed in tip_tracker_view (weekday/job type)
    """
    user = request.user

    company_id = request.GET.get("company_id")
    if company_id:
        company = get_object_or_404(Company, pk=company_id)
    else:
        company = Company.objects.first()

    # Safety: enforce company scoping if your app requires it
    # If you have per-user company access rules, apply them here.
    if company is None:
        return HttpResponseForbidden("No company found.")

    all_time_qs = TipEntry.objects.filter(company=company, user=user).order_by("tip_date", "created_at")

    # Build a DataFrame for nicer grouping/analytics
    rows = []
    for e in all_time_qs:
        duration = e.shift_duration_hours()
        tips_total = float(e.tips_total or 0)
        tips_hr = float(e.tips_per_hour() or 0)
        rows.append({
            "Date": e.tip_date,
            "Job type": e.get_job_type_display() if hasattr(e, "get_job_type_display") else getattr(e, "job_type", ""),
            "Start": e.shift_start,
            "End": e.shift_end,
            "Hours": duration,
            "Tips": tips_total,
            "Tips/hr": tips_hr,
            "Notes": e.notes or "",
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["Weekday"] = pd.to_datetime(df["Date"]).dt.day_name()

    grand_total = Decimal("0")
    try:
        grand_total = (all_time_qs.aggregate(total=Sum("tips_total")).get("total")) or Decimal("0")
    except Exception:
        grand_total = Decimal("0")

    avg_tips = float(df["Tips"].mean()) if not df.empty else 0.0
    avg_tips_hr = float(df["Tips/hr"].mean()) if not df.empty else 0.0
    total_shifts = int(len(df)) if not df.empty else 0

    # --- Workbook ---
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tip Report"

    # Print/PDF friendly page setup
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_margins.left = 0.35
    ws.page_margins.right = 0.35
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5

    thin = Side(style="thin", color="1F2937")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    header_fill = PatternFill("solid", fgColor="F3F4F6")  # light gray
    accent_fill = PatternFill("solid", fgColor="FACC15")

    title_font = Font(size=18, bold=True, color="FACC15")
    h_font = Font(size=11, bold=True, color="000000")
    normal_font = Font(size=11, color="000000")

    muted_font = Font(size=10, color="000000")


    # Background columns (make sheet look consistent with your dark UI)
    # Excel doesn't support whole-sheet background well, so we style headers + key cells.

    # --- Title / Summary ---
    ws["A1"] = "Tip Tracker Report"
    ws["A1"].font = title_font
    ws.merge_cells("A1:H1")

    ws["A2"] = f"Company: {company.name}"
    ws["A2"].font = muted_font
    ws.merge_cells("A2:H2")

    ws["A3"] = f"Generated: {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %I:%M %p')}"
    ws["A3"].font = muted_font
    ws.merge_cells("A3:H3")

    # KPI row
    kpis = [
        ("Grand total tips", float(grand_total)),
        ("Total shifts", total_shifts),
        ("Avg tips/shift", avg_tips),
        ("Avg tips/hr", avg_tips_hr),
    ]
    start_row = 5
    col = 1
    for label, value in kpis:
        c1 = ws.cell(row=start_row, column=col, value=label)
        c2 = ws.cell(row=start_row + 1, column=col, value=value)
        ws.merge_cells(start_row=start_row, start_column=col, end_row=start_row, end_column=col+1)
        ws.merge_cells(start_row=start_row+1, start_column=col, end_row=start_row+1, end_column=col+1)

        c1 = ws.cell(row=start_row, column=col)
        c2 = ws.cell(row=start_row + 1, column=col)

        c1.fill = header_fill
        c1.font = h_font
        c1.alignment = Alignment(horizontal="center", vertical="center")
        c1.border = border

        c2.fill = PatternFill("solid", fgColor="111827")
        c2.font = Font(size=14, bold=True, color="E5E7EB")
        c2.number_format = "#,##0.00" if isinstance(value, float) else "0"
        c2.alignment = Alignment(horizontal="center", vertical="center")
        c2.border = border

        # apply border to merged partner cell
        ws.cell(row=start_row, column=col+1).border = border
        ws.cell(row=start_row+1, column=col+1).border = border

        col += 2

    current_row = start_row + 3

    # --- Entries table ---
    ws["A{}".format(current_row)] = "Entries"
    ws["A{}".format(current_row)].font = Font(size=13, bold=True, color="E5E7EB")
    ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=8)
    current_row += 1

    columns = ["Date", "Weekday", "Job type", "Start", "End", "Hours", "Tips", "Tips/hr", "Notes"]
    # We'll print Notes last but keep width reasonable by truncating.
    columns = ["Date", "Weekday", "Job type", "Start", "End", "Hours", "Tips", "Tips/hr", "Notes"]

    # Header row
    for ci, name in enumerate(columns, start=1):
        cell = ws.cell(row=current_row, column=ci, value=name)
        cell.fill = header_fill
        cell.font = h_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    current_row += 1

    def _safe_note(s: str, max_len: int = 120) -> str:
        s = (s or "").strip()
        if len(s) <= max_len:
            return s
        return s[:max_len-1] + "…"

    # Data rows
    if df.empty:
        ws.cell(row=current_row, column=1, value="No entries yet.").font = muted_font
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=9)
        current_row += 2
    else:
        for _, r in df.iterrows():
            values = [
                r.get("Date"),
                r.get("Weekday"),
                r.get("Job type"),
                r.get("Start"),
                r.get("End"),
                float(r.get("Hours") or 0),
                float(r.get("Tips") or 0),
                float(r.get("Tips/hr") or 0),
                _safe_note(str(r.get("Notes") or "")),
            ]
            for ci, v in enumerate(values, start=1):
                cell = ws.cell(row=current_row, column=ci, value=v)
                cell.font = normal_font
                cell.border = border
                cell.alignment = Alignment(horizontal="left" if ci in (3,9) else "center", vertical="top", wrap_text=(ci==9))
                if ci in (6,7,8):
                    cell.number_format = "#,##0.00"
            current_row += 1
        current_row += 2

    # Freeze panes at the entries header
    ws.freeze_panes = "A{}".format(start_row + 3)

    # Column widths (PDF friendly)
    widths = {
        1: 11,  # Date
        2: 12,  # Weekday
        3: 22,  # Job type
        4: 9,   # Start
        5: 9,   # End
        6: 9,   # Hours
        7: 10,  # Tips
        8: 10,  # Tips/hr
        9: 40,  # Notes
    }
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w

    # --- Quick analytics (if data exists) ---
    if not df.empty:
        # Weekday summary
        ws["A{}".format(current_row)] = "Weekday summary"
        ws["A{}".format(current_row)].font = Font(size=13, bold=True, color="E5E7EB")
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=4)
        current_row += 1

        wd = (
            df.groupby("Weekday")
              .agg(shifts=("Tips", "count"), total_tips=("Tips", "sum"), avg_tips=("Tips", "mean"), avg_tips_hr=("Tips/hr", "mean"))
              .reset_index()
        )
        wd_cols = ["Weekday", "shifts", "total_tips", "avg_tips", "avg_tips_hr"]
        for ci, name in enumerate(wd_cols, start=1):
            cell = ws.cell(row=current_row, column=ci, value=name.replace("_", " ").title())
            cell.fill = header_fill
            cell.font = h_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border
        current_row += 1

        for _, r in wd.iterrows():
            vals = [r["Weekday"], int(r["shifts"]), float(r["total_tips"]), float(r["avg_tips"]), float(r["avg_tips_hr"])]
            for ci, v in enumerate(vals, start=1):
                cell = ws.cell(row=current_row, column=ci, value=v)
                cell.font = normal_font
                cell.border = border
                cell.alignment = Alignment(horizontal="center", vertical="center")
                if ci >= 3:
                    cell.number_format = "#,##0.00"
            current_row += 1

        current_row += 2

        # Job type summary
        ws["A{}".format(current_row)] = "Job type summary"
        ws["A{}".format(current_row)].font = Font(size=13, bold=True, color="E5E7EB")
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=4)
        current_row += 1

        jt = (
            df.groupby("Job type")
              .agg(shifts=("Tips", "count"), total_tips=("Tips", "sum"), avg_tips=("Tips", "mean"), avg_tips_hr=("Tips/hr", "mean"))
              .reset_index()
              .sort_values("avg_tips_hr", ascending=False)
        )
        jt_cols = ["Job type", "shifts", "total_tips", "avg_tips", "avg_tips_hr"]
        for ci, name in enumerate(jt_cols, start=1):
            cell = ws.cell(row=current_row, column=ci, value=name.replace("_", " ").title())
            cell.fill = header_fill
            cell.font = h_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border
        current_row += 1

        for _, r in jt.iterrows():
            vals = [r["Job type"], int(r["shifts"]), float(r["total_tips"]), float(r["avg_tips"]), float(r["avg_tips_hr"])]
            for ci, v in enumerate(vals, start=1):
                cell = ws.cell(row=current_row, column=ci, value=v)
                cell.font = normal_font
                cell.border = border
                cell.alignment = Alignment(horizontal="left" if ci == 1 else "center", vertical="center")
                if ci >= 3:
                    cell.number_format = "#,##0.00"
            current_row += 1

        current_row += 1

    # Set print area to used range
    ws.print_area = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"

    # Repeat header rows (title + company + generated + blank + KPI labels/values)
    ws.print_title_rows = "1:6"

    out = BytesIO()
    wb.save(out)
    out.seek(0)

    filename = f"tip_report_{company.name}_{timezone.localtime(timezone.now()).strftime('%Y%m%d_%H%M')}.xlsx"
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)

    return FileResponse(
        out,
        as_attachment=True,
        filename=filename,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@login_required
@require_http_methods(["GET", "POST"])
def tip_entry_delete_view(request, entry_id: int):
    entry = get_object_or_404(TipEntry, id=entry_id)

    # Permission check: owner of company (or superuser), and must match user+company
    if not (
        request.user.is_superuser
        or (entry.company and entry.company.owner == request.user)
    ):
        return HttpResponseForbidden("You are not allowed to delete this entry.")

    # Optional: also restrict to same user who created it (recommended for Hailey’s use case)
    if not request.user.is_superuser and entry.user_id != request.user.id:
        return HttpResponseForbidden("You are not allowed to delete this entry.")

    if request.method == "POST":
        confirm = (request.POST.get("confirm") or "").strip().lower()
        if confirm == "yes":
            entry.delete()
            messages.success(request, "Entry deleted.")
            return redirect("tip_tracker")

        messages.info(request, "Deletion cancelled.")
        return redirect("tip_tracker")

    # GET = warning/confirmation page
    return render(request, "core/tip_entry_confirm_delete.html", {"entry": entry})

# -----------------------------
# YoY apply/unapply logic
# - Apply YoY: replace projection cell with prev-year absolute value
# - Optional extra %: applied on top of that replacement value
# - Customer micro-deltas: add/subtract absolute units to a month+bucket
# -----------------------------

def _yoy_session_key(month_label: str, col_name: str) -> str:
    return f"{month_label}||{col_name}"


def _get_applied_yoy_overrides(request) -> dict:
    """
    Stores absolute replacement values:
      { "Dec-25||CLASSIC HQ": 1234.0, ... }
    """
    data = request.session.get("bucket_metrics_applied_yoy", {})
    if not isinstance(data, dict):
        return {}

    cleaned: dict[str, float] = {}
    for k, v in data.items():
        try:
            cleaned[str(k)] = float(v)
        except Exception:
            continue
    return cleaned


def _set_applied_yoy_overrides(request, overrides: dict) -> None:
    request.session["bucket_metrics_applied_yoy"] = {str(k): float(v) for k, v in overrides.items()}
    request.session.modified = True


def _get_applied_yoy_pct_overrides(request) -> dict:
    """
    Stores extra percent to apply AFTER YoY replacement:
      { "Dec-25||CLASSIC HQ": 0.10, ... }  # 10% as decimal
    """
    data = request.session.get("bucket_metrics_applied_yoy_pct", {})
    if not isinstance(data, dict):
        return {}

    cleaned: dict[str, float] = {}
    for k, v in data.items():
        try:
            cleaned[str(k)] = float(v)
        except Exception:
            continue
    return cleaned


def _set_applied_yoy_pct_overrides(request, overrides: dict) -> None:
    request.session["bucket_metrics_applied_yoy_pct"] = {str(k): float(v) for k, v in overrides.items()}
    request.session.modified = True


def _apply_yoy_overrides_to_projection(projection_df, applied_overrides: dict):
    """
    Replace the projection value with the stored absolute value.
    """
    if projection_df is None or projection_df.empty:
        return projection_df

    month_col = projection_df.columns[0]
    df = projection_df.copy()

    for key, target_value in (applied_overrides or {}).items():
        try:
            month_label, col_name = key.split("||", 1)
        except ValueError:
            continue

        if col_name not in df.columns:
            continue

        mask = df[month_col].astype(str) == str(month_label)
        if not mask.any():
            continue

        try:
            df.loc[mask, col_name] = float(target_value)
        except Exception:
            continue

    # round to whole numbers for display
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).round(0).astype(int)

    return df


def _apply_yoy_pct_overrides_to_projection(projection_df, yoy_pct_overrides: dict):
    """
    Applies extra % AFTER YoY replacement:
      value := value * (1 + pct)
    Only touches the specific (month, bucket) cells in yoy_pct_overrides.
    """
    if projection_df is None or projection_df.empty:
        return projection_df

    month_col = projection_df.columns[0]
    df = projection_df.copy()

    for key, pct in (yoy_pct_overrides or {}).items():
        try:
            month_label, col_name = key.split("||", 1)
        except ValueError:
            continue

        if col_name not in df.columns:
            continue

        mask = df[month_col].astype(str) == str(month_label)
        if not mask.any():
            continue

        try:
            pct = float(pct)
        except Exception:
            continue

        cur = pd.to_numeric(df.loc[mask, col_name], errors="coerce").fillna(0)
        df.loc[mask, col_name] = cur * (1.0 + pct)

    # round to whole numbers for display
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).round(0).astype(int)

    return df


# -----------------------------
# Customer micro-delta overrides (SESSION)
# -----------------------------

def _cust_delta_session_key(month_label: str, col_name: str, customer_name: str) -> str:
    return f"{month_label}||{col_name}||{customer_name}"


def _get_applied_customer_deltas(request) -> dict:
    """
    Stores per-customer additive deltas (absolute units):
      { "Jan-26||CLASSIC||Falcon Farms": 20000.0, ... }
    """
    data = request.session.get("bucket_metrics_applied_customer_deltas", {})
    if not isinstance(data, dict):
        return {}

    cleaned: dict[str, float] = {}
    for k, v in data.items():
        try:
            cleaned[str(k)] = float(v)
        except Exception:
            continue
    return cleaned


def _set_applied_customer_deltas(request, overrides: dict) -> None:
    request.session["bucket_metrics_applied_customer_deltas"] = {str(k): float(v) for k, v in overrides.items()}
    request.session.modified = True


def _apply_customer_deltas_to_projection(projection_df, applied_customer_deltas: dict):
    """
    Aggregate per-customer keys to month+bucket totals and add them to the projection table.
    """
    if projection_df is None or projection_df.empty:
        return projection_df

    month_col = projection_df.columns[0]
    df = projection_df.copy()

    agg: dict[tuple[str, str], float] = {}
    for key, delta in (applied_customer_deltas or {}).items():
        try:
            month_label, col_name, _customer = key.split("||", 2)
        except ValueError:
            continue
        try:
            d = float(delta)
        except Exception:
            continue
        agg[(str(month_label), str(col_name))] = agg.get((str(month_label), str(col_name)), 0.0) + d

    for (month_label, col_name), delta_total in agg.items():
        if col_name not in df.columns:
            continue

        mask = df[month_col].astype(str) == str(month_label)
        if not mask.any():
            continue

        cur = pd.to_numeric(df.loc[mask, col_name], errors="coerce").fillna(0)
        df.loc[mask, col_name] = cur + float(delta_total)

    # round to whole numbers for display
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).round(0).astype(int)

    return df


@login_required
@require_http_methods(["GET", "POST"])
def bucket_projections_view(request):
    tmp_path = request.session.get("bucket_metrics_tmp_path")
    if not tmp_path or not os.path.exists(tmp_path):
        return redirect("bucket_metrics")

    context = {
        "automation_name": "Bucket Projections",
        "error": None,
        "results_available": True,
        "applied_yoy": [],
        "applied_customer_deltas": [],
    }

    with open(tmp_path, "rb") as fh:
        f = BytesIO(fh.read())

    results = analyze_prognosis_workbook(f)

    reverse_map = {item["key"]: item["col"] for item in results.get("growth_fields", [])}
    request.session["bucket_metrics_growth_reverse_map"] = reverse_map
    request.session["bucket_metrics_growth_fields"] = results.get("growth_fields", [])
    request.session.modified = True

    applied_overrides = _get_applied_yoy_overrides(request)
    applied_yoy_pct = _get_applied_yoy_pct_overrides(request)
    applied_customer_deltas = _get_applied_customer_deltas(request)

    # Baseline = what the file said BEFORE any tweaks
    baseline_projection_df = results.get("projection_df")

    if request.method == "POST":
        action = request.POST.get("action") or ""

        # Apply: set projection cell to prev_year absolute value
        if action == "apply_yoy":
            month_label = (request.POST.get("month_label") or "").strip()
            col_name = (request.POST.get("col_name") or "").strip()
            prev_year_str = (request.POST.get("prev_year") or "").strip()

            target_value: float | None = None
            if prev_year_str:
                try:
                    target_value = float(prev_year_str)
                except Exception:
                    target_value = None

            if month_label and col_name and target_value is not None:
                key = _yoy_session_key(month_label, col_name)
                applied_overrides[key] = float(target_value)
                _set_applied_yoy_overrides(request, applied_overrides)

            return redirect("bucket_projections")

        # Unapply: remove override and any extra pct, revert to computed projection
        if action == "unapply_yoy":
            month_label = (request.POST.get("month_label") or "").strip()
            col_name = (request.POST.get("col_name") or "").strip()
            if month_label and col_name:
                key = _yoy_session_key(month_label, col_name)

                changed = False
                if key in applied_overrides:
                    applied_overrides.pop(key, None)
                    changed = True
                if key in applied_yoy_pct:
                    applied_yoy_pct.pop(key, None)
                    changed = True

                if changed:
                    _set_applied_yoy_overrides(request, applied_overrides)
                    _set_applied_yoy_pct_overrides(request, applied_yoy_pct)

            return redirect("bucket_projections")

        # Clear all YoY (and extra %)
        if action == "clear_all_yoy":
            _set_applied_yoy_overrides(request, {})
            _set_applied_yoy_pct_overrides(request, {})
            return redirect("bucket_projections")

        # Set extra % on top of an already-applied YoY cell
        if action == "set_yoy_pct":
            month_label = (request.POST.get("month_label") or "").strip()
            col_name = (request.POST.get("col_name") or "").strip()
            pct_raw = (request.POST.get("yoy_extra_pct") or "").strip()

            pct_val = 0.0
            try:
                pct_val = float(pct_raw) if pct_raw else 0.0
            except Exception:
                pct_val = 0.0

            if pct_val > 1.0:
                pct_val = pct_val / 100.0

            if month_label and col_name:
                key = _yoy_session_key(month_label, col_name)
                if key in applied_overrides:
                    if abs(pct_val) < 1e-12:
                        applied_yoy_pct.pop(key, None)
                    else:
                        applied_yoy_pct[key] = pct_val
                    _set_applied_yoy_pct_overrides(request, applied_yoy_pct)

            return redirect("bucket_projections")

        # -----------------------------
        # Customer delta apply/unapply
        # -----------------------------
        if action == "apply_customer_delta":
            month_label = (request.POST.get("month_label") or "").strip()
            col_name = (request.POST.get("col_name") or "").strip()
            customer_name = (request.POST.get("customer_name") or "").strip()
            delta_str = (request.POST.get("delta") or "").strip()

            delta_val: float | None = None
            if delta_str:
                try:
                    delta_val = float(delta_str)
                except Exception:
                    delta_val = None

            if month_label and col_name and customer_name and delta_val is not None:
                key = _cust_delta_session_key(month_label, col_name, customer_name)
                applied_customer_deltas[key] = float(delta_val)
                _set_applied_customer_deltas(request, applied_customer_deltas)

            return redirect("bucket_projections")

        if action == "unapply_customer_delta":
            month_label = (request.POST.get("month_label") or "").strip()
            col_name = (request.POST.get("col_name") or "").strip()
            customer_name = (request.POST.get("customer_name") or "").strip()

            if month_label and col_name and customer_name:
                key = _cust_delta_session_key(month_label, col_name, customer_name)
                if key in applied_customer_deltas:
                    applied_customer_deltas.pop(key, None)
                    _set_applied_customer_deltas(request, applied_customer_deltas)

            return redirect("bucket_projections")

        if action == "clear_all_customer_deltas":
            _set_applied_customer_deltas(request, {})
            return redirect("bucket_projections")

        # Growth rebuild
        if action == "apply_growth":
            growth_pct_by_safe_key = {}
            for key, val in request.POST.items():
                if key.startswith("growth__"):
                    safe_key = key.replace("growth__", "")
                    try:
                        pct = float(val) if str(val).strip() else 0.0
                    except ValueError:
                        pct = 0.0
                    growth_pct_by_safe_key[safe_key] = pct

            rev = request.session.get("bucket_metrics_growth_reverse_map", {})
            growth_real = {}
            for safe_key, pct in growth_pct_by_safe_key.items():
                real = rev.get(safe_key)
                if real:
                    growth_real[real] = pct

            with open(tmp_path, "rb") as fh2:
                f2 = BytesIO(fh2.read())

            projection_df, yoy_suggestions_df, start_month_label = rebuild_projection_with_growth(f2, growth_real)

            projection_df = _apply_yoy_overrides_to_projection(projection_df, applied_overrides)
            projection_df = _apply_yoy_pct_overrides_to_projection(projection_df, applied_yoy_pct)
            projection_df = _apply_customer_deltas_to_projection(projection_df, applied_customer_deltas)

            export_path = os.path.join(tempfile.gettempdir(), f"bucket_projections_{request.user.id}.xlsx")
            with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
                projection_df.to_excel(writer, index=False, sheet_name="Projections")
            request.session["bucket_metrics_projection_export_path"] = export_path
            request.session.modified = True

            results["projection_df"] = projection_df
            results["yoy_suggestions"] = yoy_suggestions_df
            results["start_month_label"] = start_month_label

    # Apply YoY replacement + extra % + customer deltas on GET too
    projection_df = results["projection_df"]
    projection_df = _apply_yoy_overrides_to_projection(projection_df, applied_overrides)
    projection_df = _apply_yoy_pct_overrides_to_projection(projection_df, applied_yoy_pct)
    projection_df = _apply_customer_deltas_to_projection(projection_df, applied_customer_deltas)

    # Export projections
    export_path = os.path.join(tempfile.gettempdir(), f"bucket_projections_{request.user.id}.xlsx")
    with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
        projection_df.to_excel(writer, index=False, sheet_name="Projections")
    request.session["bucket_metrics_projection_export_path"] = export_path
    request.session.modified = True

    # NEW: Build adjusted prognosis workbook (appends highlighted projection lines)
    try:
        prognosis_out = _generate_adjusted_prognosis_from_current_session(
            tmp_path=tmp_path,
            user_id=request.user.id,
            baseline_projection_df=baseline_projection_df,
            adjusted_projection_df=projection_df,
            applied_customer_deltas=applied_customer_deltas,
        )
        if prognosis_out:
            request.session["bucket_metrics_adjusted_prognosis_export_path"] = prognosis_out
            request.session.modified = True
    except Exception:
        # Don't break the page if prognosis generation fails
        pass

    # Build YoY records
    yoy_df = results.get("yoy_suggestions")
    yoy_records = []

    def _to_number_or_none(v):
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except Exception:
            pass
        try:
            return float(v)
        except Exception:
            return None

    if yoy_df is not None and not yoy_df.empty:
        for r in yoy_df.to_dict("records"):
            month_label = str(r.get("Month", "")).strip()
            col_name = str(r.get("Bucket Type", "")).strip()

            current_val = _to_number_or_none(r.get("This Year (current prognosis)"))
            prev_val = _to_number_or_none(r.get("Last Year (same month)"))
            pct_val = _to_number_or_none(r.get("YoY %"))

            key = _yoy_session_key(month_label, col_name)
            is_applied = key in applied_overrides

            extra_pct = float(applied_yoy_pct.get(key, 0.0))
            yoy_records.append(
                {
                    "month_label": month_label,
                    "col_name": col_name,
                    "prev_year": "" if prev_val is None else int(round(prev_val)),
                    "current_year": "" if current_val is None else int(round(current_val)),
                    "pct": "" if pct_val is None else float(pct_val),
                    "applied": is_applied,
                    "extra_pct": extra_pct,
                    "extra_pct_display": extra_pct * 100.0,
                }
            )

    applied_list = []
    for k, target in applied_overrides.items():
        try:
            m, c = k.split("||", 1)
        except ValueError:
            continue

        pct = float(applied_yoy_pct.get(k, 0.0))
        if abs(pct) > 1e-12:
            applied_list.append(f"{m} • {c} (set to {int(round(float(target)))}, +{pct * 100:.1f}%)")
        else:
            applied_list.append(f"{m} • {c} (set to {int(round(float(target)))})")

    applied_customer_list = []
    for k, delta in applied_customer_deltas.items():
        try:
            m, c, cust = k.split("||", 2)
        except ValueError:
            continue
        sign = "+" if float(delta) >= 0 else ""
        applied_customer_list.append(f"{m} • {c} • {cust} ({sign}{int(round(float(delta)))})")

    # (Optional) Customer delta suggestion records:
    # Safely renders empty if not present.
    customer_delta_records = []
    cust_df = results.get("customer_delta_suggestions")  # df from bucket_metrics.py

    def _month_sort_key(label: str):
        # "Jan-26" -> Period for correct chronological sorting
        try:
            return pd.Period(pd.to_datetime(str(label), format="%b-%y"), freq="M")
        except Exception:
            return pd.Period("1900-01", freq="M")

    if cust_df is not None and isinstance(cust_df, pd.DataFrame) and not cust_df.empty:
        df = cust_df.copy()

        # Sort by Customer first, then Month, then Bucket Type, then largest delta
        df["_month_sort"] = df["Month"].astype(str).map(_month_sort_key)
        df["_abs_delta"] = pd.to_numeric(df.get("Delta", 0), errors="coerce").fillna(0).abs()

        df = df.sort_values(
            by=["Customer", "_month_sort", "Bucket Type", "_abs_delta"],
            ascending=[True, True, True, False],
            kind="mergesort",
        )

        for r in df.to_dict("records"):
            month_label = str(r.get("Month", "")).strip()
            customer_name = str(r.get("Customer", "")).strip()
            col_name = str(r.get("Bucket Type", "")).strip()

            prev_val = _to_number_or_none(r.get("Prev Year"))
            proj_val = _to_number_or_none(r.get("Projection"))
            delta_val = _to_number_or_none(r.get("Delta"))

            key = _cust_delta_session_key(month_label, col_name, customer_name)
            is_applied = key in applied_customer_deltas

            customer_delta_records.append(
                {
                    "month_label": month_label,
                    "customer_name": customer_name,
                    "col_name": col_name,
                    "prev_year": "" if prev_val is None else int(round(prev_val)),
                    "projection": "" if proj_val is None else int(round(proj_val)),
                    "delta": "" if delta_val is None else int(round(delta_val)),
                    "applied": is_applied,
                }
            )

    context.update(
        {
            "start_month_label": results.get("start_month_label"),
            "projection_table": projection_df.to_html(classes="table table-striped table-sm", index=False, border=0),
            "growth_fields": results.get("growth_fields", []),
            "yoy_records": yoy_records,
            "applied_yoy": applied_list,
            # NEW:
            "customer_delta_records": customer_delta_records,
            "applied_customer_deltas": applied_customer_list,
            # NEW: you can use this in the template to show a download button
            "adjusted_prognosis_available": bool(request.session.get("bucket_metrics_adjusted_prognosis_export_path")),
        }
    )

    return render(request, "core/bucket_projections.html", context)


@login_required
def bucket_projections_export_view(request):
    tmp_path = request.session.get("bucket_metrics_tmp_path")
    if not tmp_path or not os.path.exists(tmp_path):
        return HttpResponseForbidden("Your uploaded file has expired. Please upload again.")

    export_path = request.session.get("bucket_metrics_projection_export_path")
    if not export_path or not os.path.exists(export_path):
        return HttpResponseForbidden("No export available yet. Open projections first.")

    # Ensure adjusted prognosis exists (or re-generate it) at export time
    try:
        # Baseline projection (from original prognosis)
        with open(tmp_path, "rb") as fh:
            f = BytesIO(fh.read())
        results = analyze_prognosis_workbook(f)
        baseline_projection_df = results.get("projection_df")

        # Current adjusted projection (what we're exporting)
        adjusted_projection_df = pd.read_excel(export_path, sheet_name="Projections")

        applied_customer_deltas = _get_applied_customer_deltas(request)

        prognosis_out = _generate_adjusted_prognosis_from_current_session(
            tmp_path=tmp_path,
            user_id=request.user.id,
            baseline_projection_df=baseline_projection_df,
            adjusted_projection_df=adjusted_projection_df,
            applied_customer_deltas=applied_customer_deltas,
        )
        if prognosis_out:
            request.session["bucket_metrics_adjusted_prognosis_export_path"] = prognosis_out
            request.session.modified = True
    except Exception as e:
        # IMPORTANT: don't swallow silently; at least show a message
        messages.warning(request, f"Could not generate adjusted prognosis: {e}")

    return FileResponse(
        open(export_path, "rb"),
        as_attachment=True,
        filename="Bucket_Projections.xlsx",
    )


# NEW: download the prognosis workbook with highlighted projection lines added
@login_required
def bucket_adjusted_prognosis_export_view(request):
    export_path = request.session.get("bucket_metrics_adjusted_prognosis_export_path")
    if not export_path or not os.path.exists(export_path):
        return HttpResponseForbidden("No adjusted prognosis export available yet. Open projections first.")

    return FileResponse(
        open(export_path, "rb"),
        as_attachment=True,
        filename="Prognosis_With_Projections.xlsx",
    )


@login_required
@require_http_methods(["GET", "POST"])
def run_automation(request, pk):
    automation = get_object_or_404(Automation.objects.select_related("company"), pk=pk)

    if not (request.user.is_superuser or automation.company.owner == request.user):
        return HttpResponseForbidden("You are not allowed to run this automation.")

    name_normalized = (automation.name or "").strip().lower()

    # --- Branch: Tip Tracker ---
    if name_normalized in {"tip tracker", "tips tracker", "tip tracking", "tips"}:
        return redirect("tip_tracker")

    # --- Branch: RPC Order Generator ---
    # In production the Automation.name may vary ("Retriever RPC Order", "RPC Order Generator", etc.).
    # Use a robust match so the RPC form + Order Tracker auto-add always runs.
    rpc_name_hits = {
        "retriever rpc order",
        "rpc order",
        "rpc order generator",
        "rpc generator",
        "rpc order form",
    }

    is_rpc_order_automation = (
        name_normalized in rpc_name_hits
        or (
            "rpc" in name_normalized
            and ("order" in name_normalized or "generator" in name_normalized)
        )
    )

    if is_rpc_order_automation:
        if request.method == "POST":
            form = RpcOrderForm(request.POST)
            if form.is_valid():
                files, outlook_status = generate_rpc_from_form(form.cleaned_data)

                # Auto-create/update an Order Tracker container from this RPC order
                ot_company = automation.company
                if not request.user.is_superuser:
                    owned_company = Company.objects.filter(owner=request.user).order_by("id").first()
                    if owned_company and (ot_company is None or ot_company.owner_id != request.user.id):
                        ot_company = owned_company

                try:
                    upsert_container_from_rpc_order(
                        company=ot_company,
                        created_by=request.user,
                        rpc_data=form.cleaned_data,
                    )
                except Exception as e:
                    # Don't fail the RPC download if tracking import fails
                    messages.warning(request, f"RPC generated, but Order Tracker auto-add failed: {e}")

                automation.last_run_at = timezone.now()
                automation.save(update_fields=["last_run_at"])

                first_file = files[0]
                status_text = outlook_status or "No Outlook status returned."
                messages.success(request, f"RPC generated. {status_text}")

                return FileResponse(
                    open(first_file, "rb"),
                    as_attachment=True,
                    filename=first_file.name,
                )
        else:
            form = RpcOrderForm()

        return render(request, "core/rpc_order_form.html", {"automation": automation, "form": form})

    # --- Branch: Bucket Metrics ---
    if "bucket metrics" in name_normalized:
        return redirect("bucket_metrics")

    # --- Branch: Pricing upload workflow ---
    if "pricing quote" in name_normalized or "pricing" in name_normalized:
        return redirect("pricing_upload")

    # --- Branch: RPC -> Master Sheet Formatter ---
    # The dashboard launches automations via /automations/<pk>/run/. Our Automation model
    # doesn't have a slug/route field in admin, so we dispatch by a robust name match.
    # This prevents falling through to the default BOL screen.
    is_rpc_master_formatter = (
        ("rpc" in name_normalized)
        and (
            "master" in name_normalized
            or "formatter" in name_normalized
            or "reformatter" in name_normalized
            or "master sheet" in name_normalized
        )
    )

    if is_rpc_master_formatter:
        return redirect("rpc_master_formatter")


    # --- Branch: Project Planner ---
    if "project planner" in name_normalized or "project planning" in name_normalized:
        return redirect("project_planner")

    # --- Branch: Schedule Dashboard ---
    if "schedule" in name_normalized or "calendar" in name_normalized:
        return redirect("schedule_dashboard")

    # --- Branch: Order Tracker ---
    if "order tracker" in name_normalized or "container tracker" in name_normalized or "order tracking" in name_normalized:
        return redirect("order_tracker")


    # --- Default: BOL generator ---
    if request.method == "POST":
        form = BOLForm(request.POST)
        if form.is_valid():
            output_path = generate_bol_from_form(form.cleaned_data)

            automation.last_run_at = timezone.now()
            automation.save(update_fields=["last_run_at"])

            messages.success(request, f"Generated BOL for {automation.company.name}")

            return FileResponse(
                open(output_path, "rb"),
                as_attachment=True,
                filename=output_path.name,
            )
    else:
        form = BOLForm()

    return render(request, "core/run_bol.html", {"automation": automation, "form": form})


@login_required


@login_required
def project_planner_view(request):
    """
    Project Planner:
      - Create + edit project ideas with cost/time/difficulty/risk/priority
      - Sort by priority/cost/time/difficulty/risk/name/created/updated
    """
    user = request.user

    if user.is_superuser:
        company = Company.objects.order_by("id").first()
    else:
        try:
            company = Company.objects.get(owner=user)
        except Company.DoesNotExist:
            company = None

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    # Sorting
    sort_key = (request.GET.get("sort") or "priority").strip().lower()
    sort_dir = (request.GET.get("dir") or "desc").strip().lower()

    sort_map = {
        "priority": "priority_level",
        "priority_level": "priority_level",
        "cost": "estimated_cost",
        "estimated_cost": "estimated_cost",
        "time": "estimated_time_hours",
        "hours": "estimated_time_hours",
        "estimated_time_hours": "estimated_time_hours",
        "difficulty": "estimated_difficulty",
        "estimated_difficulty": "estimated_difficulty",
        "risk": "risk_factor",
        "risk_factor": "risk_factor",
        "name": "project_name",
        "project_name": "project_name",
        "created": "created_at",
        "created_at": "created_at",
        "updated": "updated_at",
        "updated_at": "updated_at",
    }

    field = sort_map.get(sort_key, "priority_level")
    prefix = "-" if sort_dir != "asc" else ""
    ordering = [f"{prefix}{field}", "-updated_at", "-created_at"]

    projects = ProjectPlanEntry.objects.filter(company=company, completed=False).order_by(*ordering)
    completed_projects = ProjectPlanEntry.objects.filter(company=company, completed=True).order_by('-completed_at', '-updated_at')

    # Load edit instance (via ?edit=<id>)
    edit_id = request.GET.get("edit")
    instance = None
    if edit_id:
        instance = get_object_or_404(ProjectPlanEntry, id=edit_id, company=company)

    if request.method == "POST":
        entry_id = request.POST.get("entry_id") or None
        if entry_id:
            instance = get_object_or_404(ProjectPlanEntry, id=entry_id, company=company)

        form = ProjectPlanEntryForm(request.POST, instance=instance)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = company
            obj.user = user
            obj.save()
            messages.success(request, "Project saved.")
            return redirect("project_planner")
    else:
        form = ProjectPlanEntryForm(instance=instance)
        if instance:
            form.initial["entry_id"] = instance.id

    context = {
        "automation_name": "Project Planner",
        "company": company,
        "projects": projects,
        "completed_projects": completed_projects,
        "form": form,
        "sort": sort_key,
        "dir": sort_dir,
        "edit_instance": instance,
    }
    return render(request, "core/project_planner.html", context)


@login_required
@require_http_methods(["GET", "POST"])


@login_required
@require_http_methods(["POST"])
def project_plan_complete_view(request, pk: int):
    user = request.user

    if user.is_superuser:
        company = Company.objects.order_by("id").first()
    else:
        try:
            company = Company.objects.get(owner=user)
        except Company.DoesNotExist:
            company = None

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    project = get_object_or_404(ProjectPlanEntry, id=pk, company=company)

    if not project.completed:
        project.completed = True
        project.completed_at = timezone.now()
        project.save(update_fields=["completed", "completed_at", "updated_at"])
        messages.success(request, f"Completed: {project.project_name}")
    else:
        messages.info(request, f"Already completed: {project.project_name}")

    return redirect("project_planner")


def project_plan_delete_view(request, pk: int):
    user = request.user

    if user.is_superuser:
        company = Company.objects.order_by("id").first()
    else:
        try:
            company = Company.objects.get(owner=user)
        except Company.DoesNotExist:
            company = None

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    project = get_object_or_404(ProjectPlanEntry, id=pk, company=company)

    if request.method == "POST":
        project.delete()
        messages.success(request, "Project deleted.")
        return redirect("project_planner")

    return render(request, "core/project_plan_confirm_delete.html", {"project": project, "automation_name": "Project Planner"})


def bucket_metrics_view(request, automation_id=None):
    context = {
        "automation_name": "Bucket Metrics from Prognosis Spreadsheet",
        "results_available": False,
    }

    # Step 2: Apply growth (no re-upload)
    if request.method == "POST" and request.POST.get("action") == "apply_growth":
        tmp_path = request.session.get("bucket_metrics_tmp_path")

        if not tmp_path or not os.path.exists(tmp_path):
            context["error"] = "Your uploaded file has expired. Please upload the spreadsheet again."
            return render(request, "core/bucket_metrics.html", context)

        growth_pct_by_safe_key = {}
        for key, val in request.POST.items():
            if key.startswith("growth__"):
                safe_key = key.replace("growth__", "")
                try:
                    pct = float(val) if str(val).strip() else 0.0
                except ValueError:
                    pct = 0.0
                growth_pct_by_safe_key[safe_key] = pct

        reverse_map = request.session.get("bucket_metrics_growth_reverse_map", {})
        growth_real = {}
        for safe_key, pct in growth_pct_by_safe_key.items():
            real = reverse_map.get(safe_key)
            if real:
                growth_real[real] = pct

        try:
            with open(tmp_path, "rb") as fh:
                f = BytesIO(fh.read())

            projection_df, yoy_suggestions, start_month_label = rebuild_projection_with_growth(f, growth_real)

            context.update(
                {
                    "results_available": True,
                    "start_month_label": start_month_label,
                    "projection_table": projection_df.to_html(classes="table table-striped table-sm", index=False, border=0),
                    "yoy_suggestions_table": yoy_suggestions.to_html(classes="table table-striped table-sm", index=False, border=0),
                    "growth_fields": request.session.get("bucket_metrics_growth_fields", []),
                    "top_customers_table": request.session.get("bucket_metrics_top_customers_table"),
                    "per_customer_month_table": request.session.get("bucket_metrics_per_customer_month_table"),
                    "per_customer_city_item_table": request.session.get("bucket_metrics_per_customer_city_item_table"),
                    "per_customer_city_item_month_table": request.session.get("bucket_metrics_per_customer_city_item_month_table"),
                }
            )
        except Exception as e:
            context["error"] = f"Error rebuilding projections: {e}"

        context["projections_url"] = "bucket_projections"
        return render(request, "core/bucket_metrics.html", context)

    # Step 1: Initial upload
    if request.method == "POST" and request.FILES.get("file"):
        excel_file = request.FILES["file"]

        try:
            suffix = os.path.splitext(excel_file.name or "")[1] or ".xlsx"

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                for chunk in excel_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            request.session["bucket_metrics_tmp_path"] = tmp_path
            request.session["bucket_metrics_uploaded_name"] = excel_file.name

            with open(tmp_path, "rb") as fh:
                f = BytesIO(fh.read())

            results = analyze_prognosis_workbook(f)

            reverse_map = {item["key"]: item["col"] for item in results.get("growth_fields", [])}
            request.session["bucket_metrics_growth_reverse_map"] = reverse_map
            request.session["bucket_metrics_growth_fields"] = results.get("growth_fields", [])

            top_customers_html = results["top_customers"].to_html(classes="table table-striped table-sm", index=False, border=0)
            per_customer_month_html = results["per_customer_month"].to_html(classes="table table-striped table-sm", index=False, border=0)
            per_customer_city_item_html = results["per_customer_city_item"].to_html(classes="table table-striped table-sm", index=False, border=0)
            per_customer_city_item_month_html = results["per_customer_city_item_month"].to_html(classes="table table-striped table-sm", index=False, border=0)

            request.session["bucket_metrics_top_customers_table"] = top_customers_html
            request.session["bucket_metrics_per_customer_month_table"] = per_customer_month_html
            request.session["bucket_metrics_per_customer_city_item_table"] = per_customer_city_item_html
            request.session["bucket_metrics_per_customer_city_item_month_table"] = per_customer_city_item_month_html
            request.session.modified = True

            context.update(
                {
                    "results_available": True,
                    "start_month_label": results.get("start_month_label"),
                    "top_customers_table": top_customers_html,
                    "per_customer_month_table": per_customer_month_html,
                    "per_customer_city_item_table": per_customer_city_item_html,
                    "per_customer_city_item_month_table": per_customer_city_item_month_html,
                    "projection_table": results["projection_df"].to_html(classes="table table-striped table-sm", index=False, border=0),
                    "yoy_suggestions_table": results["yoy_suggestions"].to_html(classes="table table-striped table-sm", index=False, border=0),
                    "growth_fields": results.get("growth_fields", []),
                }
            )
        except Exception as e:
            context["error"] = f"Error reading file: {e}"

        return render(request, "core/bucket_metrics.html", context)

    return render(request, "core/bucket_metrics.html", context)


def _get_company_for_request(request):
    user = request.user

    if user.is_superuser:
        company_id = request.GET.get("company_id")
        if company_id:
            return get_object_or_404(Company, id=company_id)
        return Company.objects.order_by("id").first()

    try:
        return Company.objects.get(owner=user)
    except Company.DoesNotExist:
        return None


# -----------------------------
# Pricing workflow
# -----------------------------

@login_required
@require_http_methods(["GET", "POST"])
def pricing_upload_view(request):
    company = _get_company_for_request(request)
    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    if request.method == "POST":
        form = PricingUploadForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data["file"]

            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                for chunk in f.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            rows = parse_pricing_matrix_csv(tmp_path)

            existing_meta = {}
            for line in PricingQuoteLine.objects.select_related("customer").filter(company=company):
                key = (
                    (line.customer.name or "").strip(),
                    (line.destination or "").strip(),
                    (line.product_description or "").strip(),
                )
                existing_meta[key] = {
                    "pallet_quantity_pieces": line.pallet_quantity_pieces,
                    "include_in_quote": line.include_in_quote,
                }

            PricingQuoteLine.objects.filter(company=company).delete()

            normalized_rows = {}
            for r in rows:
                canon_customer = normalize_customer_name(r.get("customer", ""))
                if canon_customer is None:
                    continue

                dest_raw = r.get("destination", "")
                prod = (r.get("product_description") or "").strip()
                price = r["price_delivered"]

                norm_dest = normalize_destination(canon_customer, dest_raw)

                key = (canon_customer, norm_dest, prod)
                normalized_rows[key] = price

            created_lines = 0
            updated_lines = 0
            created_customers = 0

            for (canon_customer, norm_dest, prod), price in normalized_rows.items():
                customer_obj, cust_created = get_or_create_customer_safe(company, canon_customer)
                if cust_created:
                    created_customers += 1

                meta = existing_meta.get((canon_customer, norm_dest, prod), None)
                pallet_qty = meta["pallet_quantity_pieces"] if meta else 0
                include = meta["include_in_quote"] if meta else True

                PricingQuoteLine.objects.create(
                    company=company,
                    customer=customer_obj,
                    destination=norm_dest,
                    product_description=prod,
                    price_delivered=price,
                    pallet_quantity_pieces=pallet_qty,
                    include_in_quote=include,
                )

                created_lines += 1

            merge_duplicate_pricing_customers(company)

            messages.success(
                request,
                f"Imported pricing: {created_customers} customers, {created_lines} new lines, {updated_lines} updated lines.",
            )
            return redirect("pricing_customer_list")

    else:
        form = PricingUploadForm()

    return render(request, "core/pricing_upload.html", {"form": form, "company": company})


@login_required
def pricing_customer_list_view(request):
    company = _get_company_for_request(request)
    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    customers = PricingCustomer.objects.filter(company=company).order_by("name")

    return render(
        request,
        "core/pricing_customer_list.html",
        {
            "company": company,
            "customers": customers,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def pricing_customer_edit_view(request, customer_id):
    """
    Permanent edits (saved): pallet_quantity_pieces, include_in_quote
    Temporary quote-only edits (session only): product description override
    """
    company = _get_company_for_request(request)
    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    customer = get_object_or_404(PricingCustomer, id=customer_id, company=company)

    lines_qs = PricingQuoteLine.objects.filter(company=company, customer=customer).order_by(
        "destination", "product_description"
    )

    currency_code, currency_symbol = get_currency_for_customer_name(customer.name)

    overrides = get_quote_desc_overrides(request, company.id, customer.id)

    if request.method == "POST":
        if request.POST.get("clear_quote_desc") == "1":
            clear_quote_desc_overrides(request, company.id, customer.id)
            messages.success(request, "Cleared quote-only description edits.")
            return redirect("pricing_customer_edit", customer_id=customer.id)

        new_overrides = dict(overrides)

        for line in lines_qs:
            qty_key = f"pallet_{line.id}"
            if qty_key in request.POST:
                raw = (request.POST.get(qty_key) or "").strip()
                try:
                    line.pallet_quantity_pieces = int(raw) if raw else 0
                except ValueError:
                    pass

            include_key = f"include_{line.id}"
            line.include_in_quote = include_key in request.POST

            line.save(update_fields=["pallet_quantity_pieces", "include_in_quote"])

            desc_key = f"quote_desc_{line.id}"
            raw_desc = (request.POST.get(desc_key) or "").strip()

            if raw_desc and raw_desc != line.product_description:
                new_overrides[str(line.id)] = raw_desc
            else:
                new_overrides.pop(str(line.id), None)

        set_quote_desc_overrides(request, company.id, customer.id, new_overrides)

        messages.success(
            request,
            "Saved pallet quantities / inclusions. Quote-only descriptions updated for the next quote.",
        )
        return redirect("pricing_customer_edit", customer_id=customer.id)

    for line in lines_qs:
        line.quote_desc_value = overrides.get(str(line.id), line.product_description)

    return render(
        request,
        "core/pricing_customer_edit.html",
        {
            "company": company,
            "customer": customer,
            "lines": lines_qs,
            "currency_code": currency_code,
            "currency_symbol": currency_symbol,
            "has_quote_desc_overrides": bool(overrides),
        },
    )


@login_required
def pricing_customer_quote_view(request, customer_id):
    """
    HTML quote page (easy to print/save as PDF).
    Uses quote-only description overrides ONCE, then clears them.
    """
    company = _get_company_for_request(request)
    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    customer = get_object_or_404(PricingCustomer, id=customer_id, company=company)
    # NOTE: We materialize to a list because we compute a pivot grid in-memory for the quote.
    lines = list(
        PricingQuoteLine.objects.filter(
            company=company,
            customer=customer,
            include_in_quote=True,
        ).order_by("destination", "product_description")
    )

    currency_code, currency_symbol = get_currency_for_customer_name(customer.name)

    overrides = get_quote_desc_overrides(request, company.id, customer.id)

    for line in lines:
        line.display_product_description = overrides.get(
            str(line.id),
            line.product_description,
        )

    # Build pivot axes
    # X axis: destinations (locations)
    destinations: list[str] = []
    seen_dests: set[str] = set()
    # Y axis: products (descriptions)
    products: list[str] = []
    seen_products: set[str] = set()

    for line in lines:
        d = (line.destination or "").strip() or "(Unspecified)"
        p = (line.display_product_description or "").strip() or "(Unspecified)"

        if d not in seen_dests:
            destinations.append(d)
            seen_dests.add(d)

        if p not in seen_products:
            products.append(p)
            seen_products.add(p)

    # grid[product][destination] = PricingQuoteLine | None
    grid: dict[str, dict[str, PricingQuoteLine | None]] = {
        p: {d: None for d in destinations} for p in products
    }
    for line in lines:
        d = (line.destination or "").strip() or "(Unspecified)"
        p = (line.display_product_description or "").strip() or "(Unspecified)"
        # If duplicates exist, keep the first one (stable with queryset ordering)
        if p in grid and d in grid[p] and grid[p][d] is None:
            grid[p][d] = line

    # Precompute a template-friendly structure: one row per product
    def _is_grey_product(product_name: str) -> bool:
        return "grey" in (product_name or "").strip().lower()

    products_non_grey = [p for p in products if not _is_grey_product(p)]
    products_grey = [p for p in products if _is_grey_product(p)]

    quote_rows = [
        {
            "product": p,
            "cells": [grid[p].get(d) for d in destinations],
        }
        for p in products_non_grey
    ]

    grey_quote_rows = [
        {
            "product": p,
            "cells": [grid[p].get(d) for d in destinations],
        }
        for p in products_grey
    ]

    if overrides:
        clear_quote_desc_overrides(request, company.id, customer.id)

    return render(
        request,
        "core/pricing_quote.html",
        {
            "company": company,
            "customer": customer,
            "lines": lines,
            "destinations": destinations,
            "quote_rows": quote_rows,
            "grey_quote_rows": grey_quote_rows,
            "currency_code": currency_code,
            "currency_symbol": currency_symbol,
        },
    )

@require_POST
@login_required
def order_container_delete_view(request, container_id: int):
    user = request.user

    if user.is_superuser:
        # Superusers can delete any container by ID
        container = get_object_or_404(OrderContainer, id=container_id)
    else:
        # Normal users are scoped to their Company via Company.owner
        company = get_object_or_404(Company, owner=user)
        container = get_object_or_404(OrderContainer, id=container_id, company=company)

    # This will cascade-delete lines + documents if your FKs are CASCADE (they should be).
    container.delete()

    messages.success(request, "Order deleted.")
    return redirect("order_tracker")


@require_POST
@login_required
def order_container_toggle_delivered_view(request, container_id: int):
    """Toggle an order between Active and Delivered.

    Delivered is represented by status == 'Delivered' (case-insensitive).
    When toggling from Delivered -> Active, we set status to 'In transit' (safe default).
    """
    user = request.user

    if user.is_superuser:
        container = get_object_or_404(OrderContainer, id=container_id)
    else:
        company = get_object_or_404(Company, owner=user)
        container = get_object_or_404(OrderContainer, id=container_id, company=company)

    if (container.status or "").strip().lower() == "delivered":
        container.status = "In transit"
        container.save(update_fields=["status", "updated_at"])
        messages.success(request, "Order moved back to Active.")
    else:
        container.status = "Delivered"
        container.save(update_fields=["status", "updated_at"])
        messages.success(request, "Order marked Delivered.")

    # Return to where the user was (keep filters), fall back to tracker.
    return redirect(request.META.get("HTTP_REFERER") or "order_tracker")
    
@login_required
def order_tracker_view(request):
    """
    Sea container / order tracking dashboard.
    Shows containers scoped to the user's company (owner) and allows create/edit.
    """
    user = request.user

    # Superusers see ALL containers across companies.
    if user.is_superuser:
        company = None
        containers = OrderContainer.objects.all()
    else:
        company = get_object_or_404(Company, owner=user)
        containers = OrderContainer.objects.filter(company=company)

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    assigned_to = (request.GET.get("assigned_to") or "").strip()

    sort = (request.GET.get("sort") or "").strip()
    direction = (request.GET.get("dir") or "desc").strip().lower()

    if q:
        containers = containers.filter(
            Q(customer_name__icontains=q)
            | Q(location_name__icontains=q)
            | Q(po_number__icontains=q)
            | Q(rpc_number__icontains=q)
            | Q(booking_number__icontains=q)
            | Q(bill_of_lading_number__icontains=q)
        )

    if status:
        # status is free text; treat filter as "contains" so you can search partial statuses
        containers = containers.filter(status__icontains=status)

    if assigned_to:
        containers = containers.filter(assigned_to__iexact=assigned_to)

    # Sorting (whitelisted)
    sort_map = {
        "customer": "customer_name",
        "location": "location_name",
        "requested": "requested_date",
        "est_delivery": "estimated_delivery_date",
        "loading": "loading_date",
        "assigned_to": "assigned_to",
    }
    sort_field = sort_map.get(sort)

    if direction not in {"asc", "desc"}:
        direction = "desc"

    if sort_field:
        prefix = "" if direction == "asc" else "-"
        containers = containers.order_by(f"{prefix}{sort_field}", "-updated_at", "-created_at")
    else:
        containers = containers.order_by("-updated_at", "-created_at")

    # Split active vs delivered (delivered means status == "Delivered" case-insensitive)
    delivered_q = Q(status__iexact="delivered")
    delivered_containers = containers.filter(delivered_q)
    active_containers = containers.exclude(delivered_q)

    return render(
        request,
        "core/order_tracker.html",
        {
            "automation_name": "Order Tracker",
            "company": company,
            "company_display": (company.name if company else "All Companies"),
            "containers": active_containers,
            "delivered_containers": delivered_containers,
            "q": q,
            "status": status,
            "assigned_to": assigned_to,
            "sort": sort,
            "dir": direction,
        },
    )


def _ordinal(n: int) -> str:
    """Return an ordinal suffix for a positive day number (1 -> '1st')."""
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _fmt_long_date(d: dt.date | None) -> str:
    """Format like 'January 16th 2026' or 'TBD'."""
    if not d:
        return "TBD"
    return f"{d.strftime('%B')} {_ordinal(d.day)} {d.year}"


def _fmt_short_date(d: dt.date | None) -> str:
    """Format like '12/8/2025' or 'TBD'."""
    if not d:
        return "TBD"
    # avoid platform-specific %-m / %-d
    return f"{d.month}/{d.day}/{d.year}"


@login_required
def order_tracker_recap_docx_view(request):
    """Download an Order Recap DOCX sorted by Customer + Location, for all (filtered) containers."""
    user = request.user

    # Superusers see ALL containers across companies.
    if user.is_superuser:
        containers = OrderContainer.objects.all()
    else:
        company = get_object_or_404(Company, owner=user)
        containers = OrderContainer.objects.filter(company=company)

    # Respect the same filters as the dashboard (if present in the URL).
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    assigned_to = (request.GET.get("assigned_to") or "").strip()

    if q:
        containers = containers.filter(
            Q(customer_name__icontains=q)
            | Q(location_name__icontains=q)
            | Q(po_number__icontains=q)
            | Q(rpc_number__icontains=q)
            | Q(booking_number__icontains=q)
            | Q(bill_of_lading_number__icontains=q)
        )
    if status:
        containers = containers.filter(status__icontains=status)
    if assigned_to:
        containers = containers.filter(assigned_to__iexact=assigned_to)

    # Sort by Customer + Location (requested), then by Requested Date, then by PO.
    containers = containers.order_by(
        "customer_name",
        "location_name",
        "requested_date",
        "po_number",
        "-updated_at",
    ).prefetch_related("lines")

    doc = Document()

    # Color palette + formatting to match the recap example document.
    # (Word RGB hex values)
    COLOR_RED = RGBColor(0xC0, 0x00, 0x00)
    COLOR_BROWN = RGBColor(0x7F, 0x60, 0x00)
    COLOR_ORANGE = RGBColor(0xE6, 0x91, 0x38)
    COLOR_BLUE = RGBColor(0x05, 0x63, 0xC1)
    COLOR_GREEN = RGBColor(0x00, 0xB0, 0x50)
    COLOR_BLACK = RGBColor(0x11, 0x11, 0x11)

    def _add_run(p, text: str, color: RGBColor, *, bold: bool | None = None, underline: bool | None = None, highlight=None):
        r = p.add_run(text)
        r.font.color.rgb = color
        if bold is not None:
            r.bold = bold
        if underline is not None:
            r.font.underline = underline
        if highlight is not None:
            r.font.highlight_color = highlight
        return r

    # Match a clean, simple default look.
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    for idx, c in enumerate(containers):
        po = (c.po_number or "TBD").strip() or "TBD"
        rpc = (c.rpc_number or "TBD").strip() or "TBD"
        status_txt = (c.status or "TBD").strip() or "TBD"

        # Line 1: PO + Requested + Status (with colors)
        p1 = doc.add_paragraph()
        _add_run(p1, f"PO#{po}– ", COLOR_RED, bold=True)
        _add_run(p1, f"Requested {_fmt_long_date(c.requested_date)} ", COLOR_BROWN)
        # STATUS: orange + bold + highlighted (user requested highlight)
        _add_run(p1, f"***{status_txt}*** ", COLOR_ORANGE, bold=True, highlight=WD_COLOR_INDEX.YELLOW)

        # Line 2: RPC (blue, bold)
        p2 = doc.add_paragraph()
        # IMPORTANT: the RPC string already includes the city (ex: "6066 Miami"),
        # so do NOT append the location name.
        _add_run(p2, f"RPC# {rpc} ", COLOR_BLUE, bold=True)

        # Line 3: Loading Date (green, bold)
        p3 = doc.add_paragraph()
        _add_run(p3, f"Loading Date: {_fmt_short_date(c.loading_date)}", COLOR_GREEN, bold=True)

        # Content lines (green, underlined like example)
        # NOTE: user requested to remove the literal "Buckets/Pallets" label.
        for line in c.lines.all():
            desc = (line.item_description or "").strip() or "(item)"
            pallets = int(line.pallets or 0)
            upp = int(line.units_per_pallet or 0)
            total = int(line.total_units or (pallets * upp))

            p = doc.add_paragraph()
            # Description part (underlined in the example as well)
            _add_run(p, f"{desc}  (", COLOR_GREEN, underline=True)
            _add_run(p, f"{pallets} x {upp} = {total:,} ", COLOR_GREEN, underline=True)
            _add_run(p, "Pieces", COLOR_GREEN, underline=True)
            _add_run(p, ")", COLOR_GREEN, underline=True)

        # Dates (black)
        p = doc.add_paragraph()
        _add_run(p, f"ETD: {_fmt_short_date(c.etd)}", COLOR_BLACK)
        p = doc.add_paragraph()
        _add_run(p, f"ETA: {_fmt_short_date(c.eta)}", COLOR_BLACK)
        p = doc.add_paragraph()
        _add_run(p, f"Estimated Delivery: {_fmt_short_date(c.estimated_delivery_date)}", COLOR_BLACK)

        # spacing between containers
        if idx != len(containers) - 1:
            doc.add_paragraph("")

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)

    filename = f"order_recap_{timezone.localdate().isoformat()}.docx"
    return FileResponse(
        buf,
        as_attachment=True,
        filename=filename,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@login_required
@require_http_methods(["POST"])
def order_container_toggle_delivered_view(request, container_id: int):
    """Toggle an OrderContainer between Delivered and Active."""
    user = request.user

    if user.is_superuser:
        container = get_object_or_404(OrderContainer, pk=container_id)
    else:
        company = get_object_or_404(Company, owner=user)
        container = get_object_or_404(OrderContainer, pk=container_id, company=company)

    current = (container.status or "").strip()
    if current.lower() == "delivered":
        # Re-open as active
        container.status = "In transit"
        messages.success(request, "Order marked active.")
    else:
        container.status = "Delivered"
        messages.success(request, "Order marked delivered.")

    container.save(update_fields=["status", "updated_at"])
    return redirect("order_tracker")


@login_required
def order_container_edit_view(request, container_id: int | None = None):
    """
    Create or edit a container + its content lines (inline formset).
    """
    user = request.user

    # IMPORTANT FIX:
    # Superusers can edit any container, so infer company from the container when editing.
    if user.is_superuser:
        if container_id is None:
            company = Company.objects.order_by("id").first()
            container = None
        else:
            container = get_object_or_404(OrderContainer, pk=container_id)
            company = container.company
    else:
        company = get_object_or_404(Company, owner=user)
        if container_id is None:
            container = None
        else:
            container = get_object_or_404(OrderContainer, pk=container_id, company=company)

    LineFormSet = inlineformset_factory(
        parent_model=OrderContainer,
        model=OrderContainerLine,
        form=OrderContainerLineForm,
        extra=3,
        can_delete=True,
    )

    DocumentFormSet = inlineformset_factory(
        parent_model=OrderContainer,
        model=OrderContainerDocument,
        form=OrderContainerDocumentForm,
        extra=1,
        can_delete=True,
    )

    if request.method == "POST":
        form = OrderContainerForm(request.POST, instance=container)
        formset = LineFormSet(request.POST, instance=container, prefix="lines")
        doc_formset = DocumentFormSet(
            request.POST,
            request.FILES,
            instance=container,
            prefix="docs",
        )
        if form.is_valid() and formset.is_valid() and doc_formset.is_valid():
            obj: OrderContainer = form.save(commit=False)
            obj.company = company
            if obj.created_by_id is None:
                obj.created_by = user
            obj.save()

            formset.instance = obj
            formset.save()

            doc_formset.instance = obj
            doc_formset.save()

            messages.success(request, "Container saved.")
            return redirect("order_container_edit", container_id=obj.id)
        else:
            messages.error(request, "Please fix the errors below and try again.")
    else:
        form = OrderContainerForm(instance=container)
        formset = LineFormSet(instance=container, prefix="lines")
        doc_formset = DocumentFormSet(instance=container, prefix="docs")

    return render(
        request,
        "core/order_container_edit.html",
        {
            "automation_name": "Order Tracker",
            "company": company,
            "container": container,
            "form": form,
            "formset": formset,
            "doc_formset": doc_formset,
        },
    )















# =========================
# Schedule Dashboard
# =========================

@login_required
def schedule_dashboard_view(request):
    """Company scheduling dashboard (week view).

    GET params:
      - d: reference date (YYYY-MM-DD). The week shown is the Monday-starting week containing d.
      - view: "week" (default) or "month"
    """
    user = request.user

    if user.is_superuser:
        company = Company.objects.order_by("id").first()
    else:
        company = Company.objects.filter(owner=user).order_by("id").first()

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    d_str = (request.GET.get("d") or "").strip()
    try:
        ref_date = dt.date.fromisoformat(d_str) if d_str else timezone.localdate()
    except Exception:
        ref_date = timezone.localdate()

    view_mode = (request.GET.get("view") or "week").strip().lower()
    view_mode = "month" if view_mode == "month" else "week"

    # Always-on notes (not tied to a date)
    global_note_obj, _ = ScheduleGlobalNote.objects.get_or_create(company=company)
    global_note_form = ScheduleGlobalNoteForm(instance=global_note_obj)

    form = ScheduleActivityForm(initial={"date": ref_date, "repeat_every": 1, "repeat_unit": "weeks"})

    def _expand_occurrences(qs, start_date: dt.date, end_date: dt.date):
        """Return a list of *display* activities for the given date range.

        For recurring activities, we generate per-occurrence copies so that the
        same base object can appear on multiple days without overwriting state.
        """
        out = []
        for a in qs:
            if not a.is_recurring:
                out.append(copy.copy(a))
                continue

            until = a.repeat_until or end_date
            occ_end = min(end_date, until)
            if a.date > occ_end:
                continue

            unit = (a.repeat_unit or "weeks").lower()
            every = int(a.repeat_every or 1)
            if every < 1:
                every = 1

            cur = a.date

            # Advance to first occurrence on/after start_date
            if unit == "days":
                step = dt.timedelta(days=every)
                while cur < start_date:
                    cur += step
            elif unit == "weeks":
                step = dt.timedelta(days=7 * every)
                while cur < start_date:
                    cur += step
            else:  # months
                while cur < start_date:
                    cur = cur + relativedelta(months=every)

            while cur <= occ_end:
                occ = copy.copy(a)
                occ.date = cur
                occ._is_occurrence = True  # type: ignore[attr-defined]
                out.append(occ)
                if unit == "days":
                    cur += dt.timedelta(days=every)
                elif unit == "weeks":
                    cur += dt.timedelta(days=7 * every)
                else:
                    cur = cur + relativedelta(months=every)

        return out

    if view_mode == "month":
        # Month grid (Monday-starting weeks)
        month_start = ref_date.replace(day=1)
        # Find the first Monday to show
        grid_start = month_start - dt.timedelta(days=month_start.weekday())
        # Find the last day of the month
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1, day=1)
        month_end = next_month - dt.timedelta(days=1)
        # Extend to the end of the last week (Sunday)
        grid_end = month_end + dt.timedelta(days=(6 - month_end.weekday()))

        base_qs = (
            ScheduleActivity.objects
            .filter(company=company)
            .filter(
                Q(is_recurring=False, date__gte=grid_start, date__lte=grid_end)
                | (
                    Q(is_recurring=True, date__lte=grid_end)
                    & (Q(repeat_until__isnull=True) | Q(repeat_until__gte=grid_start))
                )
            )
            .order_by("date", "start_time", "created_at", "id")
        )

        display_acts = _expand_occurrences(base_qs, grid_start, grid_end)
        display_acts.sort(key=lambda a: (a.date, a.start_time or dt.time(23, 59), a.created_at, a.id))

        by_day = {}
        for a in display_acts:
            by_day.setdefault(a.date, []).append(a)

        weeks = []
        cur = grid_start
        while cur <= grid_end:
            week_days = [cur + dt.timedelta(days=i) for i in range(7)]
            weeks.append(
                [
                    {
                        "date": d,
                        "in_month": (d.month == month_start.month),
                        "activities": by_day.get(d, []),
                    }
                    for d in week_days
                ]
            )
            cur += dt.timedelta(days=7)

        # Month nav
        prev_month = (month_start - dt.timedelta(days=1)).replace(day=1)
        next_month = (month_end + dt.timedelta(days=1)).replace(day=1)

        context = {
            "automation_name": "Schedule Dashboard",
            "company": company,
            "ref_date": ref_date,
            "view_mode": "month",
            "month_start": month_start,
            "grid_start": grid_start,
            "grid_end": grid_end,
            "prev_d": prev_month.isoformat(),
            "next_d": next_month.isoformat(),
            "weeks": weeks,
            "form": form,
            "global_note_form": global_note_form,
            "global_note_obj": global_note_obj,
        }
        return render(request, "core/schedule_month.html", context)

    # Week view (default)
    week_start = ref_date - dt.timedelta(days=ref_date.weekday())
    days = [week_start + dt.timedelta(days=i) for i in range(7)]
    week_end = days[-1]

    base_qs = (
        ScheduleActivity.objects
        .filter(company=company)
        .filter(
            Q(is_recurring=False, date__gte=week_start, date__lte=week_end)
            | (
                Q(is_recurring=True, date__lte=week_end)
                & (Q(repeat_until__isnull=True) | Q(repeat_until__gte=week_start))
            )
        )
        .order_by("date", "start_time", "created_at", "id")
    )

    display_acts = _expand_occurrences(base_qs, week_start, week_end)
    display_acts.sort(key=lambda a: (a.date, a.start_time or dt.time(23, 59), a.created_at, a.id))

    by_day = {d: [] for d in days}
    for a in display_acts:
        by_day.setdefault(a.date, []).append(a)

    day_blocks = [{"date": d, "activities": by_day.get(d, [])} for d in days]

    context = {
        "automation_name": "Schedule Dashboard",
        "company": company,
        "ref_date": ref_date,
        "view_mode": "week",
        "week_start": week_start,
        "week_end": week_end,
        "prev_d": (week_start - dt.timedelta(days=7)).isoformat(),
        "next_d": (week_start + dt.timedelta(days=7)).isoformat(),
        "day_blocks": day_blocks,
        "form": form,
        "global_note_form": global_note_form,
        "global_note_obj": global_note_obj,
    }
    return render(request, "core/schedule_dashboard.html", context)


@login_required
@require_POST
def schedule_activity_add_view(request):
    user = request.user

    if user.is_superuser:
        company = Company.objects.order_by("id").first()
    else:
        company = Company.objects.filter(owner=user).order_by("id").first()

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    form = ScheduleActivityForm(request.POST)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.company = company
        obj.save()
        messages.success(request, "Activity added.")
    else:
        messages.error(request, "Could not add activity. Please check the fields.")

    back_d = (request.POST.get("back_d") or "").strip()
    back_view = (request.POST.get("back_view") or "").strip().lower()
    back_view = "month" if back_view == "month" else "week"
    if back_d:
        return redirect(f"/automations/schedule/?d={back_d}&view={back_view}")
    return redirect("schedule_dashboard")


@login_required
@require_POST
def schedule_global_note_save_view(request):
    """Save always-on notes for the scheduling dashboard."""
    user = request.user

    if user.is_superuser:
        company = Company.objects.order_by("id").first()
    else:
        company = Company.objects.filter(owner=user).order_by("id").first()

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    note_obj, _ = ScheduleGlobalNote.objects.get_or_create(company=company)
    form = ScheduleGlobalNoteForm(request.POST, instance=note_obj)
    if form.is_valid():
        form.save()
        messages.success(request, "Notes saved.")
    else:
        messages.error(request, "Could not save notes.")

    back_d = (request.POST.get("back_d") or "").strip()
    back_view = (request.POST.get("back_view") or "").strip().lower()
    back_view = "month" if back_view == "month" else "week"
    if back_d:
        return redirect(f"/automations/schedule/?d={back_d}&view={back_view}")
    return redirect("schedule_dashboard")


@login_required
def schedule_activity_edit_view(request, pk):
    user = request.user

    if user.is_superuser:
        company = Company.objects.order_by("id").first()
    else:
        company = Company.objects.filter(owner=user).order_by("id").first()

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    activity = get_object_or_404(ScheduleActivity, pk=pk, company=company)

    if request.method == "POST":
        form = ScheduleActivityForm(request.POST, instance=activity)
        if form.is_valid():
            form.save()
            messages.success(request, "Activity updated.")
            back_d = (request.POST.get("back_d") or "").strip()
            back_view = (request.POST.get("back_view") or "").strip().lower()
            back_view = "month" if back_view == "month" else "week"
            if back_d:
                return redirect(f"/automations/schedule/?d={back_d}&view={back_view}")
            return redirect("schedule_dashboard")
    else:
        form = ScheduleActivityForm(instance=activity)

    back_d = (request.GET.get("back_d") or activity.date.isoformat()).strip()
    back_view = (request.GET.get("back_view") or "week").strip().lower()
    back_view = "month" if back_view == "month" else "week"
    return render(
        request,
        "core/schedule_activity_edit.html",
        {
            "automation_name": "Edit Activity",
            "company": company,
            "activity": activity,
            "form": form,
            "back_d": back_d,
            "back_view": back_view,
        },
    )


@login_required
@require_POST
def schedule_activity_delete_view(request, pk):
    user = request.user

    if user.is_superuser:
        company = Company.objects.order_by("id").first()
    else:
        company = Company.objects.filter(owner=user).order_by("id").first()

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    activity = get_object_or_404(ScheduleActivity, pk=pk, company=company)
    activity.delete()
    messages.success(request, "Activity deleted.")

    back_d = (request.POST.get("back_d") or "").strip()
    back_view = (request.POST.get("back_view") or "").strip().lower()
    back_view = "month" if back_view == "month" else "week"
    if back_d:
        return redirect(f"/automations/schedule/?d={back_d}&view={back_view}")
    return redirect("schedule_dashboard")


@login_required
@require_POST
def schedule_activity_toggle_done_view(request, pk):
    user = request.user

    if user.is_superuser:
        company = Company.objects.order_by("id").first()
    else:
        company = Company.objects.filter(owner=user).order_by("id").first()

    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    activity = get_object_or_404(ScheduleActivity, pk=pk, company=company)

    if activity.status == ScheduleActivity.STATUS_DONE:
        activity.status = ScheduleActivity.STATUS_PLANNED
    else:
        activity.status = ScheduleActivity.STATUS_DONE
    activity.save(update_fields=["status", "updated_at"])

    back_d = (request.POST.get("back_d") or "").strip()
    back_view = (request.POST.get("back_view") or "").strip().lower()
    back_view = "month" if back_view == "month" else "week"
    if back_d:
        return redirect(f"/automations/schedule/?d={back_d}&view={back_view}")
    return redirect("schedule_dashboard")



