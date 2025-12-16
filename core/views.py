from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.utils import timezone
from django.http import FileResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.db import transaction, IntegrityError

from .bol_generation import generate_bol_from_templates, generate_bol_from_form
from .forms import BOLForm, PricingUploadForm
from .rpcforms import RpcOrderForm
from .rpc_generation import generate_rpc_from_form
from .models import Automation, Company, PricingCustomer, PricingQuoteLine

from .automations.bucket_metrics import analyze_prognosis_workbook
import tempfile

from .services.pricing_import import parse_pricing_matrix_csv

import re


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
        # ensure keys are strings
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


@require_http_methods(["GET", "POST"])
@login_required
def run_automation(request, pk):
    automation = get_object_or_404(Automation.objects.select_related("company"), pk=pk)

    if not (request.user.is_superuser or automation.company.owner == request.user):
        return HttpResponseForbidden("You are not allowed to run this automation.")

    name_normalized = automation.name.strip().lower()

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

    elif "bucket metrics" in name_normalized:
        return redirect("bucket_metrics")

    elif "pricing quote" in name_normalized or "pricing" in name_normalized:
        return redirect("pricing_upload")

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

    if request.method == "POST" and request.FILES.get("file"):
        excel_file = request.FILES["file"]

        try:
            results = analyze_prognosis_workbook(excel_file)

            context.update(
                {
                    "results_available": True,
                    "top_customers_table": results["top_customers"].to_html(
                        classes="table table-striped table-sm", index=False, border=0
                    ),
                    "per_customer_month_table": results["per_customer_month"].to_html(
                        classes="table table-striped table-sm", index=False, border=0
                    ),
                    "per_customer_city_item_table": results["per_customer_city_item"].to_html(
                        classes="table table-striped table-sm", index=False, border=0
                    ),
                    "per_customer_city_item_month_table": results[
                        "per_customer_city_item_month"
                    ].to_html(classes="table table-striped table-sm", index=False, border=0),
                }
            )
        except Exception as e:
            context["error"] = f"Error reading file: {e}"

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

                _, created = upsert_pricing_line_safe(
                    company=company,
                    customer=customer_obj,
                    destination=norm_dest,
                    product_description=prod,
                    price_delivered=price,
                )

                if created:
                    created_lines += 1
                else:
                    updated_lines += 1

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

    # Load any existing quote-only overrides for this customer
    overrides = get_quote_desc_overrides(request, company.id, customer.id)

    if request.method == "POST":
        # Optional: user clicked a "Clear quote description edits" button
        if request.POST.get("clear_quote_desc") == "1":
            clear_quote_desc_overrides(request, company.id, customer.id)
            messages.success(request, "Cleared quote-only description edits.")
            return redirect("pricing_customer_edit", customer_id=customer.id)

        new_overrides = dict(overrides)  # start with existing

        for line in lines_qs:
            # --- Permanent: Pallet quantity ---
            qty_key = f"pallet_{line.id}"
            if qty_key in request.POST:
                raw = (request.POST.get(qty_key) or "").strip()
                try:
                    line.pallet_quantity_pieces = int(raw) if raw else 0
                except ValueError:
                    pass

            # --- Permanent: Include / exclude toggle ---
            include_key = f"include_{line.id}"
            line.include_in_quote = include_key in request.POST

            line.save(update_fields=["pallet_quantity_pieces", "include_in_quote"])

            # --- Temporary: Quote-only description override (DO NOT SAVE TO DB) ---
            desc_key = f"quote_desc_{line.id}"
            raw_desc = (request.POST.get(desc_key) or "").strip()

            if raw_desc and raw_desc != line.product_description:
                new_overrides[str(line.id)] = raw_desc
            else:
                # if user cleared it or set it back to default, remove override
                new_overrides.pop(str(line.id), None)

        set_quote_desc_overrides(request, company.id, customer.id, new_overrides)

        messages.success(request, "Saved pallet quantities / inclusions. Quote-only descriptions updated for the next quote.")
        return redirect("pricing_customer_edit", customer_id=customer.id)

    # For GET: attach a helper attribute so templates can show the editable value
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

    # Apply overrides to display (no DB changes)
    for line in lines:
        line.display_product_description = overrides.get(str(line.id), line.product_description)

    # IMPORTANT: clear after generating this quote so future quotes revert automatically
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
