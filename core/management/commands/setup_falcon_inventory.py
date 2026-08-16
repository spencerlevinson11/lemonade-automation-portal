from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.models import Automation, Company


class Command(BaseCommand):
    help = "Link the FalconFarms login to a customer company and Inventory Availability automation."

    def handle(self, *args, **options):
        User = get_user_model()
        user = User.objects.filter(username__iexact="FalconFarms").first()
        if not user:
            raise CommandError('User "FalconFarms" does not exist.')

        company = Company.objects.filter(owner=user).order_by("id").first()
        if company is None:
            company = Company.objects.create(name="Falcon Farms", owner=user)
            self.stdout.write(self.style.SUCCESS(f"Created company: {company.name}"))

        automation, created = Automation.objects.get_or_create(
            company=company,
            name="Inventory Availability",
            defaults={
                "description": "Read-only bucket inventory availability for customer ordering.",
                "is_active": True,
            },
        )
        verb = "Created" if created else "Found"
        self.stdout.write(self.style.SUCCESS(f"{verb} automation #{automation.pk} for {company.name}."))
