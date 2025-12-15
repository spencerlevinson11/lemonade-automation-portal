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
from .models import Automation, Company
from .automations.bucket_metrics import analyze_prognosis_workbook


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
    elif "bucket metrics" in name_normalized:
        # Send the user to the upload UI for this automation
        return redirect("bucket_metrics")

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
