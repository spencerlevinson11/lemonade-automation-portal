from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from decimal import Decimal
from django.core.validators import MinValueValidator
from datetime import timedelta


class Company(models.Model):
    # Each client / business you work with
    name = models.CharField(max_length=255)
    contact_email = models.EmailField(blank=True)
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="companies",
        null=True,
        blank=True,
    )

    def __str__(self) -> str:
        return self.name


class Automation(models.Model):
    # A specific automation you’ve set up for a company
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="automations",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.company.name})"


# =========================
# Pricing Quote Data Models
# =========================

class PricingCustomer(models.Model):
    """
    A customer of a Company (ex: Elite, Bay State, Native IL).
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="pricing_customers",
    )
    name = models.CharField(max_length=255)

    class Meta:
        unique_together = ("company", "name")

    def __str__(self) -> str:
        return f"{self.name} ({self.company.name})"


class PricingQuote(models.Model):
    """
    Optional: a saved quote "header" for a specific customer.
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="pricing_quotes",
    )
    customer = models.ForeignKey(
        PricingCustomer,
        on_delete=models.CASCADE,
        related_name="quotes",
    )
    title = models.CharField(max_length=255, default="Pricing Quote")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.customer.name} - {self.company.name}"


class TipEntry(models.Model):
    # ---- Job type choices ----
    JOB_WELL_BARTENDER = "well_bartender"
    JOB_BARTENDER = "bartender"
    JOB_SERVER = "server"
    JOB_MIX_WELL_SERVER = "mix_well_server"
    JOB_MIX_BARTENDER_SERVER = "mix_bartender_server"

    JOB_TYPE_CHOICES = [
        (JOB_WELL_BARTENDER, "Well-bartender"),
        (JOB_BARTENDER, "Bartender"),
        (JOB_SERVER, "Server"),
        (JOB_MIX_WELL_SERVER, "Mix of well and serving"),
        (JOB_MIX_BARTENDER_SERVER, "Mix of bartender and serving"),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="tip_entries",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tip_entries",
    )

    # The date the tips were earned (defaults to "today" in the form/view)
    tip_date = models.DateField()

    # NEW: what role she worked that shift
    job_type = models.CharField(
        max_length=32,
        choices=JOB_TYPE_CHOICES,
        default=JOB_BARTENDER,
    )

    # Shift times (time-of-day)
    shift_start = models.TimeField()
    shift_end = models.TimeField()

    # Total tips for that shift
    tips_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-tip_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username} {self.tip_date} ${self.tips_total}"

    def shift_duration_hours(self) -> float:
        """
        Returns shift duration in hours. If end is earlier than start,
        we assume the shift ended after midnight (next day).
        """
        start_minutes = self.shift_start.hour * 60 + self.shift_start.minute
        end_minutes = self.shift_end.hour * 60 + self.shift_end.minute

        if end_minutes < start_minutes:
            end_minutes += 24 * 60  # crossed midnight

        minutes = end_minutes - start_minutes
        return round(minutes / 60.0, 2)

    def tips_per_hour(self) -> float:
        """Return tips per hour for this entry.

        Analytics uses this helper. It does not affect stored data.
        """
        hours = float(self.shift_duration_hours() or 0)
        if hours <= 0:
            return 0.0
        return float(self.tips_total) / hours


class TipDeposit(models.Model):
    """A "banking" event for the Tip Tracker.

    This lets the user click "deposit" to move tips earned since the last deposit
    into an all-time banked total, while leaving raw tip entries intact.
    Analytics/metrics are computed from TipEntry and are therefore unaffected.
    """

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="tip_deposits",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tip_deposits",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
    )

    deposited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-deposited_at"]

    def __str__(self) -> str:
        return f"{self.user.username} {self.deposited_at:%Y-%m-%d} ${self.amount}"


