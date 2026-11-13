// =============================================================================
// === frontend/lib/api/payroll.ts ===
// Payroll settings and pay runs (G8b part 1, 1 Nov 2026). Mirrors backend/apps/payroll/payrun_views.py.
// =============================================================================
import api from "@/lib/api";

// G12e: "until" "01:59" (empty = any later time, last row only); "start" "10:00" (empty = day off)
export interface NightRule { until: string; start: string }
export const DKCB_NIGHT_RULES: NightRule[] = [
  { until: "01:59", start: "10:00" }, { until: "04:00", start: "13:00" }, { until: "", start: "" },
];

export interface PayrollSettings {
  period_start_day:             number;
  pay_day:                      number;
  daily_divisor:                number;
  overtime_mode:                "pp35" | "flat";
  overtime_rounding:            "exact" | "nearest_half" | "down_half" | "half_down";
  flat_overtime_hour:           string;
  flat_rest_day:                string;
  meal_rule:                    "none" | "overtime_day" | "present_day" | "late_out";
  meal_allowance:               string;
  meal_late_after:              string;   // "19:00:00" (G12d)
  meal_midnight_extra:          boolean;  // G12e
  breakfast_allowance:          string;
  breakfast_before:             string;   // "07:00:00"
  overtime_min_minutes:         number;
  overtime_daily_cap_minutes:   number | null;   // G12g: null = no cap in Setujui massal
  night_ot_rules:               NightRule[];
  late_fine_per_minute:         string;
  late_tolerance_minutes:       number;
  single_tap_half_day?:         boolean;  // G17-1
  bpjs_base_includes_allowance: boolean;
  jkk_rate:                     string;
  minimum_wage:                 string;
  slip_address:                 string;
  slip_place:                   string;
  slip_signer:                  string;
  updated_at:                   string;
}

export interface RunSummary {
  id:            string;
  name:          string;
  status:        "draft" | "locked";
  status_label:  string;
  period_start:  string;
  period_end:    string;
  pay_date:      string | null;
  calculated_at: string | null;
  locked_at:     string | null;
  locked_by:     string | null;
  people:        number;
  gross:         string;
  deductions:    string;
  net:           string;
  employer_cost: string;
  warnings:      number;
  negative?:     number;                  // G17-0: people whose net pay is below zero (blocks locking)
}

export interface RegisterColumn { code: string; label: string; side: "earnings" | "deductions" }

export interface RegisterRow {
  id:            string;
  employee:      { id: string; employee_no: string; full_name: string };
  amounts:       Record<string, string>;
  gross:         string;
  deductions:    string;
  net:           string;
  warning_count: number;
  corrected:     boolean;
  present_days:  number;
  absent_days:   number;
  review_days:   number;
  exempt_days?:  number;                  // G12i: days counted as worked without tapping
  exempt_reason?: string;
  negative?:     boolean;                 // G17-0: net pay below zero
}

export interface RunDetail { run: RunSummary; columns: RegisterColumn[]; rows: RegisterRow[] }

export interface SlipLine { code: string; label: string; amount: string; quantity: string | null; unit: string }

export interface PayItem {
  id:        string;
  kind:      "earning" | "deduction";
  code:      string;
  label:     string;
  amount:    string;
  quantity:  string | null;
  unit:      string;
  recurring: boolean;
  note:      string;
}

export interface LineNumbers {
  present_days:      number;
  absent_days:       number;
  unpaid_leave_days: number;
  paid_leave_days:   number;
  outside_days:      number;
  overtime:          { date: string; minutes: number; rest_day: boolean }[];
  late_minutes:      number;
  meal_days:         number;
  review_days:       number;
  unpaid_days:       number;
  leave:             Record<string, number>;
}

export interface LineDetail {
  id:              string;
  employee:        { id: string; employee_no: string; full_name: string; pay_type: string; pay_type_label: string;
                     base_rate: string; bpjs_tk_enrolled: boolean };
  auto:            LineNumbers;
  override:        Record<string, string>;
  note:            string;
  override_fields: Record<string, string>;
  items:           PayItem[];
  result:          { earnings: SlipLine[]; deductions: SlipLine[]; employer: SlipLine[]; warnings: string[] };
  gross:           string;
  deductions:      string;
  net:             string;
  employer_cost:   string;
  loan_balance:    string | null;
}

