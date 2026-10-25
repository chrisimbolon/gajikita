"""Sign-up, login and /me — a company admin's first minute in the app."""
from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership
from rest_framework import status
from rest_framework.test import APITestCase

SIGNUP = {"email": "admin@test.id", "password": "pass12345!", "full_name": "Admin HR",
          "phone": "0811", "organization_name": "PT Maju Konstruksi"}


class AuthFlowTests(APITestCase):
    def test_register_creates_user_company_and_owner_membership(self):
        resp = self.client.post("/api/auth/register/", SIGNUP, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", resp.data["tokens"])
        user = CustomUser.objects.get(email="admin@test.id")
        self.assertEqual(user.role, "owner")
        m = OrganizationMembership.objects.get(user=user)
        self.assertEqual((m.role, m.organization.name, m.organization.invoice_code), ("owner", "PT Maju Konstruksi", "MK"))

    def test_duplicate_email_is_refused_and_nothing_is_created(self):
        self.client.post("/api/auth/register/", SIGNUP, format="json")
        resp = self.client.post("/api/auth/register/", {**SIGNUP, "organization_name": "Lain"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Organization.objects.count(), 1)

    def test_login_then_me(self):
        self.client.post("/api/auth/register/", SIGNUP, format="json")
        login = self.client.post("/api/auth/login/", {"email": SIGNUP["email"], "password": SIGNUP["password"]}, format="json")
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data["user"]["email"], SIGNUP["email"])

    def test_me_needs_login(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, status.HTTP_401_UNAUTHORIZED)
