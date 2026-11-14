"""/api/hr/ — HR's office screens (G2b): employees, sites, shifts."""
from django.urls import path

from apps.sites.hr_views import ShiftDetailView, ShiftListView, SiteDetailView, SiteListView, SitePinView

from apps.attendance.hr_views import DailyView, DayDetailView, DecideView, FixTimesView, ReviewQueueView, SelfieView
from apps.payroll.views import OvertimeMonthView
from apps.attendance.dashboard import SummaryView
from apps.payroll.payrun_views import (ItemDeleteView, LineDetailView, LineItemsView, RunDetailView, RunListView,
                                       RunLockView, RunRecalculateView, SettingsView)
from apps.payroll.slip_views import SlipsView, TransfersView
from apps.leave.hr_views import HrLeaveAttachmentView, HrLeaveBalanceView, HrLeaveDecideView, HrLeaveListView

from .hr_views import EmployeeDetailView, EmployeeListView, EmployeeLoginView
from .import_views import EmployeeImportView, EmployeeTemplateView
from apps.attendance.fingerprint_views import FingerprintImportView
from apps.attendance.fingerprint_delete_views import FingerprintDeleteView
from apps.attendance.machine_views import EmployeeMachineIdsView, MachineDetailView, MachineListView
from apps.attendance.fingerprint_link import FingerprintLinkView
from apps.attendance.day_notes_views import DayNotesDeleteView, DayNotesImportView
from apps.attendance.exemption_views import EmployeeExemptionsView, ExemptionDetailView
from apps.attendance.event_views import EventDetailView, EventListView
from apps.attendance.note_decision_views import NoteDecisionApplyView, NoteDecisionsView
from apps.attendance.rekap import RekapExportView, RekapView
from apps.attendance.review_bulk import BulkDecideView, ReviewPeriodView

