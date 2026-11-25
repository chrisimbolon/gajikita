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
}

export interface RkSlipLine { code: string; label: string; amount: string; quantity: string | null; unit: string }
export interface RkCheck { state: "none" | "same" | "stale" | "override"; changed: string[]; fixed: string[] }
export type RkMoneyBlock =
  | { source: "slip"; earnings: RkSlipLine[]; deductions: RkSlipLine[]; gross: string; deductions_total: string;
      net: string; warnings: string[]; line_id: string; note: string; check: RkCheck }
  | { source: "attendance"; parts: { group: string; label: string; amount: string }[]; check: RkCheck };

export interface RkAttention { date: string; kind: string; tone: ChipTone; text: string }

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
  people: { id: string; employee_no: string; full_name: string }[];
}

export const ringkasanApi = {
  async get(employee: string, month?: string): Promise<Ringkasan> {
    const { data } = await api.get("/api/hr/attendance/ringkasan/", { params: { employee, month }, timeout: 60000 });
    return data;
  },
};

/** The page of one person for one period (G21-1); every name in Log, Rekap, Siap gajian? and Payroll links here. */
export function ringkasanHref(employeeId: string, month?: string | null): string {
  return `/dashboard/karyawan/ringkasan?employee=${encodeURIComponent(employeeId)}${month ? `&month=${month}` : ""}`;
}
