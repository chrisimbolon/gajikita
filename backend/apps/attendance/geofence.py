# =============================================================================
# === backend/apps/attendance/geofence.py ===
# =============================================================================
"""
The geofence rules, as plain Python with no Django imports, so every rule
can be tested on its own and read in one place. GajiKita Design v0.1,
"Attendance with geofence".

The one principle: a worker can ALWAYS clock in. These functions never
refuse anything; they only work out which site the tap belongs to and
which flags HR should see in the exceptions queue.
"""
import math
from dataclasses import dataclass, field
from datetime import timedelta

EARTH_RADIUS_M = 6_371_008.8      # mean Earth radius (IUGG)
LOW_ACCURACY_M = 100              # GPS worse than +/-100 m is flagged
TIME_GAP_MINUTES = 10             # phone clock vs server clock
MAX_OFFLINE_HOURS = 72            # how long a phone may hold taps without signal (vessels)
FENCED_KINDS = ("fixed", "moving")


class Flag:
    OUTSIDE_SITE = "outside_site"
    LOW_ACCURACY = "low_accuracy"
    NO_GPS       = "no_gps"
    NO_SITE      = "no_site"
    NO_PIN       = "no_pin"
    TIME_GAP     = "time_gap"
    OFFLINE      = "offline"
    NO_SELFIE    = "no_selfie"
    NO_CLOCK_IN  = "no_clock_in"
    ALREADY_IN   = "already_in"


FLAG_LABELS = {
    Flag.OUTSIDE_SITE: "Di luar lokasi",
    Flag.LOW_ACCURACY: "GPS kurang akurat",
    Flag.NO_GPS:       "Tanpa GPS",
    Flag.NO_SITE:      "Belum ada lokasi kerja",
    Flag.NO_PIN:       "Lokasi belum punya titik",
    Flag.TIME_GAP:     "Jam HP berbeda dengan server",
    Flag.OFFLINE:      "Terkirim terlambat (offline)",
    Flag.NO_SELFIE:    "Tanpa selfie",
    Flag.NO_CLOCK_IN:  "Tidak ada absen masuk",
    Flag.ALREADY_IN:   "Sudah absen masuk",
}


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between two lat/lng points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Candidate:
    """One site the worker may clock in at, with the pin valid at the time of the tap."""
    site_id: object
    kind: str
    latitude: float = None
    longitude: float = None
    radius_m: int = None
    location_id: object = None

    @property
    def is_fenced(self):
        return self.kind in FENCED_KINDS

    @property
    def has_pin(self):
        return self.latitude is not None and self.longitude is not None


@dataclass
class Result:
    site_id: object = None
    location_id: object = None
    distance_m: int = None
    flags: list = field(default_factory=list)


def evaluate(candidates, latitude, longitude, accuracy_m):
    """
    Decide which site a tap belongs to and which flags it gets.

      1. Inside the radius of a fenced site -> the nearest such site, no flag.
      2. Not inside any, but the worker has a vessel / no-location site -> that site, no flag.
      3. Otherwise -> the nearest fenced site, flagged "outside_site" with its distance.

    GPS accuracy worse than LOW_ACCURACY_M adds "low_accuracy" on top.
    """
    result = Result()
    if accuracy_m is not None and accuracy_m > LOW_ACCURACY_M:
        result.flags.append(Flag.LOW_ACCURACY)

    if not candidates:
        result.flags.append(Flag.NO_SITE)
        return result

    unfenced = [c for c in candidates if not c.is_fenced]
    measurable = [c for c in candidates if c.is_fenced and c.has_pin]
    pinless = [c for c in candidates if c.is_fenced and not c.has_pin]

    if latitude is None or longitude is None:
        result.flags.append(Flag.NO_GPS)
        if len(candidates) == 1:
            _take(result, candidates[0])
        return result

    measured = sorted(
        ((haversine_m(latitude, longitude, c.latitude, c.longitude), c) for c in measurable),
        key=lambda pair: pair[0],
    )
    for distance, cand in measured:
        if distance <= cand.radius_m:
            _take(result, cand, distance)
            return result

    if unfenced:
        _take(result, unfenced[0])
        return result

    if measured:
        distance, cand = measured[0]
        _take(result, cand, distance)
        result.flags.append(Flag.OUTSIDE_SITE)
        return result

    _take(result, pinless[0])
    result.flags.append(Flag.NO_PIN)
    return result


def _take(result, cand, distance=None):
    result.site_id = cand.site_id
    result.location_id = cand.location_id
    result.distance_m = round(distance) if distance is not None else None


def resolve_time(received_at, phone_time, queued):
    """
    When did the tap happen? Returns (occurred_at, flags).

    Normally the server clock decides: workers can change their phone's clock.
    A tap saved on the phone without signal ("queued") keeps the phone's time,
    so a 07:00 clock-in sent at 09:00 isn't counted as late; it is flagged
    "offline" for HR when it arrives more than TIME_GAP_MINUTES late. Phone
    times in the future or older than MAX_OFFLINE_HOURS are not trusted.
    """
    if phone_time is None:
        return received_at, []
    behind = received_at - phone_time          # positive: the phone's time is earlier
    gap = timedelta(minutes=TIME_GAP_MINUTES)

    if queued:
        if behind > timedelta(hours=MAX_OFFLINE_HOURS) or behind < -gap:
            return received_at, [Flag.OFFLINE, Flag.TIME_GAP]
        if behind > gap:
            return phone_time, [Flag.OFFLINE]
        return (phone_time if behind > timedelta(0) else received_at), []

    if abs(behind) > gap:
        return received_at, [Flag.TIME_GAP]
    return received_at, []


def work_date(local_dt, shift_start=None, shift_end=None):
    """
    Which working day a clock-in belongs to. On a night shift (e.g. 22:00-06:00),
    a clock-in after midnight but before the shift ends belongs to the day
    the shift started.
    """
    if shift_start is not None and shift_end is not None and shift_end <= shift_start:
        if local_dt.time() < shift_end:
            return local_dt.date() - timedelta(days=1)
    return local_dt.date()
