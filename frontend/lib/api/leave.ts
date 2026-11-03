// =============================================================================
// === frontend/lib/api/leave.ts ===
// Cuti, sakit and izin (G7, 28 Oct 2026). Mirrors backend/apps/leave/views.py (the phone)
// and backend/apps/leave/hr_views.py (HR).
// =============================================================================
import api from "@/lib/api";

export type LeaveKind = "annual" | "sick" | "special" | "unpaid";
export type LeaveStatus = "pending" | "approved" | "rejected" | "cancelled";

export interface Leave {
  id:                string;
  employee:          { id: string; employee_no: string; full_name: string };
  kind:              LeaveKind;
  kind_label:        string;
  special_reason:    string;
  label:             string;            // "Sakit", "Cuti khusus: menikah"...
  paid:              boolean;
  start_date:        string;
  end_date:          string;
  days:              number;            // working days of the worker's shift
  reason:            string;
  has_attachment:    boolean;
  sick_note_missing: boolean;
  status:            LeaveStatus;
  status_label:      string;
  source:            "phone" | "form";
  source_label:      string;
  approver:          string | null;     // the worker's mandor / atasan; null = HR
  requested_at:      string;
  decided_by:        string | null;
  decided_at:        string | null;
  decision_note:     string;
}

export interface LeaveChoices {
  kinds:           { value: LeaveKind; label: string; paid: boolean }[];
  special_reasons: { value: string; label: string; days: number }[];
}

export interface AnnualBalance { year: number; entitled: number; used: number; left: number; from_date: string }

export interface MyLeave extends LeaveChoices {
  employee:    { id: string; full_name: string };
  approver:    string | null;
  annual:      AnnualBalance;
  requests:    Leave[];
  is_approver: boolean;
  to_approve:  Leave[];
  crew_recent: Leave[];
}

export interface LeaveInput {
  kind:           LeaveKind;
  special_reason: string;
  start_date:     string;
  end_date:       string;
  reason:         string;
  attachment:     { blob: Blob; name: string } | null;
}

export interface HrLeaveList extends LeaveChoices {
  status:   LeaveStatus | "all";
  counts:   Record<LeaveStatus, number>;
  requests: Leave[];
}

export const LEAVE_STATUS_STYLE: Record<LeaveStatus, { bg: string; fg: string }> = {
  pending:   { bg: "var(--hazard-light)", fg: "var(--hazard-dark)" },
  approved:  { bg: "var(--workshop-lt)", fg: "var(--workshop)" },
  rejected:  { bg: "var(--danger-light)", fg: "var(--danger)" },
  cancelled: { bg: "var(--paper-2)", fg: "var(--steel)" },
};

function toForm(body: LeaveInput, extra: Record<string, string> = {}): FormData {
  const form = new FormData();
  form.append("kind", body.kind);
  form.append("special_reason", body.kind === "special" ? body.special_reason : "");
  form.append("start_date", body.start_date);
  form.append("end_date", body.end_date);
  form.append("reason", body.reason);
  if (body.attachment) form.append("attachment", body.attachment.blob, body.attachment.name);
  for (const [k, v] of Object.entries(extra)) form.append(k, v);
  return form;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

/** "2 Nov 2026", "2–7 Nov 2026" or "30 Okt – 2 Nov 2026" (plain date strings, no timezone involved). */
export function periodText(start: string, end: string): string {
  const [y1, m1, d1] = start.split("-").map(Number);
  const [y2, m2, d2] = end.split("-").map(Number);
  if (start === end) return `${d1} ${MONTHS[m1 - 1]} ${y1}`;
  if (y1 === y2 && m1 === m2) return `${d1}–${d2} ${MONTHS[m1 - 1]} ${y1}`;
  if (y1 === y2) return `${d1} ${MONTHS[m1 - 1]} – ${d2} ${MONTHS[m2 - 1]} ${y2}`;
  return `${d1} ${MONTHS[m1 - 1]} ${y1} – ${d2} ${MONTHS[m2 - 1]} ${y2}`;
}

/** A phone photo of a doctor's letter, made smaller (still readable) before upload. PDFs go as they are. */
export async function shrinkPhoto(file: File): Promise<{ blob: Blob; name: string }> {
  if (!file.type.startsWith("image/")) return { blob: file, name: file.name };
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("Foto tidak bisa dibaca."));
      i.src = url;
    });
    const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return { blob: file, name: file.name };
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.8));
    return blob ? { blob, name: "surat.jpg" } : { blob: file, name: file.name };
  } finally {
    URL.revokeObjectURL(url);
  }
}

export const workerLeaveApi = {
  async mine(): Promise<MyLeave> {
    const { data } = await api.get("/api/worker/leave/");
    return data;
  },
  async ask(body: LeaveInput): Promise<{ leave: Leave; message: string }> {
    const { data } = await api.post("/api/worker/leave/", toForm(body), { timeout: 30000 });
    return data;
  },
  async cancel(id: string): Promise<Leave> {
    const { data } = await api.post(`/api/worker/leave/${id}/cancel/`);
    return data.leave;
  },
  async decide(id: string, action: "approve" | "reject", note = ""): Promise<Leave> {
    const { data } = await api.post(`/api/worker/leave/${id}/decide/`, { action, note });
    return data.leave;
  },
};

export const hrLeaveApi = {
  async list(status: LeaveStatus | "all", q = ""): Promise<HrLeaveList> {
    const { data } = await api.get("/api/hr/leave/", { params: q ? { status, q } : { status } });
    return data;
  },
  async record(employee: string, body: LeaveInput): Promise<Leave> {
    const { data } = await api.post("/api/hr/leave/", toForm(body, { employee }), { timeout: 30000 });
    return data.leave;
  },
  async decide(id: string, action: "approve" | "reject" | "cancel", note = ""): Promise<Leave> {
    const { data } = await api.post(`/api/hr/leave/${id}/decide/`, { action, note });
    return data.leave;
  },
  async balance(employeeId: string): Promise<AnnualBalance> {
    const { data } = await api.get(`/api/hr/leave/balance/${employeeId}/`);
    return data.annual;
  },
  /** The doctor's letter as a local object URL (the endpoint needs the login token). */
  async attachment(id: string): Promise<{ url: string; isPdf: boolean }> {
    const { data } = await api.get(`/api/hr/leave/${id}/attachment/`, { responseType: "blob" });
    const blob = data as Blob;
    return { url: URL.createObjectURL(blob), isPdf: blob.type === "application/pdf" };
  },
};
