// =============================================================================
// === frontend/lib/api/checklist.ts ===
// "Siap gajian?" — Perlu Tinjau as a guided checklist (G17-7, 16 Nov 2026).
// Mirrors backend/apps/attendance/checklist.py.
// =============================================================================
import api from "@/lib/api";

export interface CkEmployee { id: string; employee_no: string; full_name: string }
export interface CkNote { code: string; text: string }
interface CkDayBase { day_id: string; date: string; in: string | null; out: string | null; note: CkNote | null }
export interface CkOvertimeDay extends CkDayBase { proposed: number; suggested: number; rest_day: boolean }
export interface CkMissingDay extends CkDayBase { kind: string; forgiven: boolean; cut: boolean }
export interface CkLateDay extends CkDayBase { late: number; early: number; charged: number; half: number; rupiah: number; forgiven: boolean }
export interface CkOvertimePerson { employee: CkEmployee; days: CkOvertimeDay[]; proposed: number }
export interface CkMissingPerson { employee: CkEmployee; days: CkMissingDay[]; cut_days: number; rupiah: number }
export interface CkLatePerson { employee: CkEmployee; days: CkLateDay[]; minutes: number; rupiah: number; count: number; half_days: number }
export interface CkSuggestion { start: string; end: string; people: number; peak: number; names: string[]; absent: number; one_tap: number }
export interface CkNoTrack {                                                               // G17-7.1, G17-7.2
  employee: CkEmployee; kind: "notrack" | "left"; expected: number; tapped: number; complete: number; start: string;
  last_tap: string | null; missing_after: number;
}

export interface CkConflict {                                                              // G20-2
  date: string; day_id: string | null; kind: "taps_on_leave" | "meal_on_leave" | "overtime_on_leave" | "half_and_overtime";
  kind_label: string; text: string;
}
export interface CkConflictPerson { employee: CkEmployee; items: CkConflict[] }

export interface Checklist {
  month: string; label: string; start: string; end: string; prev: string; next: string;
  rules: { late_fine_per_minute: string; late_tolerance_minutes: number; fine_set: boolean; single_tap_half_day: boolean; overtime_cap_minutes: number | null;
           long_late_half_day_minutes: number | null };
  no_track: CkNoTrack[];
  import: { days: number; people: number; employees: number; last_import: string | null; until: string; short: boolean };
  events: { existing: { id: string; start: string; end: string; kind: string; kind_label: string; reason: string }[]; suggestions: CkSuggestion[] };
  notes: { total: number; todo: number } | null;
  overtime: { open_days: number; people: CkOvertimePerson[]; proposed: number; decided_days: number };
  missing: { days: number; cut_days: number; rupiah: number; people: CkMissingPerson[] };
  late: { count: number; minutes: number; half_days: number; rupiah: number; people: CkLatePerson[] };
  conflicts: { days: number; people: CkConflictPerson[] };                                  // G20-2
  saran: { count: number; people: CkSaranPerson[] };                                         // G21-3a
  run: { id: string; name: string; locked: boolean } | null;
}

/** G21-3a: Saran SeeGaji per person (s1-s3; leave with taps is "Tidak cocok"). */
export interface CkSaranPerson {
  employee: { id: string; employee_no: string; full_name: string }; count: number; first_date: string;
  items: { date: string; kind: string; strength: "kuat" | "lemah"; text: string }[];
}

export const checklistApi = {
  async get(month?: string): Promise<Checklist> {
    const { data } = await api.get("/api/hr/attendance/checklist/", { params: { month }, timeout: 180000 });
    return data;
  },
  async dismiss(start: string, end: string): Promise<void> {
    await api.post("/api/hr/attendance/checklist/dismiss/", { start, end });
  },
  async keepTracking(employee: string): Promise<void> {                                     // G17-7.1
    await api.post("/api/hr/attendance/checklist/dismiss/", { employee });
  },
  async conflictOk(employee: string, date: string, kind: string): Promise<void> {           // G20-2: "Sudah benar"
    await api.post("/api/hr/attendance/checklist/dismiss/", { conflict: { employee, date, kind } });
  },
};
