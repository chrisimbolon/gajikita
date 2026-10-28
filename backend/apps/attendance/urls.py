from django.urls import path

from .views import ClockView, TodayView

urlpatterns = [
    path("clock/", ClockView.as_view(), name="attendance-clock"),
    path("today/", TodayView.as_view(), name="attendance-today"),
]
