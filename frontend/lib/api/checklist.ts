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
export interface CkLateDay extends CkDayBase { late: number; early: number; charged: number; rupiah: number; forgiven: boolean }
export interface CkOvertimePerson { employee: CkEmployee; days: CkOvertimeDay[]; proposed: number }
export interface CkMissingPerson { employee: CkEmployee; days: CkMissingDay[]; cut_days: number; rupiah: number }
export interface CkLatePerson { employee: CkEmployee; days: CkLateDay[]; minutes: number; rupiah: number; count: number }
export interface CkSuggestion { start: string; end: string; people: number; peak: number; names: string[]; absent: number; one_tap: number }
export interface CkNoTrack { employee: CkEmployee; expected: number; tapped: number; complete: number; start: string }   // G17-7.1

export interface Checklist {
  month: string; label: string; start: string; end: string; prev: string; next: string;
  rules: { late_fine_per_minute: string; late_tolerance_minutes: number; fine_set: boolean; single_tap_half_day: boolean; overtime_cap_minutes: number | null };
  no_track: CkNoTrack[];
  import: { days: number; people: number; employees: number; last_import: string | null };
  events: { existing: { id: string; start: string; end: string; kind: string; kind_label: string; reason: string }[]; suggestions: CkSuggestion[] };
  notes: { total: number; todo: number } | null;
  overtime: { open_days: number; people: CkOvertimePerson[]; proposed: number; decided_days: number };
  missing: { days: number; cut_days: number; rupiah: number; people: CkMissingPerson[] };
  late: { count: number; minutes: number; rupiah: number; people: CkLatePerson[] };
  run: { id: string; name: string; locked: boolean } | null;
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
};
