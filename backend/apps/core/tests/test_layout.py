"""Guard: every app keeps its tests in a tests/ package (same rule as Arthasee)."""
from pathlib import Path

from django.test import SimpleTestCase

APPS_DIR = Path(__file__).resolve().parents[2]


class TestLayoutTests(SimpleTestCase):
    def test_no_test_files_at_app_top_level(self):
        stray = sorted(str(p.relative_to(APPS_DIR)) for p in APPS_DIR.glob("*/test*.py"))
        self.assertEqual(stray, [], "Put test files in apps/<app>/tests/ (with an __init__.py).")

    def test_every_tests_folder_is_a_package(self):
        missing = sorted(str(d.relative_to(APPS_DIR)) for d in APPS_DIR.glob("*/tests")
                         if d.is_dir() and not (d / "__init__.py").exists())
        self.assertEqual(missing, [], "Each tests/ folder needs an __init__.py or Django won't find it.")
