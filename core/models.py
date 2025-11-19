from django.db import models
from django.contrib.auth.models import User


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
