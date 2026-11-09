# =============================================================================
# === backend/apps/attendance/machine_views.py ===
# =============================================================================
"""
Fingerprint machines and each employee's ID per machine (G12f.1a, 9 Nov 2026).

  GET/POST     /api/hr/fingerprint/machines/              the main machine + the company's other machines / add one
  PATCH/DELETE /api/hr/fingerprint/machines/<id>/         rename, set site / Dept. labels, turn off / delete
                                                          (delete only while no employee ID and no tap uses it)
  GET/PUT      /api/hr/employees/<id>/machine-ids/        an employee's IDs on the other machines; PUT replaces
                                                          the whole list: [{"machine": id, "fingerprint_id": "2"}]

The main machine has no row: its IDs are "ID Mesin Fingerprint" on the employee, edited as before.
An ID is unique per machine, so 12 can be Herianto on the main machine and Tari on "Mesin Kantor".
Every change is audited.
"""
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR
from apps.sites.models import Site

from .fingerprint import clean_id
from .machines import ALL, AUTO, AUTO_NAME, MAIN, MAIN_NAME, dept_conflicts, parse_dept_labels
from .models import ClockEvent, EmployeeMachineId, FingerprintMachine


def resolve_machine(org, value, allowed=(MAIN, AUTO)):
    """
    The "machine" an HR request names -> MAIN / AUTO / ALL / a FingerprintMachine of this company.
    "" means MAIN (as before G12f.1a). Raises ValueError with a message for HR.
    """
    value = str(value or "").strip()
    if value in ("", MAIN) and MAIN in allowed:
        return MAIN
    if value in (AUTO, ALL) and value in allowed:
        return value
    machine = None
    try:
        machine = FingerprintMachine.objects.filter(organization=org, pk=value).first()
    except Exception:                                   # not a UUID
        machine = None
    if machine is None:
        raise ValueError("Mesin fingerprint tidak ditemukan. Pilih lagi mesinnya.")
    if not machine.is_active and AUTO in allowed:        # importing needs an active machine; deleting does not
        raise ValueError(f"{machine.name} sedang nonaktif. Aktifkan dulu di daftar mesin.")
    return machine


def machine_label(machine):
    if machine == MAIN:
        return MAIN_NAME
    if machine == AUTO:
        return AUTO_NAME
    if machine == ALL:
        return "Semua mesin"
    return machine.name


