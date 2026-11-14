// =============================================================================
// === frontend/lib/api/hr.ts ===
// HR's office screens (G2b, 27 Oct 2026). Mirrors backend/apps/employees/hr_views.py
// and backend/apps/sites/hr_views.py.
// =============================================================================
import api from "@/lib/api";

export type SiteKind = "fixed" | "moving" | "vessel" | "none";

export const SITE_KIND_LABEL: Record<SiteKind, string> = {
  fixed: "Tetap", moving: "Berpindah", vessel: "Kapal", none: "Tanpa lokasi",
};

export interface Pin {
  id:         string;
  latitude:   number;
  longitude:  number;
  radius_m:   number;
  valid_from: string;
}

export interface Site {
  id:             string;
  name:           string;
  kind:           SiteKind;
  project_code:   string;
  is_active:      boolean;
  location:       Pin | null;
  employee_count: number | null;
  history?:       Pin[];
}

export interface Shift {
  id:               string;
  name:             string;
  start_time:       string;   // "08:00:00"
  end_time:         string;
  grace_minutes:    number;
  working_days:     string;   // "123456" (1 = Senin ... 7 = Minggu)
  is_active:        boolean;
  crosses_midnight: boolean;
  saturday_end_time?: string | null;   // G17-5: "12:00:00" when Saturdays end earlier
}

export const EMPLOYMENT_TYPE_LABEL = {
  pkwtt: "PKWTT (tetap)", pkwt: "PKWT (kontrak)", harian_lepas: "Harian lepas", borongan: "Borongan",
} as const;
export const PAY_TYPE_LABEL = { monthly: "Bulanan", daily: "Harian", piece: "Per pekerjaan" } as const;
export const PTKP_OPTIONS = ["TK/0", "TK/1", "TK/2", "TK/3", "K/0", "K/1", "K/2", "K/3"] as const;

export interface Employee {
  id:                string;
  employee_no:       string;
  full_name:         string;
  position:          string;
  nik:               string;
  npwp:              string;
  ptkp_status:       string;
  join_date:         string;
  end_date:          string | null;
  employment_type:   keyof typeof EMPLOYMENT_TYPE_LABEL;
  pay_type:          keyof typeof PAY_TYPE_LABEL;
  base_rate:         string;
  fixed_allowance:   string;
  overtime_eligible: boolean;
  bpjs_tk_enrolled:  boolean;
  meal_rule:         "" | "none" | "present_day" | "overtime_day" | "late_out";   // G12d
  bank_name:         string;
  bank_account_no:   string;
  bank_account_name: string;
  bpjs_kesehatan_no: string;
  bpjs_tk_no:        string;
  phone:             string;
  fingerprint_id:    string;
  probation_end_date: string | null;
  sites:             string[];
  default_site:      string | null;
  default_shift:     string | null;
  mandor:            string | null;
  status:            "active" | "resigned";
  login_phone:       string | null;
  must_change_pin:   boolean;
  has_login:         boolean;
  login_locked:      boolean;
  machine_ids:       { machine: string; machine_name: string; fingerprint_id: string }[];   // G12f.1a, read-only
  attendance_exempt?: { id: string; start: string; end: string | null; reason: string } | null;  // G12i, read-only
}

// G12d: uang makan per employee; "" = follow Payroll → Pengaturan
export const MEAL_RULE_OPTIONS: [string, string][] = [
  ["", "Ikut pengaturan perusahaan"], ["present_day", "Per hari hadir"], ["overtime_day", "Per hari lembur"],
  ["late_out", "Per hari pulang malam"], ["none", "Tidak ada"],
];

export type EmployeeInput = Omit<Employee, "id" | "login_phone" | "must_change_pin" | "has_login" | "login_locked"
                                  | "machine_ids" | "attendance_exempt">;   // saved through machineApi / exemptionApi

export const hrApi = {
  // employees
  async employees(q = ""): Promise<Employee[]> {
    const { data } = await api.get("/api/hr/employees/", { params: q ? { q } : {} });
    return data.employees;
  },
  async createEmployee(body: Partial<EmployeeInput>): Promise<Employee> {
    const { data } = await api.post("/api/hr/employees/", body);
    return data.employee;
  },
  async updateEmployee(id: string, body: Partial<EmployeeInput>): Promise<Employee> {
    const { data } = await api.patch(`/api/hr/employees/${id}/`, body);
    return data.employee;
  },
  async enableLogin(id: string, phone: string): Promise<{ pin: string; login_phone: string; employee: Employee }> {
    const { data } = await api.post(`/api/hr/employees/${id}/login/`, { phone });
    return data;
  },

  // sites
  async sites(): Promise<Site[]> {
    const { data } = await api.get("/api/hr/sites/");
    return data.sites;
  },
  async site(id: string): Promise<Site> {
    const { data } = await api.get(`/api/hr/sites/${id}/`);
    return data.site;
  },
  async createSite(body: { name: string; kind: SiteKind; project_code?: string }): Promise<Site> {
    const { data } = await api.post("/api/hr/sites/", body);
    return data.site;
  },
  async updateSite(id: string, body: Partial<Pick<Site, "name" | "kind" | "project_code" | "is_active">>): Promise<Site> {
    const { data } = await api.patch(`/api/hr/sites/${id}/`, body);
    return data.site;
  },
  async movePin(id: string, latitude: number, longitude: number, radius_m: number): Promise<Site> {
    const { data } = await api.post(`/api/hr/sites/${id}/pin/`, { latitude, longitude, radius_m });
    return data.site;
  },

  // shifts
  async shifts(): Promise<Shift[]> {
    const { data } = await api.get("/api/hr/shifts/");
    return data.shifts;
  },
  async createShift(body: Omit<Shift, "id" | "crosses_midnight">): Promise<Shift> {
    const { data } = await api.post("/api/hr/shifts/", body);
    return data.shift;
  },
  async updateShift(id: string, body: Partial<Omit<Shift, "id" | "crosses_midnight">>): Promise<Shift> {
    const { data } = await api.patch(`/api/hr/shifts/${id}/`, body);
    return data.shift;
  },
};

/**
 * Turn a DRF error into { field: "message" } plus one summary line.
 * Handles {"field": ["msg"]}, {"message": "..."}, {"detail": "..."} and network failures.
 */
export function readErrors(err: unknown): { fields: Record<string, string>; summary: string } {
  const e = err as { response?: { status?: number; data?: unknown } };
  if (!e?.response) return { fields: {}, summary: "Tidak bisa terhubung ke server. Periksa koneksi lalu coba lagi." };
  const data = e.response.data;
  const fields: Record<string, string> = {};
  let summary = "";
  if (data && typeof data === "object") {
    const d = data as Record<string, unknown>;
    if (typeof d.message === "string") summary = d.message;
    if (typeof d.detail === "string") summary = d.detail;
    const source = (d.errors && typeof d.errors === "object" ? d.errors : d) as Record<string, unknown>;
    for (const [key, val] of Object.entries(source)) {
      if (["success", "message", "detail", "errors"].includes(key)) continue;
      const msg = Array.isArray(val) ? String(val[0]) : typeof val === "string" ? val : "";
      if (msg) fields[key] = msg;
    }
  }
  if (!summary) {
    summary = Object.keys(fields).length ? "Periksa isian yang ditandai merah." : "Terjadi kesalahan. Coba lagi.";
    if (fields.non_field_errors) summary = fields.non_field_errors;
  }
  if (e.response.status === 403 && !summary) summary = "Anda tidak punya akses ke halaman ini.";
  return { fields, summary };
}
