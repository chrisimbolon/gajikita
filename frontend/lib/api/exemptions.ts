// =============================================================================
// === frontend/lib/api/exemptions.ts ===
// "Tidak wajib absen" periods per employee (G12i, 11 Nov 2026). Mirrors backend/apps/attendance/exemption_views.py.
// Inside a period every scheduled working day counts as worked (Rekap code DL); leave still counts.
// =============================================================================
import api from "@/lib/api";

export interface Exemption { id: string; start: string; end: string | null; reason: string }
export interface ExemptionList { exemptions: Exemption[]; current: Exemption | null }

export const exemptionApi = {
  async list(employeeId: string): Promise<ExemptionList> {
    const { data } = await api.get(`/api/hr/employees/${employeeId}/attendance-exemptions/`);
    return data;
  },
  async create(employeeId: string, body: { start: string; end: string | null; reason: string }): Promise<ExemptionList> {
    const { data } = await api.post(`/api/hr/employees/${employeeId}/attendance-exemptions/`, body);
    return data;
  },
  async update(id: string, body: { end?: string | null; reason?: string }): Promise<ExemptionList> {
    const { data } = await api.patch(`/api/hr/attendance-exemptions/${id}/`, body);
    return data;
  },
  async remove(id: string): Promise<ExemptionList> {
    const { data } = await api.delete(`/api/hr/attendance-exemptions/${id}/`);
    return data;
  },
};