export interface SlipBook {
  company: { name: string; address: string; phone: string };
  run:     { id: string; name: string; status: string; draft: boolean; period: string; pay_date: string };
  place:   string;
  signer:  string;
  slips:   { line_id: string; employee: { employee_no: string; full_name: string; position: string };
             earnings: SlipLine[]; deductions: SlipLine[]; gross: string; deductions_total: string; net: string;
             loan_balance: string | null; leave_left: number | null }[];
}

export interface TransferList {
  run:      { id: string; name: string; pay_date: string | null };
  rows:     { employee_no: string; full_name: string; bank_name: string; account_no: string; account_name: string;
              amount: string; problem: string }[];
  total:    string;
  ready:    number;
  problems: number;
}

export const payrollApi = {
  async slips(runId: string, lineId?: string): Promise<SlipBook> {
    const { data } = await api.get(`/api/hr/payroll/runs/${runId}/slips/`, { params: lineId ? { line: lineId } : {} });
    return data;
  },
  async transfers(runId: string): Promise<TransferList> {
    const { data } = await api.get(`/api/hr/payroll/runs/${runId}/transfers/`);
    return data;
  },
  async settings(): Promise<PayrollSettings> {
    const { data } = await api.get("/api/hr/payroll/settings/");
    return data.settings;
  },
  async saveSettings(body: Partial<PayrollSettings>): Promise<PayrollSettings> {
    const { data } = await api.patch("/api/hr/payroll/settings/", body);
    return data.settings;
  },
  async runs(): Promise<RunSummary[]> {
    const { data } = await api.get("/api/hr/payroll/runs/");
    return data.runs;
  },
  async createRun(month: string): Promise<RunSummary> {
    const { data } = await api.post("/api/hr/payroll/runs/", { month }, { timeout: 120000 });
    return data.run;
  },
  async run(id: string): Promise<RunDetail> {
    const { data } = await api.get(`/api/hr/payroll/runs/${id}/`);
    return data;
  },
  async deleteRun(id: string): Promise<void> {
    await api.delete(`/api/hr/payroll/runs/${id}/`);
  },
  async recalculate(id: string): Promise<RunDetail> {
    const { data } = await api.post(`/api/hr/payroll/runs/${id}/recalculate/`, {}, { timeout: 120000 });
    return data;
  },
  async lock(id: string, action: "lock" | "reopen", note = ""): Promise<RunSummary> {
    const { data } = await api.post(`/api/hr/payroll/runs/${id}/lock/`, { action, note }, { timeout: 120000 });
    return data.run;
  },
  async line(runId: string, lineId: string): Promise<LineDetail> {
    const { data } = await api.get(`/api/hr/payroll/runs/${runId}/lines/${lineId}/`);
    return data.line;
  },
  async saveLine(runId: string, lineId: string, body: { override?: Record<string, string>; note?: string; loan_balance?: string | null }): Promise<LineDetail> {
    const { data } = await api.patch(`/api/hr/payroll/runs/${runId}/lines/${lineId}/`, body);
    return data.line;
  },
  async addItem(runId: string, lineId: string, body: Omit<PayItem, "id" | "code" | "quantity" | "unit"> &
                { quantity?: string | null; unit?: string }): Promise<LineDetail> {
    const { data } = await api.post(`/api/hr/payroll/runs/${runId}/lines/${lineId}/items/`, body);
    return data.line;
  },
  async deleteItem(runId: string, itemId: string): Promise<LineDetail> {
    const { data } = await api.delete(`/api/hr/payroll/runs/${runId}/items/${itemId}/`);
    return data.line;
  },
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

/** "26 Sep – 25 Okt 2026" from two YYYY-MM-DD strings (no timezone involved). */
export function periodLabel(start: string, end: string): string {
  const [y1, m1, d1] = start.split("-").map(Number);
  const [y2, m2, d2] = end.split("-").map(Number);
  return y1 === y2 ? `${d1} ${MONTHS[m1 - 1]} – ${d2} ${MONTHS[m2 - 1]} ${y2}`
                   : `${d1} ${MONTHS[m1 - 1]} ${y1} – ${d2} ${MONTHS[m2 - 1]} ${y2}`;
}

export function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}
