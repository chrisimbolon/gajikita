// =============================================================================
// frontend/lib/api/spl.ts — SPL (Surat Perintah Lembur), G17-E1 (23 Nov 2026).
// HR records the paper SPL once for several people; the taps give the hours.
// =============================================================================
import api from "@/lib/api";

export interface SplPerson { id: string; full_name: string; employee_no: string; overtime_eligible: boolean }

export type SplDayState = "spl" | "decided" | "waiting" | "none";

export interface SplOrder {
  id: string; number: number; start_date: string; end_date: string; work: string;
  site: { id: string; name: string } | null;
  planned_start: string | null; planned_end: string | null; issued_by_name: string;
  source: string; source_label: string; note: string; status: "active" | "cancelled"; cancel_note: string;
  has_attachment: boolean; created_by: string; created_at: string;
  people: { employee: SplPerson; consent: "yes" | "pending" | "no";
            days: { date: string; proposed: number; paid: number; state: SplDayState; over_plan: number }[] }[];
}

export interface SplUnmatched {
  day_id: string; employee: SplPerson; date: string; minutes: number; in: string | null; out: string | null;
}

export interface SplPage {
  mode: "decision" | "spl";
  period: { year: number; month: number; start: string; end: string };
  orders: SplOrder[];
  unmatched: SplUnmatched[];
  people: SplPerson[];
  sites: { id: string; name: string }[];
  message?: string;
}

export interface SplInput {
  start_date: string; end_date: string; work: string; site: string | null;
  planned_start: string | null; planned_end: string | null; issued_by_name: string;
  employee_ids: string[]; consent: "yes" | "pending"; note: string;
  attachment?: File | null; remove_attachment?: boolean;
}

function toForm(body: SplInput): FormData {
  const f = new FormData();
  for (const [k, v] of Object.entries(body)) {
    if (k === "employee_ids") (v as string[]).forEach((id) => f.append("employee_ids", id));
    else if (k === "attachment") { if (v) f.append("attachment", v as File); }
    else if (typeof v === "boolean") f.append(k, v ? "true" : "false");
    else f.append(k, v == null ? "" : String(v));
  }
  return f;
}

export const splApi = {
  async page(month?: string): Promise<SplPage> {
    const { data } = await api.get("/api/hr/attendance/spl/", { params: month ? { month } : {} });
    return data;
  },
  async create(body: SplInput, month?: string): Promise<SplPage> {
    const { data } = await api.post("/api/hr/attendance/spl/", toForm(body), { params: month ? { month } : {} });
    return data;
  },
  async update(id: string, body: SplInput, month?: string): Promise<SplPage> {
    const { data } = await api.patch(`/api/hr/attendance/spl/${id}/`, toForm(body), { params: month ? { month } : {} });
    return data;
  },
  async cancel(id: string, note: string, month?: string): Promise<SplPage> {
    const { data } = await api.post(`/api/hr/attendance/spl/${id}/cancel/`, { note }, { params: month ? { month } : {} });
    return data;
  },
  async photo(id: string): Promise<Blob> {
    const { data } = await api.get(`/api/hr/attendance/spl/${id}/attachment/`, { responseType: "blob" });
    return data;
  },
};