urlpatterns = [
    path("employees/",                EmployeeListView.as_view(),   name="hr-employees"),
    path("employees/<uuid:pk>/",      EmployeeDetailView.as_view(), name="hr-employee"),
    path("employees/<uuid:pk>/login/", EmployeeLoginView.as_view(), name="hr-employee-login"),
    # imports (G9)
    path("employees/import/",          EmployeeImportView.as_view(),   name="hr-employee-import"),
    path("employees/import/template/", EmployeeTemplateView.as_view(), name="hr-employee-template"),
    path("attendance/fingerprint/import/", FingerprintImportView.as_view(), name="hr-fingerprint-import"),
    path("attendance/fingerprint/delete/", FingerprintDeleteView.as_view(), name="hr-fingerprint-delete"),   # G9b
    # fingerprint machines and IDs per machine (G12f.1a)
    path("fingerprint/machines/",            MachineListView.as_view(),        name="hr-fp-machines"),
    path("fingerprint/machines/<uuid:pk>/",  MachineDetailView.as_view(),      name="hr-fp-machine"),
    path("employees/<uuid:pk>/machine-ids/", EmployeeMachineIdsView.as_view(), name="hr-employee-machine-ids"),
    path("employees/<uuid:pk>/attendance-exemptions/", EmployeeExemptionsView.as_view(), name="hr-employee-exemptions"),
    path("attendance-exemptions/<uuid:pk>/", ExemptionDetailView.as_view(), name="hr-exemption-detail"),   # G12i
    path("attendance/events/",               EventListView.as_view(),   name="hr-events"),                 # G17-2
    path("attendance/events/<uuid:pk>/",     EventDetailView.as_view(), name="hr-event"),
    path("attendance/note-decisions/",        NoteDecisionsView.as_view(),     name="hr-note-decisions"),   # G17-4
    path("attendance/note-decisions/apply/",  NoteDecisionApplyView.as_view(), name="hr-note-decisions-apply"),
    path("attendance/fingerprint/link/",     FingerprintLinkView.as_view(),    name="hr-fingerprint-link"),   # G12f.2
    # HR's notes per day from the recap (G12f.3.1)
    path("attendance/notes/import/", DayNotesImportView.as_view(), name="hr-day-notes-import"),
    path("attendance/notes/delete/", DayNotesDeleteView.as_view(), name="hr-day-notes-delete"),
    # Rekap Absensi (G10)
    path("attendance/rekap/",        RekapView.as_view(),       name="hr-att-rekap"),
    # Tinjau massal per periode (G11)
    path("attendance/review/period/", ReviewPeriodView.as_view(), name="hr-att-review-period"),
    path("attendance/review/bulk/",   BulkDecideView.as_view(),   name="hr-att-review-bulk"),
    path("attendance/rekap/export/", RekapExportView.as_view(), name="hr-att-rekap-export"),
    path("sites/",                    SiteListView.as_view(),       name="hr-sites"),
    path("sites/<uuid:pk>/",          SiteDetailView.as_view(),     name="hr-site"),
    path("sites/<uuid:pk>/pin/",      SitePinView.as_view(),        name="hr-site-pin"),
    path("shifts/",                   ShiftListView.as_view(),      name="hr-shifts"),
    path("shifts/<uuid:pk>/",         ShiftDetailView.as_view(),    name="hr-shift"),
    # attendance review (G3)
    path("attendance/daily/",                  DailyView.as_view(),       name="hr-att-daily"),
    path("attendance/review/",                 ReviewQueueView.as_view(), name="hr-att-review"),
    path("attendance/days/<uuid:pk>/",         DayDetailView.as_view(),   name="hr-att-day"),
    path("attendance/days/<uuid:pk>/decide/",  DecideView.as_view(),      name="hr-att-decide"),
    path("attendance/fix/",                    FixTimesView.as_view(),    name="hr-att-fix"),
    path("attendance/events/<uuid:pk>/selfie/", SelfieView.as_view(),     name="hr-att-selfie"),
    # overtime in rupiah, PP 35/2021 (G4a)
    path("overtime/",                          OvertimeMonthView.as_view(), name="hr-overtime"),
    # the Ringkasan dashboard in one call (G6)
    path("summary/",                           SummaryView.as_view(),     name="hr-summary"),
    # cuti & izin (G7)
    path("leave/",                             HrLeaveListView.as_view(),       name="hr-leave"),
    path("leave/<uuid:pk>/decide/",            HrLeaveDecideView.as_view(),     name="hr-leave-decide"),
    path("leave/<uuid:pk>/attachment/",        HrLeaveAttachmentView.as_view(), name="hr-leave-attachment"),
    path("leave/balance/<uuid:employee_id>/",  HrLeaveBalanceView.as_view(),    name="hr-leave-balance"),
    # payroll (G8b part 1)
    path("payroll/settings/",                                    SettingsView.as_view(),       name="hr-payroll-settings"),
    path("payroll/runs/",                                        RunListView.as_view(),        name="hr-payroll-runs"),
    path("payroll/runs/<uuid:pk>/",                              RunDetailView.as_view(),      name="hr-payroll-run"),
    path("payroll/runs/<uuid:pk>/recalculate/",                  RunRecalculateView.as_view(), name="hr-payroll-recalc"),
    path("payroll/runs/<uuid:pk>/lock/",                         RunLockView.as_view(),        name="hr-payroll-lock"),
    path("payroll/runs/<uuid:pk>/lines/<uuid:line_id>/",         LineDetailView.as_view(),     name="hr-payroll-line"),
    path("payroll/runs/<uuid:pk>/lines/<uuid:line_id>/items/",   LineItemsView.as_view(),      name="hr-payroll-items"),
    path("payroll/runs/<uuid:pk>/items/<uuid:item_id>/",         ItemDeleteView.as_view(),     name="hr-payroll-item"),
    path("payroll/runs/<uuid:pk>/slips/",                        SlipsView.as_view(),          name="hr-payroll-slips"),
    path("payroll/runs/<uuid:pk>/transfers/",                    TransfersView.as_view(),      name="hr-payroll-transfers"),
]
