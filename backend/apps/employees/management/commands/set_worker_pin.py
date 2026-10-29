"""
Turn on phone + PIN login for one employee (until HR's Employees page exists in G2b).

    python manage.py set_worker_pin BWI-001 --phone 081234567890
    python manage.py set_worker_pin BWI-001 --phone 081234567890 --pin 482913 --org "PT Bangun Wira Indah"

Without --pin a random PIN is made and printed. The worker must change it on first login.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.employees.models import Employee
from apps.employees.worker_login import enable_login


class Command(BaseCommand):
    help = "Set a worker's login phone and PIN."

    def add_arguments(self, parser):
        parser.add_argument("employee_no")
        parser.add_argument("--phone", required=True)
        parser.add_argument("--pin", default=None)
        parser.add_argument("--org", default=None, help="Company name or code, if the employee no. exists in several.")

    def handle(self, *args, **opts):
        qs = Employee.objects.filter(employee_no=opts["employee_no"]).select_related("organization")
        if opts["org"]:
            qs = qs.filter(Q(organization__name__iexact=opts["org"]) | Q(organization__invoice_code__iexact=opts["org"]))
        found = list(qs[:2])
        if not found:
            raise CommandError(f"No employee with no. {opts['employee_no']!r}.")
        if len(found) > 1:
            raise CommandError("That employee no. exists in more than one company; add --org.")
        emp = found[0]
        try:
            pin = enable_login(emp, opts["phone"], opts["pin"])
        except ValueError as err:
            raise CommandError(str(err))
        self.stdout.write(self.style.SUCCESS(
            f"Login on for {emp.full_name} ({emp.organization.name})\n"
            f"  No. HP : {emp.login_phone}\n"
            f"  PIN    : {pin}   (must be changed on first login)"
        ))
