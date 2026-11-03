// =============================================================================
// === frontend/lib/api/attendance.ts ===
// HR's attendance screens (G3, 28 Oct 2026). Mirrors backend/apps/attendance/hr_views.py.
// =============================================================================
import api from "@/lib/api";

export type DayStatus =
  | "not_yet" | "working" | "on_time" | "late" | "early_out" | "no_clock_out"
  | "absent" | "day_off" | "day_off_work" | "rejected" | "present" | "leave";

export interface DayRow {
  employee:                  { id: string; employee_no: string; full_name: string };
  date:                      string;
  day_id:                    string | null;
  status:                    DayStatus;
  status_label:              string;
  leave?:                    string;       // the approved leave that day, e.g. "Sakit" (G7)
  tags:                      DayStatus[];
  first_in:                  string | null;
  last_out:                  string | null;
  late_minutes:              number;
  early_minutes:             number;
  worked_minutes:            number;
  overtime_proposed_minutes: number;
  overtime_approved_minutes: number | null;
  site_minutes:              Record<string, number>;
  review_reasons:            string[];
  needs_review:              boolean;
  decision:                  "" | "approved" | "rejected";
  is_locked:                 boolean;
  hr_fixed:                  boolean;
}

export interface Counter { key: DayStatus | "needs_review"; label: string; count: number }

export interface TapView {
  id:          string;
  kind:        "in" | "switch" | "out";
  kind_label:  string;
  source:      string;
  source_code?: "app" | "kiosk" | "fingerprint" | "hr_edit";   // G9b
  occurred_at: string;
  time:        string;
  received_at: string;
  site:        string | null;
  latitude:    number | null;
  longitude:   number | null;
  accuracy_m:  number | null;
  distance_m:  number | null;
  flags:       string[];
  flag_labels: string[];
  has_selfie:  boolean;
}

export interface AuditView { id: string; at: string; actor: string; action: string; summary: string; note: string }

export interface DayDetail extends DayRow {
  shift:         { name: string; start: string; end: string } | null;
  events:        TapView[];
  decision_note: string;
  waive_late:    boolean;
  decided_by:    string | null;
  decided_at:    string | null;
  audit:         AuditView[];
  overtime_pay:  DayOvertimePay | null;
}

// Overtime in rupiah for one day (PP 35/2021, G4a); an estimate until HR approves the minutes.
export type DayOvertimePay =
  | { minutes: number; not_paid: string }
  | { minutes: number; rest_day: boolean; hourly_rate: string; amount: string; warnings: string[]; estimate: boolean;
      lines: { minutes: number; multiplier: string; amount: string }[] };

export const STATUS_STYLE: Record<DayStatus, { bg: string; fg: string }> = {
  on_time:      { bg: "var(--workshop-lt)", fg: "var(--workshop)" },
  present:      { bg: "var(--workshop-lt)", fg: "var(--workshop)" },
  working:      { bg: "var(--workshop-lt)", fg: "var(--workshop)" },
  late:         { bg: "var(--hazard-light)", fg: "var(--hazard-dark)" },
  early_out:    { bg: "var(--hazard-light)", fg: "var(--hazard-dark)" },
  day_off_work: { bg: "var(--hazard-light)", fg: "var(--hazard-dark)" },
  no_clock_out: { bg: "var(--danger-light)", fg: "#A3261C" },
  absent:       { bg: "var(--danger-light)", fg: "#A3261C" },
  rejected:     { bg: "var(--danger-light)", fg: "var(--danger)" },
  not_yet:      { bg: "var(--paper-2)", fg: "var(--steel)" },
  day_off:      { bg: "var(--paper-2)", fg: "var(--steel)" },      // grey, never red: a day off is not a problem
  leave:        { bg: "var(--midnight-soft)", fg: "var(--midnight)" },  // approved cuti / sakit / izin (G7)
};

// Rekap Absensi (G10): everyone x every day of a pay period. Mirrors backend/apps/attendance/rekap.py.
export interface RekapCell {
  d: string; c: string; s: DayStatus | "outside"; l: string; fi: string | null; lo: string | null;
  day: string | null; rv: boolean; ot: number; otp: number; late: number; early: number;
}
export interface RekapSummary {
  present: number; absent: number; late_times: number; late_minutes: number; early_times: number; early_minutes: number;
  no_clock_out: number; leave: Record<string, number>; unpaid_leave: number; paid_leave: number;
  overtime_minutes: number; overtime_pending_minutes: number; meal_days: number; review: number; problem: boolean;
}
export interface RekapRow {
  employee: { id: string; employee_no: string; full_name: string; position: string; shift: string };
  cells: RekapCell[]; summary: RekapSummary;
}
export interface RekapData {
  month: string; label: string; start: string; end: string; prev: string; next: string;
  days: { d: string; day: number; dow: string; sunday: boolean }[]; legend: { code: string; label: string }[];
  total: number; page: number; pages: number; rows: RekapRow[];
}
export interface RekapParams { month?: string; q?: string; site?: string; shift?: string; problems?: string; page?: number }

export const attendanceApi = {
  async rekap(params: RekapParams): Promise<RekapData> {
    const { data } = await api.get("/api/hr/attendance/rekap/", { params, timeout: 120000 });
    return data;
  },
  async exportRekap(params: RekapParams, filename: string): Promise<void> {
    const { data } = await api.get("/api/hr/attendance/rekap/export/", { params, responseType: "blob", timeout: 120000 });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(data as Blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  },
  async daily(date: string): Promise<{ date: string; counters: Counter[]; rows: DayRow[] }> {
    const { data } = await api.get("/api/hr/attendance/daily/", { params: { date } });
    return data;
  },
  async review(days = 7): Promise<{ count: number; summary: { label: string; count: number }[]; rows: DayRow[] }> {
    const { data } = await api.get("/api/hr/attendance/review/", { params: { days } });
    return data;
  },
  async day(id: string): Promise<DayDetail> {
    const { data } = await api.get(`/api/hr/attendance/days/${id}/`);
    return data.day;
  },
  async decide(id: string, body: { action: "approve" | "reject" | "reset"; note?: string; waive_late?: boolean;
                                   overtime_minutes?: number | null }): Promise<DayDetail> {
    const { data } = await api.post(`/api/hr/attendance/days/${id}/decide/`, body);
    return data.day;
  },
  async fix(body: { employee: string; date: string; clock_in?: string | null; clock_out?: string | null;
                    reason: string }): Promise<DayDetail> {
    const { data } = await api.post("/api/hr/attendance/fix/", body);
    return data.day;
  },
  /** The selfie as a local object URL (the endpoint needs the login token, so a plain <img src> can't load it). */
  async selfieUrl(eventId: string): Promise<string> {
    const { data } = await api.get(`/api/hr/attendance/events/${eventId}/selfie/`, { responseType: "blob" });
    return URL.createObjectURL(data as Blob);
  },
};

export function minutesText(m: number): string {
  if (!m) return "0 mnt";
  const h = Math.floor(m / 60), r = m % 60;
  return h ? `${h} j ${r ? `${r} mnt` : ""}`.trim() : `${r} mnt`;
}
