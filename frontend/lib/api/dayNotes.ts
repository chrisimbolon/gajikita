// =============================================================================
// === frontend/lib/api/dayNotes.ts ===
// HR's notes per day, from the recap HR keeps beside the machine (G12f.3.2, 10 Nov 2026).
// Mirrors backend/apps/attendance/day_notes_views.py and day_notes_import.py.
// A note is text and a colour code ("UL" on yellow). It never changes status, lateness, overtime or pay.
// =============================================================================
import api from "@/lib/api";

export type NoteState = "new" | "changed" | "same" | "locked";

export interface NoteLine {
  date: string; code: string; color: string; text: string; state: NoteState;
  before: string;                                   // the saved text, when state is "changed"
}

export interface DayNotesPerson {
  employee: { id: string; employee_no: string; full_name: string };
  machine_id: string; machines: { machine: string; machine_id: string }[]; name_in_file: string;
  name_check: "ok" | "bad" | "none"; mismatch_name: string;
  codes: { code: string; count: number }[];
  notes: number; new: number; changed: number; same: number; removed: number; locked: number;
  lines: NoteLine[];
}

export interface DayNotesImportResult {
  file: string; sheet: string;
  period: { start: string; end: string }; period_in_file: boolean; colors_read: boolean;
  legend: { color: string; label: string }[];
  unreadable: number; outside: number;
  repeated: { machine_id: string; name: string; date: string }[];
  machine: { mode: "main" | "auto" | "one"; id: string | null; name: string };
  suggest_machine: { mode: "main" | "auto" | "one"; id: string | null; value: string; name: string;
                     known: number; name_ok: number; chosen_known: number; chosen_name_bad: number } | null;
  unknown: { machine_id: string; name: string; rows: number; notes: number; machine: string; machine_key: string;
             link_machine: string }[];
  people: DayNotesPerson[];
  totals: { people: number; unknown: number; unknown_notes: number; notes: number; new: number; changed: number;
            same: number; removed: number; locked: number; name_mismatch: number };
  applied?: { added: number; changed: number; removed: number };
}

export interface DayNotesDeleteResult {
  start: string; end: string;
  totals: { notes: number; people: number; locked: number };
  people: { employee: { id: string; employee_no: string; full_name: string }; notes: number }[];
  applied?: { removed: number };
}

export const dayNotesApi = {
  async importNotes(file: File, commit: boolean, machine: string, confirmNames = false): Promise<DayNotesImportResult> {
    const f = new FormData();
    f.append("file", file, file.name);
    f.append("commit", commit ? "1" : "0");
    f.append("machine", machine);
    if (confirmNames) f.append("confirm_names", "1");
    const { data } = await api.post("/api/hr/attendance/notes/import/", f, { timeout: 300000 });
    return data;
  },
  async deleteNotes(body: { start: string; end: string; commit: boolean; reason?: string }): Promise<DayNotesDeleteResult> {
    const { data } = await api.post("/api/hr/attendance/notes/delete/", body);
    return data;
  },
};
