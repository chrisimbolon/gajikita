# =============================================================================
# === backend/apps/employees/worker_login.py ===
# =============================================================================
"""
Phone + PIN login for workers (G2a, 27 Oct 2026).

Workers don't have work email addresses, so each worker who can log in
gets a hidden CustomUser (role "employee", an internal email nobody types)
whose password is the PIN, hashed by Django like any password. The worker
only ever sees: phone number + 6-digit PIN.

  enable_login(employee, phone, pin=None)  HR (or a command) turns login on; returns the PIN
  check_login(phone, pin)                  used by POST /api/worker/login/
  change_pin(employee, current, new)       used by POST /api/worker/pin/

5 wrong PINs lock the login for 15 minutes.
"""
import re
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.authentication.models import CustomUser

from .models import Employee

MAX_ATTEMPTS = 5
LOCK_MINUTES = 15
WORKER_EMAIL_DOMAIN = "pekerja.gajikita.id"


class LoginError(Exception):
    def __init__(self, message, locked_minutes=None):
        super().__init__(message)
        self.message = message
        self.locked_minutes = locked_minutes


def normalize_phone(raw):
    """'+62 812-3456-7890', '6281234567890', '81234567890' -> '081234567890'."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("62"):
        digits = "0" + digits[2:]
    elif digits.startswith("8"):
        digits = "0" + digits
    return digits


def validate_pin(pin):
    """6 digits, not all the same, not a straight run like 123456 or 654321."""
    pin = pin or ""
    if not re.fullmatch(r"\d{6}", pin):
        raise ValueError("PIN harus 6 angka.")
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    if steps in ({0}, {1}, {-1}):
        raise ValueError("PIN terlalu mudah ditebak. Hindari angka sama atau berurutan.")
    return pin


def generate_pin():
    while True:
        pin = f"{secrets.randbelow(1_000_000):06d}"
        try:
            return validate_pin(pin)
        except ValueError:
            continue


def enable_login(employee, phone, pin=None):
    """Turn on phone + PIN login for this employee. Returns the PIN to hand to the worker."""
    phone = normalize_phone(phone)
    if not re.fullmatch(r"08\d{7,12}", phone):
        raise ValueError("No. HP tidak valid. Contoh: 0812 3456 7890.")
    if Employee.objects.filter(login_phone=phone).exclude(pk=employee.pk).exists():
        raise ValueError("No. HP ini sudah dipakai login oleh karyawan lain.")
    pin = validate_pin(pin) if pin else generate_pin()

    with transaction.atomic():
        user = employee.user
        if user is None:
            user = CustomUser.objects.create_user(
                email=f"w-{employee.id.hex}@{WORKER_EMAIL_DOMAIN}", password=pin,
                full_name=employee.full_name, phone=phone, role=CustomUser.Role.EMPLOYEE,
            )
        else:
            user.set_password(pin)
            user.phone = phone
            user.save(update_fields=["password", "phone"])
        employee.user = user
        employee.login_phone = phone
        employee.phone = employee.phone or phone
        employee.must_change_pin = True
        employee.pin_failed_attempts = 0
        employee.pin_locked_until = None
        employee.save(update_fields=["user", "login_phone", "phone", "must_change_pin",
                                     "pin_failed_attempts", "pin_locked_until", "updated_at"])
    return pin


WRONG = "No. HP atau PIN salah."


def _minutes_left(until, now):
    return max(1, int((until - now).total_seconds() // 60) + 1)


def check_login(phone, pin):
    """Returns the Employee on success; raises LoginError otherwise."""
    error = _check_login(normalize_phone(phone), pin or "", timezone.now())
    if isinstance(error, LoginError):
        # Raised only AFTER the transaction has committed, so the failed-attempt
        # count is saved (raising inside it would roll the count back).
        raise error
    return error


def _check_login(phone, pin, now):
    with transaction.atomic():
        # of=("self",): lock only the employee row. Postgres refuses to lock the
        # nullable side of the LEFT JOIN that select_related("user") adds.
        emp = (Employee.objects.select_for_update(of=("self",)).select_related("user", "organization")
               .filter(login_phone=phone).first()) if phone else None
        if emp is None or emp.user is None or not emp.is_active or not emp.user.is_active:
            return LoginError(WRONG)
        if emp.pin_locked_until and emp.pin_locked_until > now:
            left = _minutes_left(emp.pin_locked_until, now)
            return LoginError(f"Terlalu banyak percobaan. Coba lagi dalam {left} menit "
                              "atau minta HR mengatur ulang PIN.", locked_minutes=left)
        if not emp.user.check_password(pin):
            emp.pin_failed_attempts += 1
            if emp.pin_failed_attempts >= MAX_ATTEMPTS:
                emp.pin_failed_attempts = 0
                emp.pin_locked_until = now + timedelta(minutes=LOCK_MINUTES)
                emp.save(update_fields=["pin_failed_attempts", "pin_locked_until"])
                return LoginError(f"Terlalu banyak percobaan. Login dikunci {LOCK_MINUTES} menit.",
                                  locked_minutes=LOCK_MINUTES)
            emp.save(update_fields=["pin_failed_attempts"])
            return LoginError(f"{WRONG} Sisa percobaan: {MAX_ATTEMPTS - emp.pin_failed_attempts}.")
        if emp.pin_failed_attempts or emp.pin_locked_until:
            emp.pin_failed_attempts = 0
            emp.pin_locked_until = None
            emp.save(update_fields=["pin_failed_attempts", "pin_locked_until"])
        return emp


def change_pin(employee, current, new):
    if not employee.user or not employee.user.check_password(current or ""):
        raise ValueError("PIN lama salah.")
    validate_pin(new)
    if new == current:
        raise ValueError("PIN baru harus berbeda dari PIN lama.")
    employee.user.set_password(new)
    employee.user.save(update_fields=["password"])
    employee.must_change_pin = False
    employee.save(update_fields=["must_change_pin", "updated_at"])
