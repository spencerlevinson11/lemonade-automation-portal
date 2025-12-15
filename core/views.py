from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.core.mail import send_mail
from django.utils import timezone
from django.http import FileResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods

from .bol_generation import generate_bol_from_templates, generate_bol_from_form
from .forms import BOLForm
from .rpcforms import RpcOrderForm
from .rpc_generation import generate_rpc_from_form
from .models import Automation, Company, PricingCustomer, PricingQuoteLine

from .automations.bucket_metrics import analyze_prognosis_workbook
import tempfile

from .forms import PricingUploadForm
from .services.pricing_import import parse_pricing_matrix_csv
from .models import PricingCustomer, PricingQuoteLine


@login_required
def dashboard(request):
    user = request.user
    company = None

    if user.is_superuser:
        # Admin view: see all automations across all companies
        automations = Automation.objects.select_related("company").all()
        # (We leave company = None for admins; banner will use is_admin)
    else:
        # Client view: only see automations for your company
        try:
            company = Company.objects.get(owner=user)
        except Company.DoesNotExist:
            company = None

        if company:
            automations = Automation.objects.select_related("company").filter(
                company=company
            )
        else:
            # No company linked to this user yet
            automations = Automation.objects.none()

    context = {
        "automations": automations,
        "company": company,
        "is_admin": user.is_superuser,
    }
    return render(request, "core/dashboard.html", context)


def custom_logout(request):
    """
    Simple logout view that allows GET requests.
    Logs the user out, then redirects to the login page.
    """
    logout(request)
    return redirect("login")


@require_http_methods(["GET", "POST"])
@login_required
def run_automation(request, pk):
    """
    Run an automation.

    - If the automation is named "Retriever RPC Order", we show the RPC form,
      generate an RPC Excel workbook, and (locally on Windows) try to create
      Outlook drafts.
    - If the automation name contains "Bucket Metrics", we redirect to the
      upload-and-metrics view.
    - Otherwise, we treat it as a BOL generator automation.
    """

    automation = get_object_or_404(Automation.objects.select_related("company"), pk=pk)

    # Permission check: only superuser or the company owner
    if not (request.user.is_superuser or automation.company.owner == request.user):
        return HttpResponseForbidden("You are not allowed to run this automation.")

    name_normalized = automation.name.strip().lower()

    # --- Branch: Retriever RPC Order ----------------------------------------
    if name_normalized == "retriever rpc order":
        if request.method == "POST":
            form = RpcOrderForm(request.POST)
            if form.is_valid():
                # generate_rpc_from_form now returns (files, outlook_status)
                files, outlook_status = generate_rpc_from_form(form.cleaned_data)

                # Record last run time on the automation
                automation.last_run_at = timezone.now()
                automation.save(update_fields=["last_run_at"])

                # Use the first generated file as the download
                first_file = files[0]

                status_text = outlook_status or "No Outlook status returned."
                messages.success(
                    request,
                    f"RPC generated. {status_text}",
                )

                return FileResponse(
                    open(first_file, "rb"),
                    as_attachment=True,
                    filename=first_file.name,
                )
        else:
            form = RpcOrderForm()

        return render(
            request,
            "core/rpc_order_form.html",
            {
                "automation": automation,
                "form": form,
            },
        )

    # --- Branch: Bucket Metrics – any automation whose name contains it -----
     # --- Branch: Bucket Metrics – any automation whose name contains it -----
    elif "bucket metrics" in name_normalized:
        return redirect("bucket_metrics")

    # --- Branch: Pricing Quote Generator -----------------------------------
    elif "pricing quote" in name_normalized or "pricing" in name_normalized:
        # Send them to the pricing workflow UI
        return redirect("pricing_upload")

    # --- Default branch: treat as BOL generator -----------------------------


    # --- Default branch: treat as BOL generator -----------------------------

    if request.method == "POST":
        form = BOLForm(request.POST)
        if form.is_valid():
            output_path = generate_bol_from_form(form.cleaned_data)

            # Record last run time on the automation
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

    return render(
        request,
        "core/run_bol.html",
        {
            "automation": automation,
            "form": form,
        },
    )


@login_required
def bucket_metrics_view(request, automation_id=None):
    """
    Upload a Prognosis spreadsheet and display bucket metrics.

    This view is meant to be wired to an Automation entry like
    "Bucket Metrics – Prognosis Spreadsheet" via a Run button.
    """
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
                        classes="table table-striped table-sm",
                        index=False,
                        border=0,
                    ),
                    "per_customer_month_table": results[
                        "per_customer_month"
                    ].to_html(
                        classes="table table-striped table-sm",
                        index=False,
                        border=0,
                    ),
                    "per_customer_city_item_table": results[
                        "per_customer_city_item"
                    ].to_html(
                        classes="table table-striped table-sm",
                        index=False,
                        border=0,
                    ),
                    "per_customer_city_item_month_table": results[
                        "per_customer_city_item_month"
                    ].to_html(
                        classes="table table-striped table-sm",
                        index=False,
                        border=0,
                    ),
                }
            )
        except Exception as e:
            context["error"] = f"Error reading file: {e}"

    return render(request, "core/bucket_metrics.html", context)

def _get_company_for_request(request):
    """
    For normal users: their owned company.
    For superusers: allow ?company_id=123, otherwise pick the first company.
    """
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
                customer_obj, cust_created = PricingCustomer.objects.get_or_create(
                    company=company,
                    name=r["customer"].strip(),
                )
                if cust_created:
                    created_customers += 1

                # Upsert line WITHOUT overwriting pallet_quantity_pieces
                obj, was_created = PricingQuoteLine.objects.update_or_create(
                    company=company,
                    customer=customer_obj,
                    destination=r["destination"].strip(),
                    product_description=r["product_description"].strip(),
                    defaults={
                        "price_delivered": r["price_delivered"],
                    },
                )

                if was_created:
                    created_lines += 1
                else:
                    updated_lines += 1

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
        {"company": company, "customers": customers},
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
        # inputs: pallet_<line.id>
        for line in lines_qs:
            key = f"pallet_{line.id}"
            if key in request.POST:
                raw = (request.POST.get(key) or "").strip()
                try:
                    line.pallet_quantity_pieces = int(raw) if raw else 0
                    line.save(update_fields=["pallet_quantity_pieces"])
                except ValueError:
                    # ignore invalid values; keep previous
                    pass

        messages.success(request, "Saved pallet quantities.")
        return redirect("pricing_customer_edit", customer_id=customer.id)

    return render(
        request,
        "core/pricing_customer_edit.html",
        {"company": company, "customer": customer, "lines": lines_qs},
    )


@login_required
def pricing_customer_quote_view(request, customer_id):
    """
    HTML quote page (easy to print/save as PDF).
    """
    company = _get_company_for_request(request)
    if not company:
        return HttpResponseForbidden("No company is associated with this user.")

    customer = get_object_or_404(PricingCustomer, id=customer_id, company=company)
    lines = PricingQuoteLine.objects.filter(company=company, customer=customer).order_by(
        "destination", "product_description"
    )

    return render(
        request,
        "core/pricing_quote.html",
        {"company": company, "customer": customer, "lines": lines},
    )

