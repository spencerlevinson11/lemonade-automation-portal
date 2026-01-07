# core/forms.py
from django import forms
from django.utils import timezone

from .models import ProjectPlanEntry


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
    entry_id = forms.IntegerField(required=False, widget=forms.HiddenInput())

def clean(self):
    cleaned = super().clean()
    priority = cleaned.get("priority_level")
    weeks = cleaned.get("weeks_to_complete")
    # Priority 4 = Urgent (see model constants)
    if priority == ProjectPlanEntry.PRIORITY_URGENT:
        if not weeks:
            self.add_error("weeks_to_complete", "For Urgent projects, please enter how many weeks you have to complete it.")
    else:
        # Not urgent: clear any value
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



