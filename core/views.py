from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.utils import timezone
from django.http import FileResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods

from .models import Automation, Company
from .bol_generation import generate_bol_from_templates, generate_bol_from_form
from .forms import BOLForm
from .rpcforms import RpcOrderForm
from .rpc_generation import generate_rpc_from_form


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


@require_http_methods(["GET", "POST"])
@login_required
def run_automation(request, pk):
    """
    Run a single automation.

    - If the automation is "Retriever RPC Order", show the RPC form,
      generate the RPC Excel, and (optionally) Outlook drafts.
    - Otherwise, treat it as a BOL automation:
      show the BOL form, generate the BOL workbook, and download it.
    """
    automation = get_object_or_404(
        Automation.objects.select_related("company"),
        pk=pk,
    )

    # Permission check: only superuser or the company owner
    if not (request.user.is_superuser or automation.company.owner == request.user):
        return HttpResponseForbidden("You are not allowed to run this automation.")

    # ---- Branch 1: Retriever RPC automation ----
    if automation.name.strip().lower() == "retriever rpc order":
        if request.method == "POST":
            form = RpcOrderForm(request.POST)
            if form.is_valid():
                files = generate_rpc_from_form(form.cleaned_data)

                # Record last run time on the automation
                automation.last_run_at = timezone.now()
                automation.save(update_fields=["last_run_at"])

                # For now, return the first generated file (if multiple)
                first_file = files[0]

                messages.success(
                    request,
                    "RPC generated. Outlook drafts were created if Outlook/pywin32 "
                    "is available on this machine.",
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

    # ---- Branch 2: default = BOL automation ----
    if request.method == "POST":
        form = BOLForm(request.POST)
        if form.is_valid():
            output_path = generate_bol_from_form(form.cleaned_data)

            # Record last run time on the automation
            automation.last_run_at = timezone.now()
            automation.save(update_fields=["last_run_at"])

            messages.success(
                request,
                f"Generated BOL for {automation.company.name}",
            )

            return FileResponse(
                open(output_path, "rb"),
                as_attachment=True,
                filename=output_path.name,
            )
    else:
        # Empty BOL form on first load
        form = BOLForm()

    return render(
        request,
        "core/run_bol.html",
        {
            "automation": automation,
            "form": form,
        },
    )


def custom_logout(request):
    """
    Simple logout view that allows GET requests.
    Logs the user out, then redirects to the login page.
    """
    logout(request)
    return redirect("login")
