// =============================================================================
// === frontend/lib/api/imports.ts ===
// Employee import and fingerprint import (G9, 1 Nov 2026). Mirrors
// backend/apps/employees/import_views.py and backend/apps/attendance/fingerprint_views.py.
// =============================================================================
import api from "@/lib/api";

export interface EmployeeImportRow {
  row:         number;
  employee_no: string;
  full_name:   string;
  action:      "create" | "update" | "same" | "error" | "skip";
  changes:     { field: string; old: string; new: string }[];
  errors:      string[];
  warnings:    string[];
  skip:        string;
}

export interface ImportColumn { index: number; title: string; key: string; field: string; auto: boolean; sample: string[] }
export interface UnknownValue {
  field: string; label: string; raw: string; key: string; count: number;
  options: { value: string; label: string }[]; mapped?: string | null;
}
export interface EmployeeImportOptions {
  mapping?: Record<string, string>;                  // column title key -> field, or "-"
  values?:  Record<string, Record<string, string>>;  // field -> their word key -> our word ("" = leave empty)
  sheet?:   string;
  reset?:   boolean;
}

function mappedForm(file: File, commit: boolean, o: EmployeeImportOptions, report = false): FormData {
  const f = new FormData();
  f.append("file", file, file.name);
  f.append("commit", commit ? "1" : "0");
  if (o.mapping && Object.keys(o.mapping).length) f.append("mapping", JSON.stringify(o.mapping));
  if (o.values && Object.keys(o.values).length) f.append("values", JSON.stringify(o.values));
  if (o.sheet) f.append("sheet", o.sheet);
  if (o.reset) f.append("reset", "1");
  if (report) f.append("report", "1");
  return f;
}

export interface EmployeeImportResult {
  file:            string;
  columns_found:   string[];
  columns_missing: string[];
  columns_ignored?: string[];   // G9c: titles in the file GajiKita did not recognise
  // G9d: "Import dari file apa saja"
  sheet?:          string;
  sheets?:         string[];
  header_row?:     number;
  profile_used?:   boolean;
  needs_mapping?:  boolean;
  message?:        string;
  columns?:        ImportColumn[];
  fields?:         { field: string; label: string; required: boolean }[];
  unknown_values?: UnknownValue[];
  counts:          Record<EmployeeImportRow["action"], number>;
  rows:            EmployeeImportRow[];
  applied?:        { created: number; updated: number };
}

export interface FingerprintImportResult {
  file:       string;
  format:     string;
  punches:    number;
  unreadable: number;
  period:     { start: string; end: string } | null;
  people:     { employee: { id: string; employee_no: string; full_name: string }; machine_id: string; name_in_file: string;
                days: number; new_days: number; already_days: number; locked_days: number; no_clock_out: number;
                machines?: { machine: string; machine_id: string }[];
                name_check?: "ok" | "bad" | "none"; mismatch_name?: string }[];      // G12f.2
  unknown:    { machine_id: string; name: string; taps: number; first: string; last: string;
                machine?: string; machine_key?: string;
                link_machine?: string;                                               // G12f.2: "main" | a machine id
                suggest?: { id: string; full_name: string; employee_no: string } | null }[];
  // G12f.2: the calendar span of the file, and a clearly better machine choice if there is one
  file_period?: { start: string; end: string; days: number } | null;
  suggest_machine?: { mode: "main" | "auto" | "one"; id: string | null; value: string; name: string;
                      known: number; name_ok: number; chosen_known: number; chosen_name_bad: number } | null;
  // G12f.1a: which machine the file was matched on, and (auto) where each Dept. went
  machine?:   { mode: "main" | "auto" | "one"; id: string | null; name: string };
  machines?:  { id: string; name: string; dept_labels: string }[];
  depts?:     { dept: string; people: number; taps: number; machine: string; machine_key: string }[];
  not_linked: { employee_no: string; full_name: string }[];
  totals:     { people: number; unknown: number; new_days: number; already_days: number; locked_days: number;
                name_mismatch?: number };
  applied?:   { events: number; days: number };
}

// "Hapus data import" (G9b). Mirrors backend/apps/attendance/fingerprint_delete.py.
export interface FingerprintDeleteResult {
  start: string; end: string; keep_decided: boolean;
  machine?: string;            // G12f.1a: "Semua mesin" / "Mesin utama" / a machine's name
  totals: { taps: number; days: number; people: number; locked_days: number; decided_kept: number; decided_removed: number };
  people: { employee: { id: string; employee_no: string; full_name: string }; taps: number; days: number }[];
  decided: { employee_no: string; full_name: string; date: string; what: string[] }[];
  draft_runs: string[]; locked_runs: string[];
  applied?: { taps: number; days: number; days_removed: number };
}

function form(file: File, commit: boolean, machine?: string): FormData {
  const f = new FormData();
  f.append("file", file, file.name);
  f.append("commit", commit ? "1" : "0");
  if (machine) f.append("machine", machine);        // G12f.1a: "main" | "auto" | a machine id
  return f;
}

export const importApi = {
  async employees(file: File, commit: boolean): Promise<EmployeeImportResult> {
    const { data } = await api.post("/api/hr/employees/import/", form(file, commit), { timeout: 180000 });
    return data;
  },
  async employeesMapped(file: File, commit: boolean, o: EmployeeImportOptions): Promise<EmployeeImportResult> {
    const { data } = await api.post("/api/hr/employees/import/", mappedForm(file, commit, o), { timeout: 300000 });
    return data;
  },
  async downloadErrorRows(file: File, o: EmployeeImportOptions): Promise<void> {
    const { data } = await api.post("/api/hr/employees/import/", mappedForm(file, false, o, true),
                                    { responseType: "blob", timeout: 300000 });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(data as Blob);
    link.download = "Perbaiki_Data_Karyawan.xlsx";
    link.click();
    URL.revokeObjectURL(link.href);
  },
  async downloadTemplate(): Promise<void> {
    const { data } = await api.get("/api/hr/employees/import/template/", { responseType: "blob" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(data as Blob);
    link.download = "Template_Data_Karyawan_GajiKita.xlsx";
    link.click();
    URL.revokeObjectURL(link.href);
  },
  async deleteFingerprint(body: { start: string; end: string; keep_decided: boolean; commit: boolean; reason: string;
                                  machine?: string }):
      Promise<FingerprintDeleteResult> {
    const { data } = await api.post("/api/hr/attendance/fingerprint/delete/", body, { timeout: 120000 });
    return data;
  },
  async fingerprint(file: File, commit: boolean, machine?: string, confirmNames = false): Promise<FingerprintImportResult> {
    const body = form(file, commit, machine);
    if (confirmNames) body.append("confirm_names", "1");              // G12f.2: "Saya sudah cek"
    const { data } = await api.post("/api/hr/attendance/fingerprint/import/", body, { timeout: 300000 });
    return data;
  },
  /** G12f.2 "Ini siapa?": link machine IDs to employees. All or nothing; never overwrites. */
  async linkFingerprint(links: { machine: string; fingerprint_id: string; employee: string }[]): Promise<{ linked: number }> {
    const { data } = await api.post("/api/hr/attendance/fingerprint/link/", { links });
    return data;
  },
};
