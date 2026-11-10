# =============================================================================
# === backend/apps/attendance/rekap.py ===
# =============================================================================
"""
Rekap Absensi: everyone x every day of a pay period (G10, 1 Nov 2026).

  GET /api/hr/attendance/rekap/?month=YYYY-MM&q=&site=&shift=&problems=1&page=1
        The period that ENDS in that month (pay period from the payroll settings, e.g.
        26 Sep - 25 Okt for October); without month, the period that holds today.
        One row per employee: a cell per day (code, times, review dot, overtime) and the
        summary columns. 100 employees per page.
  GET /api/hr/attendance/rekap/export/?month=...   the same as an Excel file (sheet "Rekap"
        with codes, sheet "Jam" with clock-in / clock-out times, sheet "Keterangan").

Every number comes from payroll.payrun.collect_numbers(), the loop payroll uses, so the rekap
and the payroll always agree.

G12f.3.1: each cell carries "hn" = HR's note for that day ({code, color, text} or null); the export shows
it as a comment on the cell of sheet "Rekap".
"""
import io
import re
from datetime import date as Date, timedelta

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR
from apps.payroll import engine
from apps.payroll.models import PayrollSettings
from apps.payroll.payrun import MONTHS, _days_by_employee, _leaves_by_employee, collect_numbers, employees_in_period

from .day_notes_import import notes_for                                         # G12f.3.1
from .rekap_codes import LEGEND, summarize
from .review import night_context                                                # G12e

PAGE_SIZE = 100
DOW = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]


def period_of(org, month=None):
    """(year, month, start, end) for the pay period ending in month, or the one holding today."""
    cfg = PayrollSettings.for_org(org)
    m = re.fullmatch(r"(\d{4})-(\d{2})", month or "")
    if m and 1 <= int(m.group(2)) <= 12:
        y, mo = int(m.group(1)), int(m.group(2))
    else:
        today = timezone.localdate()
        y, mo = today.year, today.month
        start, end = engine.period_for(y, mo, cfg.period_start_day)
        if today > end:
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    start, end = engine.period_for(y, mo, cfg.period_start_day)
    return y, mo, start, end


def _shift_month(y, m, step):
    m += step
    return (y + (m - 1) // 12, (m - 1) % 12 + 1)


def _hhmm(dt):
    return timezone.localtime(dt).strftime("%H:%M") if dt else None


def build(org, start, end, params):
    cfg = PayrollSettings.for_org(org)
    employees = employees_in_period(org, start, end).select_related("default_shift", "default_site")
    q = (params.get("q") or "").strip()
    if q:
        employees = employees.filter(Q(full_name__icontains=q) | Q(employee_no__icontains=q))
    if params.get("site"):
        employees = employees.filter(default_site_id=params["site"])
    if params.get("shift"):
        employees = employees.filter(default_shift_id=params["shift"])
    employees = list(employees)
    ids = [e.id for e in employees]
    days = _days_by_employee(org, start, end, ids)
    ctx = night_context(org.id, ids, start, end)                                    # G12e
    leaves = _leaves_by_employee(org, start, end, ids)
    notes = notes_for(org, ids, start, end)                                         # G12f.3.1
    now = timezone.now()
    rows = []
    for emp in employees:
        cells = []
        nums = collect_numbers(emp, start, end, cfg, days.get(emp.id, {}), leaves.get(emp.id, {}), now, cells=cells,
                               ctx=ctx)
        summary = summarize(nums, cells)
        if params.get("problems") in ("1", "true") and not summary["problem"]:
            continue
        rows.append({
            "employee": {"id": str(emp.id), "employee_no": emp.employee_no, "full_name": emp.full_name,
                         "position": emp.position, "shift": emp.default_shift.name if emp.default_shift else ""},
            "cells": [{**c, "fi": _hhmm(c["fi"]), "lo": _hhmm(c["lo"]),
                       "hn": notes.get((emp.id, Date.fromisoformat(c["d"])))} for c in cells],   # G12f.3.1
            "summary": summary,
        })
    return rows


def _days_header(start, end):
    out, d = [], start
    while d <= end:
        out.append({"d": d.isoformat(), "day": d.day, "dow": DOW[d.weekday()], "sunday": d.weekday() == 6})
        d += timedelta(days=1)
    return out


class RekapView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        y, m, start, end = period_of(request.hr_org, request.query_params.get("month"))
        rows = build(request.hr_org, start, end, request.query_params)
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except ValueError:
            page = 1
        pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages)
        py, pm = _shift_month(y, m, -1)
        ny, nm = _shift_month(y, m, 1)
        return Response({
            "success": True, "month": f"{y}-{m:02d}", "label": f"{MONTHS[m - 1]} {y}",
            "start": start.isoformat(), "end": end.isoformat(),
            "prev": f"{py}-{pm:02d}", "next": f"{ny}-{nm:02d}",
            "days": _days_header(start, end), "legend": [{"code": c, "label": l} for c, l in LEGEND],
            "total": len(rows), "page": page, "pages": pages,
            "rows": rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE],
        })


