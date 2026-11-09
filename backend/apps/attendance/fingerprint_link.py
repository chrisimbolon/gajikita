# =============================================================================
# === backend/apps/attendance/fingerprint_link.py ===
# =============================================================================
"""
"Ini siapa?" — connect machine IDs to employees right from the import preview (G12f.2, 9 Nov 2026).

  POST /api/hr/attendance/fingerprint/link/
       {"links": [{"machine": "main" | <machine id>, "fingerprint_id": "7", "employee": <employee id>}, ...]}

All or nothing: every line is checked first; one problem = nothing saved, every problem listed.
Never overwrites: an ID another person has on that machine, or a person who already has a different
ID on that machine, is refused with a plain message (change it in Karyawan if it really is wrong).
A line that is already exactly so is accepted and changes nothing. Each new link is audited.
"""
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR

from .fingerprint import clean_id
from .machine_views import machine_label, resolve_machine
from .machines import MAIN
from .models import EmployeeMachineId


class LinkItem(serializers.Serializer):
    machine = serializers.CharField(max_length=40, allow_blank=True)
    fingerprint_id = serializers.CharField(max_length=30)
    employee = serializers.UUIDField()


class LinkSerializer(serializers.Serializer):
    links = LinkItem(many=True, allow_empty=False)


class FingerprintLinkView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        org = request.hr_org
        ser = LinkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        items = ser.validated_data["links"]
        employees = {e.pk: e for e in Employee.objects.filter(organization=org, pk__in=[i["employee"] for i in items])}
        main_owner = {clean_id(e.fingerprint_id): e
                      for e in Employee.objects.filter(organization=org).exclude(fingerprint_id="")}

        errors, todo, ids_seen, people_seen = [], [], set(), set()
        for n, item in enumerate(items, 1):
            try:
                machine = resolve_machine(org, item["machine"], allowed=(MAIN,))
            except ValueError as err:
                errors.append(f"Baris {n}: {err}")
                continue
            emp = employees.get(item["employee"])
            fid = clean_id(item["fingerprint_id"])
            label = machine_label(machine)
            key = MAIN if machine == MAIN else machine.pk
            if emp is None:
                errors.append(f"Baris {n}: karyawan tidak ditemukan.")
                continue
            if not fid:
                errors.append(f"Baris {n}: nomor ID kosong.")
                continue
            if machine != MAIN and not machine.is_active:
                errors.append(f"{label} sedang nonaktif. Aktifkan dulu di Lokasi → Mesin fingerprint.")
                continue
            if (key, fid) in ids_seen:
                errors.append(f"ID {fid} di {label} dipilih untuk dua orang.")
                continue
            if (key, emp.pk) in people_seen:
                errors.append(f"{emp.full_name} dipilih dua kali untuk {label}.")
                continue
            ids_seen.add((key, fid))
            people_seen.add((key, emp.pk))

            if machine == MAIN:
                owner = main_owner.get(fid)
                current = clean_id(emp.fingerprint_id)
                if owner is not None and owner.pk != emp.pk:
                    errors.append(f"ID {fid} di {label} sudah dipakai {owner.full_name} ({owner.employee_no}).")
                elif current and current != fid:
                    errors.append(f"{emp.full_name} sudah punya ID {current} di {label}. "
                                  f"Kalau memang salah, ubah di menu Karyawan.")
                elif current != fid:
                    todo.append((emp, machine, fid, label))
            else:
                other = (EmployeeMachineId.objects.filter(machine=machine, fingerprint_id=fid).exclude(employee=emp)
                         .select_related("employee").first())
                mine = EmployeeMachineId.objects.filter(machine=machine, employee=emp).first()
                if other is not None:
                    errors.append(f"ID {fid} di {label} sudah dipakai {other.employee.full_name} "
                                  f"({other.employee.employee_no}).")
                elif mine is not None and mine.fingerprint_id != fid:
                    errors.append(f"{emp.full_name} sudah punya ID {mine.fingerprint_id} di {label}. "
                                  f"Kalau memang salah, ubah di menu Karyawan.")
                elif mine is None:
                    todo.append((emp, machine, fid, label))

        if errors:
            return Response({"success": False, "message": " ".join(errors), "errors": errors},
                            status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            for emp, machine, fid, label in todo:
                if machine == MAIN:
                    emp.fingerprint_id = fid
                    emp.save(update_fields=["fingerprint_id", "updated_at"])
                else:
                    EmployeeMachineId.objects.create(organization=org, employee=emp, machine=machine, fingerprint_id=fid)
                record_audit(organization=org, actor=request.user, action="employees.machine_link", target=emp,
                             summary=f"ID {fid} di {label} dihubungkan ke {emp.full_name}",
                             after={"machine": label, "fingerprint_id": fid})
        return Response({"success": True, "linked": len(todo)})
