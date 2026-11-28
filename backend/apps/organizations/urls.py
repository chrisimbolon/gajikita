from django.urls import path

from .members import MembersView, MemberView
from .views import MyOrganizationView

urlpatterns = [
    path("mine/", MyOrganizationView.as_view(), name="organization-mine"),
    path("members/", MembersView.as_view(), name="organization-members"),                  # G22-1
    path("members/<uuid:pk>/", MemberView.as_view(), name="organization-member"),
]
