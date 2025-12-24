from __future__ import annotations

import os
import re
import tempfile
from io import BytesIO

import pandas as pd
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .automations.bucket_metrics import analyze_prognosis_workbook, rebuild_projection_with_growth
from .bol_generation import generate_bol_from_form, generate_bol_from_templates
from .forms import BOLForm, PricingUploadForm
from .models import Automation, Company, PricingCustomer, PricingQuoteLine
from .rpc_generation import generate_rpc_from_form
from .rpcforms import RpcOrderForm
from .services.pricing_import import parse_pricing_matrix_csv


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
        return ("EUR", "€")
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
    # Keep customer in the key so you can unapply a single customer's delta cleanly.
    return f"{month_label}||{col_name}||{customer_name}"


def _get_applied_customer_deltas(request) -> dict:
    """
    Stores per-customer additive deltas (absolute units):
      { "Jan-26||CLASSIC||Falcon Farms": 20000.0, ... }
    These get aggregated to month+bucket when applying to the projection table.
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
    Apply additive deltas to the projection table.

    We aggregate:
      (month, bucket) += sum(delta for all customers)

    This intentionally does NOT try to re-split customers, because the projection table
    is bucket totals per month.
    """
    if projection_df is None or projection_df.empty:
        return projection_df

    month_col = projection_df.columns[0]
    df = projection_df.copy()

    # Aggregate per-customer keys to month+bucket totals
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
        # NEW: optional list for customer-delta applied summary
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

            # allow user to type 10 (meaning 10%) or 0.10 (meaning 10%)
            if pct_val > 1.0:
                pct_val = pct_val / 100.0

            if month_label and col_name:
                key = _yoy_session_key(month_label, col_name)

                # only apply pct if YoY is applied
                if key in applied_overrides:
                    if abs(pct_val) < 1e-12:
                        applied_yoy_pct.pop(key, None)  # 0% removes it
                    else:
                        applied_yoy_pct[key] = pct_val

                    _set_applied_yoy_pct_overrides(request, applied_yoy_pct)

            return redirect("bucket_projections")

        # -----------------------------
        # NEW: Customer delta apply/unapply
        # -----------------------------
        if action == "apply_customer_delta":
            month_label = (request.POST.get("month_label") or "").strip()
            col_name = (request.POST.get("col_name") or "").strip()
            customer_name = (request.POST.get("customer_name") or "").strip()

            # expected to be an absolute delta like "20000" (can be negative too)
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

            # Apply YoY replacement, THEN YoY extra %, THEN customer deltas (additive)
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

    export_path = os.path.join(tempfile.gettempdir(), f"bucket_projections_{request.user.id}.xlsx")
    with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
        projection_df.to_excel(writer, index=False, sheet_name="Projections")
    request.session["bucket_metrics_projection_export_path"] = export_path
    request.session.modified = True

    # Build YoY records from your analyzer's YoY table (the one that actually has Prev/Current)
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
                    "extra_pct": extra_pct,  # decimal
                    "extra_pct_display": extra_pct * 100.0,  # percent number for input
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

    # Build a friendly summary for applied customer deltas
    applied_customer_list = []
    for k, delta in applied_customer_deltas.items():
        try:
            m, c, cust = k.split("||", 2)
        except ValueError:
            continue
        sign = "+" if float(delta) >= 0 else ""
        applied_customer_list.append(f"{m} • {c} • {cust} ({sign}{int(round(float(delta)))})")

    # (Optional) Customer delta suggestion records:
    # We'll expect the analyzer to *eventually* provide results["customer_delta_suggestions"] as a DF.
    # For now, this safely renders empty if not present.
    customer_delta_records = []
    cust_df = results.get("customer_delta_suggestions")  # may not exist yet
    if cust_df is not None and isinstance(cust_df, pd.DataFrame) and not cust_df.empty:
        for r in cust_df.to_dict("records"):
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
        }
    )

    return render(request, "core/bucket_projections.html", context)


@login_required
def bucket_projections_export_view(request):
    export_path = request.session.get("bucket_metrics_projection_export_path")
    if not export_path or not os.path.exists(export_path):
        return HttpResponseForbidden("No export available yet. Open projections first.")

    return FileResponse(
        open(export_path, "rb"),
        as_attachment=True,
        filename="Bucket_Projections.xlsx",
    )


@login_required
@require_http_methods(["GET", "POST"])
def run_automation(request, pk):
    automation = get_object_or_404(Automation.objects.select_related("company"), pk=pk)

    if not (request.user.is_superuser or automation.company.owner == request.user):
        return HttpResponseForbidden("You are not allowed to run this automation.")

    name_normalized = (automation.name or "").strip().lower()

    # --- Branch: Retriever RPC Order ---
    if name_normalized == "retriever rpc order":
        if request.method == "POST":
            form = RpcOrderForm(request.POST)
            if form.is_valid():
                files, outlook_status = generate_rpc_from_form(form.cleaned_data)

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
    lines = PricingQuoteLine.objects.filter(
        company=company,
        customer=customer,
        include_in_quote=True,
    ).order_by("destination", "product_description")

    currency_code, currency_symbol = get_currency_for_customer_name(customer.name)

    overrides = get_quote_desc_overrides(request, company.id, customer.id)

    for line in lines:
        line.display_product_description = overrides.get(str(line.id), line.product_description)

    if overrides:
        clear_quote_desc_overrides(request, company.id, customer.id)

    return render(
        request,
        "core/pricing_quote.html",
        {
            "company": company,
            "customer": customer,
            "lines": lines,
            "currency_code": currency_code,
            "currency_symbol": currency_symbol,
        },
    )

