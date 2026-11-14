# =============================================================================
# === backend/apps/attendance/event_views.py ===
# =============================================================================
"""
Company events ("Kejadian", G17-2, 14 Nov 2026): a power cut or a holiday, entered once.

GET    /api/hr/attendance/events/          every event, newest first
POST   /api/hr/attendance/events/          {"start", "end", "kind", "reason", "everyone", "site_ids", "employee_ids"}
PATCH  /api/hr/attendance/events/<id>/     the same fields, all optional
DELETE /api/hr/attendance/events/<id>/

Rules: end on or after start, at most 62 days; a reason of 3+ letters; when not everyone, at least one location
or person, all from this company; no change may touch the dates of a LOCKED payroll. Every change is audited.
"""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR
from apps.sites.models import Site

from .company_events import LABELS, MAX_DAYS
from .exemption_views import _d, _locked
from .exemptions import changed_ranges, locked_hit
from .models import CompanyEvent


def event_json(x):
    sites = sorted(x.sites.all(), key=lambda s: s.name)
    people = sorted(x.employees.all(), key=lambda e: e.full_name)
    return {
        "id": str(x.pk), "start": x.start.isoformat(), "end": x.end.isoformat(), "kind": x.kind,
        "kind_label": LABELS.get(x.kind, x.kind), "reason": x.reason, "everyone": x.everyone,
        "days": (x.end - x.start).days + 1,
        "sites": [{"id": str(s.pk), "name": s.name} for s in sites],
        "employees": [{"id": str(e.pk), "employee_no": e.employee_no, "full_name": e.full_name} for e in people],
        "who": who_text(x.everyone, sites, people),
        "created_by": x.created_by.full_name if x.created_by else "",
    }


def who_text(everyone, sites, people):
    if everyone:
        return "Semua karyawan"
    parts = []
    if sites:
        parts.append("Lokasi " + ", ".join(s.name for s in sites))
    if people:
        names = [e.full_name for e in people]
        parts.append(", ".join(names[:3]) + (f" +{len(names) - 3} lainnya" if len(names) > 3 else ""))
    return " · ".join(parts)


def _bad(message):
    return Response({"success": False, "message": message}, status=status.HTTP_400_BAD_REQUEST)


def _summary(x):
    return f"{LABELS.get(x.kind, x.kind)} {_d(x.start)} s/d {_d(x.end)} ({x.reason}) · {event_json(x)['who']}"


