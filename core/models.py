from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal


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

class PricingQuote(models.Model):
    """
    A saved quote "header" for a company (client).
    You can generate a new PDF from this any time.
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="pricing_quotes",
    )

    # Optional metadata you might want later
    title = models.CharField(max_length=255, default="Pricing Quote")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.company.name}"


class PricingQuoteLine(models.Model):
    """
    One line item in a company's pricing quote.
    IMPORTANT: pallet_quantity_pieces persists between runs until edited.
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="pricing_quote_lines",
    )

    # If you want lines tied to a specific "quote header", keep this FK.
    # If you prefer "one persistent set of lines per company", you can remove this
    # and just generate from company lines directly.
    quote = models.ForeignKey(
        PricingQuote,
        on_delete=models.CASCADE,
        related_name="lines",
        null=True,
        blank=True,
    )

    destination = models.CharField(max_length=255)
    product_description = models.CharField(max_length=255)

    # Delivered price from CSV
    price_delivered = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal("0.0"),
    )

    # Persisted quantity input (your requirement)
    pallet_quantity_pieces = models.IntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("company", "destination", "product_description")

    def __str__(self):
        return f"{self.company.name} | {self.destination} | {self.product_description}"