class PricingQuoteLine(models.Model):
    """
    One line item for one customer’s quote.
    Pallet qty persists until edited.
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="pricing_quote_lines",
    )
    customer = models.ForeignKey(
        PricingCustomer,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    # Optional: keep if you want “quote versions”
    quote = models.ForeignKey(
        PricingQuote,
        on_delete=models.CASCADE,
        related_name="lines",
        null=True,
        blank=True,
    )

    destination = models.CharField(max_length=255)
    product_description = models.CharField(max_length=255)

    price_delivered = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal("0.0"),
    )

    pallet_quantity_pieces = models.IntegerField(default=0)
    include_in_quote = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("company", "customer", "destination", "product_description")

    def __str__(self) -> str:
        return f"{self.customer.name} | {self.destination} | {self.product_description}"


class ProjectPlanEntry(models.Model):
    # IMPORTANT: Explicit id to match the existing migration that created this table with AutoField
    id = models.AutoField(primary_key=True)

    PRIORITY_LOW = 1
    PRIORITY_MEDIUM = 2
    PRIORITY_HIGH = 3
    PRIORITY_URGENT = 4

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    # 1 (easy) → 5 (very hard)
    DIFFICULTY_CHOICES = [(i, str(i)) for i in range(1, 6)]

    # 1 (low risk) → 5 (high risk)
    RISK_CHOICES = [(i, str(i)) for i in range(1, 6)]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="project_plans",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project_plans",
    )

    project_name = models.CharField(max_length=255)
    notes = models.TextField(blank=True)

    estimated_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=Decimal("0.00"),
    )

    estimated_time_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=Decimal("0.00"),
        help_text="Estimated total hours.",
    )

    estimated_difficulty = models.IntegerField(choices=DIFFICULTY_CHOICES, default=3)
    priority_level = models.IntegerField(choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    risk_factor = models.IntegerField(choices=RISK_CHOICES, default=3, help_text="Overall risk factor (1-5).")

    # If urgent, how many weeks do you have to complete it?
    weeks_to_complete = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="If priority is Urgent, number of weeks to complete the project.",
    )

    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority_level", "-updated_at", "-created_at"]

    def due_date(self):
        """
        Return a due date if weeks_to_complete is set (Urgent projects).
        """
        if not self.weeks_to_complete:
            return None
        # Use created_at as the start point (consistent & always present)
        return self.created_at + timedelta(weeks=int(self.weeks_to_complete))

    def weeks_remaining(self):
        """
        Number of whole weeks remaining until due_date (can be negative).
        """
        due = self.due_date()
        if due is None:
            return None
        delta = due - timezone.now()
        return int(delta.days // 7)

    def __str__(self) -> str:
        return f"{self.project_name} ({self.company.name})"

# =========================
# Sea Container Order Tracking
# =========================

# JSONCargo shipping line mapping (id -> display label + query param)
JSONCARGO_SHIPPING_LINE_CHOICES = [
    ("", "—"),
    ("0010", "Maersk (0010)"),
    ("0011", "Hapag-Lloyd (0011)"),
    ("0012", "HMM (0012)"),
    ("0013", "ONE (0013)"),
    ("0014", "Evergreen (0014)"),
    ("0015", "MSC (0015)"),
    ("0016", "CMA CGM (0016)"),
    ("0017", "COSCO (0017)"),
    ("0018", "ZIM (0018)"),
    ("0019", "Yang Ming (0019)"),
]

JSONCARGO_SHIPPING_LINE_PARAM_BY_ID = {
    "0010": "MAERSK",
    "0011": "HAPAG_LLOYD",
    "0012": "HMM",
    "0013": "ONE",
    "0014": "EVERGREEN",
    "0015": "MSC",
    "0016": "CMA_CGM",
    "0017": "COSCO",
    "0018": "ZIM",
    "0019": "YANG_MING",
}

class OrderContainer(models.Model):
    """
    Tracks an in-transit sea container order, scoped to a Company.
    Customer + Location are stored as plain text so "Elite Flower Group - Miami"
    can remain separate from "Elite Flower Group - Lebanon".
    """
    # Status is free-text (user requested custom status).

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="order_containers",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_order_containers",
    )

    customer_name = models.CharField(max_length=255)
    location_name = models.CharField(max_length=255, blank=True)

    po_number = models.CharField(max_length=64, blank=True)
    requested_date = models.DateField(null=True, blank=True)
    # Optional requested date text when customer provides a fuzzy window (e.g., "first week of February").
    requested_date_text = models.CharField(max_length=255, blank=True)
    # If checked, the customer wants this order ASAP (requested_date can be blank).
    requested_asap = models.BooleanField(default=False)

    status = models.CharField(max_length=128, blank=True)

    # Archived orders are excluded from JSONCargo syncing + dashboard tracking.
    # Use this to keep historical delivered orders without cluttering the tracker.
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    # Who owns this order?
    assigned_to = models.CharField(max_length=32, blank=True)

    rpc_number = models.CharField(max_length=64, blank=True)  # your internal RPC#
    loading_date = models.DateField(null=True, blank=True)

    etd = models.DateField(null=True, blank=True)
    eta = models.DateField(null=True, blank=True)
    # Optional destination city text shown alongside ETA (e.g., "Chicago").
    eta_city = models.CharField(max_length=128, blank=True)
    estimated_delivery_date = models.DateField(null=True, blank=True)

    booking_number = models.CharField(max_length=128, blank=True)
    bill_of_lading_number = models.CharField(max_length=128, blank=True)

    # Container number used for API tracking (e.g., TCNU1825001)
    container_number = models.CharField(max_length=32, blank=True)

    # Optional shipping line hint for JSONCargo (use when a prefix is third-party/shared)
    shipping_line_id = models.CharField(max_length=4, choices=JSONCARGO_SHIPPING_LINE_CHOICES, blank=True)

    # Optional carrier / shipping line for API tracking.
    # JSONCargo uses this to disambiguate containers that share a third-party prefix.
    # Examples: MAERSK, MSC, CMA_CGM, HAPAG_LLOYD, ONE
    carrier = models.CharField(max_length=64, blank=True)

    # Optional vessel metadata (for live AIS mapping)
    vessel_name = models.CharField(max_length=255, blank=True)
    vessel_mmsi = models.BigIntegerField(null=True, blank=True)
    vessel_imo = models.BigIntegerField(null=True, blank=True)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def jsoncargo_shipping_line_param(self) -> str | None:
        """Return the JSONCargo `shipping_line` query param value for this order.

        Priority:
          1) shipping_line_id (dropdown) -> mapped enum (MAERSK, MSC, ...)
          2) legacy free-text carrier field (already stored on some rows)
        """
        sid = (self.shipping_line_id or "").strip()
        if sid and sid in JSONCARGO_SHIPPING_LINE_PARAM_BY_ID:
            return JSONCARGO_SHIPPING_LINE_PARAM_BY_ID[sid]

        legacy = (getattr(self, "carrier", "") or "").strip()
        if legacy:
            # normalize common user inputs
            legacy_norm = legacy.upper().replace(" ", "_").replace("-", "_")
            return legacy_norm
        return None

    def __str__(self) -> str:
        loc = f" - {self.location_name}" if self.location_name else ""
        base = f"{self.customer_name}{loc}"
        if self.po_number:
            base += f" | PO {self.po_number}"
        return base


class OrderContainerTrackingUpdate(models.Model):
    """Proposed tracking updates pulled from JSONCargo.

    We do NOT auto-apply these changes. A user must approve them first.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    container = models.ForeignKey(
        OrderContainer,
        on_delete=models.CASCADE,
        related_name="tracking_updates",
    )

    proposed_eta = models.DateField(null=True, blank=True)
    proposed_eta_city = models.CharField(max_length=128, blank=True)


    KIND_CHANGE = "change"
    KIND_NO_CHANGE = "no_change"
    KIND_ERROR = "error"
    KIND_CHOICES = [
        (KIND_CHANGE, "Change"),
        (KIND_NO_CHANGE, "No change"),
        (KIND_ERROR, "Error"),
    ]

    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_CHANGE)
    note = models.TextField(blank=True)

    # "last_updated" timestamp from JSONCargo, if provided.
    source_last_updated = models.DateTimeField(null=True, blank=True)

    # Store the raw payload for debugging.
    source_payload = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)

    decided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_tracking_update_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Update for {self.container_id} ({self.status})"


