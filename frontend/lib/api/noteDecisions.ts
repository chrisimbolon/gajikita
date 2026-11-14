// =============================================================================
// === frontend/lib/api/noteDecisions.ts ===
// HR's notes -> decisions (G17-4, 14 Nov 2026). Mirrors backend/apps/attendance/note_decision_views.py.
// =============================================================================
import api from "@/lib/api";

export type NoteState = "todo" | "done" | "locked" | "no_taps" | "info";

export interface NoteRow {
  employee: { id: string; employee_no: string; full_name: string };
  date: string; code: string; text: string; taps: string | null; state: NoteState; balance_left?: number;
}
export interface NoteGroup {
  key: string; label: string; explain: string; actionable: boolean;
  choices: { key: string; label: string }[]; todo: number; rows: NoteRow[];
}
export interface NoteDecisions {
  month: string; label: string; start: string; end: string; prev: string; next: string; total: number;
  groups: NoteGroup[]; applied?: number; errors?: { name: string; date: string; message: string }[];
}

export const noteDecisionApi = {
  async get(month?: string): Promise<NoteDecisions> {
    const { data } = await api.get("/api/hr/attendance/note-decisions/", { params: { month }, timeout: 120000 });
    return data;
  },
  async apply(body: { month: string; group: string; items: { employee: string; date: string; choice?: string }[] }): Promise<NoteDecisions> {
    const { data } = await api.post("/api/hr/attendance/note-decisions/apply/", body, { timeout: 300000 });
    return data;
  },
};
