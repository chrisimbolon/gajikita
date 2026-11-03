// =============================================================================
// === frontend/lib/api/dashboard.ts ===
// The Ringkasan dashboard in one call (G6, 28 Oct 2026). Mirrors backend/apps/attendance/dashboard.py.
// =============================================================================
import api from "@/lib/api";
import type { DayRow } from "@/lib/api/attendance";

export interface Summary {
  user_name:        string;
  date:             string;
  employees_active: number;
  sites_active:     number;
  present:          number;
  counters:         Record<string, number>;
  review:           { count: number; summary: { label: string; count: number }[] };
  today:            DayRow[];
  today_total:      number;
  leave:            { pending: number; today: number };     // G7
  overtime: {
    month:   string;
    amount:  string;
    minutes: number;
    people:  number;
    sites:   { site: string; minutes: number; amount: string; share: number }[];
  };
}

export const dashboardApi = {
  async summary(): Promise<Summary> {
    const { data } = await api.get("/api/hr/summary/");
    return data;
  },
};
