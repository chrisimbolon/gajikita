from django.urls import include, path

from .views import WorkerLoginView, WorkerPinView

urlpatterns = [
    path("login/", WorkerLoginView.as_view(), name="worker-login"),
    path("pin/",   WorkerPinView.as_view(),   name="worker-pin"),
    path("leave/", include("apps.leave.urls")),          # cuti / izin from the phone (G7)
]