class EventInput(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    kind = serializers.ChoiceField(choices=list(LABELS), required=False)
    reason = serializers.CharField(max_length=200, required=False)
    everyone = serializers.BooleanField(required=False)
    site_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    employee_ids = serializers.ListField(child=serializers.UUIDField(), required=False)

    def validate_reason(self, value):
        value = " ".join(value.split())
        if len(value) < 3:
            raise serializers.ValidationError("Tulis alasannya, mis. \"Mati lampu\" atau \"Libur HUT perusahaan\".")
        return value


def _resolve(org, d, x=None):
    """-> (fields dict, sites, people) or a plain message."""
    start = d.get("start", x.start if x else None)
    end = d.get("end", x.end if x else None)
    if start is None or end is None:
        return "Isi tanggal mulai dan selesai."
    if end < start:
        return "Tanggal selesai tidak boleh sebelum tanggal mulai."
    if (end - start).days + 1 > MAX_DAYS:
        return f"Satu kejadian paling lama {MAX_DAYS} hari. Pecah jadi beberapa kejadian bila perlu."
    kind = d.get("kind", x.kind if x else None)
    reason = d.get("reason", x.reason if x else None)
    if not kind:
        return "Pilih jenisnya: Gangguan absen atau Libur."
    if not reason:
        return "Tulis alasannya, mis. \"Mati lampu\"."
    everyone = d.get("everyone", x.everyone if x else True)
    site_ids = d["site_ids"] if "site_ids" in d else ([s.pk for s in x.sites.all()] if x else [])
    employee_ids = d["employee_ids"] if "employee_ids" in d else ([e.pk for e in x.employees.all()] if x else [])
    sites, people = [], []
    if not everyone:
        sites = list(Site.objects.filter(organization=org, pk__in=site_ids))
        people = list(Employee.objects.filter(organization=org, pk__in=employee_ids))
        if len(sites) != len(set(site_ids)) or len(people) != len(set(employee_ids)):
            return "Ada lokasi atau karyawan yang tidak ditemukan di perusahaan ini."
        if not sites and not people:
            return "Pilih minimal satu lokasi atau satu karyawan, atau pilih Semua karyawan."
    return ({"start": start, "end": end, "kind": kind, "reason": reason, "everyone": everyone}, sites, people)


def _locked_problem(org, old, new):
    hit = locked_hit(changed_ranges(old, new), _locked(org))
    if hit is None:
        return None
    return (f"{hit[2]} ({_d(hit[0])} s/d {_d(hit[1])}) sudah dikunci dan dibayar seperti ini. Kejadian di periode itu "
            f"tidak bisa ditambah, diubah atau dihapus; buka kunci payroll dulu.")


def _list(org):
    qs = CompanyEvent.objects.filter(organization=org).select_related("created_by").prefetch_related(
        "sites", "employees").order_by("-start", "-created_at")[:200]
    return {"success": True, "events": [event_json(x) for x in qs]}


class EventListView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        return Response(_list(request.hr_org))

    def post(self, request):
        org = request.hr_org
        ser = EventInput(data=request.data)
        ser.is_valid(raise_exception=True)
        got = _resolve(org, ser.validated_data)
        if isinstance(got, str):
            return _bad(got)
        fields, sites, people = got
        problem = _locked_problem(org, None, (fields["start"], fields["end"]))
        if problem:
            return _bad(problem)
        with transaction.atomic():
            x = CompanyEvent.objects.create(organization=org, created_by=request.user, **fields)
            x.sites.set(sites)
            x.employees.set(people)
            record_audit(organization=org, actor=request.user, action="attendance.event_create", target=org,
                         summary=f"Kejadian: {_summary(x)}", after=event_json(x))
        body = _list(org)
        body["event"] = event_json(x)
        return Response(body, status=status.HTTP_201_CREATED)


class EventDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def patch(self, request, pk):
        org = request.hr_org
        x = get_object_or_404(CompanyEvent.objects.prefetch_related("sites", "employees"), pk=pk, organization=org)
        ser = EventInput(data=request.data)
        ser.is_valid(raise_exception=True)
        got = _resolve(org, ser.validated_data, x)
        if isinstance(got, str):
            return _bad(got)
        fields, sites, people = got
        # any change re-decides every day of the old and the new range
        problem = (_locked_problem(org, (x.start, x.end), None)
                   or _locked_problem(org, None, (fields["start"], fields["end"])))
        if problem:
            return _bad(problem)
        before = event_json(x)
        with transaction.atomic():
            for k, v in fields.items():
                setattr(x, k, v)
            x.save()
            x.sites.set(sites)
            x.employees.set(people)
            x = CompanyEvent.objects.prefetch_related("sites", "employees").get(pk=x.pk)
            record_audit(organization=org, actor=request.user, action="attendance.event_update", target=org,
                         summary=f"Kejadian diubah: {_summary(x)}", before=before, after=event_json(x))
        body = _list(org)
        body["event"] = event_json(x)
        return Response(body)

    def delete(self, request, pk):
        org = request.hr_org
        x = get_object_or_404(CompanyEvent.objects.prefetch_related("sites", "employees"), pk=pk, organization=org)
        problem = _locked_problem(org, (x.start, x.end), None)
        if problem:
            return _bad(problem)
        with transaction.atomic():
            before, text = event_json(x), _summary(x)
            x.delete()
            record_audit(organization=org, actor=request.user, action="attendance.event_delete", target=org,
                         summary=f"Kejadian dihapus: {text}", before=before)
        return Response(_list(org))
