"""/api/hr/ — HR's office screens (G2b): employees, sites, shifts."""
from django.urls import path

from apps.sites.hr_views import ShiftDetailView, ShiftListView, SiteDetailView, SiteListView, SitePinView

from apps.attendance.hr_views import DailyView, DayDetailView, DecideView, FixTimesView, ReviewQueueView, SelfieView
from apps.payroll.views import OvertimeMonthView
from apps.attendance.dashboard import SummaryView

from .hr_views import EmployeeDetailView, EmployeeListView, EmployeeLoginView

urlpatterns = [
    path("employees/",                EmployeeListView.as_view(),   name="hr-employees"),
    path("employees/<uuid:pk>/",      EmployeeDetailView.as_view(), name="hr-employee"),
    path("employees/<uuid:pk>/login/", EmployeeLoginView.as_view(), name="hr-employee-login"),
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
]
