// =============================================================================
// frontend/lib/api/finalPay.ts — "Hak akhir" (G16-4, 23 Nov 2026): what a leaving worker is owed under
// UU 27/2026 (pesangon, UPMK, UPH, uang pisah, kompensasi PKWT) and the PPh 21 final (PP 68/2009).
// =============================================================================
import api from "@/lib/api";

export interface FinalPayLine {
  key: string; code: string; label: string; basis: string; article: string;
  law_amount: string; amount: string; changed: boolean; reason: string;
}

export interface FinalPayResult {
  reason: string; reason_label: string; article: string;
  service: { years: number; months: number; days: number; text: string };
  upah: string; upah_note?: string; per_day: string; daily_divisor: number;
  lines: FinalPayLine[]; total: string;
  tax: { amount: string; steps: { text: string; tax: string }[] };
  net: string; notes: string[];
  loan?: { balance: string; deducted: boolean };
  paid_out?: string;
}

export interface Override { amount: string; reason: string }

export interface FinalPayInput {
  id?: string | null;
  employee: string;
  end_date: string;
  reason: string;
  upah: string | null;          // null = from Karyawan (Pasal 234)
  leave_days: string | null;    // null = the annual leave left on the end date
  travel: string;
  other_items: { label: string; amount: string }[];
  overrides: Record<string, Override>;
  deduct_loan: boolean;
  note: string;
}

export interface FinalPayRecord extends Omit<FinalPayInput, "employee"> {
  id: string;
  result: FinalPayResult;
  run: { id: string; name: string; locked: boolean } | null;
  attached_at: string | null;
  updated_at: string | null;
}

export interface FinalPayPage {
  employee: { id: string; employee_no: string; full_name: string; position: string; join_date: string;
              end_date: string | null; employment_type: string; pay_type: string };
  reasons: { value: string; label: string; article: string }[];
  defaults: { end_date: string; upah: string; upah_note: string; leave_days: string; separation_pay_months: string;
              small_business: boolean; daily_divisor: number; reason: string };
  records: FinalPayRecord[];
}

export const finalPayApi = {
  async load(employeeId: string): Promise<FinalPayPage> {
    const { data } = await api.get("/api/hr/payroll/final-pay/", { params: { employee: employeeId } });
    return data;
  },
  async preview(input: FinalPayInput): Promise<FinalPayResult> {
    const { data } = await api.post("/api/hr/payroll/final-pay/preview/", input);
    return data.result;
  },
  async save(input: FinalPayInput): Promise<{ record: FinalPayRecord; message: string }> {
    const { data } = await api.post("/api/hr/payroll/final-pay/", input);
    return data;
  },
  async attach(id: string): Promise<{ record: FinalPayRecord; message: string }> {
    const { data } = await api.post(`/api/hr/payroll/final-pay/${id}/attach/`);
    return data;
  },
  async remove(id: string): Promise<string> {
    const { data } = await api.delete(`/api/hr/payroll/final-pay/${id}/`);
    return data.message;
  },
};
