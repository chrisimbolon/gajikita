"""
G17-12 (19 Nov 2026) — fingerprint taps get a location from their machine; old taps are filled once, with undo.
Made-up people (the shapes of test_fingerprint_import).
"""
from datetime import date

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.attendance.tests import test_fingerprint_import as base             # the module: its tests run once there
from apps.organizations.models import Organization
from apps.sites.models import Site

MACHINES, MAIN, FILL = ("/api/hr/fingerprint/machines/", "/api/hr/fingerprint/machines/main/",
                        "/api/hr/fingerprint/machines/fill-site/")


class MachineSiteTests(base.FingerprintImportTests):
    def setUp(self):
        super().setUp()
        self.plant = Site.objects.create(organization=self.org, name="Plant Contoh")

    def set_main(self, site):
        r = self.client.patch(MAIN, {"site": str(site.pk) if site else None}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data["main"]

    def sites(self):
        return set(ClockEvent.objects.values_list("site__name", flat=True))

    def test_new_taps_take_the_machine_location(self):
        self.assertEqual(self.set_main(self.plant)["site_name"], "Plant Contoh")
        self.post("1")
        self.assertEqual(self.sites(), {"Plant Contoh"})
        self.assertEqual(self.client.get(MACHINES).data["main"]["no_site"], 0)

    def test_old_taps_are_filled_once_and_can_be_put_back(self):
        self.post("1")                                                       # imported before a location existed
        self.assertEqual(self.sites(), {None})
        r = self.client.post(FILL, {"machine": "main"}, format="json")
        self.assertEqual((r.status_code, r.data["message"]), (400, "Pilih dulu lokasi mesin ini, lalu simpan."))
        self.assertEqual(self.set_main(self.plant)["no_site"], 6)
        AttendanceDay.objects.filter(employee=self.sudar, date=date(2026, 10, 3)).update(is_locked=True)   # 2 taps
        self.assertEqual(self.client.post(FILL, {"machine": "main"}, format="json").data["count"], 4)
        r = self.client.post(FILL, {"machine": "main", "commit": True}, format="json").data
        self.assertEqual((r["filled"], r["main"]["no_site"]), (4, 0))
        self.assertEqual(ClockEvent.objects.filter(site=self.plant).count(), 4)
        self.assertEqual(ClockEvent.objects.filter(site__isnull=True, day__is_locked=True).count(), 2)   # locked: untouched
        u = self.client.post(FILL, {"undo": r["batch"]}, format="json").data
        self.assertEqual((u["undone"], u["main"]["no_site"]), (4, 4))
        self.assertFalse(ClockEvent.objects.filter(site=self.plant).exists())

    def test_moving_the_machine_never_rewrites_old_taps(self):
        self.set_main(self.plant)
        self.post("1")
        other = Site.objects.create(organization=self.org, name="Lobam Contoh")
        self.assertEqual(self.set_main(other)["no_site"], 0)                # nothing to fill: all have a location
        self.assertEqual(self.sites(), {"Plant Contoh"})

    def test_another_companys_site_is_refused(self):
        stranger = Site.objects.create(organization=Organization.objects.create(name="PT Lain"), name="Lain")
        r = self.client.patch(MAIN, {"site": str(stranger.pk)}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.patch(MAIN, {"site": "bukan-uuid"}, format="json").status_code, 400)


for _name in [n for n in dir(base.FingerprintImportTests) if n.startswith("test_")]:
    setattr(MachineSiteTests, _name, None)                                   # base tests run in their own module
