// =============================================================================
// === frontend/lib/api/overtime.ts ===
// Overtime in rupiah, PP 35/2021 (G4a, 28 Oct 2026). Mirrors backend/apps/payroll/views.py.
// =============================================================================
import api from "@/lib/api";

export interface PayLine { minutes: number; multiplier: string; amount: string }

export interface OvertimeDay {
  date:         string;
  day_id:       string;
  site:         string;
  minutes:      number;
  rest_day:     boolean;
  hourly_rate?: string;
  lines:        PayLine[];
  amount:       string;
  warnings:     string[];
  mode?:        "pp35" | "flat";            // G11c
  rounded_minutes?: number;
  pp35_amount?: string | null;
}

export interface OvertimePerson {
  employee:     { id: string; employee_no: string; full_name: string };
  days:         OvertimeDay[];
  minutes:      number;
  amount:       string;
  hourly_rate?: string;
  warnings:     string[];
  not_paid:     string | null;
}

export interface OvertimeMonth {
  month:     string;
  totals:    { people: number; minutes: number; amount: string };
  employees: OvertimePerson[];
  sites:     { site: string; minutes: number; amount: string }[];
}

export const overtimeApi = {
  async month(month: string): Promise<OvertimeMonth> {
    const { data } = await api.get("/api/hr/overtime/", { params: { month } });
    return data;
  },
};