class OrderContainerLine(models.Model):
    """
    One content line inside a container (supports mixed containers).
    Example: "5 liter vase (12 x 6210) = 74520"
    """
    container = models.ForeignKey(
        OrderContainer,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    item_description = models.CharField(max_length=255)
    pallets = models.PositiveIntegerField(default=0)
    units_per_pallet = models.PositiveIntegerField(default=0)
    total_units = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        # Auto-calc total if both inputs present
        try:
            self.total_units = int(self.pallets or 0) * int(self.units_per_pallet or 0)
        except Exception:
            pass
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.item_description} ({self.pallets} x {self.units_per_pallet})"


class OrderContainerDocument(models.Model):
    """PDF or other document attached to an OrderContainer."""

    container = models.ForeignKey(
        OrderContainer,
        on_delete=models.CASCADE,
        related_name="documents",
    )

    file = models.FileField(upload_to="order_docs/")
    label = models.CharField(max_length=255, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self) -> str:
        return self.label or (self.file.name if self.file else "Document")


class OrderContainerImportFile(models.Model):
    """Uploaded spreadsheet used for one-time OrderContainer imports."""

    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_container_import_files",
    )
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_order_container_import_files",
    )

    label = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to="imports/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self) -> str:
        base = self.label or (self.file.name if self.file else "Import File")
        if self.company_id:
            base += f" ({self.company.name})"
        return base


