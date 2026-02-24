# core/forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    ProjectPlanEntry,
    ScheduleActivity,
    ScheduleGlobalNote,
    OrderContainer,
    OrderContainerLine,
    OrderContainerDocument,
)


class MultipleFileInput(forms.ClearableFileInput):
    """A file input widget that supports selecting multiple files.

    In Django 5.x, FileInput/ClearableFileInput will raise ValueError if
    attrs contains {"multiple": True} unless allow_multiple_selected=True.
    """

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A FileField that can validate and return multiple uploaded files."""

    def clean(self, data, initial=None):
        # When using a widget that allows selecting multiple files, Django
        # gives us a list/tuple of UploadedFile objects.
        if isinstance(data, (list, tuple)):
            cleaned = []
            errors = []
            for item in data:
                try:
                    cleaned.append(super().clean(item, initial))
                except ValidationError as e:
                    errors.extend(e.error_list)
            if errors:
                raise ValidationError(errors)
            return cleaned
        return super().clean(data, initial)


class BOLForm(forms.Form):
    # These labels mirror your "BOL INFORMATION SHEET" rows

    # Row 1
    shipper_number = forms.CharField(
        label="Shippers #",
        required=False,
        help_text="Internal shipper number (e.g., 48, 50)."
    )

    # Row 2
    carrier = forms.CharField(
        label="Carrier",
        required=False,
    )

    # Row 3
    quote_number = forms.CharField(
        label="Quote #",
        required=False,
    )

    # Row 4
    pro_number = forms.CharField(
        label="PRO #",
        required=False,
    )

    # Row 5
    ship_date = forms.DateField(
        label="Date",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    # Row 6
    po_number = forms.CharField(
        label="PO #",
        required=False,
    )

    # Row 7# core/forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    ProjectPlanEntry,
    ScheduleActivity,
    ScheduleGlobalNote,
    OrderContainer,
    OrderContainerLine,
    OrderContainerDocument,
)


class MultipleFileInput(forms.ClearableFileInput):
    """A file input widget that supports selecting multiple files.

    In Django 5.x, FileInput/ClearableFileInput will raise ValueError if
    attrs contains {"multiple": True} unless allow_multiple_selected=True.
    """

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A FileField that can validate and return multiple uploaded files."""

    def clean(self, data, initial=None):
        # When using a widget that allows selecting multiple files, Django
        # gives us a list/tuple of UploadedFile objects.
        if isinstance(data, (list, tuple)):
            cleaned = []
            errors = []
            for item in data:
                try:
                    cleaned.append(super().clean(item, initial))
                except ValidationError as e:
                    errors.extend(e.error_list)
            if errors:
                raise ValidationError(errors)
            return cleaned
        return super().clean(data, initial)


