# =============================================================================
# === backend/apps/attendance/spl_views.py ===
# =============================================================================
"""
G17-E1 (23 Nov 2026) — Lembur -> SPL: HR records the paper SPL once for several people (see spl.py).

  GET   attendance/spl/?month=2026-10        the pay period's SPLs, each person's days (paid by the SPL / decided
                                             by HR / no overtime in the taps), "Lembur tanpa SPL", people, sites
  POST  attendance/spl/                      a new SPL (JSON or multipart with a photo of the paper)
  PATCH attendance/spl/<id>/                 change it (dates, work, time, people, photo)
  POST  attendance/spl/<id>/cancel/          cancel it (nothing is deleted; the audit log keeps it)
  GET   attendance/spl/<id>/attachment/      the photo
A payroll that is locked is never changed: an SPL touching its dates can't be added, changed or cancelled.
"""
import mimetypes
import os
from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR
from apps.payroll.models import PayrollSettings
from apps.sites.models import Site

from . import spl as S
from .models import AttendanceDay, OvertimeOrder, OvertimeOrderPerson
from .day_status import Status                                                         # G17-E3
from .rekap import period_of
from .review_kinds import capped_overtime
from .review import evaluate, leaves_between, night_context

MAX_DAYS = 14
FILE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
FILE_MAX = 5 * 1024 * 1024


def _bad(message):
    return Response({"success": False, "message": message}, status=status.HTTP_400_BAD_REQUEST)


def _d(d):
    return f"{d:%d-%m-%Y}"


def _t(t):
    return t.strftime("%H:%M") if t else None


def _person(e):
    return {"id": str(e.pk), "full_name": e.full_name, "employee_no": e.employee_no,
            "overtime_eligible": e.overtime_eligible}


class SplInput(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField(required=False, allow_null=True)
    work = serializers.CharField(max_length=200)
    site = serializers.UUIDField(required=False, allow_null=True)
    planned_start = serializers.TimeField(required=False, allow_null=True)
    planned_end = serializers.TimeField(required=False, allow_null=True)
    issued_by_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    employee_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)
    consent = serializers.ChoiceField(choices=[S.CONSENT_YES, S.CONSENT_PENDING], required=False,
                                      default=S.CONSENT_YES)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    attachment = serializers.FileField(required=False, allow_null=True)
    remove_attachment = serializers.BooleanField(required=False, default=False)

    def to_internal_value(self, data):
        if hasattr(data, "getlist"):                       # multipart: employee_ids repeated, "" = no value
            plain = {k: data.get(k) for k in data.keys()}
            plain["employee_ids"] = [x for x in data.getlist("employee_ids") if x]
            for k in ("site", "planned_start", "planned_end", "end_date", "attachment"):
                if plain.get(k) in ("", "null"):
                    plain[k] = None
            data = plain
        return super().to_internal_value(data)


def _locked(org, ranges):
    from apps.payroll.models import PayRun
    for start, end in ranges:
        run = PayRun.objects.filter(organization=org, status=PayRun.Status.LOCKED, period_start__lte=end,
                                    period_end__gte=start).first()
        if run is not None:
            return (f"{run.name} ({_d(run.period_start)} s/d {_d(run.period_end)}) sudah dikunci. SPL di periode itu "
                    f"tidak bisa ditambah, diubah atau dibatalkan; buka kunci payroll dulu.")
    return None


def _resolve(org, d):
    """-> (fields, employees) or an error message."""
    start = d["start_date"]
    end = d.get("end_date") or start
    if end < start:
        return "Tanggal selesai tidak boleh sebelum tanggal mulai."
    if (end - start).days + 1 > MAX_DAYS:
        return f"Satu SPL paling lama {MAX_DAYS} hari. Buat SPL baru untuk sisanya."
    if not d["work"].strip():
        return "Tulis pekerjaannya, mis. \"Cor lantai 2 proyek X\"."
    if bool(d.get("planned_start")) != bool(d.get("planned_end")):
        return "Isi jam rencana mulai dan selesai, atau kosongkan keduanya."
    site = None
    if d.get("site"):
        site = Site.objects.filter(organization=org, pk=d["site"]).first()
        if site is None:
            return "Lokasi tidak ditemukan."
    ids = list(dict.fromkeys(d["employee_ids"]))
    people = list(Employee.objects.filter(organization=org, pk__in=ids))
    if len(people) != len(ids):
        return "Ada karyawan yang tidak ditemukan di perusahaan ini."
    not_eligible = [e.full_name for e in people if not e.overtime_eligible]
    if not_eligible:
        return (f"Tidak berhak upah lembur: {', '.join(not_eligible)} (Karyawan → Berhak Upah Lembur). "
                f"Hapus dari SPL atau ubah data karyawannya.")
    f = d.get("attachment")
    if f:
        if os.path.splitext(f.name)[1].lower() not in FILE_TYPES:
            return "Foto SPL harus JPG/PNG atau PDF."
        if f.size > FILE_MAX:
            return "Foto SPL paling besar 5 MB."
    return ({"start_date": start, "end_date": end, "work": d["work"].strip(), "site": site,
             "planned_start": d.get("planned_start"), "planned_end": d.get("planned_end"),
             "issued_by_name": (d.get("issued_by_name") or "").strip(), "note": (d.get("note") or "").strip()},
            people)


