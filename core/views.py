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


def normalize_customer_name(raw: str) -> str | None:
    """
    Returns a canonical customer name, or None to skip the row entirely.
    """
    if raw is None:
        return None

    s = str(raw).strip()
    if not s:
        return None

    low = s.lower().strip()

    # Remove the "Los" / LA general pricing customer entirely
    if low in {"los", "los angeles", "los angeles pricing", "la"}:
        return None

    # Normalize common whitespace
    s = re.sub(r"\s+", " ", s).strip()

    # Kendal == Kendal - (remove trailing dash variants)
    s = re.sub(r"\s*-\s*$", "", s).strip()
    low = s.lower()

    # Hard canonical mappings (your rules)
    mapping = {
        "designers": "Designers Choice",
        "desginers": "Designers Choice",
        "designer's choice": "Designers Choice",
        "designers choice": "Designers Choice",
        "falcon": "Falcon",
        "falcon long": "Falcon",
        "golden": "Golden State",
        "golden state": "Golden State",
    }

    if low in mapping:
        return mapping[low]

    return s


def get_or_create_customer_safe(company, name: str):
    """
    Safer than get_or_create under concurrency: if the INSERT races and hits
    the unique constraint, we re-fetch.
    """
    try:
        obj = PricingCustomer.objects.get(company=company, name=name)
        return obj, False
    except PricingCustomer.DoesNotExist:
        try:
            obj = PricingCustomer.objects.create(company=company, name=name)
            return obj, True
        except IntegrityError:
            obj = PricingCustomer.objects.get(company=company, name=name)
            return obj, False


@transaction.atomic
def merge_duplicate_pricing_customers(company):
    """
    Merge PricingCustomer rows that normalize to the same canonical name.
    Also merges PricingQuoteLine rows without blowing away pallet quantities.
    """
    customers = list(PricingCustomer.objects.filter(company=company).order_by("id"))

    # Group customers by canonical normalized name
    buckets: dict[str, list[PricingCustomer]] = {}
    for c in customers:
        canon = normalize_customer_name(c.name)
        # If a stored customer is "Los", we'll treat it as removable
        if canon is None:
            buckets.setdefault("__DELETE__", []).append(c)
        else:
            buckets.setdefault(canon, []).append(c)

    # Delete any "Los" customers + their lines
    for c in buckets.get("__DELETE__", []):
        PricingQuoteLine.objects.filter(company=company, customer=c).delete()
        c.delete()

    # Merge duplicates
    for canon_name, cust_list in buckets.items():
        if canon_name == "__DELETE__":
            continue
        if not cust_list:
            continue

        # CRITICAL FIX:
        # Pick as primary the customer that ALREADY has the canonical name (if present),
        # so we never try to rename a different row to a name that already exists.
        primary = next((c for c in cust_list if (c.name or "").strip() == canon_name), None)
        if primary is None:
            primary = cust_list[0]
            # Only rename if no one else already has canon_name (should be true now)
            if primary.name != canon_name:
                primary.name = canon_name
                primary.save(update_fields=["name"])

        duplicates = [c for c in cust_list if c.id != primary.id]

        for dup in duplicates:
            dup_lines = PricingQuoteLine.objects.filter(company=company, customer=dup)

            for line in dup_lines:
                existing = PricingQuoteLine.objects.filter(
                    company=company,
                    customer=primary,
                    destination=line.destination,
                    product_description=line.product_description,
                ).first()

                if existing:
                    # Only update price_delivered (don’t overwrite pallet qty / include flags)
                    if existing.price_delivered != line.price_delivered:
                        existing.price_delivered = line.price_delivered
                        existing.save(update_fields=["price_delivered"])
                    line.delete()
                else:
                    line.customer = primary
                    line.save(update_fields=["customer"])

            dup.delete()


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

            created_lines = 0
            updated_lines = 0
            created_customers = 0

            for r in rows:
                canon_customer = normalize_customer_name(r.get("customer", ""))
                if canon_customer is None:
                    continue

                customer_obj, cust_created = get_or_create_customer_safe(company, canon_customer)
                if cust_created:
                    created_customers += 1

                obj, was_created = PricingQuoteLine.objects.update_or_create(
                    company=company,
                    customer=customer_obj,
                    destination=r["destination"].strip(),
                    product_description=r["product_description"].strip(),
                    defaults={"price_delivered": r["price_delivered"]},
                )

                if was_created:
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
    company = _get_company_for_request(request)
    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    customer = get_object_or_404(PricingCustomer, id=customer_id, company=company)

    lines_qs = PricingQuoteLine.objects.filter(company=company, customer=customer).order_by(
        "destination", "product_description"
    )

    if request.method == "POST":
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

        messages.success(request, "Saved pallet quantities and quote inclusions.")
        return redirect("pricing_customer_edit", customer_id=customer.id)

    return render(
        request,
        "core/pricing_customer_edit.html",
        {"company": company, "customer": customer, "lines": lines_qs},
    )


@login_required
def pricing_customer_quote_view(request, customer_id):
    company = _get_company_for_request(request)
    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    customer = get_object_or_404(PricingCustomer, id=customer_id, company=company)
    lines = PricingQuoteLine.objects.filter(
        company=company, customer=customer, include_in_quote=True
    ).order_by("destination", "product_description")

    return render(
        request,
        "core/pricing_quote.html",
        {"company": company, "customer": customer, "lines": lines},
    )
