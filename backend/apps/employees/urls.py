from django.urls import path

from .views import WorkerLoginView, WorkerPinView

urlpatterns = [
    path("login/", WorkerLoginView.as_view(), name="worker-login"),
    path("pin/",   WorkerPinView.as_view(),   name="worker-pin"),
]
