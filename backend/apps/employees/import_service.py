# =============================================================================
# === backend/apps/employees/import_service.py ===
# =============================================================================
"""
Employee import against the database (G9, 1 Nov 2026).

  plan_import(org, items)      what each row would do: create / update (with the changes) /
                               same / error / skip. Reads only.
  apply_import(org, plan, actor)   saves the create and update rows in one transaction
                               (all or nothing), then links mandors, then writes one audit entry.

Matching is by No. Karyawan (case-insensitive) inside the company. Shift, site and mandor are
looked up by name / No. Karyawan; one that doesn't exist yet becomes a warning and is left empty.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.sites.models import Shift, Site

from .importer import LABELS, REQUIRED_NEW
from .models import Employee

PLAIN_FIELDS = ["full_name", "position", "nik", "npwp", "ptkp_status", "join_date", "probation_end_date", "end_date",
                "employment_type", "pay_type", "base_rate", "fixed_allowance", "overtime_eligible", "bpjs_tk_enrolled",
                "bpjs_tk_no", "bpjs_kesehatan_no", "bank_name", "bank_account_no", "bank_account_name", "phone",
                "fingerprint_id"]


def show(value):
    """How a value reads in the preview."""
    if value is None or value == "":
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, bool):
        return "Ya" if value else "Tidak"
    if isinstance(value, Decimal):
        return "Rp " + f"{value:,.0f}".replace(",", ".")
    if hasattr(value, "name") and not isinstance(value, str):
        return value.name
    if hasattr(value, "employee_no"):
        return value.employee_no
    return str(value)


def plan_import(org, items):
    employees = {e.employee_no.lower(): e for e in Employee.objects.filter(organization=org)
                 .select_related("default_shift", "default_site", "mandor")}
    shifts = {s.name.strip().lower(): s for s in Shift.objects.filter(organization=org)}
    sites = {s.name.strip().lower(): s for s in Site.objects.filter(organization=org)}
    fp_owner = {e.fingerprint_id: e.employee_no for e in employees.values() if e.fingerprint_id}
    file_nos = {i["values"]["employee_no"].lower() for i in items
                if not i["skip"] and not i["errors"] and i["values"].get("employee_no")}
    fp_in_file = {}
    plan = []
    for item in items:
        v = dict(item["values"])
        row = {"row": item["row"], "employee_no": v.get("employee_no", ""), "full_name": v.get("full_name", ""),
               "action": "", "changes": [], "errors": list(item["errors"]), "warnings": list(item["warnings"]),
               "skip": item["skip"], "_values": {}, "_mandor": None}
        if item["skip"]:
            row["action"] = "skip"
            plan.append(row)
            continue
        no = v.get("employee_no", "").lower()
        existing = employees.get(no)
        if existing and not row["full_name"]:
            row["full_name"] = existing.full_name

        # shift / site / mandor by name
        resolved = {}
        for field, table, model_field, word in (("shift", shifts, "default_shift", "Shift"),
                                                ("site", sites, "default_site", "Lokasi")):
            if field in v:
                obj = table.get(v.pop(field).strip().lower())
                if obj is None:
                    row["warnings"].append(f"{word} \"{item['values'][field]}\" belum ada di GajiKita; dikosongkan")
                else:
                    resolved[model_field] = obj
        if "mandor" in v:
            mandor_no = v.pop("mandor").strip()
            if mandor_no.lower() == no:
                row["warnings"].append("Mandor tidak bisa dirinya sendiri; dikosongkan")
            elif mandor_no.lower() in employees or mandor_no.lower() in file_nos:
                row["_mandor"] = mandor_no.lower()
            else:
                row["warnings"].append(f"Mandor {mandor_no} tidak ditemukan; dikosongkan")
        v.pop("employee_no", None)

        fid = v.get("fingerprint_id")
        if fid:
            owner = fp_owner.get(fid)
            if owner and owner.lower() != no:
                row["errors"].append(f"ID fingerprint {fid} sudah dipakai karyawan {owner}")
            elif fid in fp_in_file:
                row["errors"].append(f"ID fingerprint {fid} juga dipakai di baris {fp_in_file[fid]}")
            else:
                fp_in_file[fid] = item["row"]

        if row["errors"]:
            row["action"] = "error"
            plan.append(row)
            continue
        values = {**v, **resolved}
        if existing is None:
            missing = [LABELS[f] for f in REQUIRED_NEW if f != "employee_no" and f not in item["values"]]
            if missing:
                row["errors"].append("Wajib diisi untuk karyawan baru: " + ", ".join(missing))
                row["action"] = "error"
            else:
                row["action"] = "create"
        else:
            for f, new in values.items():
                old = getattr(existing, f)
                if (old or None) != (new or None) and not (isinstance(old, Decimal) and Decimal(new or 0) == old):
                    row["changes"].append({"field": LABELS.get(f, LABELS.get(f.replace("default_", ""), f)),
                                           "old": show(old), "new": show(new)})
            if row["_mandor"] and (existing.mandor is None or existing.mandor.employee_no.lower() != row["_mandor"]):
                row["changes"].append({"field": LABELS["mandor"], "old": show(existing.mandor), "new": row["_mandor"].upper()})
            row["action"] = "update" if row["changes"] else "same"
        row["_values"] = values
        plan.append(row)
    return plan


def summary(plan):
    counts = {k: 0 for k in ("create", "update", "same", "error", "skip")}
    for r in plan:
        counts[r["action"]] += 1
    return counts


def public(plan):
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in plan]


def apply_import(org, plan, actor):
    today = timezone.localdate()
    created = updated = 0
    with transaction.atomic():
        by_no = {}
        for r in plan:
            if r["action"] not in ("create", "update"):
                continue
            values = r["_values"]
            if r["action"] == "create":
                emp = Employee(organization=org, employee_no=r["employee_no"])
                created += 1
            else:
                emp = Employee.objects.select_for_update().get(organization=org, employee_no__iexact=r["employee_no"])
                updated += 1
            for f, value in values.items():
                setattr(emp, f, value)
            if values.get("end_date"):
                emp.status = Employee.Status.RESIGNED if values["end_date"] <= today else Employee.Status.ACTIVE
            emp.save()
            by_no[r["employee_no"].lower()] = emp
        # mandors last: they may be new rows in the same file
        for r in plan:
            if r["action"] in ("create", "update") and r["_mandor"]:
                mandor = by_no.get(r["_mandor"]) or Employee.objects.filter(
                    organization=org, employee_no__iexact=r["_mandor"]).first()
                emp = by_no[r["employee_no"].lower()]
                if mandor and mandor.pk != emp.pk and emp.mandor_id != mandor.pk:
                    emp.mandor = mandor
                    emp.save(update_fields=["mandor"])
        if created or updated:
            record_audit(organization=org, actor=actor, action="employees.import", target=org,
                         summary=f"Import data karyawan: {created} baru, {updated} diperbarui",
                         after={"created": created, "updated": updated})
    return {"created": created, "updated": updated}
