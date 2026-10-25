"""Health check and tenant isolation — the two things everything else stands on."""
import uuid

from apps.authentication.models import CustomUser
from apps.core.models import Outbox
from apps.core.views import TenantScopedAPIView
from apps.organizations.models import Organization, OrganizationMembership
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase


class HealthTests(APITestCase):
    def test_health_is_open_and_ok(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "ok")


class TenantIsolationTests(APITestCase):
    """Outbox is a TenantScopedModel, so it doubles as the test subject."""

    def _row(self, org):
        return Outbox.objects.create(organization=org, event_id=uuid.uuid4(), event_type="Test",
                                     payload={}, occurred_at=timezone.now())

    def _view_for(self, user):
        view = TenantScopedAPIView()
        view.model = Outbox
        view.request = type("Req", (), {"user": user})()
        return view

    def setUp(self):
        self.company_a = Organization.objects.create(name="Perusahaan A")
        self.company_b = Organization.objects.create(name="Perusahaan B")
        self.owner_a = CustomUser.objects.create_user(email="a@test.id", password="pass12345!", full_name="A")
        OrganizationMembership.objects.create(organization=self.company_a, user=self.owner_a, role="owner")
        self.row_a, self.row_b = self._row(self.company_a), self._row(self.company_b)

    def test_owner_sees_only_their_company(self):
        ids = set(self._view_for(self.owner_a).get_queryset().values_list("id", flat=True))
        self.assertEqual(ids, {self.row_a.id})

    def test_inactive_membership_sees_nothing(self):
        OrganizationMembership.objects.filter(user=self.owner_a).update(is_active=False)
        self.assertFalse(self._view_for(self.owner_a).get_queryset().exists())

    def test_super_admin_sees_every_company(self):
        admin = CustomUser.objects.create_superuser(email="admin@test.id", password="pass12345!", full_name="Admin")
        self.assertEqual(self._view_for(admin).get_queryset().count(), 2)
        self.assertIsNone(self._view_for(admin).get_organization())
