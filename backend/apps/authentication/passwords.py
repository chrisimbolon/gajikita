"""
G22-1 (28 Nov 2026) — passwords for office users: a readable temporary password, the checks a new password
must pass (in plain Indonesian), and "keluar dari semua perangkat" so an old or leaked password stops working.
"""
import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

# no 0/O, 1/l/I: a temporary password is read out loud or typed from a screen
ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MIN_LENGTH = 8


def temp_password(length=10):
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def password_problems(user, new, old=None):
    """[] when `new` may be used; otherwise the reasons, one sentence each."""
    problems = []
    if len(new or "") < MIN_LENGTH:
        problems.append(f"Password baru minimal {MIN_LENGTH} karakter.")
    if old is not None and new == old:
        problems.append("Password baru harus berbeda dari password lama.")
    if not problems:
        try:
            validate_password(new, user)                  # Django's own checks (common, similar to email, numeric)
        except ValidationError as err:
            problems.extend(err.messages)
    return problems


def sign_out_everywhere(user):
    """Every refresh token this user holds stops working (rotation + blacklist are on). Access tokens die on their own
    within ACCESS_TOKEN_LIFETIME (60 minutes)."""
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def set_password(user, new, *, temporary):
    user.set_password(new)
    user.must_change_password = temporary
    user.save(update_fields=["password", "must_change_password"])
    sign_out_everywhere(user)