FILLS = {"H": "E3F2EA", "T": "FDF0D9", "PC": "FDF0D9", "TP": "FBE4E2", "A": "FBE4E2", "X": "FBE4E2", "K": "E3F2EA",
         "C": "DCE8F0", "S": "DCE8F0", "CK": "DCE8F0", "I": "DCE8F0", "L": "E3EAF0", "LK": "FDF0D9", "-": "F4F6F8"}
SUMMARY_COLS = [("Hadir", lambda s: s["present"]), ("Terlambat (kali)", lambda s: s["late_times"]),
                ("Terlambat (menit)", lambda s: s["late_minutes"]), ("Pulang cepat (menit)", lambda s: s["early_minutes"]),
                ("Tidak absen pulang", lambda s: s["no_clock_out"]), ("Tidak hadir", lambda s: s["absent"]),
                ("Cuti/sakit/izin dibayar", lambda s: s["paid_leave"]), ("Izin tanpa upah", lambda s: s["unpaid_leave"]),
                ("Lembur disetujui (jam)", lambda s: round(s["overtime_minutes"] / 60, 2)),
                ("Lembur menunggu (jam)", lambda s: round(s["overtime_pending_minutes"] / 60, 2)),
                ("Uang makan (hari)", lambda s: s["meal_days"]), ("Perlu ditinjau", lambda s: s["review"])]


class RekapExportView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        from openpyxl import Workbook
        from openpyxl.comments import Comment
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        y, m, start, end = period_of(request.hr_org, request.query_params.get("month"))
        rows = build(request.hr_org, start, end, request.query_params)
        days = _days_header(start, end)
        wb = Workbook()
        center = Alignment(horizontal="center", vertical="center", wrap_text=True)

        def sheet(ws, title, value_of, height):
            ws["A1"] = f"{title} — {request.hr_org.name}"
            ws["A1"].font = Font(bold=True, size=13, color="013D5A")
            ws["A2"] = f"Periode {start:%d/%m/%Y} s/d {end:%d/%m/%Y}"
            head = ["No. Karyawan", "Nama", "Jabatan"] + [f"{d['day']}\n{d['dow']}" for d in days] + \
                   ([c for c, _ in SUMMARY_COLS] if value_of is None else [])
            for i, h in enumerate(head, start=1):
                c = ws.cell(row=4, column=i, value=h)
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="013D5A")
                c.alignment = center
            for r, row in enumerate(rows, start=5):
                ws.cell(row=r, column=1, value=row["employee"]["employee_no"])
                ws.cell(row=r, column=2, value=row["employee"]["full_name"])
                ws.cell(row=r, column=3, value=row["employee"]["position"])
                for k, cell in enumerate(row["cells"], start=4):
                    if value_of is None:
                        v = cell["c"] + ("*" if cell["rv"] else "")
                    else:
                        v = value_of(cell)
                    x = ws.cell(row=r, column=k, value=v)
                    x.alignment = center
                    if cell["c"] in FILLS:
                        x.fill = PatternFill("solid", fgColor=FILLS[cell["c"]])
                    if value_of is None and cell.get("hn"):                          # G12f.3.1
                        hn = cell["hn"]
                        x.comment = Comment(f"Catatan HR{' (' + hn['code'] + ')' if hn['code'] else ''}: "
                                            f"{hn['text'] or '-'}", "SeeGaji")
                if value_of is None:
                    for j, (_, fn) in enumerate(SUMMARY_COLS, start=4 + len(days)):
                        ws.cell(row=r, column=j, value=fn(row["summary"])).alignment = center
                ws.row_dimensions[r].height = height
            ws.column_dimensions["A"].width = 13
            ws.column_dimensions["B"].width = 26
            ws.column_dimensions["C"].width = 18
            for k in range(4, 4 + len(days)):
                ws.column_dimensions[get_column_letter(k)].width = 6.5 if value_of is None else 7
            for k in range(4 + len(days), 4 + len(days) + len(SUMMARY_COLS)):
                ws.column_dimensions[get_column_letter(k)].width = 11
            ws.row_dimensions[4].height = 44
            ws.freeze_panes = "D5"

        ws = wb.active
        ws.title = "Rekap"
        sheet(ws, "Rekap Absensi", None, 18)
        sheet(wb.create_sheet("Jam"), "Jam Masuk & Pulang",
              lambda c: "\n".join(x for x in (c["fi"], c["lo"]) if x) or c["c"], 30)
        legend = wb.create_sheet("Keterangan")
        for i, (code, label) in enumerate(LEGEND + [("*", "Perlu ditinjau HR")], start=1):
            legend.cell(row=i, column=1, value=code).font = Font(bold=True)
            legend.cell(row=i, column=2, value=label)
            if code in FILLS:
                legend.cell(row=i, column=1).fill = PatternFill("solid", fgColor=FILLS[code])
        legend.column_dimensions["B"].width = 30
        buf = io.BytesIO()
        wb.save(buf)
        resp = HttpResponse(buf.getvalue(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="Rekap_Absensi_{MONTHS[m - 1]}_{y}.xlsx"'
        return resp
