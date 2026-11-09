// =============================================================================
// === frontend/lib/api/machines.ts ===
// Fingerprint machines and each employee's ID per machine (G12f.1a/b, 9 Nov 2026).
// Mirrors backend/apps/attendance/machine_views.py.
//
// "Mesin utama" has no row: its IDs are "ID Mesin Fingerprint" on the employee.
// A company with no other machine never sees any of this.
// =============================================================================
import api from "@/lib/api";

export const MAIN_MACHINE = "main";
export const AUTO_MACHINE = "auto";
export const ALL_MACHINES = "all";
export const MAIN_MACHINE_NAME = "Mesin utama";

export interface MainMachine { name: string; employees: number; taps: number }

export interface Machine {
  id:          string;
  name:        string;
  site:        string | null;
  site_name:   string;
  dept_labels: string;        // "Staf, Manager": the Dept. values of this machine in a combined report
  is_active:   boolean;
  employees:   number;        // employees with an ID on this machine
  taps:        number;        // imported taps from this machine
}

export interface MachineList { main: MainMachine; machines: Machine[] }

export interface MachineInput { name: string; site: string | null; dept_labels: string; is_active: boolean }

export interface EmployeeMachineIds {
  employee:    { id: string; employee_no: string; full_name: string };
  main:        { name: string; fingerprint_id: string };
  machine_ids: { machine: string; machine_name: string; fingerprint_id: string }[];
  machines:    { id: string; name: string; is_active: boolean }[];
}

export const machineApi = {
  async list(): Promise<MachineList> {
    const { data } = await api.get("/api/hr/fingerprint/machines/");
    return { main: data.main, machines: data.machines };
  },
  async create(body: Partial<MachineInput>): Promise<Machine[]> {
    const { data } = await api.post("/api/hr/fingerprint/machines/", body);
    return data.machines;
  },
  async update(id: string, body: Partial<MachineInput>): Promise<Machine[]> {
    const { data } = await api.patch(`/api/hr/fingerprint/machines/${id}/`, body);
    return data.machines;
  },
  async remove(id: string): Promise<Machine[]> {
    const { data } = await api.delete(`/api/hr/fingerprint/machines/${id}/`);
    return data.machines;
  },
  async employeeIds(employeeId: string): Promise<EmployeeMachineIds> {
    const { data } = await api.get(`/api/hr/employees/${employeeId}/machine-ids/`);
    return data;
  },
  /** Replaces the employee's whole list; an empty fingerprint_id removes the ID on that machine. */
  async setEmployeeIds(employeeId: string, ids: { machine: string; fingerprint_id: string }[]): Promise<EmployeeMachineIds> {
    const { data } = await api.put(`/api/hr/employees/${employeeId}/machine-ids/`, { machine_ids: ids });
    return data;
  },
};
