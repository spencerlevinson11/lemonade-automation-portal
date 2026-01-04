from django.db import models
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

    def __str__(self):
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

    def __str__(self):
        return f"{self.name} ({self.company.name})"


# =========================
# Pricing Quote Data Models
# =========================

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

    def __str__(self):
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

    def __str__(self):
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

    def __str__(self):
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
        hrs = self.shift_duration_hours()
        if hrs <= 0:
            return 0.0
        return float(self.tips_total) / hrs


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

    def __str__(self):
        return f"{self.customer.name} | {self.destination} | {self.product_description}"

