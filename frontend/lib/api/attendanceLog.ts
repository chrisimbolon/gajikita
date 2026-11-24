// =============================================================================
// frontend/lib/api/attendanceLog.ts — Log Kehadiran (G20-1, 23 Nov 2026).
// Mirrors backend/apps/attendance/attendance_log.py: who, how much, on what basis, at what cost.
// Read-only; every number comes from the payroll's own day-by-day decisions.
// =============================================================================
import api from "@/lib/api";

export interface LogEmployee { id: string; employee_no: string; full_name: string }

/** none = no payroll yet · same = the slip says the same · stale = Hitung ulang payroll · override = HR corrected the line */
export type SlipState = "none" | "same" | "stale" | "override";
export interface LogSlip { state: SlipState; amount: string | null }
export interface LogBonus { amount: string; lost: boolean; why: string[] }

export interface LogDay {
  date: string; day_id: string | null; in: string | null; out: string | null;
  amount: string; basis: string; label: string;
  minutes?: number; charged?: number; half?: boolean;          // late / early
  warn?: boolean;                                              // absent / meal
  meals?: number; breakfast?: boolean; missed?: boolean;       // meal
}

export interface LatePerson {
  employee: LogEmployee; days: number; minutes: number; charged_minutes: number; half_days: number;
  forgiven_days: number; grace_days: number; grace_minutes: number; rupiah: string;
  bonus: LogBonus | null; slip: LogSlip; items: LogDay[];
}
export interface EarlyPerson {
  employee: LogEmployee; days: number; minutes: number; charged_minutes: number; half_days: number;
  forgiven_days: number; rupiah: string; bonus: LogBonus | null; slip: LogSlip; items: LogDay[];
}
export interface AbsentPerson {
  employee: LogEmployee; days: number; unpaid_leave_days: number; rejected_days: number; no_basis_days: number;
  rupiah: string; daily_worker: boolean; bonus: LogBonus | null; slip: LogSlip; items: LogDay[];
}
export interface MealPerson {
  employee: LogEmployee; rule: string; rule_label: string; meals: number; meal_rupiah: string;
  breakfasts: number; breakfast_rupiah: string; rupiah: string; missed_days: number; warn_days: number;
  slip: LogSlip; items: LogDay[];
}

interface Slips { stale: number; override: number }
export interface AttendanceLog {
  month: string; label: string; start: string; end: string; prev: string; next: string;
  rules: {
    late_fine_per_minute: string; late_tolerance_minutes: number; long_late_half_day_minutes: number | null;
    meal_allowance: string; breakfast_allowance: string; daily_divisor: number;
    shifts: { name: string; grace_minutes: number }[];
  };
  run: { id: string; name: string; locked: boolean; calculated_at: string | null } | null;
  late: { summary: Slips & { people: number; days: number; minutes: number; charged_minutes: number; half_days: number;
                             forgiven_days: number; rupiah: string; bonus_people: number; bonus_rupiah: string;
                             grace_people: number; grace_days: number }; people: LatePerson[] };
  early: { summary: Slips & { people: number; days: number; minutes: number; charged_minutes: number; half_days: number;
                              forgiven_days: number; rupiah: string; bonus_people: number; bonus_rupiah: string };
           people: EarlyPerson[] };
  absent: { summary: Slips & { people: number; days: number; no_basis_days: number; rupiah: string;
                               bonus_people: number; bonus_rupiah: string }; people: AbsentPerson[] };
  meal: { summary: Slips & { people: number; meals: number; breakfasts: number; rupiah: string; missed_days: number;
                             warn_days: number }; people: MealPerson[] };
}

export const attendanceLogApi = {
  async get(month?: string): Promise<AttendanceLog> {
    const { data } = await api.get("/api/hr/attendance/log/", { params: { month }, timeout: 120000 });
    return data;
  },
};
