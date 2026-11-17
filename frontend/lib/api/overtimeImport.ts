// =============================================================================
// === frontend/lib/api/overtimeImport.ts ===
// Overtime decided from HR's recap file (G17-8, 17 Nov 2026): the overtime row under each person's taps
// ("ASR Edit"). Mirrors backend/apps/attendance/overtime_import_views.py and overtime_import.py.
// =============================================================================
import api from "@/lib/api";

export type OtLineState = "pay" | "unpay" | "none" | "same" | "locked" | "rejected" | "not_eligible" | "outside";

export interface OtLine {
  date: string; state: OtLineState;
  book: number;                 // minutes HR paid in the file (0 = none)
  proposed: number;             // minutes the taps propose
  current: number | null;       // minutes SeeGaji pays now (null = not decided)
  in: string | null; out: string | null; day_id: string | null;
}

export interface OtPerson {
  employee: { id: string; employee_no: string; full_name: string };
  machine_id: string; machines: { machine: string; machine_id: string }[];
  name_in_file: string; names_in_file: string[]; name_check: "ok" | "bad" | "none"; mismatch_name: string;
  file_minutes: number; file_total: number | null; total_mismatch: boolean;
  twice: string[]; unreadable: { date: string; text: string }[]; proposed_minutes: number;
  todo: number; pay: number; unpay: number; none: number; same: number;
  locked: number; rejected: number; not_eligible: number; outside: number;
  lines: OtLine[];
}

export interface OvertimeImportResult {
  file: string; sheet: string; period: { start: string; end: string };
  machine: { mode: "main" | "auto" | "one"; id: string | null; name: string };
  suggest_machine: { mode: "main" | "auto" | "one"; id: string | null; value: string; name: string;
                     known: number; name_ok: number; chosen_known: number; chosen_name_bad: number } | null;
  depts?: { dept: string; people: number; taps: number; machine: string; machine_key: string; claimed: boolean }[];
  no_row: number;
  unknown: { machine_id: string; name: string; minutes: number; machine: string; machine_key: string; link_machine: string }[];
  people: OtPerson[];
  totals: { people: number; unknown: number; unknown_with_overtime: number; file_minutes: number;
            todo: number; pay: number; unpay: number; none: number; same: number;
            locked: number; rejected: number; not_eligible: number; outside: number;
            people_todo: number; name_mismatch: number; total_mismatch: number };
  applied?: { decided: number; skipped: number; minutes: number; batch: string | null };
}

export const overtimeImportApi = {
  async run(file: File, commit: boolean, machine: string, confirmNames = false): Promise<OvertimeImportResult> {
    const f = new FormData();
    f.append("file", file, file.name);
    f.append("commit", commit ? "1" : "0");
    f.append("machine", machine);
    if (confirmNames) f.append("confirm_names", "1");
    const { data } = await api.post("/api/hr/attendance/overtime/import/", f, { timeout: 300000 });
    return data;
  },
};
