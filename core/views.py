from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.core.mail import send_mail
from .bol_generation import generate_bol_from_templates, generate_bol_from_form
from .forms import BOLForm
from django.utils import timezone
from django.http import FileResponse, HttpResponseForbidden

from .models import Automation, Company


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


@login_required
def run_automation(request, pk):
    """
    Manually run a single automation:
    - send 'hello world' to the company's contact_email
    - update last_run_at
    """

    # Load the automation + its company
    automation = get_object_or_404(
        Automation.objects.select_related("company"),
        pk=pk,
    )

    # Permission check:
    # - superusers can run anything
    # - non-superusers can only run automations for their own company
    if not request.user.is_superuser:
        if automation.company.owner != request.user:
            messages.error(request, "You do not have permission to run this automation.")
            return redirect("dashboard")

    # Make sure there is somewhere to send the email
    if not automation.company.contact_email:
        messages.error(
            request,
            f"Company '{automation.company.name}' has no contact email set. "
            "Add one in the admin before running this automation.",
        )
        return redirect("dashboard")

    # Send the email (using console backend for now)
    send_mail(
        subject=f"[TEST] {automation.name}",
        message="hello world",
        from_email=None,  # uses DEFAULT_FROM_EMAIL from settings
        recipient_list=[automation.company.contact_email],
        fail_silently=False,
    )

    # Update last_run_at
    automation.last_run_at = timezone.now()
    automation.save(update_fields=["last_run_at"])

    messages.success(
        request,
        f"Automation '{automation.name}' ran successfully. "
        f"Email sent to {automation.company.contact_email}.",
    )

    return redirect("dashboard")


def custom_logout(request):
    """
    Simple logout view that allows GET requests.
    Logs the user out, then redirects to the login page.
    """
    logout(request)
    return redirect("login")

from django.views.decorators.http import require_http_methods
# (put this with your other imports if you like)


@require_http_methods(["GET", "POST"])
@login_required
def run_automation(request, pk):
    """
    For now, this treats the automation as a "Generate BOL" automation.

    - GET: display a BOL form (fields matching BOL INFORMATION SHEET)
    - POST: validate the form, generate a filled-out BOL Excel, and download it
    """
    automation = get_object_or_404(Automation, pk=pk)

    # Permission check: only superuser or the company owner
    if not (request.user.is_superuser or automation.company.owner == request.user):
        return HttpResponseForbidden("You are not allowed to run this automation.")

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
        # Empty form on first load
        form = BOLForm()

    return render(
        request,
        "core/run_bol.html",
        {
            "automation": automation,
            "form": form,
        },
    )

