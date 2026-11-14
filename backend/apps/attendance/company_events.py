# =============================================================================
# === backend/apps/attendance/company_events.py ===
# =============================================================================
"""
Company events ("Kejadian", G17-2, 14 Nov 2026). Pure Python, no Django.

DKCB, 12-14 Okt 2026: the power went out. People tapped once, twice or not at all, and Anthony paid everyone
a full day ("Mati lampu" in his notes). SeeGaji asked HR about it person by person, day by day, and cut ½ days.
An event is entered ONCE for a date range and a group of people:

  DISRUPTION ("gangguan")  attendance disrupted (power cut, broken machine): a working day counts as worked.
                           No late, early-out, no-clock-in/out or ½-day cut; no taps = present. Overtime from a
                           real late tap still counts. Leave, "tidak wajib absen" and HR's decisions still win.
  HOLIDAY ("libur")        a company or national holiday: a working day becomes a day off. Nobody is absent;
                           whoever works is paid the rest-day rate.

Who: everyone, or chosen locations (the employee's main location) and/or chosen people.

  Event(...).applies(employee_id, site_id, day)
  event_for(events, employee_id, site_id, day)   (kind, reason) or None; a holiday wins over a disruption
  label(kind, reason)                            "Gangguan absen: Mati lampu"
"""
from dataclasses import dataclass, field
from datetime import date as Date

DISRUPTION, HOLIDAY = "gangguan", "libur"
LABELS = {DISRUPTION: "Gangguan absen", HOLIDAY: "Libur"}
MAX_DAYS = 62                     # one event covers at most two pay periods; longer is a typo


@dataclass(frozen=True)
class Event:
    start: Date
    end: Date
    kind: str
    reason: str
    everyone: bool = True
    site_ids: frozenset = field(default_factory=frozenset)
    employee_ids: frozenset = field(default_factory=frozenset)

    def applies(self, employee_id, site_id, day):
        if not (self.start <= day <= self.end):
            return False
        return self.everyone or employee_id in self.employee_ids or (site_id is not None and site_id in self.site_ids)


def event_for(events, employee_id, site_id, day):
    hits = [e for e in events if e.applies(employee_id, site_id, day)]
    if not hits:
        return None
    e = next((x for x in hits if x.kind == HOLIDAY), hits[0])
    return (e.kind, e.reason)


def label(kind, reason):
    return f"{LABELS.get(kind, kind)}: {reason}"