class MachineSerializer(serializers.ModelSerializer):
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.none(), allow_null=True, required=False)

    class Meta:
        model = FingerprintMachine
        fields = ["id", "name", "site", "dept_labels", "is_active"]
        read_only_fields = ["id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = Site.objects.filter(organization=self.context["org"])

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Isi nama mesin.")
        if value.casefold() == MAIN_NAME.casefold():
            raise serializers.ValidationError(f"\"{MAIN_NAME}\" sudah ada: itu ID di data karyawan. Pakai nama lain.")
        qs = FingerprintMachine.objects.filter(organization=self.context["org"], name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Nama mesin ini sudah dipakai.")
        return value

    def validate_dept_labels(self, value):
        return ", ".join(parse_dept_labels(value))

    def validate(self, attrs):
        active = attrs.get("is_active", getattr(self.instance, "is_active", True))
        labels = attrs.get("dept_labels", getattr(self.instance, "dept_labels", ""))
        if active and labels:
            others = FingerprintMachine.objects.filter(organization=self.context["org"], is_active=True)
            if self.instance:
                others = others.exclude(pk=self.instance.pk)
            clash = dept_conflicts(labels, [(m.name, m.dept_labels) for m in others])
            if clash:
                label, other = clash[0]
                raise serializers.ValidationError(
                    {"dept_labels": f"Dept. \"{label}\" sudah dipakai {other}. Satu Dept. hanya untuk satu mesin."})
        return attrs


def _machine_rows(org):
    machines = list(FingerprintMachine.objects.filter(organization=org).select_related("site")
                    .annotate(ids=Count("employee_ids")))
    taps = dict(ClockEvent.objects.filter(organization=org, machine__isnull=False).order_by()
                .values("machine").annotate(n=Count("id")).values_list("machine", "n"))
    return [{"id": str(m.pk), "name": m.name, "site": str(m.site_id) if m.site_id else None,
             "site_name": m.site.name if m.site_id else "", "dept_labels": m.dept_labels, "is_active": m.is_active,
             "employees": m.ids, "taps": taps.get(m.pk, 0)} for m in machines]


def _snapshot(m):
    return {"name": m.name, "site": str(m.site_id) if m.site_id else None, "dept_labels": m.dept_labels,
            "is_active": m.is_active}


class MachineListView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        org = request.hr_org
        main = {"name": MAIN_NAME,
                "employees": Employee.objects.filter(organization=org).exclude(fingerprint_id="").count(),
                "taps": ClockEvent.objects.filter(organization=org, source=ClockEvent.Source.FINGERPRINT,
                                                  machine__isnull=True).count()}
        return Response({"success": True, "main": main, "machines": _machine_rows(org)})

    def post(self, request):
        ser = MachineSerializer(data=request.data, context={"org": request.hr_org})
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            m = ser.save(organization=request.hr_org)
            record_audit(organization=request.hr_org, actor=request.user, action="attendance.machine_create",
                         target=m, summary=f"Mesin fingerprint ditambah: {m.name}", after=_snapshot(m))
        return Response({"success": True, "machines": _machine_rows(request.hr_org), "id": str(m.pk)},
                        status=status.HTTP_201_CREATED)


class MachineDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def patch(self, request, pk):
        m = get_object_or_404(FingerprintMachine, pk=pk, organization=request.hr_org)
        before = _snapshot(m)
        ser = MachineSerializer(m, data=request.data, partial=True, context={"org": request.hr_org})
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            m = ser.save()
            after = _snapshot(m)
            if after != before:
                record_audit(organization=request.hr_org, actor=request.user, action="attendance.machine_update",
                             target=m, summary=f"Mesin fingerprint diubah: {m.name}", before=before, after=after)
        return Response({"success": True, "machines": _machine_rows(request.hr_org)})

    def delete(self, request, pk):
        m = get_object_or_404(FingerprintMachine, pk=pk, organization=request.hr_org)
        ids = m.employee_ids.count()
        taps = ClockEvent.objects.filter(machine=m).count()
        if ids or taps:
            return Response({"success": False,
                             "message": f"{m.name} sudah dipakai ({ids} ID karyawan, {taps} tap). "
                                        f"Nonaktifkan saja supaya datanya tetap ada."},
                            status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            record_audit(organization=request.hr_org, actor=request.user, action="attendance.machine_delete",
                         target=m, summary=f"Mesin fingerprint dihapus: {m.name}", before=_snapshot(m))
            m.delete()
        return Response({"success": True, "machines": _machine_rows(request.hr_org)})


def employee_machine_ids(emp):
    """[{machine, machine_name, fingerprint_id}] for one employee, in machine-name order."""
    return [{"machine": str(r.machine_id), "machine_name": r.machine.name, "fingerprint_id": r.fingerprint_id}
            for r in emp.machine_ids.all()]


class MachineIdItem(serializers.Serializer):
    machine = serializers.UUIDField()
    fingerprint_id = serializers.CharField(max_length=30, allow_blank=True)


class MachineIdsSerializer(serializers.Serializer):
    machine_ids = MachineIdItem(many=True)


class EmployeeMachineIdsView(APIView):
    permission_classes = [IsCompanyHR]

    def _body(self, org, emp):
        emp = Employee.objects.prefetch_related("machine_ids__machine").get(pk=emp.pk)
        return {"success": True, "employee": {"id": str(emp.pk), "employee_no": emp.employee_no,
                                              "full_name": emp.full_name},
                "main": {"name": MAIN_NAME, "fingerprint_id": emp.fingerprint_id},
                "machine_ids": employee_machine_ids(emp),
                "machines": [{"id": str(m.pk), "name": m.name, "is_active": m.is_active}
                             for m in FingerprintMachine.objects.filter(organization=org)]}

    def get(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, organization=request.hr_org)
        return Response(self._body(request.hr_org, emp))

    def put(self, request, pk):
        org = request.hr_org
        emp = get_object_or_404(Employee, pk=pk, organization=org)
        ser = MachineIdsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        machines = {m.pk: m for m in FingerprintMachine.objects.filter(organization=org)}

        wanted, errors = {}, []
        for n, item in enumerate(ser.validated_data["machine_ids"], 1):
            m = machines.get(item["machine"])
            if m is None:
                errors.append(f"Baris {n}: mesin tidak ditemukan.")
                continue
            if m.pk in wanted:
                errors.append(f"Baris {n}: {m.name} muncul dua kali.")
                continue
            fid = clean_id(item["fingerprint_id"])
            if not fid:
                continue                                  # an empty ID = no ID on that machine
            other = (EmployeeMachineId.objects.filter(machine=m, fingerprint_id=fid).exclude(employee=emp)
                     .select_related("employee").first())
            if other:
                errors.append(f"ID {fid} di {m.name} sudah dipakai {other.employee.full_name} "
                              f"({other.employee.employee_no}).")
                continue
            wanted[m.pk] = fid
        if errors:
            return Response({"success": False, "message": " ".join(errors), "errors": errors},
                            status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            current = {r.machine_id: r for r in EmployeeMachineId.objects.select_for_update().filter(employee=emp)}
            before = {machines[k].name: r.fingerprint_id for k, r in current.items()}
            for key, row in current.items():
                if key not in wanted:
                    row.delete()
                elif row.fingerprint_id != wanted[key]:
                    row.fingerprint_id = wanted[key]
                    row.save(update_fields=["fingerprint_id"])
            for key, fid in wanted.items():
                if key not in current:
                    EmployeeMachineId.objects.create(organization=org, employee=emp, machine=machines[key],
                                                     fingerprint_id=fid)
            after = {machines[k].name: fid for k, fid in wanted.items()}
            if after != before:
                shown = ", ".join(f"{k} {v}" for k, v in sorted(after.items())) or "tidak ada"
                record_audit(organization=org, actor=request.user, action="employees.machine_ids", target=emp,
                             summary=f"ID mesin {emp.full_name}: {shown}", before=before, after=after)
        return Response(self._body(org, emp))