def order_json(x, matches=None):
    people = sorted(x.people.all(), key=lambda p: p.employee.full_name)
    return {
        "id": str(x.pk), "number": x.number, "start_date": x.start_date.isoformat(), "end_date": x.end_date.isoformat(),
        "work": x.work, "site": {"id": str(x.site_id), "name": x.site.name} if x.site_id else None,
        "planned_start": _t(x.planned_start), "planned_end": _t(x.planned_end), "issued_by_name": x.issued_by_name,
        "source": x.source, "source_label": x.get_source_display(), "note": x.note, "status": x.status,
        "cancel_note": x.cancel_note, "has_attachment": bool(x.attachment),
        "created_by": getattr(x.created_by, "full_name", "") or "", "created_at": x.created_at.isoformat(),
        "people": [{"employee": _person(p.employee), "consent": p.consent,
                    "days": (matches or {}).get((p.employee_id, str(x.pk)), [])} for p in people],
    }


def _snapshot(x):
    return {"number": x.number, "start": x.start_date.isoformat(), "end": x.end_date.isoformat(), "work": x.work,
            "planned": [_t(x.planned_start), _t(x.planned_end)], "status": x.status,
            "people": sorted(p.employee.full_name for p in x.people.all())}


def _period_days(org, start, end):
    """Every tapped day of the period, evaluated with the SPL rules: [(day, result)]."""
    ctx = night_context(org.id, None, start, end)
    leaves = leaves_between(org.id, start, end)
    now = timezone.now()
    days = (AttendanceDay.objects.filter(organization=org, date__gte=start, date__lte=end)
            .select_related("employee", "employee__default_shift", "shift").prefetch_related("events__site"))
    return [(day, evaluate(day, now, leave=leaves.get((day.employee_id, day.date), ""), ctx=ctx)) for day in days]


def page(org, month=None):
    y, mo, start, end = period_of(org, month)
    cfg = PayrollSettings.for_org(org)
    mode = cfg.overtime_source
    index = S.spl_index(org.id, None, start, end)
    matches, unmatched = {}, []
    cap = cfg.overtime_daily_cap_minutes
    paid_by_person, no_spl_minutes = {}, 0                                                   # G17-E3
    for day, r in _period_days(org, start, end):
        ref = index.get((day.employee_id, day.date))
        proposed = r.overtime_proposed_minutes or 0
        rest = Status.DAY_OFF_WORK in r.tags or r.holiday
        spl_paid = (capped_overtime(r.overtime_spl_minutes, None if rest else cap) or 0) if r.overtime_spl_minutes else 0
        decided_paid = (day.overtime_approved_minutes or 0) if day.decision == "approved" else 0
        paid_day = decided_paid or (0 if day.decision else spl_paid)                          # what payroll pays
        if paid_day:
            paid_by_person.setdefault(day.employee_id, (day.employee, []))[1].append((day.date, paid_day))
        if ref is not None:
            if day.decision:
                state, paid = "decided", decided_paid
            elif r.overtime_spl_minutes:
                state, paid = "spl", spl_paid
            elif proposed:
                state, paid = "waiting", 0                     # "decision" mode: HR still decides
            else:
                state, paid = "none", 0
            matches.setdefault((day.employee_id, ref.id), []).append(
                {"date": day.date.isoformat(), "proposed": proposed, "paid": paid, "state": state,
                 "over_plan": r.spl_over_plan})
        elif proposed and not day.decision and day.overtime_approved_minutes is None and not day.is_locked:
            no_spl_minutes += proposed
            unmatched.append({"day_id": str(day.pk), "employee": _person(day.employee), "date": day.date.isoformat(),
                              "minutes": proposed, "in": r.first_in.isoformat() if r.first_in else None,
                              "out": r.last_out.isoformat() if r.last_out else None})
    unmatched.sort(key=lambda u: (u["date"], u["employee"]["full_name"]))
    orders = (OvertimeOrder.objects.filter(organization=org, start_date__lte=end, end_date__gte=start)
              .select_related("site", "created_by").prefetch_related("people__employee").order_by("-start_date", "-number"))
    people = Employee.objects.filter(organization=org, status=Employee.Status.ACTIVE).order_by("full_name")
    orders_json = [order_json(x, matches) for x in orders]
    return {
        "success": True, "mode": mode,
        "period": {"year": y, "month": mo, "start": start.isoformat(), "end": end.isoformat()},
        "orders": orders_json,
        "unmatched": unmatched,
        "summary": summary(orders_json, paid_by_person, no_spl_minutes),                     # G17-E3
        "people": [_person(e) for e in people],
        "sites": [{"id": str(s.pk), "name": s.name} for s in Site.objects.filter(organization=org).order_by("name")],
    }


