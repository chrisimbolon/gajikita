"use client";
// =============================================================================
// FingerprintImport — the "Import fingerprint" dialog on Absensi (G9, 1 Nov 2026).
// Choose the machine's file (attlog.dat, CSV, or the "Attendance Record Report" .xlsx/.xls),
// see who matched and which machine IDs are unknown, then save. Saving the same file
// twice adds nothing; days already in a locked payroll are left alone.
// G12f.1b: with more than one machine, choose where the file comes from: Mesin utama, one
// machine, or "Otomatis menurut Dept. di file" (Anthony's combined report). Changing the
// choice clears the preview, so what is saved is always what was previewed.
// =============================================================================
import { readErrors } from "@/lib/api/hr";
import { FingerprintImportResult, importApi } from "@/lib/api/imports";
import { AUTO_MACHINE, MAIN_MACHINE, MAIN_MACHINE_NAME, Machine, machineApi } from "@/lib/api/machines";
import { AlertTriangle, CheckCircle2, Fingerprint, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import FingerprintDelete from "@/components/FingerprintDelete";

function d(iso: string) {
  const [y, m, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" })
    .format(new Date(Date.UTC(y, m - 1, day)));
}

export default function FingerprintImport({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<FingerprintImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [machines, setMachines] = useState<Machine[]>([]);       // G12f.1b: other machines (active)
  const [machine, setMachine] = useState<string>(MAIN_MACHINE);

  useEffect(() => {
    machineApi.list().then((l) => setMachines(l.machines.filter((m) => m.is_active))).catch(() => setMachines([]));
  }, []);
  const several = machines.length > 0;

  const run = async (commit: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await importApi.fingerprint(file, commit, several ? machine : MAIN_MACHINE);
      setResult(r);
      if (commit) onDone();
    } catch (err) {
      setError(readErrors(err).summary);
    } finally {
      setBusy(false);
    }
  };

  const [deleting, setDeleting] = useState(false);
  const t = result?.totals;
  const depts = result?.depts ?? [];
  const suggestAuto = several && result && !result.applied && machine !== AUTO_MACHINE && depts.length > 1;
  const idLabel = (p: FingerprintImportResult["people"][number]) =>
    several && p.machines?.length ? p.machines.map((m) => `${m.machine_id} (${m.machine})`).join(", ") : p.machine_id;

  if (deleting) {
    return <FingerprintDelete period={result?.period} onBack={() => { setDeleting(false); setResult(null); setFile(null); }}
                              onClose={onClose} onDone={onDone} />;
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(1,61,90,0.45)", zIndex: 50, display: "flex", alignItems: "center",
                  justifyContent: "center", padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 820, maxWidth: "100%", maxHeight: "92vh", overflowY: "auto", padding: 22 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 19, fontWeight: 800, color: "var(--midnight)" }}>Import absensi dari mesin fingerprint</div>
          <button onClick={onClose} aria-label="Tutup" style={{ background: "none", border: "none" }}><X size={18} /></button>
        </div>
        <div style={{ fontSize: 13.5, color: "var(--steel)", margin: "4px 0 14px" }}>
          File yang bisa dibaca: <b>attlog.dat</b> (download dari mesin lewat flashdisk), <b>CSV</b>, atau Excel <b>Attendance Record
          Report</b> (.xlsx / .xls). Karyawan dicocokkan lewat <b>ID Mesin Fingerprint</b> di data karyawan. Tap pertama = masuk, tap terakhir = pulang.
          {" "}<button onClick={() => setDeleting(true)} style={{ background: "none", border: "none", padding: 0, color: "var(--rust)",
                                                                fontWeight: 600, cursor: "pointer", fontSize: 13.5 }}>
            Salah import? Hapus data import →
          </button>
        </div>

        {result?.applied ? (
          <div style={{ background: "var(--workshop-lt)", color: "var(--workshop)", borderRadius: 8, padding: "14px 16px", fontWeight: 700 }}>
            <CheckCircle2 size={16} style={{ verticalAlign: "-3px" }} /> Tersimpan: {result.applied.events} tap di {result.applied.days} hari kerja
            {several && result.machine ? ` (${result.machine.name})` : ""}.
            <div style={{ fontWeight: 500, color: "var(--ink)", marginTop: 4, fontSize: 13.5 }}>
              Lembur, terlambat dan lupa absen pulang sekarang menunggu di <Link href="/dashboard/absensi/tinjau">Perlu Tinjau</Link>.
            </div>
            <div style={{ marginTop: 10 }}><button className="btn-rust" onClick={onClose}>Selesai</button></div>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <label className="btn-ghost" style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <Fingerprint size={15} /> {file ? file.name : "Pilih file dari mesin"}
              <input type="file" accept=".dat,.txt,.csv,.xlsx,.xls" style={{ display: "none" }}
                     onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null); }} />
            </label>
            {several && (
              <select className="input" aria-label="Mesin asal file" value={machine} style={{ width: "auto", minWidth: 220 }}
                      onChange={(e) => { setMachine(e.target.value); setResult(null); setError(null); }}>
                <option value={MAIN_MACHINE}>Dari {MAIN_MACHINE_NAME}</option>
                {machines.map((m) => <option key={m.id} value={m.id}>Dari {m.name}</option>)}
                <option value={AUTO_MACHINE}>Otomatis menurut Dept. di file</option>
              </select>
            )}
            <button className="btn-rust" disabled={!file || busy} onClick={() => run(false)}
                    style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />} Pratinjau
            </button>
          </div>
        )}

        {error && <div style={{ color: "var(--danger)", fontSize: 14, marginTop: 12 }}>{error}</div>}

        {result && t && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 14, marginBottom: 10 }}>
              <b>{result.format}</b> · {result.punches.toLocaleString("id-ID")} tap
              {result.period ? ` · ${d(result.period.start)} – ${d(result.period.end)}` : ""}
              {several && result.machine ? <> · <b>{result.machine.name}</b></> : ""}
              {result.unreadable > 0 && <span style={{ color: "var(--hazard-dark)" }}> · {result.unreadable} baris tidak terbaca</span>}
            </div>

            {suggestAuto && (
              <div style={{ background: "var(--hazard-light)", borderRadius: 8, padding: "10px 12px", marginBottom: 12, fontSize: 13.5 }}>
                <AlertTriangle size={13} style={{ verticalAlign: "-2px", color: "var(--hazard-dark)" }} />{" "}
                File ini berisi beberapa Dept. ({depts.map((x) => x.dept).join(", ")}), mungkin dari lebih dari satu mesin.
                Kalau begitu, pilih <b>Otomatis menurut Dept. di file</b> lalu klik Pratinjau lagi.
              </div>
            )}
            {several && result.machine?.mode === "auto" && depts.length > 0 && (
              <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "8px 12px", marginBottom: 12, fontSize: 13.5 }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>Dept. di file → mesin</div>
                {depts.map((x) => (
                  <div key={x.dept}>{x.dept} → <b>{x.machine}</b> · {x.people} orang · {x.taps.toLocaleString("id-ID")} tap</div>
                ))}
                <div style={{ color: "var(--steel)", fontSize: 12.5, marginTop: 4 }}>
                  Salah mesin? Ubah "Dept. di file" di <Link href="/dashboard/lokasi">Lokasi → Mesin fingerprint</Link>.
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
              <span className="pill" style={{ background: "var(--workshop-lt)", color: "var(--workshop)", fontSize: 13 }}>{t.people} karyawan cocok</span>
              <span className="pill" style={{ background: "var(--midnight-soft)", color: "var(--midnight)", fontSize: 13 }}>{t.new_days} hari baru</span>
              {t.already_days > 0 && <span className="pill" style={{ background: "var(--paper-2)", color: "var(--steel)", fontSize: 13 }}>{t.already_days} hari sudah pernah diimport</span>}
              {t.locked_days > 0 && <span className="pill" style={{ background: "var(--paper-2)", color: "var(--steel)", fontSize: 13 }}>{t.locked_days} hari terkunci (payroll), dilewati</span>}
              {t.unknown > 0 && <span className="pill" style={{ background: "var(--danger-light)", color: "var(--danger)", fontSize: 13 }}>{t.unknown} ID mesin tidak dikenal</span>}
            </div>

            {result.unknown.length > 0 && (
              <div style={{ background: "var(--hazard-light)", borderRadius: 8, padding: "10px 12px", marginBottom: 12, fontSize: 13.5 }}>
                <div style={{ fontWeight: 700, color: "var(--hazard-dark)", marginBottom: 4 }}>
                  <AlertTriangle size={13} style={{ verticalAlign: "-2px" }} /> ID mesin ini belum terhubung ke karyawan (tap-nya tidak disimpan):
                </div>
                {result.unknown.map((u) => (
                  <div key={`${u.machine_key ?? ""}-${u.machine_id}`}>
                    {several && u.machine ? `${u.machine} · ` : ""}ID <b>{u.machine_id}</b>{u.name ? ` (${u.name})` : ""} · {u.taps} tap
                  </div>
                ))}
                <div style={{ marginTop: 4, color: "var(--steel)" }}>
                  {several
                    ? <>Isi ID-nya di <Link href="/dashboard/karyawan">Karyawan</Link> ("ID di Mesin utama" atau "ID di mesin lain"), lalu import file yang sama lagi.</>
                    : <>Isi "ID Mesin Fingerprint" di <Link href="/dashboard/karyawan">Karyawan</Link>, lalu import file yang sama lagi.</>}
                </div>
              </div>
            )}

            <div style={{ border: "1px solid var(--line)", borderRadius: 8, maxHeight: 320, overflowY: "auto" }}>
              <table className="data-table">
                <thead><tr><th>ID mesin</th><th>Karyawan</th><th>Hari</th><th>Baru</th><th>Sudah ada</th><th>Tanpa pulang</th></tr></thead>
                <tbody>
                  {result.people.length === 0 && <tr><td colSpan={6} style={{ color: "var(--steel)" }}>Tidak ada karyawan yang cocok.</td></tr>}
                  {result.people.map((p) => (
                    <tr key={p.employee.id}>
                      <td className="mono" style={{ fontSize: several ? 12.5 : undefined }}>{idLabel(p)}</td>
                      <td><div style={{ fontWeight: 600 }}>{p.employee.full_name}</div>
                        <div style={{ fontSize: 12, color: "var(--steel)" }}>{p.employee.employee_no}{p.name_in_file ? ` · di mesin: ${p.name_in_file}` : ""}</div></td>
                      <td>{p.days}</td><td>{p.new_days}</td><td>{p.already_days}</td>
                      <td style={{ color: p.no_clock_out ? "var(--hazard-dark)" : undefined }}>{p.no_clock_out}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {result.not_linked.length > 0 && (
              <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 8 }}>
                Karyawan aktif tanpa ID mesin: {result.not_linked.map((n) => n.full_name).join(", ")}
              </div>
            )}

            {!result.applied && (
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
                <button className="btn-ghost" onClick={onClose}>Batal</button>
                <button className="btn-rust" disabled={busy || t.new_days === 0} onClick={() => run(true)}>
                  {busy && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
                  {t.new_days === 0 ? "Tidak ada tap baru" : `Simpan ${t.new_days} hari absensi`}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