class ScheduleActivity(models.Model):
    """Simple company scheduler activity (week-view).

    V1: one-off activities (no recurrence).
    """

    STATUS_PLANNED = "planned"
    STATUS_DONE = "done"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned"),
        (STATUS_DONE, "Done"),
        (STATUS_CANCELED, "Canceled"),
    ]

    CAT_DELIVERY = "delivery"
    CAT_PRODUCTION = "production"
    CAT_INVENTORY = "inventory"
    CAT_SALES = "sales"
    CAT_ADMIN = "admin"
    CAT_OTHER = "other"

    CATEGORY_CHOICES = [
        (CAT_DELIVERY, "Delivery"),
        (CAT_PRODUCTION, "Production"),
        (CAT_INVENTORY, "Inventory"),
        (CAT_SALES, "Sales"),
        (CAT_ADMIN, "Admin"),
        (CAT_OTHER, "Other"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="schedule_activities")

    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    title = models.CharField(max_length=160)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, default=CAT_OTHER)
    assigned_to = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)

    # Recurrence (optional)
    is_recurring = models.BooleanField(default=False)
    repeat_every = models.PositiveSmallIntegerField(default=1)
    repeat_unit = models.CharField(
        max_length=8,
        choices=[
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        default="weeks",
    )
    repeat_until = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PLANNED)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "start_time", "created_at", "id"]

    def __str__(self) -> str:
        when = self.date.isoformat()
        return f"{when} - {self.title}"


class ScheduleGlobalNote(models.Model):
    """Always-on notes for the Scheduling dashboard.

    These notes are not tied to any specific date and are shown at the top of
    the scheduler for a company.
    """

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="schedule_global_note",
    )
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Schedule Notes - {self.company.name}"


# =========================
# Microsoft Graph OAuth Token
# =========================

class MicrosoftGraphToken(models.Model):
    """Stores delegated Microsoft Graph tokens per Django user."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="ms_graph_token",
    )

    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def __str__(self) -> str:
        return f"MicrosoftGraphToken({self.user.username})"


# =========================
# Permaculture Garden Planner
# =========================


class GardenMap(models.Model):
    """Stores a user's editable garden map (zones + objects) as JSON."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="garden_map",
    )

    # Grid dimensions are stored so users can resize later.
    rows = models.PositiveSmallIntegerField(default=12)
    cols = models.PositiveSmallIntegerField(default=18)

    # JSON payload schema (kept flexible for future upgrades):
    # {
    #   "version": 1,
    #   "cells": {
    #       "r-c": {"kind":"bed|path|water|tree|sun|shade|custom", "label":"...", "notes":"..."}
    #   }
    # }
    data = models.JSONField(default=dict, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"GardenMap({self.user.username})"


class PlantProfile(models.Model):
    """Cached plant profiles enriched from external sources (and/or manual curation).

    NOTE: There is no single source that provides *complete* companion + zone + care
    metadata for "every plant". This model stores a merged/normalized profile for the
    plants the user actually searches/uses, and can be extended with additional
    providers over time.
    """

    scientific_name = models.CharField(max_length=255, unique=True)
    common_name = models.CharField(max_length=255, blank=True, default="")

    # USDA hardiness zones (string so we can support ranges like "4-10")
    hardiness_zones = models.CharField(max_length=64, blank=True, default="")

    sunlight = models.CharField(max_length=128, blank=True, default="")
    water = models.CharField(max_length=128, blank=True, default="")
    nitrogen = models.CharField(max_length=128, blank=True, default="")

    benefits = models.TextField(blank=True, default="")
    drawbacks = models.TextField(blank=True, default="")

    companions_good = models.JSONField(default=list, blank=True)
    companions_bad = models.JSONField(default=list, blank=True)

    # Track where we got the data ("perenual", "openfarm", "curated", ...)
    source = models.CharField(max_length=64, blank=True, default="")
    raw = models.JSONField(default=dict, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.scientific_name













































































