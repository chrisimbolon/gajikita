"""
G22-1 (28 Nov 2026) — office users inside SeeGaji: "Akun saya → Ubah password" and "Pengguna" (add HR, temporary
password changed at first login, switch off, reset, role). Made-up company and people.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.organizations.models import OrganizationMembership

OWNER = {"email": "pemilik@contoh.id", "password": "Bintan-Raya-2026", "full_name": "Budi Pemilik",
         "organization_name": "PT Contoh Beton"}
MEMBERS = "/api/organizations/members/"
PASSWORD = "/api/auth/password/"
HR_SCREEN = "/api/hr/payroll/settings/"          # any office screen behind IsCompanyHR


class UsersTests(APITestCase):
    def setUp(self):
        self.client.post("/api/auth/register/", OWNER, format="json")
        self.login(OWNER["email"], OWNER["password"])

    def login(self, email, password, expect=status.HTTP_200_OK):
        self.client.credentials()
        r = self.client.post("/api/auth/login/", {"email": email, "password": password}, format="json")
        self.assertEqual(r.status_code, expect, r.data)
        if expect == status.HTTP_200_OK:
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        return r.data

    def add(self, email="sari@contoh.id", name="Sari HR", role="hr", expect=status.HTTP_201_CREATED):
        r = self.client.post(MEMBERS, {"email": email, "full_name": name, "role": role}, format="json")
        self.assertEqual(r.status_code, expect, r.data)
        return r.data

    def act(self, member_id, action, expect=status.HTTP_200_OK, **extra):
        r = self.client.patch(f"{MEMBERS}{member_id}/", {"action": action, **extra}, format="json")
        self.assertEqual(r.status_code, expect, r.data)
        return r.data

    def test_owner_adds_hr_who_must_change_the_temporary_password(self):
        data = self.add()
        temp = data["temp_password"]
        self.assertEqual(len(temp), 10)
        self.assertEqual((data["member"]["role"], data["member"]["user"]["must_change_password"]), ("hr", True))
        self.assertTrue(AuditEntry.objects.filter(action="user.add").exists())
        self.login("sari@contoh.id", temp)
        self.assertTrue(self.client.get("/api/auth/me/").data["user"]["must_change_password"])
        r = self.client.get(HR_SCREEN)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)                   # office screens wait
        self.assertIn("Ganti password sementara", str(r.data))
        r = self.client.post(PASSWORD, {"old_password": temp, "new_password": "Sari-Kantor-77"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertFalse(r.data["user"]["must_change_password"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['tokens']['access']}")
        self.assertEqual(self.client.get(HR_SCREEN).status_code, status.HTTP_200_OK)

    def test_change_password_checks(self):
        bad = lambda body: self.client.post(PASSWORD, body, format="json")
        self.assertIn("old_password", bad({"old_password": "salah", "new_password": "Apa-Saja-123"}).data["errors"])
        self.assertIn("new_password", bad({"old_password": OWNER["password"], "new_password": "pendek"}).data["errors"])
        same = bad({"old_password": OWNER["password"], "new_password": OWNER["password"]})
        self.assertIn("harus berbeda", str(same.data))

    def test_changing_the_password_signs_out_other_devices(self):
        other = self.login(OWNER["email"], OWNER["password"])                       # e.g. the leaked login
        self.client.post(PASSWORD, {"old_password": OWNER["password"], "new_password": "Baru-Aman-2026"}, format="json")
        r = self.client.post("/api/auth/refresh/", {"refresh": other["refresh"]}, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        self.login(OWNER["email"], OWNER["password"], expect=status.HTTP_401_UNAUTHORIZED)
        self.login(OWNER["email"], "Baru-Aman-2026")

    def test_switch_off_reset_and_back_on(self):
        data = self.add()
        mid, temp = data["member"]["id"], data["temp_password"]
        self.act(mid, "deactivate")
        self.assertFalse(CustomUser.objects.get(email="sari@contoh.id").is_active)
        self.login(OWNER["email"], OWNER["password"])
        self.act(mid, "activate")
        reset = self.act(mid, "reset_password")
        self.assertNotEqual(reset["temp_password"], temp)
        self.login("sari@contoh.id", temp, expect=status.HTTP_401_UNAUTHORIZED)      # the old one is gone
        self.login("sari@contoh.id", reset["temp_password"])
        self.assertTrue(self.client.get("/api/auth/me/").data["user"]["must_change_password"])

    def test_who_may_do_what(self):
        self.add(email="sari@contoh.id")
        self.add(email="sari@contoh.id", expect=status.HTTP_400_BAD_REQUEST)        # email already used
        admin = self.add(email="adi@contoh.id", name="Adi Admin", role="admin")
        owner_row = OrganizationMembership.objects.get(user__email=OWNER["email"])
        self.act(owner_row.pk, "deactivate", expect=status.HTTP_400_BAD_REQUEST)      # not yourself
        # the admin, once their password is changed, may add HR but not another admin, and not touch the owner
        self.login("adi@contoh.id", admin["temp_password"])
        r = self.client.post(PASSWORD, {"old_password": admin["temp_password"], "new_password": "Kunci-Rahasia-55"},
                             format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['tokens']['access']}")
        self.add(email="tono@contoh.id", name="Tono HR")
        self.add(email="ani@contoh.id", role="admin", expect=status.HTTP_400_BAD_REQUEST)
        self.act(owner_row.pk, "deactivate", expect=status.HTTP_403_FORBIDDEN)
        listing = self.client.get(MEMBERS).data
        self.assertEqual((listing["my_role"], listing["can_assign"]), ("admin", ["hr"]))
        self.assertEqual(len(listing["members"]), 4)
        # plain HR cannot open the page
        tono = CustomUser.objects.get(email="tono@contoh.id")
        tono.set_password("Tono-HR-2026")
        tono.must_change_password = False
        tono.save()
        self.login("tono@contoh.id", "Tono-HR-2026")
        self.assertEqual(self.client.get(MEMBERS).status_code, status.HTTP_403_FORBIDDEN)
