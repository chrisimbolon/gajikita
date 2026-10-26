"""GET/PATCH /api/organizations/mine/ — owner-only edits, never plan or is_active."""
from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership
from rest_framework import status
from rest_framework.test import APITestCase

URL = "/api/organizations/mine/"


class MyOrganizationTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Bangun Wira Indah")
        self.owner = CustomUser.objects.create_user(email="o@test.id", password="pass12345!", full_name="Owner")
        self.staff = CustomUser.objects.create_user(email="s@test.id", password="pass12345!", full_name="Staff")
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role="owner")
        OrganizationMembership.objects.create(organization=self.org, user=self.staff, role="admin")

    def test_invoice_code_is_generated_from_the_name(self):
        self.assertEqual(self.org.invoice_code, "BWI")

    def test_get_returns_my_company_and_role(self):
        self.client.force_authenticate(self.staff)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual((resp.data["organization"]["name"], resp.data["role"]), ("PT Bangun Wira Indah", "admin"))

    def test_owner_can_edit_but_not_plan(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.patch(URL, {"name": "Bangun Wira", "invoice_code": "bw", "plan": "pro"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.org.refresh_from_db()
        self.assertEqual((self.org.name, self.org.invoice_code, self.org.plan), ("Bangun Wira", "BW", "free"))

    def test_staff_cannot_edit(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.patch(URL, {"name": "X"}, format="json").status_code, status.HTTP_403_FORBIDDEN)

    def test_user_without_company_gets_404(self):
        lonely = CustomUser.objects.create_user(email="l@test.id", password="pass12345!", full_name="L")
        self.client.force_authenticate(lonely)
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_404_NOT_FOUND)
