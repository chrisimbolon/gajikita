"""
One command to get a working demo for testing the Absen page on a real phone:
a demo company, one site pinned where you are, a day shift, and one worker
with phone + PIN login. Safe to run again (moves the pin if you pass new coordinates).

    python manage.py seed_demo_attendance --lat 1.130000 --lng 104.050000 --phone 081234567890

Get --lat/--lng from Google Maps: long-press the spot, the numbers appear at the top.
"""
from datetime import time
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.employees.models import Employee
from apps.employees.worker_login import enable_login
from apps.organizations.models import Organization
from apps.sites.models import Shift, Site

ORG_NAME = "PT Demo GajiKita"


class Command(BaseCommand):
    help = "Create (or refresh) a demo company, site, shift and worker login for testing attendance."

    def add_arguments(self, parser):
        parser.add_argument("--lat", type=Decimal, required=True)
        parser.add_argument("--lng", type=Decimal, required=True)
        parser.add_argument("--radius", type=int, default=150)
        parser.add_argument("--phone", required=True)
        parser.add_argument("--pin", default=None)

    def handle(self, *args, **opts):
        lat, lng = opts["lat"].quantize(Decimal("0.000001")), opts["lng"].quantize(Decimal("0.000001"))
        with transaction.atomic():
            org, _ = Organization.objects.get_or_create(name=ORG_NAME)
            site, _ = Site.objects.get_or_create(organization=org, name="Kantor Demo",
                                                 defaults={"kind": Site.Kind.FIXED})
            pin_now = site.location_at()
            if pin_now is None or (pin_now.latitude, pin_now.longitude, pin_now.radius_m) != (lat, lng, opts["radius"]):
                site.move_pin(lat, lng, radius_m=opts["radius"])
            shift, _ = Shift.objects.get_or_create(
                organization=org, name="Pagi",
                defaults={"start_time": time(8), "end_time": time(17), "working_days": "123456"},
            )
            emp, _ = Employee.objects.get_or_create(
                organization=org, employee_no="DEMO-001",
                defaults={"full_name": "Karyawan Demo", "join_date": timezone.localdate(),
                          "default_site": site, "default_shift": shift},
            )
            try:
                pin = enable_login(emp, opts["phone"], opts["pin"])
            except ValueError as err:
                raise CommandError(str(err))

        self.stdout.write(self.style.SUCCESS(
            f"Demo ready: {org.name}\n"
            f"  Site   : {site.name} at {lat}, {lng} (radius {opts['radius']} m)\n"
            f"  Shift  : {shift}\n"
            f"  Worker : {emp.full_name} ({emp.employee_no})\n"
            f"  No. HP : {emp.login_phone}\n"
            f"  PIN    : {pin}   (you'll be asked to change it on first login)\n"
            f"Open /absen on your phone and log in."
        ))
