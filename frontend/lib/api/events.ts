// =============================================================================
// === frontend/lib/api/events.ts ===
// Company events ("Kejadian", G17-2, 14 Nov 2026). Mirrors backend/apps/attendance/event_views.py.
// gangguan = attendance disrupted (power cut): working days count as worked, nothing is cut.
// libur    = holiday: working days become days off; working that day is paid the rest-day rate.
// =============================================================================
import api from "@/lib/api";

export type EventKind = "gangguan" | "libur";

export interface CompanyEvent {
  id:         string;
  start:      string;
  end:        string;
  kind:       EventKind;
  kind_label: string;
  reason:     string;
  everyone:   boolean;
  days:       number;
  sites:      { id: string; name: string }[];
  employees:  { id: string; employee_no: string; full_name: string }[];
  who:        string;
  created_by: string;
}

export interface EventInput {
  start: string; end: string; kind: EventKind; reason: string;
  everyone: boolean; site_ids: string[]; employee_ids: string[];
}

export const eventApi = {
  async list(): Promise<CompanyEvent[]> {
    const { data } = await api.get("/api/hr/attendance/events/");
    return data.events;
  },
  async create(body: EventInput): Promise<{ events: CompanyEvent[]; event: CompanyEvent }> {
    const { data } = await api.post("/api/hr/attendance/events/", body);
    return data;
  },
  async update(id: string, body: Partial<EventInput>): Promise<{ events: CompanyEvent[]; event: CompanyEvent }> {
    const { data } = await api.patch(`/api/hr/attendance/events/${id}/`, body);
    return data;
  },
  async remove(id: string): Promise<CompanyEvent[]> {
    const { data } = await api.delete(`/api/hr/attendance/events/${id}/`);
    return data.events;
  },
};