def summary(orders_json, paid_by_person, no_spl_minutes):
    """G17-E3: the SPL log of one pay period: who orders overtime, for what, how long, and who goes past
    UU 27/2026 Pasal 116 ayat 1 huruf c (4 h a day, 18 h a week). Paid minutes as payroll pays them."""
    by_issuer, by_work = {}, {}
    for o in orders_json:
        if o["status"] != "active":
            continue
        days = [d for p in o["people"] for d in p["days"] if d["paid"]]
        for key, bucket in ((o["issued_by_name"] or "(tanpa nama)", by_issuer), (o["work"], by_work)):
            b = bucket.setdefault(key, {"name": key, "orders": 0, "person_days": 0, "minutes": 0})
            b["orders"] += 1
            b["person_days"] += len(days)
            b["minutes"] += sum(d["paid"] for d in days)
    persons = []
    for employee, days in paid_by_person.values():
        long_days, heavy = S.over_limits(days)
        persons.append({"employee": _person(employee), "days": len(days), "minutes": sum(m for _, m in days),
                        "long_days": [d.isoformat() for d in long_days],
                        "heavy_weeks": [{"week": w.isoformat(), "minutes": m} for w, m in heavy]})
    persons.sort(key=lambda p: (-p["minutes"], p["employee"]["full_name"]))
    order = lambda b: sorted(b.values(), key=lambda x: (-x["minutes"], x["name"]))
    return {"total_minutes": sum(p["minutes"] for p in persons), "no_spl_minutes": no_spl_minutes,
            "over_limit": sum(1 for p in persons if p["long_days"] or p["heavy_weeks"]),
            "by_issuer": order(by_issuer), "by_work": order(by_work), "by_person": persons}


def _set_people(org, x, people, consent):
    keep = {p.employee_id: p for p in x.people.all()}
    wanted = {e.pk for e in people}
    OvertimeOrderPerson.objects.filter(order=x).exclude(employee_id__in=wanted).delete()
    now = timezone.now()
    for e in people:
        p = keep.get(e.pk)
        if p is None:
            OvertimeOrderPerson.objects.create(organization=org, order=x, employee=e, consent=consent,
                                               consent_via="paper" if consent == S.CONSENT_YES else "",
                                               consent_at=now if consent == S.CONSENT_YES else None)
        elif p.consent != consent:
            p.consent = consent
            p.consent_via = "paper" if consent == S.CONSENT_YES else ""
            p.consent_at = now if consent == S.CONSENT_YES else None
            p.save(update_fields=["consent", "consent_via", "consent_at"])


def _create_numbered(org, user, fields):
    """The next SPL number of the company (1, 2, 3 ...). Two HR users saving at once: the unique
    (organization, number) pair refuses the second, which simply takes the next number."""
    from django.db import IntegrityError
    for _ in range(5):
        number = (OvertimeOrder.objects.filter(organization=org).aggregate(n=Max("number"))["n"] or 0) + 1
        try:
            with transaction.atomic():
                return OvertimeOrder.objects.create(organization=org, number=number, created_by=user,
                                                    source=OvertimeOrder.Source.PAPER, **fields)
        except IntegrityError:
            continue
    raise IntegrityError("SPL number")


