# =============================================================================
# === backend/apps/attendance/services.py ===
# =============================================================================
"""
record_clock_event() — the one way a tap becomes a ClockEvent. The phone
app, the gate kiosk (G2) and the fingerprint import (G2) all go through it,
so the same rules and flags apply whichever way a worker clocked in.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.employees.models import Employee

from .geofence import Candidate, Flag, evaluate, resolve_time, work_date
from .models import AttendanceDay, ClockEvent

# A clock-out up to this many hours after the last tap still belongs to the
# same working day (covers a 12-hour shift plus overtime, and night shifts).
OPEN_DAY_HOURS = 20


def _candidate(site, when):
    loc = site.location_at(when)
    return Candidate(
        site_id=site.id, kind=site.kind,
        latitude=float(loc.latitude) if loc else None,
        longitude=float(loc.longitude) if loc else None,
        radius_m=loc.radius_m if loc else None,
        location_id=loc.id if loc else None,
    )


def open_day(employee, at):
    """The day this worker is clocked in on (last tap within OPEN_DAY_HOURS wasn't a clock-out), or None."""
    last = (ClockEvent.objects
            .filter(employee=employee, occurred_at__gte=at - timedelta(hours=OPEN_DAY_HOURS), occurred_at__lte=at)
            .select_related("day").order_by("-occurred_at", "-received_at").first())
    if last is None or last.kind == ClockEvent.Kind.OUT:
        return None
    return last.day


def _day_for(employee, kind, occurred_at):
    current = open_day(employee, occurred_at)
    if kind == ClockEvent.Kind.IN:
        if current is not None:
            return current, [Flag.ALREADY_IN]
        shift = employee.default_shift
        date = work_date(timezone.localtime(occurred_at),
                         shift.start_time if shift else None, shift.end_time if shift else None)
        day, _ = AttendanceDay.objects.get_or_create(
            employee=employee, date=date,
            defaults={"organization": employee.organization, "shift": shift},
        )
        return day, []
    # Pindah lokasi / Pulang
    if current is not None:
        return current, []
    day, _ = AttendanceDay.objects.get_or_create(
        employee=employee, date=timezone.localtime(occurred_at).date(),
        defaults={"organization": employee.organization, "shift": employee.default_shift},
    )
    return day, [Flag.NO_CLOCK_IN]


def _dec(value, places):
    return None if value is None else Decimal(str(round(float(value), places)))


def record_clock_event(*, employee, kind, latitude=None, longitude=None, accuracy_m=None,
                       phone_time=None, queued=False, client_id=None, site=None, selfie=None,
                       source=ClockEvent.Source.APP):
    """
    Record one tap. Never refuses: unusual taps get flags for HR instead.
    Returns (event, created). A repeat of the same client_id returns the first event.
    """
    if client_id is not None:
        existing = ClockEvent.objects.filter(employee=employee, client_id=client_id).first()
        if existing is not None:
            return existing, False

    received_at = timezone.now()
    occurred_at, flags = resolve_time(received_at, phone_time, queued)

    sites = [site] if site is not None else employee.candidate_sites()
    by_id = {s.id: s for s in sites}
    geo = evaluate([_candidate(s, occurred_at) for s in sites],
                   None if latitude is None else float(latitude),
                   None if longitude is None else float(longitude),
                   None if accuracy_m is None else float(accuracy_m))
    flags += geo.flags
    if source == ClockEvent.Source.APP and not selfie:
        flags.append(Flag.NO_SELFIE)

    with transaction.atomic():
        # One tap at a time per worker, so two quick taps can't both open a day.
        Employee.objects.select_for_update().filter(pk=employee.pk).first()
        if client_id is not None:
            existing = ClockEvent.objects.filter(employee=employee, client_id=client_id).first()
            if existing is not None:
                return existing, False
        day, day_flags = _day_for(employee, kind, occurred_at)
        event = ClockEvent(
            organization=employee.organization, day=day, employee=employee, kind=kind, source=source,
            site=by_id.get(geo.site_id), site_location_id=geo.location_id,
            occurred_at=occurred_at, received_at=received_at, phone_time=phone_time,
            latitude=_dec(latitude, 6), longitude=_dec(longitude, 6), accuracy_m=_dec(accuracy_m, 1),
            distance_m=geo.distance_m, flags=list(dict.fromkeys(flags + day_flags)), client_id=client_id,
        )
        if selfie:
            event.selfie = selfie
        event.save()
    return event, True
