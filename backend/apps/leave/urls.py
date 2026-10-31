"""/api/worker/leave/ — the worker's leave requests (G7)."""
from django.urls import path

from .views import CrewLeaveDecideView, MyLeaveCancelView, MyLeaveView

urlpatterns = [
    path("",                    MyLeaveView.as_view(),         name="worker-leave"),
    path("<uuid:pk>/cancel/",   MyLeaveCancelView.as_view(),   name="worker-leave-cancel"),
    path("<uuid:pk>/decide/",   CrewLeaveDecideView.as_view(), name="worker-leave-decide"),
]