class BOLForm(forms.Form):
    # These labels mirror your "BOL INFORMATION SHEET" rows

    # Row 1
    shipper_number = forms.CharField(
        label="Shippers #",
        required=False,
        help_text="Internal shipper number (e.g., 48, 50)."
    )

    # Row 2
    carrier = forms.CharField(
        label="Carrier",
        required=False,
    )

    # Row 3
    quote_number = forms.CharField(
        label="Quote #",
        required=False,
    )

    # Row 4
    pro_number = forms.CharField(
        label="PRO #",
        required=False,
    )

    # Row 5
    ship_date = forms.DateField(
        label="Date",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    # Row 6
    po_number = forms.CharField(
        label="PO #",
        required=False,
    )

    # Row 7
    seal_number = forms.CharField(
        label="Seal #",
        required=False,
    )

    # Row 8
    consignee_name = forms.CharField(
        label="Consignee Name",
        required=True,
    )

    # Row 9
    consignee_street_address = forms.CharField(
        label="Consignee Street Address",
        required=True,
    )

    # Row 10
    consignee_city_state_zip = forms.CharField(
        label="Consignee City, State, Zip",
        required=True,
    )

    # Row 11
    attention = forms.CharField(
        label="Attn:",
        required=False,
    )

    # Row 12
    num_pallets = forms.IntegerField(
        label="No. of Pallets",
        required=True,
    )

    # Row 13
    article_description = forms.CharField(
        label="Article Description",
        required=True,
        initial="Plastic Bouquet Buckets",
    )

    # Row 14
    specific_article = forms.CharField(
        label="Specific Article",
        required=True,
        help_text="e.g., 10 liter wide classic buckets",
    )

    # Row 15
    amount_of_article = forms.CharField(
        label="Amount of Article",
        required=True,
        help_text="e.g., (2 x 2660) = 5320 buckets",
    )

    # Row 16
    pallet_dimensions = forms.CharField(
        label="Article Pallet Dimensions",
        required=True,
        help_text="e.g., 2 pallets @ 40 x 45 x 94",
    )

    # Row 17
    weight = forms.CharField(
        label="Weight",
        required=True,
        help_text="e.g., 2100 lbs",
    )

    # Row 18
    freight_class = forms.CharField(
        label="Class",
        required=True,
        help_text="e.g., 92",
    )


# =========================
# Pricing Quote Forms
# =========================

class PricingUploadForm(forms.Form):
    file = forms.FileField(
        label="Pricing CSV file",
        help_text="Upload your pricing matrix CSV."
    )


# =========================
# RPC -> Master Spreadsheet Formatter
# =========================

class RpcMasterFormatUploadForm(forms.Form):
    files = MultipleFileField(
        label="RPC order spreadsheet(s) (.xlsx)",
        help_text=(
            "Upload one or more RPC order Excel files (e.g., RPC#5670 Miami.xlsx). "
            "You can select multiple files at once."
        ),
        # Django requires a widget with allow_multiple_selected=True.
        # We process via request.FILES.getlist('files') in the view.
        widget=MultipleFileInput(attrs={"multiple": True}),
    )


class TipEntryForm(forms.Form):
    # Step 3 edit: job type selector
    JOB_TYPE_CHOICES = [
        ("well_bartender", "Well-bartender"),
        ("bartender", "Bartender"),
        ("server", "Server"),
        ("mix_well_server", "Mix of well and serving"),
        ("mix_bartender_server", "Mix of bartender and serving"),
    ]

    tip_date = forms.DateField(
        label="Tip date",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
        initial=timezone.localdate,
        help_text="Defaults to today, but you can change it.",
    )

    job_type = forms.ChoiceField(
        label="Job type",
        required=True,
        choices=JOB_TYPE_CHOICES,
        initial="bartender",
        help_text="Select what you worked this shift.",
    )

    shift_start = forms.TimeField(
        label="Shift start",
        required=True,
        widget=forms.TimeInput(attrs={"type": "time"}),
        help_text="Example: 5:00 PM",
    )

    shift_end = forms.TimeField(
        label="Shift end",
        required=True,
        widget=forms.TimeInput(attrs={"type": "time"}),
        help_text="Example: 11:00 PM (if it ends after midnight, still enter the time, e.g. 2:00 AM)",
    )

    tips_total = forms.DecimalField(
        label="Total tips",
        required=True,
        min_value=0,
        decimal_places=2,
        max_digits=10,
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )

    notes = forms.CharField(
        label="Notes",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Any notes about the shift..."}),
    )


class PricingPalletQuantityUpdateForm(forms.Form):
    """
    Used for updating pallet quantities for a single customer's quote lines.
    We'll render inputs manually in the template, so this is optional,
    but it's useful if you want basic validation later.
    """
    # We intentionally don't declare dynamic fields here.
    # We'll read POST keys like pallet_<line_id> in the view.
    pass



class ProjectPlanEntryForm(forms.ModelForm):
    # Used for editing existing entries (your view reads this)
    entry_id = forms.IntegerField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = ProjectPlanEntry
        fields = [
            "project_name",
            "estimated_cost",
            "estimated_time_hours",
            "estimated_difficulty",
            "risk_factor",
            "priority_level",
            "weeks_to_complete",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def clean(self):
        cleaned = super().clean()

        priority = cleaned.get("priority_level")
        weeks = cleaned.get("weeks_to_complete")

        # If urgent, weeks_to_complete is required
        if priority == ProjectPlanEntry.PRIORITY_URGENT:
            if weeks in (None, ""):
                raise ValidationError({"weeks_to_complete": "Required for Urgent projects."})
        else:
            # If not urgent, keep it blank so you don't store stale values
            cleaned["weeks_to_complete"] = None

        return cleaned


    class Meta:
        model = ProjectPlanEntry
        fields = [
            "project_name",
            "estimated_cost",
            "estimated_time_hours",
            "estimated_difficulty",
            "risk_factor",
            "priority_level",
            "weeks_to_complete",
            "notes",
        ]
        widgets = {
            "project_name": forms.TextInput(attrs={"placeholder": "e.g., Replace bathroom faucet"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional notes / parts needed / links"}),
        }


# =========================
# Order Tracking Forms
# =========================



class ScheduleActivityForm(forms.ModelForm):
    class Meta:
        model = ScheduleActivity
        fields = [
            "date",
            "start_time",
            "end_time",
            "title",
            "category",
            "assigned_to",
            "notes",
            "is_recurring",
            "repeat_every",
            "repeat_unit",
            "repeat_until",
            "status",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "repeat_every": forms.NumberInput(attrs={"min": 1, "inputmode": "numeric"}),
            "repeat_until": forms.DateInput(attrs={"type": "date"}),
            "is_recurring": forms.CheckboxInput(attrs={"style": "width:auto;"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get("start_time")
        et = cleaned.get("end_time")
        if st and et and et < st:
            raise ValidationError("End time cannot be earlier than start time.")

        is_recurring = cleaned.get("is_recurring")
        repeat_every = cleaned.get("repeat_every")
        repeat_unit = cleaned.get("repeat_unit")
        repeat_until = cleaned.get("repeat_until")

        if not is_recurring:
            # Normalize recurrence fields when recurrence is off
            cleaned["repeat_every"] = 1
            cleaned["repeat_unit"] = "weeks"
            cleaned["repeat_until"] = None
        else:
            if not repeat_every or repeat_every < 1:
                raise ValidationError("Repeat every must be at least 1.")
            if repeat_unit not in {"days", "weeks", "months"}:
                raise ValidationError("Invalid repeat unit.")
            # If repeat_until is before the start date, it's unusable
            d = cleaned.get("date")
            if repeat_until and d and repeat_until < d:
                raise ValidationError("Repeat-until date cannot be earlier than the start date.")
        return cleaned


class ScheduleGlobalNoteForm(forms.ModelForm):
    class Meta:
        model = ScheduleGlobalNote
        fields = ["notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 5, "placeholder": "Always-on notes (not tied to a date)..."}),
        }


class OrderContainerForm(forms.ModelForm):
    assigned_to = forms.ChoiceField(
        required=False,
        choices=[("", "—"), ("Spencer", "Spencer"), ("Jaime", "Jaime")],
        widget=forms.RadioSelect,
    )

    class Meta:
        model = OrderContainer
        fields = [
            "customer_name",
            "location_name",
            "po_number",
            "requested_date",
            "requested_date_text",
            "requested_asap",
            "status",
            "assigned_to",
            "rpc_number",
            "loading_date",
            "etd",
            "eta",
            "eta_city",
            "estimated_delivery_date",
            "booking_number",
            "bill_of_lading_number",
            "container_number",
            "carrier",
            "vessel_name",
            "vessel_mmsi",
            "vessel_imo",
            "notes",
        ]
        widgets = {
            "status": forms.TextInput(attrs={"placeholder": "e.g., Booked, On water, Customs hold, Delivered..."}),
            "requested_date": forms.DateInput(attrs={"type": "date"}),
            "requested_date_text": forms.TextInput(attrs={"placeholder": "e.g., first week of February"}),
            "loading_date": forms.DateInput(attrs={"type": "date"}),
            "etd": forms.DateInput(attrs={"type": "date"}),
            "eta": forms.DateInput(attrs={"type": "date"}),
            "estimated_delivery_date": forms.DateInput(attrs={"type": "date"}),
            "status": forms.TextInput(attrs={"placeholder": "e.g., booked, on water, customs hold, delivered"}),
            "eta_city": forms.TextInput(attrs={"placeholder": "e.g., Chicago"}),
            "container_number": forms.TextInput(attrs={"placeholder": "e.g., TCNU1825001"}),
            "carrier": forms.TextInput(attrs={"placeholder": "e.g., MAERSK, MSC, CMA_CGM (optional)"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional notes..."}),
            "vessel_name": forms.TextInput(attrs={"placeholder": "e.g., CMA CGM Marco Polo"}),
            "vessel_mmsi": forms.NumberInput(attrs={"placeholder": "9-digit MMSI (recommended)", "inputmode": "numeric"}),
            "vessel_imo": forms.NumberInput(attrs={"placeholder": "7-digit IMO (optional)", "inputmode": "numeric"}),
        }

    def clean(self):
        """Enforce mutual exclusivity for requested date fields.

        Priority:
        1) ASAP checkbox
        2) Requested date text
        3) Requested date
        """
        cleaned = super().clean()
        asap = bool(cleaned.get("requested_asap"))
        text = (cleaned.get("requested_date_text") or "").strip()

        if asap:
            cleaned["requested_date"] = None
            cleaned["requested_date_text"] = ""
            return cleaned

        if text:
            cleaned["requested_date"] = None
            cleaned["requested_date_text"] = text
            return cleaned

        cleaned["requested_date_text"] = ""
        return cleaned


class OrderContainerDocumentForm(forms.ModelForm):
    class Meta:
        model = OrderContainerDocument
        fields = ["file", "label"]
        widgets = {
            "label": forms.TextInput(attrs={"placeholder": "Optional label (e.g., BOL, Booking, Invoice)"}),
        }


class OrderContainerLineForm(forms.ModelForm):
    class Meta:
        model = OrderContainerLine
        fields = ["item_description", "pallets", "units_per_pallet"]
        widgets = {
            "item_description": forms.TextInput(attrs={"placeholder": "e.g., 5 liter vase"}),
            "pallets": forms.NumberInput(attrs={"min": 0, "inputmode": "numeric"}),
            "units_per_pallet": forms.NumberInput(attrs={"min": 0, "inputmode": "numeric"}),
        }







