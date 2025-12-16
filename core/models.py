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