class SplListView(APIView):
    permission_classes = [IsCompanyHR]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        return Response(page(request.hr_org, request.query_params.get("month")))

    def post(self, request):
        org = request.hr_org
        ser = SplInput(data=request.data)
        ser.is_valid(raise_exception=True)
        got = _resolve(org, ser.validated_data)
        if isinstance(got, str):
            return _bad(got)
        fields, people = got
        problem = _locked(org, [(fields["start_date"], fields["end_date"])])
        if problem:
            return _bad(problem)
        with transaction.atomic():
            x = _create_numbered(org, request.user, fields)
            if ser.validated_data.get("attachment"):
                x.attachment = ser.validated_data["attachment"]
                x.save(update_fields=["attachment"])
            _set_people(org, x, people, ser.validated_data["consent"])
            record_audit(organization=org, actor=request.user, action="attendance.spl_create", target=x,
                         summary=f"SPL {x.number}: {x.work}, {_d(x.start_date)}" +
                                 (f" s/d {_d(x.end_date)}" if x.end_date != x.start_date else "") +
                                 f", {len(people)} orang", after=_snapshot(x))
        body = page(org, request.query_params.get("month"))
        body["message"] = f"SPL {x.number} dicatat untuk {len(people)} orang."
        return Response(body, status=status.HTTP_201_CREATED)


class SplDetailView(APIView):
    permission_classes = [IsCompanyHR]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def patch(self, request, pk):
        org = request.hr_org
        x = get_object_or_404(OvertimeOrder.objects.prefetch_related("people__employee"), pk=pk, organization=org)
        if x.status != OvertimeOrder.Status.ACTIVE:
            return _bad("SPL ini sudah dibatalkan.")
        ser = SplInput(data=request.data)
        ser.is_valid(raise_exception=True)
        got = _resolve(org, ser.validated_data)
        if isinstance(got, str):
            return _bad(got)
        fields, people = got
        problem = _locked(org, [(x.start_date, x.end_date), (fields["start_date"], fields["end_date"])])
        if problem:
            return _bad(problem)
        with transaction.atomic():
            before = _snapshot(x)
            for k, v in fields.items():
                setattr(x, k, v)
            if ser.validated_data.get("attachment"):
                x.attachment = ser.validated_data["attachment"]
            elif ser.validated_data.get("remove_attachment"):
                x.attachment = None
            x.save()
            _set_people(org, x, people, ser.validated_data["consent"])
            x = OvertimeOrder.objects.prefetch_related("people__employee").get(pk=x.pk)
            record_audit(organization=org, actor=request.user, action="attendance.spl_update", target=x,
                         summary=f"SPL {x.number} diubah", before=before, after=_snapshot(x))
        body = page(org, request.query_params.get("month"))
        body["message"] = f"SPL {x.number} disimpan."
        return Response(body)


class SplCancelView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request, pk):
        org = request.hr_org
        x = get_object_or_404(OvertimeOrder.objects.prefetch_related("people__employee"), pk=pk, organization=org)
        if x.status != OvertimeOrder.Status.ACTIVE:
            return _bad("SPL ini sudah dibatalkan.")
        problem = _locked(org, [(x.start_date, x.end_date)])
        if problem:
            return _bad(problem)
        note = str(request.data.get("note") or "").strip()[:200]
        with transaction.atomic():
            before = _snapshot(x)
            x.status, x.cancel_note = OvertimeOrder.Status.CANCELLED, note
            x.save(update_fields=["status", "cancel_note", "updated_at"])
            record_audit(organization=org, actor=request.user, action="attendance.spl_cancel", target=x,
                         summary=f"SPL {x.number} dibatalkan" + (f": {note}" if note else ""), before=before,
                         after=_snapshot(x))
        body = page(org, request.query_params.get("month"))
        body["message"] = f"SPL {x.number} dibatalkan."
        return Response(body)


class SplAttachmentView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk):
        x = get_object_or_404(OvertimeOrder, pk=pk, organization=request.hr_org)
        if not x.attachment:
            raise Http404("Tidak ada foto SPL.")
        name = os.path.basename(x.attachment.name)
        resp = FileResponse(x.attachment.open("rb"), content_type=mimetypes.guess_type(name)[0] or "application/octet-stream")
        resp["Cache-Control"] = "private, max-age=3600"
        return resp
