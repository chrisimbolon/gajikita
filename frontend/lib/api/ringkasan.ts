// =============================================================================
// frontend/lib/api/ringkasan.ts — Ringkasan Karyawan (G21-1, 25 Nov 2026).
// Mirrors backend/apps/attendance/ringkasan.py: one person, one period, every day with its reasons.
// Read-only; every number comes from the payroll's own day-by-day decisions (like the Log).
// =============================================================================
import api from "@/lib/api";
import type { HrNote } from "@/lib/api/attendance";

export type DayKind = "present" | "late" | "absent" | "unpaid" | "leave" | "sick" | "event" | "exempt" | "off"
  | "pending" | "outside";
export type ChipTone = "blue" | "green" | "amber" | "red" | "violet" | "indigo" | "sky" | "slate";

export interface RkChip { key: string; label: string; tone: ChipTone }
export interface RkMoney { label: string; amount: string; group: "wage" | "overtime" | "meal" | "late" | "cut" }
export interface RkConflict { kind: string; kind_label: string; text: string }

export interface RkDay {
  date: string; dow: string; day: number; day_id: string | null;
  code: string; status: string; status_label: string; kind: DayKind; working: boolean;
  in: string | null; out: string | null;
  in_min: number | null; out_min: number | null;            // minutes from 00:00 of the date (next day > 1440)
  shift: { start: number; end: number } | null;
  worked_minutes: number; overtime_minutes: number; overtime_open_minutes: number; late_minutes: number;
  meals: number; breakfast: boolean; review: boolean; hr_fixed: boolean; decision: string; locked: boolean;
  note: string; hr_note: HrNote | null;
  chips: RkChip[]; money: RkMoney[]; rupiah: string; why: string[]; conflicts: RkConflict[];
  moved: { event: string; time: string; from: string }[];                         // G21-3b: taps a suggestion moved here
}

export interface RkSlipLine { code: string; label: string; amount: string; quantity: string | null; unit: string }
/** none = no payroll yet · missing = a payroll without this person (G21-2) · same · stale = Hitung ulang · override */
export interface RkCheck { state: "none" | "missing" | "same" | "stale" | "override"; changed: string[]; fixed: string[] }
export type RkMoneyBlock =
  | { source: "slip"; earnings: RkSlipLine[]; deductions: RkSlipLine[]; gross: string; deductions_total: string;
      net: string; warnings: string[]; line_id: string; note: string; check: RkCheck }
  | { source: "attendance"; parts: { group: string; label: string; amount: string }[]; check: RkCheck };

export interface RkAttention { date: string; kind: string; tone: ChipTone; text: string }

/** G21-3a: Saran SeeGaji (s1 night tap is the day before's pulang, s2 lembur without pulang, s3 lone night tap,
 *  s4 leave with taps). kuat = a statement with its evidence, lemah = a question. Read-only until G21-3b. */
export interface RkSuggestion {
  id: string; kind: "s1" | "s2" | "s3" | "s4"; kind_label: string; date: string; to_date: string | null; tap: string | null;
  strength: "kuat" | "lemah"; question: boolean; text: string; evidence: string[]; cost: string;
  prefill: { clock_in: string | null; clock_out: string; source: string; clock_in_source: string } | null;
  conflict_kind?: string;
}

export interface Ringkasan {
  month: string; label: string; start: string; end: string; prev: string; next: string;
  employee: {
    id: string; employee_no: string; full_name: string; position: string;
    pay_type: string; pay_type_label: string; base_rate: string; join_date: string | null; end_date: string | null;
    overtime_eligible: boolean; meal_rule: string; meal_rule_label: string;
    shift: { name: string; start: string; end: string; grace_minutes: number; working_days: string } | null;
  };
  rules: { late_fine_per_minute: string; late_tolerance_minutes: number; meal_allowance: string;
           meal_late_after: string | null; per_day: string; half_day: string };
  run: { id: string; name: string; locked: boolean; calculated_at: string | null } | null;
  money: RkMoneyBlock;
  totals: {
    working_days: number; present_days: number; absent_days: number; unpaid_days: number; unpaid_leave_days: number;
    paid_leave_days: number; leave: Record<string, number>; sick_days: number; late_days: number; late_minutes: number;
    half_days: number; overtime_minutes: number; overtime_days: number; overtime_open_days: number;
    meals: number; breakfasts: number; review_days: number; hr_fixed_days: number;
  };
  kinds: Record<DayKind, string>;
  days: RkDay[];
  attention: RkAttention[];
  suggestions: RkSuggestion[];                                                    // G21-3a
  people: { id: string; employee_no: string; full_name: string }[];
}

/** G21-3b: what a suggestion changes (the real apply, rolled back) and what it did to the slip. */
export interface SaranPreview {
  changes: { date: string; label: string; before: string; after: string }[];
  net_before: string | null; net_after: string | null; run: string | null;
}
export interface SaranDone {
  message: string;
  payroll: { run: string; locked: boolean; net_before?: string; net_after?: string } | null;
}
type SaranTimes = { clock_in?: string | null; clock_out?: string | null };

export const saranApi = {
  async preview(employee: string, month: string, id: string, times: SaranTimes = {}): Promise<SaranPreview> {
    const { data } = await api.post("/api/hr/attendance/suggestions/preview/", { employee, month, id, ...times }, { timeout: 60000 });
    return data;
  },
  async apply(employee: string, month: string, id: string, times: SaranTimes = {}): Promise<SaranDone> {
    const { data } = await api.post("/api/hr/attendance/suggestions/apply/", { employee, month, id, ...times }, { timeout: 60000 });
    return data;
  },
  async dismiss(employee: string, month: string, id: string): Promise<SaranDone> {
    const { data } = await api.post("/api/hr/attendance/suggestions/dismiss/", { employee, month, id });
    return { message: data.message, payroll: null };
  },
  async undo(employee: string, event: string): Promise<SaranDone> {
    const { data } = await api.post("/api/hr/attendance/suggestions/undo/", { employee, event }, { timeout: 60000 });
    return data;
  },
};

export const ringkasanApi = {
  async get(employee: string, month?: string): Promise<Ringkasan> {
    const { data } = await api.get("/api/hr/attendance/ringkasan/", { params: { employee, month }, timeout: 60000 });
    return data;
  },
};

/** The page of one person for one period (G21-1); every name in Log, Rekap, Siap gajian? and Payroll links here. */
export function ringkasanHref(employeeId: string, month?: string | null, day?: string | null): string {
  return `/dashboard/karyawan/ringkasan?employee=${encodeURIComponent(employeeId)}${month ? `&month=${month}` : ""}`
    + (day ? `&day=${day}` : "");                                                   // G21-3a: opened on that day
}
