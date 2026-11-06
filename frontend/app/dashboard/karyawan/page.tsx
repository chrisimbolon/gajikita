"use client";
// =============================================================================
// /dashboard/karyawan — HR's Employees page (G2b, 27 Oct 2026).
// List + search on the left; a panel on the right to add or edit one
// employee and to turn on their phone + PIN login.
// =============================================================================
import {
  EMPLOYMENT_TYPE_LABEL, Employee, EmployeeInput, MEAL_RULE_OPTIONS, PAY_TYPE_LABEL, PTKP_OPTIONS, Shift, Site, hrApi, readErrors,
} from "@/lib/api/hr";
import { hhmm, rupiah, todayISO } from "@/lib/format";
import EmployeeImport from "@/components/EmployeeImportWizard";     // G9d: template or the company's own file
import { FileSpreadsheet, KeyRound, Loader2, Plus, Save, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

type Form = Omit<EmployeeInput, "end_date" | "probation_end_date"> & { end_date: string; probation_end_date: string };

// G9e: how money and NPWP read in the form (stored as plain digits)
const RP = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });
function moneyText(value: string): string {
  if (value === "" || value == null) return "";
  const n = Math.trunc(Number(value));
  return Number.isFinite(n) ? RP.format(n) : value;
}
/** 15 digits -> 12.345.678.9-012.345 (the old NPWP); 16 digits (NIK as NPWP) stay as they are. */
function npwpText(value: string): string {
  const d = (value ?? "").replace(/\D/g, "");
  if (d.length !== 15) return d;
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}.${d.slice(8, 9)}-${d.slice(9, 12)}.${d.slice(12)}`;
}

const blank = (): Form => ({
  employee_no: "", full_name: "", position: "", fingerprint_id: "", probation_end_date: "", nik: "", npwp: "", ptkp_status: "TK/0", join_date: todayISO(), end_date: "",
  employment_type: "pkwtt", pay_type: "monthly", base_rate: "0", fixed_allowance: "0", overtime_eligible: true, bpjs_tk_enrolled: true, meal_rule: "",
  bank_name: "", bank_account_no: "",
  bank_account_name: "", bpjs_kesehatan_no: "", bpjs_tk_no: "", phone: "", sites: [], default_site: null,
  default_shift: null, mandor: null, status: "active",
});

const fromEmployee = (e: Employee): Form => ({
  employee_no: e.employee_no, full_name: e.full_name, position: e.position, fingerprint_id: e.fingerprint_id,
  probation_end_date: e.probation_end_date ?? "", nik: e.nik, npwp: e.npwp, ptkp_status: e.ptkp_status,
  join_date: e.join_date, end_date: e.end_date ?? "", employment_type: e.employment_type, pay_type: e.pay_type,
  base_rate: e.base_rate, fixed_allowance: e.fixed_allowance, overtime_eligible: e.overtime_eligible,
  bpjs_tk_enrolled: e.bpjs_tk_enrolled, meal_rule: e.meal_rule ?? "",
  bank_name: e.bank_name, bank_account_no: e.bank_account_no,
  bank_account_name: e.bank_account_name, bpjs_kesehatan_no: e.bpjs_kesehatan_no, bpjs_tk_no: e.bpjs_tk_no,
  phone: e.phone, sites: e.sites.map(String), default_site: e.default_site, default_shift: e.default_shift,
  mandor: e.mandor, status: e.status,
});

function loginPill(e: Employee) {
  if (!e.has_login) return <span className="pill" style={{ background: "var(--paper-2)", color: "var(--steel)" }}>Belum</span>;
  if (e.login_locked) return <span className="pill due"><span className="dot" />Terkunci</span>;
  if (e.must_change_pin) return <span className="pill soon"><span className="dot" />PIN baru</span>;
  return <span className="pill ok"><span className="dot" />Aktif</span>;
}

export default function KaryawanPage() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Employee | "new" | null>(null);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [e, s, sh] = await Promise.all([hrApi.employees(), hrApi.sites(), hrApi.shifts()]);
      setEmployees(e); setSites(s); setShifts(sh); setPageError(null);
    } catch (err) {
      setPageError(readErrors(err).summary);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const siteName = useMemo(() => Object.fromEntries(sites.map((s) => [s.id, s.name])), [sites]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return employees;
    return employees.filter((e) => e.full_name.toLowerCase().includes(t) || e.employee_no.toLowerCase().includes(t)
      || e.phone.includes(t));
  }, [employees, q]);

  const onSaved = (emp: Employee) => {
    setEmployees((cur) => {
      const rest = cur.filter((e) => e.id !== emp.id);
      return [...rest, emp].sort((a, b) => a.full_name.localeCompare(b.full_name));
    });
    setEditing(emp);
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <h1 className="display" style={{ fontSize: 28, marginBottom: 4, textTransform: "none" }}>Karyawan</h1>
          <p style={{ color: "var(--steel)", margin: 0, fontSize: 14 }}>
            {employees.filter((e) => e.status === "active").length} aktif · {employees.length} total
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-ghost" onClick={() => setImporting(true)} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <FileSpreadsheet size={16} /> Import Excel
          </button>
          <button className="btn-rust" onClick={() => setEditing("new")}><Plus size={16} /> Tambah Karyawan</button>
        </div>
      </div>

      {pageError && <div className="card" style={{ color: "var(--danger)", marginBottom: 16 }}>{pageError}</div>}
      {importing && <EmployeeImport onClose={() => setImporting(false)} onDone={() => { setEditing(null); load(); }} />}

      <div style={{ display: "grid", gridTemplateColumns: editing ? "minmax(0, 1fr) 440px" : "1fr", gap: 18, alignItems: "start" }}>
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: 14, borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", gap: 8 }}>
            <Search size={16} style={{ color: "var(--steel)" }} />
            <input className="input" style={{ border: "none", background: "transparent", padding: 4 }}
                   placeholder="Cari nama, no. karyawan atau no. HP" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {loading ? (
            <div style={{ padding: 30, textAlign: "center", color: "var(--steel)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /></div>
          ) : shown.length === 0 ? (
            <div style={{ padding: 30, color: "var(--steel)", fontSize: 14 }}>
              {employees.length === 0 ? "Belum ada karyawan. Klik \"Tambah Karyawan\" untuk mulai." : "Tidak ada yang cocok."}
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>No.</th><th>Nama</th>{!editing && <th>Upah</th>}{!editing && <th>Lokasi utama</th>}<th>Login</th></tr>
              </thead>
              <tbody>
                {shown.map((e) => (
                  <tr key={e.id} onClick={() => setEditing(e)} style={{ cursor: "pointer",
                      background: editing !== "new" && editing?.id === e.id ? "var(--paper)" : undefined,
                      opacity: e.status === "resigned" ? 0.55 : 1 }}>
                    <td className="mono" style={{ fontSize: 13, whiteSpace: "nowrap" }}>{e.employee_no}</td>
                    <td style={{ fontWeight: 600 }}>{e.full_name}{e.status === "resigned" ? " (keluar)" : ""}</td>
                    {!editing && <td style={{ fontSize: 13, whiteSpace: "nowrap" }}>{PAY_TYPE_LABEL[e.pay_type]} · {rupiah(e.base_rate)}</td>}
                    {!editing && <td style={{ fontSize: 13 }}>{e.default_site ? siteName[e.default_site] ?? "-" : "-"}</td>}
                    <td style={{ whiteSpace: "nowrap" }}>{loginPill(e)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {editing && (
          <EmployeePanel key={editing === "new" ? "new" : editing.id} employee={editing === "new" ? null : editing}
                         employees={employees} sites={sites} shifts={shifts} onClose={() => setEditing(null)} onSaved={onSaved} />
        )}
      </div>
    </div>
  );
}

// ── the add / edit panel ──
interface PanelProps {
  employee:  Employee | null;
  employees: Employee[];
  sites:     Site[];
  shifts:    Shift[];
  onClose:   () => void;
  onSaved:   (e: Employee) => void;
}

function EmployeePanel({ employee, employees, sites, shifts, onClose, onSaved }: PanelProps) {
  const [form, setForm] = useState<Form>(employee ? fromEmployee(employee) : blank());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  };

  const save = async () => {
    setSaving(true); setErrors({}); setSummary(null);
    const body: Partial<EmployeeInput> = { ...form, end_date: form.end_date || null, probation_end_date: form.probation_end_date || null, base_rate: form.base_rate || "0",
                                         fixed_allowance: form.fixed_allowance || "0" };
    try {
      const emp = employee ? await hrApi.updateEmployee(employee.id, body) : await hrApi.createEmployee(body);
      onSaved(emp);
      setSaved(true);
    } catch (err) {
      const r = readErrors(err);
      setErrors(r.fields); setSummary(r.summary);
    } finally {
      setSaving(false);
    }
  };

  const toggleSite = (id: string) =>
    set("sites", form.sites.includes(id) ? form.sites.filter((s) => s !== id) : [...form.sites, id]);

  const text = (key: keyof Form, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <div style={{ marginBottom: 12 }}>
      <label className="label">{label}</label>
      <input className="input" value={String(form[key] ?? "")} onChange={(e) => set(key, e.target.value as never)} {...props}
             style={errors[key] ? { borderColor: "var(--danger)" } : undefined} />
      {errors[key] && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{errors[key]}</div>}
    </div>
  );

  const money = (key: "base_rate" | "fixed_allowance", label: string) => (
    <div style={{ marginBottom: 12 }}>
      <label className="label">{label}</label>
      <div style={{ position: "relative" }}>
        <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--steel)",
                       fontSize: 14, pointerEvents: "none" }}>Rp</span>
        <input className="input" inputMode="numeric" aria-label={label} value={moneyText(String(form[key] ?? ""))}
               onChange={(e) => set(key, e.target.value.replace(/\D/g, "").slice(0, 13) as never)}
               style={{ paddingLeft: 40, ...(errors[key] ? { borderColor: "var(--danger)" } : {}) }} />
      </div>
      {errors[key] && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{errors[key]}</div>}
    </div>
  );

  const npwp = () => (
    <div style={{ marginBottom: 12 }}>
      <label className="label">NPWP</label>
      <input className="input" inputMode="numeric" aria-label="NPWP" placeholder="15 atau 16 angka" value={npwpText(form.npwp)}
             onChange={(e) => set("npwp", e.target.value.replace(/\D/g, "").slice(0, 16))}
             style={errors.npwp ? { borderColor: "var(--danger)" } : undefined} />
      {errors.npwp && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{errors.npwp}</div>}
    </div>
  );

  const select = (key: keyof Form, label: string, options: [string, string][], allowEmpty = false) => (
    <div style={{ marginBottom: 12 }}>
      <label className="label">{label}</label>
      <select className="input" value={String(form[key] ?? "")}
              onChange={(e) => set(key, (e.target.value || (allowEmpty ? null : "")) as never)}>
        {allowEmpty && <option value="">-</option>}
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      {errors[key] && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 4 }}>{errors[key]}</div>}
    </div>
  );

  const section = (title: string) => (
    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--steel)", textTransform: "uppercase", letterSpacing: "0.05em",
                  margin: "18px 0 10px", paddingTop: 12, borderTop: "1px solid var(--line)" }}>{title}</div>
  );

  const activeSites = sites.filter((s) => s.is_active || form.sites.includes(s.id));
  const mandorOptions = employees.filter((e) => e.status === "active" && e.id !== employee?.id);

  return (
    <div className="card" style={{ position: "sticky", top: 20, maxHeight: "calc(100vh - 40px)", overflowY: "auto", padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontWeight: 700, fontSize: 17 }}>{employee ? employee.full_name : "Karyawan baru"}</div>
        <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none", color: "var(--steel)" }}><X size={18} /></button>
      </div>

      {section("Data diri")}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        {text("employee_no", "No. karyawan", { placeholder: "BWI-001" })}
        {select("ptkp_status", "Status PTKP", PTKP_OPTIONS.map((p): [string, string] => [p, p]))}
      </div>
      {text("full_name", "Nama lengkap")}
      {text("position", "Jabatan", { placeholder: "Driver TM" })}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        {text("nik", "NIK (KTP)", { inputMode: "numeric", maxLength: 16 })}
        {npwp()}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        {text("phone", "No. HP", { inputMode: "tel", placeholder: "0812 3456 7890" })}
        {text("fingerprint_id", "ID mesin fingerprint", { placeholder: "mis. 15" })}
      </div>

      {section("Pekerjaan")}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        {text("join_date", "Tanggal masuk", { type: "date" })}
        {text("end_date", "Tanggal keluar", { type: "date" })}
        {text("probation_end_date", "Lolos magang / probation", { type: "date" })}
        {select("employment_type", "Hubungan kerja", Object.entries(EMPLOYMENT_TYPE_LABEL))}
        {select("pay_type", "Jenis upah", Object.entries(PAY_TYPE_LABEL))}
      </div>
      {money("base_rate", form.pay_type === "daily" ? "Upah per hari" : form.pay_type === "piece" ? "Tarif per pekerjaan" : "Gaji pokok sebulan")}
      {money("fixed_allowance", "Tunjangan tetap sebulan")}
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, marginBottom: 12 }}>
        <input type="checkbox" checked={form.overtime_eligible} onChange={(e) => set("overtime_eligible", e.target.checked)} />
        Berhak upah lembur (PP 35/2021)
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, marginBottom: 12 }}>
        <input type="checkbox" checked={form.bpjs_tk_enrolled} onChange={(e) => set("bpjs_tk_enrolled", e.target.checked)} />
        Terdaftar BPJS Ketenagakerjaan (JHT 2% dipotong dari gaji)
      </label>
      {select("meal_rule", "Uang makan", MEAL_RULE_OPTIONS)}
      {select("default_shift", "Shift utama", shifts.filter((s) => s.is_active || s.id === form.default_shift)
        .map((s): [string, string] => [s.id, `${s.name} (${hhmm(s.start_time)}-${hhmm(s.end_time)})`]), true)}
      {select("default_site", "Lokasi utama", activeSites.map((s): [string, string] => [s.id, s.name]), true)}
      <div style={{ marginBottom: 12 }}>
        <label className="label">Boleh absen di lokasi</label>
        {activeSites.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--steel)" }}>Belum ada lokasi. Tambahkan di menu Lokasi.</div>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {activeSites.map((s) => (
              <label key={s.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, padding: "5px 10px",
                                         border: "1px solid var(--line)", borderRadius: 999, cursor: "pointer",
                                         background: form.sites.includes(s.id) ? "var(--workshop-lt)" : "transparent" }}>
                <input type="checkbox" checked={form.sites.includes(s.id)} onChange={() => toggleSite(s.id)} /> {s.name}
              </label>
            ))}
          </div>
        )}
        <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 6 }}>
          Kosong = boleh di semua lokasi aktif. Lokasi utama selalu termasuk.
        </div>
      </div>
      {select("mandor", "Mandor", mandorOptions.map((e): [string, string] => [e.id, `${e.full_name} (${e.employee_no})`]), true)}
      {select("status", "Status", [["active", "Aktif"], ["resigned", "Keluar"]])}

      {section("Bank & BPJS")}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        {text("bank_name", "Bank", { placeholder: "BCA" })}
        {text("bank_account_no", "No. rekening", { inputMode: "numeric" })}
      </div>
      {text("bank_account_name", "Nama pemilik rekening")}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        {text("bpjs_kesehatan_no", "No. BPJS Kesehatan")}
        {text("bpjs_tk_no", "No. BPJS Ketenagakerjaan")}
      </div>

      {summary && <div style={{ color: "var(--danger)", fontSize: 13.5, margin: "8px 0" }}>{summary}</div>}
      {saved && !summary && <div style={{ color: "var(--workshop)", fontSize: 13.5, margin: "8px 0", fontWeight: 600 }}>Tersimpan.</div>}
      <button className="btn-rust" onClick={save} disabled={saving} style={{ width: "100%", justifyContent: "center", marginTop: 6 }}>
        {saving ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={16} />}
        {employee ? "Simpan perubahan" : "Simpan karyawan"}
      </button>

      {employee && <LoginBox employee={employee} onSaved={onSaved} />}
    </div>
  );
}

// ── turn on login / reset PIN ──
function LoginBox({ employee, onSaved }: { employee: Employee; onSaved: (e: Employee) => void }) {
  const [phone, setPhone] = useState(employee.login_phone ?? employee.phone ?? "");
  const [pin, setPin] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const go = async () => {
    const again = employee.has_login
      ? window.confirm(`Atur ulang PIN ${employee.full_name}? PIN lama tidak bisa dipakai lagi.`)
      : true;
    if (!again) return;
    setBusy(true); setError(null); setPin(null);
    try {
      const res = await hrApi.enableLogin(employee.id, phone);
      setPin(res.pin);
      onSaved(res.employee);
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 22, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>Login HP karyawan</div>
      <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 12 }}>
        {employee.has_login
          ? `Aktif dengan No. HP ${employee.login_phone}.${employee.login_locked ? " Saat ini terkunci karena salah PIN; atur ulang PIN untuk membuka." : ""}`
          : "Belum aktif. Karyawan absen lewat HP dengan No. HP + PIN."}
      </div>
      <label className="label">No. HP untuk login</label>
      <input className="input" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="0812 3456 7890" />
      {error && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 6 }}>{error}</div>}
      <button className="btn-ghost" onClick={go} disabled={busy || employee.status !== "active"}
              style={{ width: "100%", marginTop: 10, display: "flex", justifyContent: "center", alignItems: "center", gap: 6 }}>
        {busy ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> : <KeyRound size={16} />}
        {employee.has_login ? "Atur ulang PIN" : "Aktifkan login"}
      </button>
      {pin && (
        <div style={{ marginTop: 12, padding: 14, background: "var(--hazard-light)", borderRadius: 6 }}>
          <div style={{ fontSize: 13 }}>Berikan PIN ini ke {employee.full_name}. PIN hanya ditampilkan sekali:</div>
          <div className="mono" style={{ fontSize: 28, fontWeight: 700, letterSpacing: "0.2em", margin: "6px 0" }}>{pin}</div>
          <div style={{ fontSize: 12.5, color: "var(--ink-soft)" }}>
            Karyawan membuka <b>/absen/masuk</b>, login dengan No. HP {employee.login_phone ?? phone} dan PIN ini, lalu wajib membuat PIN baru.
          </div>
        </div>
      )}
    </div>
  );
}
